"""Choosing to take part: /trigger join and leave, countdown alerts, website sign-ups, only those in are scored."""
import asyncio
import json
import re
import time

import pytest

from tests.test_challenges import FakeServer


class TriggerServer(FakeServer):
    """The challenge fake, plus trigger objectives and score resets."""
    def __init__(self, online):
        super().__init__(online)
        self.id, self.is_java, self.trig = "oi-srv", True, {}

    async def rcon(self, cmd):
        m = re.match(r"execute if entity @a\[scores=\{(\w+)=1\.\.\}\]", cmd)
        if m:
            n = sum(1 for (p, o), v in self.trig.items() if o == m.group(1) and v >= 1)
            return f"Test passed, count: {n}" if n else "Test failed"
        m = re.match(r"scoreboard players (get|set) (\S+) (join|leave)(?: (\d+))?", cmd)
        if m:
            if m.group(1) == "set":
                self.trig[(m.group(2), m.group(3))] = int(m.group(4))
                return ""
            return f"{m.group(2)} has {self.trig.get((m.group(2), m.group(3)), 0)} [{m.group(3)}]"
        m = re.match(r"scoreboard players reset (\S+) (\S+)", cmd)
        if m:
            self.scores.pop((m.group(1), self.objectives.get(m.group(2))), None)
            return ""
        return await super().rcon(cmd)


@pytest.fixture()
def oi(monkeypatch):
    from app import challenges, gather, optin, settings_store
    from app import servers as S
    monkeypatch.setattr(gather, "LEAD", 0)
    for sec in ("challenges", "races", "games", "optin_state", "optin"):
        settings_store.save_section(sec, {})
    optin._ready.clear(); optin._polled.clear()
    srv = TriggerServer(["Tyler", "Gimli_Jr"])

    async def online(_s):
        return list(srv.online), "rcon"
    monkeypatch.setattr(S, "online_players", online)
    told = []

    async def send(_srv, cmds, delay=0):
        told.extend(cmds)
    monkeypatch.setattr(optin.welcome, "send", send)
    monkeypatch.setattr(challenges.fwshow, "push", lambda *a, **k: None)
    optin.save({"alerts": [600, 300, 60]})
    yield optin, challenges, srv, told
    for sec in ("challenges", "races", "games", "optin_state", "optin"):
        settings_store.save_section(sec, {})


def _to(told, who):
    return [c for c in told if c.startswith(f"tellraw {who} ")]


def _tick(optin, srv):
    optin._polled.clear()
    asyncio.run(optin.tick([srv]))


