"""Challenges: scheduled contests counted with scoreboards, prizes given (or kept for later)."""
import asyncio
import re
import time

import pytest


class FakeServer:
    """Just enough of a Minecraft server: scoreboards, give, tellraw."""
    def __init__(self, online):
        self.id, self.display_name, self.online = "ch-srv", "Family", list(online)
        self.objectives, self.scores, self.given, self.said = {}, {}, [], []
        self.mc_version, self.cmds = "26.1", []

    def rcon_conf(self):
        return {"host": "x"}

    async def rcon(self, cmd):
        self.cmds.append(cmd)
        m = re.match(r"scoreboard objectives add (\S+) (\S+)", cmd)
        if m:
            if "pale_oak" in m.group(2):
                return "Unknown criterion 'minecraft.mined:minecraft.pale_oak_log'"
            self.objectives[m.group(1)] = m.group(2)
            return f"Created new objective [{m.group(1)}]"
        m = re.match(r"scoreboard objectives remove (\S+)", cmd)
        if m:
            self.objectives.pop(m.group(1), None)
            return "Removed"
        m = re.match(r"scoreboard players get (\S+) (\S+)", cmd)
        if m:
            v = self.scores.get((m.group(1), self.objectives.get(m.group(2))))
            return f"{m.group(1)} has {v} [{m.group(2)}]" if v is not None else f"Can't get value of {m.group(2)} for {m.group(1)}; none is set"
        m = re.match(r"give (\S+) (\S+) (\d+)", cmd)
        if m:
            if m.group(1) not in self.online:
                return "No player was found"
            self.given.append((m.group(1), m.group(2), int(m.group(3))))
            return f"Gave {m.group(3)} [x] to {m.group(1)}"
        if cmd.startswith(("tellraw", "title")):
            self.said.append(cmd)
        if cmd.startswith("scoreboard players set"):
            self.sets = getattr(self, "sets", 0) + 1
        return ""


@pytest.fixture()
def fake(monkeypatch):
    from app import challenges, gather, settings_store
    from app import servers as S
    monkeypatch.setattr(gather, "LEAD", 0)               # "right now" means now here (the countdown has its own test)
    settings_store.save_section("challenges", {})
    srv = FakeServer(["Tyler", "Gimli_Jr"])

    async def online(_s):
        return list(srv.online), "rcon"
    monkeypatch.setattr(S, "online_players", online)
    pushed = []
    monkeypatch.setattr(challenges.fwshow, "push", lambda *a, **k: pushed.append(a))
    yield challenges, srv, pushed
    settings_store.save_section("challenges", {})


def test_fishing_contest_start_to_prize(fake):
    challenges, srv, pushed = fake
    c = challenges.create(srv.id, {"kind": "fish", "start": time.time() + 60, "minutes": 10,
                                   "prize": {"item": "diamond", "count": 5}, "second": {"item": "minecraft:cookie", "count": 16}})
    assert c["state"] == "scheduled" and c["prize"] == {"item": "minecraft:diamond", "count": 5, "name": ""}
    asyncio.run(challenges.tick([srv]))                              # not yet
    assert challenges.list_for(srv.id)[0]["state"] == "scheduled"
    d = challenges._load(); d["items"][0]["start"] = time.time() - 1; challenges._save(d)
    asyncio.run(challenges.tick([srv]))                              # starts: objectives made, sidebar shown
    c = challenges.list_for(srv.id)[0]
    assert c["state"] == "running" and "minecraft.custom:minecraft.fish_caught" in srv.objectives.values()
    assert any("has started" in s for s in srv.said)
    fish = "minecraft.custom:minecraft.fish_caught"
    srv.scores[("Tyler", fish)] = 3; srv.scores[("Gimli_Jr", fish)] = 7
    asyncio.run(challenges.tick([srv]))                              # live scores for the pages
    assert challenges.list_for(srv.id)[0]["scores"] == {"Gimli_Jr": 7, "Tyler": 3}
    assert not getattr(srv, "sets", 0)                               # one statistic: the sidebar shows it directly
    assert any("setdisplay sidebar" in c for c in srv.said) is False and challenges.list_for(srv.id)[0]["direct"]
    banner = challenges.banners(srv.id)[0]
    assert banner["text"] == "Fishing contest: Gimli_Jr leads with 7 fish" and banner["countdown"]
    d = challenges._load(); d["items"][0]["ends_at"] = time.time() - 1; challenges._save(d)
    asyncio.run(challenges.tick([srv]))                              # time's up
    c = challenges.list_for(srv.id)[0]
    assert c["state"] == "done" and c["winners"] == ["Gimli_Jr"] and c["seconds"] == ["Tyler"]
    assert ("Gimli_Jr", "minecraft:diamond", 5) in srv.given and ("Tyler", "minecraft:cookie", 16) in srv.given
    assert c["result"] == "Gimli_Jr won Fishing contest with 7 fish!" and not srv.objectives      # cleaned up
    assert pushed and pushed[0][2] == "challenge"


