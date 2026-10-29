"""Announcements, birthdays, bedtime banners, daily recaps (with old-log backfill) and TV settings."""
import gzip
import time
from datetime import date, datetime, timedelta


def test_recap_summary_and_on_this_day(tmp_path):
    from app import db, recap
    zone = db.tz()
    day = date(2025, 6, 14)
    t0 = datetime(2025, 6, 14, 15, 0, tzinfo=zone).timestamp()
    r = recap.summarize(day, [("Tyler", "u1", t0, t0 + 3600), ("Ava", None, t0 + 1800, t0 + 5400),
                              ("Ava", None, t0 - 86400 * 2, t0 - 86400 * 2 + 60)],
                        [(t0 + 60, "advancement", "Ava", "Ava has completed the challenge [Monster Hunter]"),
                         (t0 + 90, "death", "Tyler", "Tyler fell from a high place"), (t0 + 100, "chat", "Ava", "hi")],
                        seen_before={"tyler"})
    assert [p["name"] for p in r["players"]] == ["Tyler", "Ava"] and r["players"][0]["seconds"] == 3600
    assert r["peak"] == 2 and r["newcomers"] == ["Ava"] and r["chats"] == 1
    assert r["advancements"][0] == {"player": "Ava", "title": "Monster Hunter", "kind": "challenge", "ts": round(t0 + 60)}

    # Stored a year ago -> shows up under "on this day".
    recap._store("otd", r, "logs")
    recap._store("otd", recap.summarize(date(2026, 5, 14), [("Tyler", None, datetime(2026, 5, 14, 9, tzinfo=zone).timestamp(),
                                                                     datetime(2026, 5, 14, 10, tzinfo=zone).timestamp())], [], set()), "live")
    otd = recap.on_this_day("otd", date(2026, 6, 14))
    assert [o["label"] for o in otd] == ["A month ago", "A year ago"]
    nb = recap.neighbours("otd", date(2026, 1, 1))
    assert nb["prev"] == "2025-06-14" and nb["next"] == "2026-05-14" and nb["first"] == "2025-06-14"


def test_backfill_from_old_logs(tmp_path):
    from app import recap
    logs = tmp_path / "logs"
    logs.mkdir()
    # Sessions crossing midnight, a crash with someone online, Paper-style lines too.
    a = ("[23:50:00] [Server thread/INFO]: Tyler joined the game\n"
         "[23:55:10] [Server thread/INFO]: Tyler has made the advancement [Stone Age]\n"
         "[00:10:00] [Server thread/INFO]: Tyler left the game\n"
         "[00:20:00] [Server thread/INFO]: <Tyler> secret chat\n")
    with gzip.open(logs / "2024-03-09-1.log.gz", "wt") as f:
        f.write(a)
    b = ("[10:00:00 INFO]: Ava joined the game\n"
         "[10:30:00 INFO]: Ava was slain by Zombie\n"
         "[11:00:00 INFO]: Stopping server\n")
    with gzip.open(logs / "2024-03-11-1.log.gz", "wt") as f:
        f.write(b)
    (logs / "latest.log").write_text("[09:00:00] [Server thread/INFO]: Nobody joined the game\n")
    n = recap.backfill("logsrv", tmp_path, {"tyler": "uuid-t"})
    assert n == 3
    d9, d10, d11 = (recap.stored("logsrv", date(2024, 3, x)) for x in (9, 10, 11))
    assert d9["players"][0] == {"name": "Tyler", "uuid": "uuid-t", "seconds": 600, "first": d9["players"][0]["first"]}
    assert d9["advancements"][0]["title"] == "Stone Age" and d9["source"] == "logs" and d9["newcomers"] == ["Tyler"]
    assert d10["players"][0]["seconds"] == 600 and d10["chats"] == 1 and d10["newcomers"] == []
    assert d11["players"][0]["name"] == "Ava" and d11["deaths"][0]["message"] == "Ava was slain by Zombie"
    assert recap.backfill("logsrv", tmp_path, {}) == 0          # nothing new the second time


def test_recap_api(client, viewer, anon, sid):
    from app import db
    now = time.time()
    db.x("INSERT INTO sessions(server_id, player, uuid, start_ts, last_seen_ts, end_ts) VALUES (?,?,?,?,?,?)",
         (sid, "Tyler", "069a79f4-44e9-4726-a5be-fca90e38aaf5", now - 900, now - 10, now - 10))
    r = viewer.get(f"/api/servers/{sid}/recap").json()
    assert r["day"] == r["today"] and any(p["name"] == "Tyler" for p in r["recap"]["players"]) and "yesterday" in r
    yday = (date.fromisoformat(r["today"]) - timedelta(days=1)).isoformat()
    assert viewer.get(f"/api/servers/{sid}/recap?day={yday}").json()["day"] == yday
    assert viewer.get(f"/api/servers/{sid}/recap?day=nope").status_code == 400
    assert anon.get(f"/api/public/recap/{sid}").status_code == 404        # status page off
    assert viewer.post("/api/recap/backfill").status_code == 403
    assert isinstance(client.post("/api/recap/backfill").json()["days"], int)