def test_join_alerts_and_only_joined_players_count(oi):
    optin, challenges, srv, told = oi
    c = challenges.create(srv.id, {"kind": "fish", "name": "Fishing night", "start": time.time() + 300, "minutes": 10, "optin": True,
                                   "prize": {"item": "diamond", "count": 1}})
    assert optin.busy()
    _tick(optin, srv)
    # the 5-minute alert (the 10-minute one went by before it was made, so it's skipped), with the clickable command
    assert len(_to(told, "Tyler")) == 1 and "starts in 5 minutes" in _to(told, "Tyler")[0] and "/trigger join" in _to(told, "Tyler")[0]
    assert '"run_command"' in _to(told, "Tyler")[0]
    assert "scoreboard objectives add join trigger" in srv.cmds and "scoreboard players enable @a join" in srv.cmds
    told.clear()
    _tick(optin, srv)
    assert told == []                                                  # each alert once
    srv.trig[("Tyler", "join")] = 1                                     # /trigger join
    _tick(optin, srv)
    assert "You're in" in _to(told, "Tyler")[0] and srv.trig[("Tyler", "join")] == 0 and not _to(told, "Gimli_Jr")
    assert optin.joined(f"contest:{c['id']}") == ["tyler"]
    told.clear()
    srv.trig[("Tyler", "join")] = 1                                     # again: already in
    _tick(optin, srv)
    assert "already in" in _to(told, "Tyler")[0]
    # it starts: only Tyler is in (the title is his alone); Gimli hears there's still time to join
    told.clear(); srv.said.clear()
    d = challenges._load(); d["items"][0]["start"] = time.time() - 1; challenges._save(d)
    asyncio.run(challenges.tick([srv]))
    c = challenges.list_for(srv.id)[0]
    assert c["state"] == "running" and c["players"] == ["Tyler"] and not c["direct"]
    assert any(x.startswith("title Tyler title") for x in srv.said) and not any(x.startswith("title @a") for x in srv.said)
    assert "still time to join" in _to(told, "Gimli_Jr")[0]
    fish = "minecraft.custom:minecraft.fish_caught"
    srv.scores[("Tyler", fish)] = 3; srv.scores[("Gimli_Jr", fish)] = 9
    d = challenges._load(); d["items"][0]["read_at"] = 0; challenges._save(d)
    asyncio.run(challenges.tick([srv]))
    assert challenges.list_for(srv.id)[0]["scores"] == {"Tyler": 3}        # Gimli fished, but isn't in
    # Gimli joins late: what was caught before joining doesn't count
    told.clear()
    srv.trig[("Gimli_Jr", "join")] = 1
    _tick(optin, srv)
    assert "It's on now" in _to(told, "Gimli_Jr")[0]
    srv.scores[("Gimli_Jr", fish)] = 2
    d = challenges._load(); d["items"][0]["read_at"] = 0; challenges._save(d)
    asyncio.run(challenges.tick([srv]))
    assert challenges.list_for(srv.id)[0]["scores"] == {"Tyler": 3, "Gimli_Jr": 2}
    srv.scores[("Gimli_Jr", fish)] = 5
    d = challenges._load(); d["items"][0]["ends_at"] = time.time() - 1; challenges._save(d)
    asyncio.run(challenges.tick([srv]))
    c = challenges.list_for(srv.id)[0]
    assert c["state"] == "done" and c["winners"] == ["Gimli_Jr"] and c["scores"] == {"Tyler": 3, "Gimli_Jr": 5}


def test_back_to_back_one_at_a_time_and_leaving(oi):
    optin, challenges, srv, told = oi
    first = challenges.create(srv.id, {"kind": "fish", "name": "Round one", "start": time.time() + 600, "minutes": 10, "optin": True, "prize": {"item": "diamond"}})
    second = challenges.create(srv.id, {"kind": "mobs", "name": "Round two", "start": time.time() + 1500, "minutes": 10, "optin": True, "prize": {"item": "diamond"}})
    late = challenges.create(srv.id, {"kind": "mobs", "name": "Tomorrow", "start": time.time() + 86400, "minutes": 10, "optin": True, "prize": {"item": "diamond"}})
    assert asyncio.run(optin.join(srv, "Tyler")) == f"contest:{first['id']}"
    assert asyncio.run(optin.join(srv, "Tyler")) == f"contest:{second['id']}"       # the next one, not both at once
    assert asyncio.run(optin.join(srv, "Tyler")) == "already"                         # tomorrow's isn't open yet
    assert asyncio.run(optin.leave(srv, "Tyler")) == f"contest:{first['id']}"
    assert optin.joined(f"contest:{first['id']}") == [] and optin.joined(f"contest:{second['id']}") == ["tyler"]
    assert "You've left Round one" in _to(told, "Tyler")[-1] and "/trigger join" in _to(told, "Tyler")[-1]
    assert optin.joined(f"contest:{late['id']}") == []
    # an event everyone takes part in has nothing to join
    settings_store_items = challenges._load()
    for c in settings_store_items["items"]:
        c["optin"] = False
    challenges._save(settings_store_items)
    assert asyncio.run(optin.join(srv, "Gimli_Jr")) == "none"
    assert "nothing to join" in _to(told, "Gimli_Jr")[-1]