def test_ties_offline_winners_and_unknown_blocks(fake, monkeypatch):
    challenges, srv, _ = fake
    monkeypatch.setattr(challenges, "RETIRED", ())            # no longer offered, but the several-statistics path stays
    challenges.create(srv.id, {"kind": "logs", "start": time.time(), "minutes": 5, "prize": {"item": "golden_apple", "count": 1}})
    asyncio.run(challenges.tick([srv]))
    assert not any("pale_oak" in v for v in srv.objectives.values()) and len(srv.objectives) >= 9   # 8 logs + total
    srv.scores[("Tyler", "minecraft.mined:minecraft.oak_log")] = 4
    srv.scores[("Gimli_Jr", "minecraft.mined:minecraft.birch_log")] = 4
    asyncio.run(challenges.tick([srv]))
    sets = srv.sets
    d = challenges._load(); d["items"][0]["read_at"] = 0; challenges._save(d)
    asyncio.run(challenges.tick([srv]))
    assert srv.sets == sets                                          # nothing changed: nothing sent
    srv.online = ["Tyler"]                                            # Gimli_Jr logs off before the end
    d = challenges._load(); d["items"][0]["ends_at"] = time.time() - 1; challenges._save(d)
    asyncio.run(challenges.tick([srv]))
    c = challenges.list_for(srv.id)[0]
    assert c["winners"] == ["Gimli_Jr", "Tyler"] and ("Tyler", "minecraft:golden_apple", 1) in srv.given
    assert [g["player"] for g in challenges.gifts_for(srv.id)] == ["Gimli_Jr"]                 # kept for later
    srv.online = ["Tyler", "Gimli_Jr"]
    asyncio.run(challenges.on_join(srv, "Gimli_Jr"))
    assert ("Gimli_Jr", "minecraft:golden_apple", 1) in srv.given and challenges.gifts_for(srv.id) == []


def test_validation_and_cancel(fake):
    challenges, srv, _ = fake
    with pytest.raises(ValueError):
        challenges.create(srv.id, {"kind": "nope", "prize": {"item": "diamond"}})
    with pytest.raises(ValueError):
        challenges.create(srv.id, {"kind": "fish", "prize": {}})
    with pytest.raises(ValueError):
        challenges.create(srv.id, {"kind": "fish", "start": time.time() - 3600, "prize": {"item": "diamond"}})
    for gone in ("diamonds", "logs", "stone", "breed", "jumps"):
        with pytest.raises(ValueError):
            challenges.create(srv.id, {"kind": gone, "prize": {"item": "diamond"}})
    assert {k["key"] for k in challenges.kinds() if not k["retired"]} == {"fish", "mobs", "creepers", "fish_points", "fish_heaviest"}
    c = challenges.create(srv.id, {"kind": "creepers", "start": time.time(), "prize": {"item": "diamond"}})
    asyncio.run(challenges.tick([srv]))
    assert srv.objectives
    assert asyncio.run(challenges.cancel(srv, c["id"])) and not srv.objectives
    assert challenges.list_for(srv.id)[0]["state"] == "cancelled"


def test_api(client, viewer, sid):
    assert viewer.get(f"/api/servers/{sid}/challenges").status_code == 403
    d = client.get(f"/api/servers/{sid}/challenges").json()
    assert any(k["key"] == "fish" for k in d["kinds"])
    r = client.post(f"/api/servers/{sid}/challenges", json={"kind": "fish", "start": time.time() + 3600, "minutes": 10, "prize": {"item": "diamond", "count": 3}})
    assert r.status_code == 200
    cid = r.json()["id"]
    assert client.put(f"/api/servers/{sid}/challenges/{cid}", json={"minutes": 15}).json()["minutes"] == 15
    assert client.post(f"/api/servers/{sid}/challenges", json={"kind": "fish"}).status_code == 400
    assert client.delete(f"/api/servers/{sid}/challenges/{cid}").json() == {"ok": True}
    from app import settings_store
    settings_store.save_section("challenges", {})


def test_chat_api(client, viewer, sid):
    from app import db
    assert viewer.get(f"/api/servers/{sid}/chat").status_code == 403
    eid = db.add_event(sid, time.time(), "chat", "hello from the game", "Tyler")
    try:
        _chat_checks(client, sid)
    finally:
        db.x("DELETE FROM events WHERE id=?", (eid,))            # other tests read the newest events


def _chat_checks(client, sid):
    d = client.get(f"/api/servers/{sid}/chat").json()
    assert d["items"][-1]["message"] == "hello from the game" and "online" in d
    last = d["items"][-1]["id"]
    assert client.get(f"/api/servers/{sid}/chat?after={last}").json()["items"] == []
    assert client.post(f"/api/servers/{sid}/chat", json={"message": "  "}).status_code == 400
    assert client.post(f"/api/servers/{sid}/chat", json={"message": "hi", "to": "bad name!"}).status_code == 400


