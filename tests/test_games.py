"""Hide and seek, treasure hunt and archery (incl. HORSE) against a pretend server."""
import asyncio
import re
import time

import pytest

UUID = {"Tyler": "00000001-0000-0002-0000-000300000001", "Gimli_Jr": "00000001-0000-0002-0000-000300000002",
        "MomCrafts": "00000001-0000-0002-0000-000300000003"}


def _ints(u):
    h = u.replace("-", "")
    return [int(h[i:i + 8], 16) - (1 << 32) * (int(h[i:i + 8], 16) >= 1 << 31) for i in range(0, 32, 8)]


class FakeServer:
    is_java = True

    def __init__(self, names=("Tyler", "Gimli_Jr", "MomCrafts")):
        self.id, self.display_name, self.mc_version = "game-srv", "Family", "26.1"
        self.online = list(names)
        self.pos = {n: [0.0, 64.0, 0.0] for n in names}
        self.cmds, self.said, self.gm, self.teams, self.blocks = [], [], {n: "survival" for n in names}, {}, {}
        self.chest_items = None
        self.log = []

    def rcon_conf(self):
        return {"host": "x"}

    def add_log(self, k, who, pos=None, s=0):
        self.log.append((k, who, pos, s, len(self.log) + 1))

    async def rcon(self, cmd):
        self.cmds.append(cmd)
        m = re.match(r"data get entity (\w+) Pos", cmd)
        if m:
            x, y, z = self.pos[m.group(1)]
            return f"{m.group(1)} has the following entity data: [{x}d, {y}d, {z}d]"
        if "data get entity @e[tag=solth_" in cmd:
            return "Marker has the following entity data: [100.5d, 71.0d, -40.5d]"
        m = re.match(r"gamemode (\w+) (\w+)", cmd)
        if m:
            self.gm[m.group(2)] = m.group(1)
            return ""
        m = re.match(r"team join (\w+) (\w+)", cmd)
        if m:
            self.teams[m.group(2)] = m.group(1)
        m = re.search(r"setblock (-?\d+) (-?\d+) (-?\d+) minecraft:(\w+)", cmd)
        if m:
            self.blocks[(int(m.group(1)), int(m.group(2)), int(m.group(3)))] = m.group(4)
            if m.group(4) == "chest":
                self.chest_items = "full"
            return "Changed the block"
        if "data get block" in cmd and "Items" in cmd:
            return "100, 71, -41 has the following block data: [{Slot: 0b, id: \"minecraft:diamond\", count: 5}]" if self.chest_items == "full" else "Found no elements matching Items"
        if cmd == "data get storage solstone:games log":
            body = ", ".join(("{k: \"%s\", u: [I; %s], %si: %d}" % (k, ", ".join(map(str, _ints(UUID[w]))),
                              (f"p: [{p[0]}d, {p[1]}d, {p[2]}d], " if p else "") + (f"s: {s}, " if s else ""), i)) for k, w, p, s, i in self.log)
            return f"Storage solstone:games has the following contents: [{body}]"
        if cmd.startswith("execute if block"):
            return "Test passed"
        if cmd.startswith("tellraw") or cmd.startswith("title"):
            self.said.append(cmd)
        return ""


@pytest.fixture()
def game(monkeypatch):
    from app import games, settings_store
    from app import servers as S
    settings_store.save_section("games", {}); settings_store.save_section("challenges", {})
    srv = FakeServer()

    async def online(_s):
        return list(srv.online), "rcon"

    async def live(_s, name):
        return {"gamemode": srv.gm.get(name, "survival")}
    monkeypatch.setattr(S, "online_players", online)
    monkeypatch.setattr(S, "live_player", live)
    monkeypatch.setattr(S, "known_players", lambda _s: {u: {"name": n} for n, u in UUID.items()})
    monkeypatch.setattr(games.fwshow, "push", lambda *a, **k: None)
    yield games, srv
    settings_store.save_section("games", {}); settings_store.save_section("challenges", {})


def _set(games, **kv):
    d = games._load()
    d["runs"][0].update(kv)
    games._save(d)


def _run(games):
    return games._load()["runs"][0]