def test_website_sign_up_counts_once_theyre_on(oi):
    from app import auth, community
    optin, challenges, srv, told = oi
    u = auth.create_user("oi_kid", "kid-pass-123", "player", check=False)
    auth.add_player(u.id, ("00000000-0000-0000-0000-0000000000o1", "Tyler"))
    try:
        c = challenges.create(srv.id, {"kind": "fish", "name": "Sign-up night", "start": time.time() + 1200, "minutes": 10, "optin": True, "prize": {"item": "diamond"}})
        community.sign_up(community.event_key("contest", c["name"], c["start"]), u.id, True)
        _tick(optin, srv)
        assert optin.joined(f"contest:{c['id']}") == ["tyler"] and "on the website" in _to(told, "Tyler")[0]
        asyncio.run(optin.leave(srv, "Tyler"))                     # changed their mind in the game: stays out
        _tick(optin, srv)
        assert optin.joined(f"contest:{c['id']}") == []
        assert optin.players("contest", challenges._load()["items"][0], ["Tyler", "Gimli_Jr"]) == []
    finally:
        auth.delete_user(u.id)


def test_races_and_games_nobody_joined(oi, monkeypatch):
    from app import games, races
    optin, challenges, srv, told = oi
    cid = races.save_course(srv.id, {"name": "Loop", "points": [{"x": 0, "y": 64, "z": 0}, {"x": 20, "y": 64, "z": 0}, {"x": 40, "y": 64, "z": 0}]})["id"]
    r = races.schedule(srv.id, {"course": cid, "start": time.time() - 1, "optin": True})
    srv.trig[("Tyler", "join")] = 0
    asyncio.run(races.tick([srv]))
    r = races.runs_for(srv.id)[0]
    assert r["state"] == "skipped" and r["result"] == "Nobody joined"
    g = games.create(srv.id, {"game": "archery", "target": {"x": 0, "y": 65, "z": 0}, "optin": True, "start": time.time() + 600})
    asyncio.run(optin.join(srv, "Tyler"))
    d = games._load(); d["runs"][0]["start"] = time.time() - 1; games._save(d)
    asyncio.run(games.tick([srv]))
    g = games.runs_for(srv.id)[0]
    assert g["entrants"] == ["Tyler"] and list(g["players"]) == ["Tyler"]
    assert any(x.startswith("give Tyler") for x in srv.cmds) and not any(x.startswith("give @a") for x in srv.cmds)


def test_settings_and_clickable_command(client, viewer):
    from app import optin, welcome
    assert viewer.get("/api/settings/optin").status_code == 403
    r = client.put("/api/settings/optin", json={"alerts": [600, 60, 7, "x"], "joined_text": "", "alert_text": "&aJoin {event}: {join}", "open_minutes": 1}).json()
    assert r["alerts"] == [600, 60] and r["joined_text"] == optin.TEXTS["joined_text"] and r["open_minutes"] == 5
    assert r["alert_text"] == "&aJoin {event}: {join}" and r["labels"]["alert_text"]
    parts = json.loads(welcome.commands("Tyler", "Type /trigger join now")[0].split(" ", 2)[2])
    click = next(p for p in parts if p.get("text") == "/trigger join")
    assert click["clickEvent"] == {"action": "run_command", "value": "/trigger join"} and click["click_event"]["command"] == "/trigger join"
    client.put("/api/settings/optin", json={"alerts": [600, 300, 120, 60, 30], "alert_text": optin.TEXTS["alert_text"], "open_minutes": 60})


def test_nights_on_the_events_list(oi):
    from app import upcoming
    optin, challenges, srv, told = oi
    t = time.time() + 7200
    challenges.create(srv.id, {"kind": "fish", "name": "One", "start": t, "minutes": 10, "optin": True, "prize": {"item": "diamond"}})
    challenges.create(srv.id, {"kind": "mobs", "name": "Two", "start": t + 900, "minutes": 10, "prize": {"item": "diamond"}})
    challenges.create(srv.id, {"kind": "mobs", "name": "Much later", "start": t + 6 * 3600, "minutes": 10, "prize": {"item": "diamond"}})
    got = {i["title"]: i for i in upcoming.items({srv.id: "Family"}) if i["kind"] == "contest"}
    assert not got["One"]["then"] and got["Two"]["then"] and not got["Much later"]["then"]
    assert "/trigger join" in got["One"]["detail"] and "/trigger" not in got["Two"]["detail"]