def test_countdown_bar_and_warnings():
    from app import bossbar

    class Srv:
        cmds = []

        async def rcon(self, cmd):
            self.cmds.append(cmd)
            return ""
    srv, st = Srv(), {}
    asyncio.run(bossbar.show(srv, st, "c_x", "Biggest catch", time.time() + 400, 900))
    assert any(c.startswith("bossbar add solstone:c_x") for c in srv.cmds) and any("max 900" in c for c in srv.cmds)
    n = len(srv.cmds)
    asyncio.run(bossbar.show(srv, st, "c_x", "Biggest catch", time.time() + 400, 900))
    assert len(srv.cmds) == n                                    # not again within a few seconds
    assert bossbar.due_warning(st, time.time() + 290, 900) == 5 and bossbar.due_warning(st, time.time() + 290, 900) is None
    assert bossbar.due_warning({}, time.time() + 290, 300) is None                     # a 5-minute contest: no "5 minutes left"
    asyncio.run(bossbar.hide(srv, st))
    assert srv.cmds[-1] == "bossbar remove solstone:c_x" and not st["bar"]


def test_live_scoreboard_for_status_page(monkeypatch):
    from app import challenges
    c = {"id": "x1", "server": "s1", "kind": "fish_heaviest", "name": "Big one", "state": "running", "ends_at": 2000.0,
         "scores": {"amy": 162, "bo": 300, "cy": 0}}
    monkeypatch.setattr(challenges, "_load", lambda: {"items": [c, {**c, "id": "x2", "server": "other"}], "gifts": []})
    live = challenges.live("s1")
    assert len(live) == 1 and live[0]["ends_at"] == 2000.0
    assert [(r["name"], r["value"]) for r in live[0]["rows"]] == [("bo", "30 lb"), ("amy", "16.2 lb"), ("cy", "0 lb")]


def test_contest_rods_given_and_taken_back(fake):
    challenges, srv, _p = fake
    challenges.create(srv.id, {"kind": "fish_heaviest", "minutes": 10, "lure": 5, "prize": {"item": "diamond", "count": 1}})
    asyncio.run(challenges.tick([srv]))
    gives = [c for c in srv.cmds if c.startswith("give ") and "fishing_rod" in c]
    assert len(gives) == 2 and '"minecraft:lure":5' in gives[0] and "solrod:1b" in gives[0]
    asyncio.run(challenges.on_join(srv, "Tyler"))                       # already has one
    assert len([c for c in srv.cmds if c.startswith("give ") and "fishing_rod" in c]) == 2
    srv.online.remove("Gimli_Jr")
    d = challenges._load(); d["items"][0]["ends_at"] = time.time() - 1; challenges._save(d)
    asyncio.run(challenges.tick([srv]))
    assert "clear tyler minecraft:fishing_rod[minecraft:custom_data={solrod:1b}]" in srv.cmds
    assert challenges._load()["items"][0]["rod_owed"] == ["gimli_jr"]
    asyncio.run(challenges.on_join(srv, "Gimli_Jr"))                    # back later: theirs goes too
    assert "clear Gimli_Jr minecraft:fishing_rod[minecraft:custom_data={solrod:1b}]" in srv.cmds
    assert challenges._load()["items"][0]["rod_owed"] == []
    assert challenges.clean({"kind": "mobs", "lure": 5, "prize": {"item": "dirt"}}, "x")["lure"] == 0     # rods only for fishing


def test_fishing_hot_zone_bonus(fake):
    challenges, srv, _p = fake
    challenges.create(srv.id, {"kind": "fish_points", "minutes": 10, "hot": True, "hot_bonus": 3, "hot_on": 30, "hot_off": 10,
                               "prize": {"item": "diamond", "count": 1}})
    c = challenges._load()["items"][0]
    assert c["hot"] and c["hot_bonus"] == 3 and c["hot_on"] == 30 and c["hot_off"] == 10
    asyncio.run(challenges.tick([srv]))
    d = challenges._load(); d["items"][0]["hot_zone"] = {"on": True, "x": 100.5, "y": 62, "z": 50.5, "until": time.time() + 30}; challenges._save(d)
    fish = {"name": "Bluegill", "lb": "0.5", "weight": 0.5, "quality": 1, "quality_name": "Normal", "points": 10}
    asyncio.run(challenges.on_catch(srv, "Tyler", {**fish, "pos": [102.0, 62.0, 52.0]}))           # cast into it
    assert "scoreboard players add Tyler solfish_cp 20" in srv.cmds and any("×3 hot zone" in x and "+30 points" in x for x in srv.said)
    n = len(srv.cmds)
    asyncio.run(challenges.on_catch(srv, "Gimli_Jr", {**fish, "pos": [140.0, 62.0, 52.0]}))        # well outside
    assert not any("players add" in x for x in srv.cmds[n:])
    asyncio.run(challenges.on_catch(srv, "Gimli_Jr", {**fish, "pos": None}))                      # an older pack: no position, no bonus
    assert not any("players add" in x for x in srv.cmds[n:])
    assert "hot zone open" in challenges.live(srv.id)[0]["sub"]
