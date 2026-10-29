"""Manage → Play time: bedtime schedules per server, and screen time per person (all their names together)."""
from datetime import date, datetime

from app import auth, playtime, settings_store


def _at(day, hh, mm):  # 2026-10-19 is a Monday
    return datetime(2026, 10, 19 + day, hh, mm)


def test_bedtime_schedules_by_server_and_day():
    cfg = playtime.clean({"bedtimes": [
        {"id": "school", "name": "School nights", "days": [6, 0, 1, 2, 3], "start": "21:00", "end": "07:00", "servers": "all"},
        {"id": "weekend", "name": "Weekends", "days": [4, 5], "start": "22:30", "end": "08:00", "servers": ["fam"]}]})
    assert playtime.server_state(cfg, "fam", _at(0, 21, 30))[3]["id"] == "school"           # Monday night
    assert playtime.server_state(cfg, "fam", _at(4, 21, 30))[:2] == ("before", 3600)         # Friday: later
    assert playtime.server_state(cfg, "fam", _at(5, 7, 30))[3]["id"] == "weekend"            # Friday night into Saturday
    assert playtime.server_state(cfg, "mods", _at(4, 23, 0)) is None                          # weekend one isn't for it
    assert playtime.server_state(cfg, "mods", _at(6, 22, 0))[3]["id"] == "school"
    off = playtime.clean({"bedtimes": [{"days": [0], "start": "21:00", "end": "07:00", "enabled": False}]})
    assert playtime.server_state(off, "fam", _at(0, 22, 0)) is None


def test_settings_cleaned():
    cfg = playtime.clean({"bedtimes": [{"start": "nine", "days": [9, 1], "servers": "all"}], "warn_minutes": [5, "x", 500],
                          "limit_action": "explode", "people": {"p:tyler": {"limit": "90"}, "bad key": {"limit": 5},
                                                                 "p:mom": {"bedtime": True}}})
    assert cfg["bedtimes"][0]["start"] == "21:00" and cfg["bedtimes"][0]["days"] == [1]
    assert cfg["warn_minutes"] == [15, 5, 1] and cfg["limit_action"] == "notify"
    assert cfg["people"] == {"p:tyler": {"bedtime": True, "limit": 90, "weekend_limit": 0}}   # defaults aren't kept


def test_one_limit_for_all_of_a_persons_names(client):
    u = auth.create_user("pt_kid", "kid-pass-123", "player", check=False)
    auth.add_player(u.id, ("00000000-0000-0000-0000-00000000aaaa", "KidJava"))
    auth.add_player(u.id, ("00000000-0000-0000-0000-00000000bbbb", ".KidRock"))
    try:
        cfg = playtime.clean({"people": {f"u{u.id}": {"limit": 60, "weekend_limit": 120, "bedtime": False}}})
        totals = {"kidjava": 2000, ".kidrock": 2000, "other": 9000}
        monday, saturday = date(2026, 10, 19), date(2026, 10, 24)
        assert playtime.over_limit(cfg, totals, monday) == [(f"u{u.id}", 4000, 60)]            # 33 + 33 min > 60
        assert playtime.over_limit(cfg, totals, saturday) == []                                # 120 at weekends
        assert playtime.stays_up(cfg, ".KidRock") and not playtime.stays_up(cfg, "Other")
        # settings given to a name before it had an account still count
        old = playtime.clean({"people": {"p:kidjava": {"limit": 30}}})
        assert playtime.over_limit(old, {"kidjava": 2000}, monday) == [(f"u{u.id}", 2000, 30)]
    finally:
        auth.delete_user(u.id)


def test_older_settings_move_over(client, sid):
    data = settings_store.load()
    keep = {k: data.get(k) for k in ("playtime", "notify", "servers")}
    try:
        settings_store.save_section("playtime", None)
        settings_store.update_server(sid, {"bedtime": {"enabled": True, "start": "20:30", "end": "06:45", "days": [0, 1, 2, 3, 4],
                                                       "warn_minutes": [10], "exempt": ["MomCrafts"], "message": "Night!"}})
        settings_store.save_section("notify", {**(keep["notify"] or {}), "limits": {"gimli_jr": 90}, "limit_action": "kick"})
        cfg = playtime.config()
        r = cfg["bedtimes"][0]
        assert (r["start"], r["end"], r["days"], r["servers"]) == ("20:30", "06:45", [0, 1, 2, 3, 4], "all")
        assert cfg["warn_minutes"] == [10] and cfg["message"] == "Night!" and cfg["limit_action"] == "kick"
        assert cfg["people"]["p:gimli_jr"]["limit"] == 90 and cfg["people"]["p:momcrafts"]["bedtime"] is False
    finally:
        data = settings_store.load()
        for k, v in keep.items():
            if v is None:
                data.pop(k, None)
            else:
                data[k] = v
        settings_store._write(data)


def test_playtime_page_api(client, viewer, sid):
    assert viewer.get("/api/settings/playtime").status_code == 403
    d = client.get("/api/settings/playtime").json()
    assert any(s["id"] == sid for s in d["servers"]) and {r["label"] for r in d["rows"]} >= {"Tyler", "Gimli_Jr"}
    keep = {k: d[k] for k in ("bedtimes", "people", "warn_minutes", "message", "limit_action", "grace_minutes", "limit_warn")}
    try:
        r = client.put("/api/settings/playtime", json={"bedtimes": [{"name": "Weekends", "days": [4, 5], "start": "22:30", "end": "08:00",
                                                                     "servers": [sid]}],
                                                       "people": {"p:tyler": {"bedtime": False, "limit": 90, "weekend_limit": 0}},
                                                       "banner": {"show": True, "minutes": 20}}).json()
        assert r["bedtimes"][0]["name"] == "Weekends" and r["banner"]["minutes"] == 20
        row = next(x for x in r["rows"] if x["label"] == "Tyler")
        assert row["limit"] == 90 and row["bedtime"] is False and "today" in row
        info = client.get(f"/api/servers/{sid}/control").json() if client.get(f"/api/servers/{sid}/control").status_code == 200 else None
        if info:
            assert info["bedtime"][0]["name"] == "Weekends"
    finally:
        client.put("/api/settings/playtime", json={**keep, "people": {k: {"bedtime": True, "limit": 0, "weekend_limit": 0}
                                                                      for k in ("p:tyler",)} | keep["people"]})