def test_hide_and_seek(game):
    games, srv = game
    games.create(srv.id, {"game": "hideseek", "center": {"x": 0, "y": 64, "z": 0}, "radius": 40, "hide_secs": 30, "minutes": 5,
                          "seeker": "Tyler", "prizes": [{"item": "cookie", "count": 8}]})
    asyncio.run(games.tick([srv]))
    r = _run(games)
    assert r["state"] == "hiding" and r["players"]["Tyler"]["role"] == "seeker"
    assert srv.gm["Gimli_Jr"] == "adventure" and srv.teams["Gimli_Jr"] == "solhs_h" and srv.teams["Tyler"] == "solhs_s"
    assert any("nametagVisibility never" in c for c in srv.cmds) and any("blindness" in c and "Tyler" in c for c in srv.cmds)
    assert games.hidden_from_map(srv.id) == {"Gimli_Jr", "MomCrafts"}
    srv.pos["Gimli_Jr"] = [30.0, 64.0, 0.0]; srv.pos["MomCrafts"] = [-20.0, 70.0, 25.0]
    _set(games, phase_ends=time.time() - 1)
    asyncio.run(games.tick([srv]))
    assert _run(games)["state"] == "running" and any("effect clear Tyler" in c for c in srv.cmds)
    asyncio.run(games.on_chat(srv, "Tyler", "Marco!"))                     # where are they?
    polo = [c for c in srv.said if c.startswith("tellraw Tyler") and "Polo" in c][-1]
    assert "east" in polo and "north-west" not in polo and "south-west" in polo
    srv.pos["MomCrafts"] = [100.0, 64.0, 0.0]                                # ran out of the area
    srv.pos["Tyler"] = [29.0, 64.0, 1.0]                                     # next to Gimli_Jr
    asyncio.run(games.tick([srv]))
    r = _run(games)
    assert r["players"]["Gimli_Jr"]["role"] == "seeker" and srv.teams["Gimli_Jr"] == "solhs_s"      # infection
    assert any(c.startswith("execute in minecraft:overworld run spreadplayers") and c.endswith("MomCrafts") for c in srv.cmds)
    srv.pos["MomCrafts"] = [10.0, 64.0, 10.0]; srv.pos["Gimli_Jr"] = [11.0, 64.0, 11.0]
    asyncio.run(games.tick([srv]))
    r = _run(games)
    assert r["state"] == "done" and "Tyler found everyone" in r["result"]
    assert srv.gm["Gimli_Jr"] == "survival" and any(c == "team remove solhs_h" for c in srv.cmds)
    assert not games.hidden_from_map(srv.id)


def test_treasure_hunt(game):
    games, srv = game
    games.create(srv.id, {"game": "treasure", "center": {"x": 0, "z": 0}, "radius": 150, "minutes": 10, "hint_after": 0,
                          "spot": {"x": 100, "z": -41}, "items": [{"item": "diamond", "count": 5}]})
    asyncio.run(games.tick([srv]))
    r = _run(games)
    assert r["chest"] == {"x": 100, "y": 71, "z": -41} and srv.blocks[(100, 71, -41)] == "chest"
    assert any('Items:[{Slot:0b,id:"minecraft:diamond",count:5}]' in c for c in srv.cmds)
    asyncio.run(games.tick([srv]))
    bars = [c for c in srv.cmds if c.startswith("title Tyler actionbar")]
    assert "Freezing" in bars[-1] or "Cold" in bars[-1]
    srv.pos["Gimli_Jr"] = [99.0, 71.0, -40.0]
    srv.chest_items = None                                                   # someone emptied it
    asyncio.run(games.tick([srv]))
    r = _run(games)
    assert r["state"] == "done" and r["result"] == "Gimli_Jr found the treasure!" and srv.blocks[(100, 71, -41)] == "air"