def test_announcements_birthdays_bedtime(client, viewer, anon, sid):
    from app import board, db
    zone = db.tz()
    now = datetime.now(zone)
    soon = (now + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M")
    past = (now - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M")
    yday = now - timedelta(days=1)
    assert viewer.get("/api/board").status_code == 403
    cfg = client.put("/api/board", json={
        "items": [{"text": "  Build contest  ", "emoji": "🏗️", "style": "party", "countdown": soon, "show": "grand-finale", "say": True},
                  {"text": "Old news", "end": past},
                  {"text": "Login only", "where": ["login"]},
                  {"text": ""}, {"text": "bad dates", "start": "tomorrow", "style": "loud"}],
        "birthdays": [{"player": "Tyler", "month": now.month, "day": now.day, "show": "gentle-night"},
                      {"player": "Ava", "month": yday.month, "day": yday.day},
                      {"player": "bad name!", "month": 1, "day": 1}, {"player": "Mo", "month": 2, "day": 30}],
        "birthday_soon": 400}).json()
    assert [i["text"] for i in cfg["items"]] == ["Build contest", "Old news", "Login only", "bad dates"]
    assert cfg["items"][3]["start"] == "" and cfg["items"][3]["style"] == "info"
    assert [b["player"] for b in cfg["birthdays"]] == ["Tyler", "Ava"] and cfg["birthday_soon"] == 31
    assert "Tyler" in cfg["players"] and any(s["id"] == "grand-finale" for s in cfg["shows"])

    items = viewer.get(f"/api/public/board?where=app&sid={sid}").json()["items"]
    texts = [i["text"] for i in items]
    assert "Build contest" in texts and "Happy birthday, Tyler!" in texts and "Old news" not in texts and "Login only" not in texts
    note = next(i for i in items if i["text"] == "Build contest")
    assert note["countdown"] > time.time() and note["show"]["name"] == "Grand finale"
    assert next(i for i in items if i["kind"] == "birthday")["show"]["id"] == "gentle-night"
    assert not any(i["kind"] == "birthday-soon" for i in items)          # Ava's was yesterday: a year away

    # Anonymous: no app banners; login page without player names while the status page is off.
    assert anon.get("/api/public/board?where=app").status_code == 401
    assert anon.get("/api/public/board?where=status").status_code == 404
    login = [i["text"] for i in anon.get("/api/public/board?where=login").json()["items"]]
    assert "Login only" in login and not any("Tyler" in t for t in login)

    # Bedtime: a countdown in the last half hour, and "asleep" during bedtime.
    class Srv:
        id, display_name, settings = "x", "Family", {}
    srv = Srv()
    now = datetime(2026, 6, 1, 18, 0, tzinfo=zone)
    start = (now + timedelta(minutes=20)).strftime("%H:%M")
    from app import playtime
    keep = playtime.config()
    rule = {"id": "t", "start": start, "end": (now + timedelta(hours=8)).strftime("%H:%M"), "days": list(range(7)), "servers": ["x"]}
    try:
        playtime.save({**keep, "bedtimes": [rule]})
        got = [i for i in board.active("status", None, True, now, [srv]) if i["kind"] == "bedtime"]
        assert got and got[0]["text"] == "Bedtime on Family" and 0 < got[0]["countdown"] - now.timestamp() <= 20 * 60
        playtime.save({**keep, "bedtimes": [{**rule, "start": (now - timedelta(minutes=5)).strftime("%H:%M")}]})
        assert board.active("status", None, True, now, [srv])[0]["text"] == "Family is asleep"
        playtime.save({**keep, "bedtimes": [{**rule, "start": (now + timedelta(hours=3)).strftime("%H:%M")}]})
        assert not [i for i in board.active("status", None, True, now, [srv]) if i["kind"] == "bedtime"]
        playtime.save({**keep, "bedtimes": [{**rule, "servers": ["another"], "start": start}]})       # not this server's
        assert not [i for i in board.active("status", None, True, now, [srv]) if i["kind"] == "bedtime"]
    finally:
        playtime.save(keep)
    client.put("/api/board", json={"items": [], "birthdays": []})


def test_public_live_extras(client, anon, sid):
    assert client.get("/api/settings/tv").status_code == 404          # TV mode went with the status page
    assert anon.get(f"/api/public/leaderboard/{sid}").status_code == 404
    client.put("/api/settings/status", json={"enabled": True})
    try:
        assert "tv" not in anon.get("/api/public/status").json()
        lb = anon.get(f"/api/public/leaderboard/{sid}").json()
        assert lb["players"] and "play_time" not in lb["players"][0] and "xp_level" in lb["players"][0]
        r = anon.get(f"/api/public/recap/{sid}").json()
        assert "recap" in r and "on_this_day" in r
        assert anon.get("/api/public/board?where=status").status_code == 200
    finally:
        client.put("/api/settings/status", json={"enabled": False})
