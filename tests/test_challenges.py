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

    def rcon_conf(self):
        return {"host": "x"}

    async def rcon(self, cmd):
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
        return ""


@pytest.fixture()
def fake(monkeypatch):
    from app import challenges, settings_store
    from app import servers as S
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
    c = challenges.create(srv.id, {"kind": "fish", "start": time.time() + 1, "minutes": 10,
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
    banner = challenges.banners(srv.id)[0]
    assert banner["text"] == "Fishing contest: Gimli_Jr leads with 7 fish" and banner["countdown"]
    d = challenges._load(); d["items"][0]["ends_at"] = time.time() - 1; challenges._save(d)
    asyncio.run(challenges.tick([srv]))                              # time's up
    c = challenges.list_for(srv.id)[0]
    assert c["state"] == "done" and c["winners"] == ["Gimli_Jr"] and c["seconds"] == ["Tyler"]
    assert ("Gimli_Jr", "minecraft:diamond", 5) in srv.given and ("Tyler", "minecraft:cookie", 16) in srv.given
    assert c["result"] == "Gimli_Jr won Fishing contest with 7 fish!" and not srv.objectives      # cleaned up
    assert pushed and pushed[0][2] == "challenge"


def test_ties_offline_winners_and_unknown_blocks(fake):
    challenges, srv, _ = fake
    challenges.create(srv.id, {"kind": "logs", "start": time.time(), "minutes": 5, "prize": {"item": "golden_apple", "count": 1}})
    asyncio.run(challenges.tick([srv]))
    assert not any("pale_oak" in v for v in srv.objectives.values()) and len(srv.objectives) >= 9   # 8 logs + total
    srv.scores[("Tyler", "minecraft.mined:minecraft.oak_log")] = 4
    srv.scores[("Gimli_Jr", "minecraft.mined:minecraft.birch_log")] = 4
    asyncio.run(challenges.tick([srv]))
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
    c = challenges.create(srv.id, {"kind": "jumps", "start": time.time(), "prize": {"item": "diamond"}})
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