def test_archery_points(game):
    games, srv = game
    games.create(srv.id, {"game": "archery", "mode": "points", "target": {"x": 0, "y": 65, "z": 0}, "place_target": True, "minutes": 5})
    asyncio.run(games.tick([srv]))
    assert srv.blocks[(0, 65, 0)] == "target" and any(c == "give @a minecraft:arrow 64" for c in srv.cmds)
    srv.add_log("shot", "Tyler", (0.5, 65.0, 20.5)); srv.add_log("hit", "Tyler", (0.5, 65, 20.5), 15)      # bullseye from 20 blocks
    srv.add_log("shot", "Gimli_Jr", (0.5, 65.0, 10.5)); srv.add_log("hit", "Gimli_Jr", (0.5, 65, 10.5), 5)
    asyncio.run(games.tick([srv]))
    r = _run(games)
    assert r["players"]["Tyler"]["points"] == 45 and r["players"]["Gimli_Jr"]["points"] == 10       # 15 x 3, 5 x 2
    srv.add_log("shot", "MomCrafts", (5.0, 65.0, 5.0))                                                 # a miss: no hit follows
    asyncio.run(games.tick([srv]))
    for s in _run(games)["pending"]["MomCrafts"]:
        s["at"] -= 10
    d = games._load(); d["runs"][0]["pending"]["MomCrafts"][0]["at"] -= 10; games._save(d)
    asyncio.run(games.tick([srv]))
    assert _run(games)["players"]["MomCrafts"]["shots"] == 1 and _run(games)["players"]["MomCrafts"]["hits"] == 0
    _set(games, phase_ends=time.time() - 1)
    asyncio.run(games.tick([srv]))
    r = _run(games)
    assert r["state"] == "done" and r["result"].startswith("Tyler won Archery: most points with 45 points") and srv.blocks[(0, 65, 0)] == "air"


def test_archery_horse(game):
    games, srv = game
    srv.online = ["Tyler", "Gimli_Jr"]
    games.create(srv.id, {"game": "archery", "mode": "horse", "word": "PIG", "target": {"x": 0, "y": 65, "z": 0}, "give_bow": False})
    asyncio.run(games.tick([srv]))
    r = _run(games)
    assert r["turn"] == "Gimli_Jr" and r["order"] == ["Gimli_Jr", "Tyler"]
    srv.add_log("shot", "Gimli_Jr", (10.5, 65.0, 0.5)); srv.add_log("hit", "Gimli_Jr", None, 9)
    asyncio.run(games.tick([srv]))
    r = _run(games)
    assert r["spot"]["x"] == 10.5 and r["turn"] == "Tyler"
    srv.add_log("shot", "Tyler", (0.5, 65.0, 20.5)); srv.add_log("hit", "Tyler", None, 15)              # not from the spot: doesn't count
    asyncio.run(games.tick([srv]))
    assert _run(games)["turn"] == "Tyler" and _run(games)["players"]["Tyler"]["letters"] == ""
    for _ in range(3):                                                                                   # Tyler misses from the spot 3 times
        srv.add_log("shot", "Tyler", (10.0, 65.0, 1.0))
        asyncio.run(games.tick([srv]))
        d = games._load(); [s.update(at=s["at"] - 10) for s in d["runs"][0]["pending"].get("Tyler", [])]; games._save(d)
        asyncio.run(games.tick([srv]))
        r = _run(games)
        if r["state"] == "done":
            break
        # Gimli sets again and makes it, Tyler's turn again
        srv.add_log("shot", "Gimli_Jr", (10.5, 65.0, 0.5)); srv.add_log("hit", "Gimli_Jr", None, 9)
        asyncio.run(games.tick([srv]))
    r = _run(games)
    assert r["players"]["Tyler"]["letters"] == "PIG" and r["state"] == "done" and r["result"] == "Gimli_Jr won Archery: PIG!"


def test_games_api(client, viewer, sid):
    assert viewer.get(f"/api/servers/{sid}/games").status_code == 403
    assert client.get(f"/api/servers/{sid}/games").json()["runs"] == []
    r = client.post(f"/api/servers/{sid}/games", json={"game": "hideseek", "start": time.time() + 3600, "center": {"x": 0, "y": 64, "z": 0}})
    assert r.status_code == 200
    assert client.post(f"/api/servers/{sid}/games", json={"game": "treasure", "center": {"x": 0, "z": 0}}).status_code == 400   # empty chest
    assert client.delete(f"/api/servers/{sid}/games/{r.json()['id']}").json() == {"ok": True}
    from app import settings_store
    settings_store.save_section("games", {})
