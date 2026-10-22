"""Hide and seek, treasure hunt and archery (incl. HORSE) against a pretend server."""
import asyncio
import math
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
        self.ground = {}                     # (x, z) -> the block under the surface there (grass if not given)
        self.floor = {}                      # (x, z) -> the bottom of the water there

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
        m = re.search(r"positioned (-?\d+) 320 (-?\d+) positioned over (\w+)", cmd)
        if m:
            self.last_probe = (int(m.group(1)), int(m.group(2)), m.group(3))
        if "data get entity @e[tag=solth_" in cmd:
            x, z, hm = getattr(self, "last_probe", (100, -41, ""))
            y = self.floor.get((x, z), 60) if hm == "ocean_floor" else 71
            return f"Marker has the following entity data: [{x}.5d, {y}.0d, {z}.5d]"
        m = re.match(r"execute in \S+ if block (-?\d+) (-?\d+) (-?\d+) (\S+)", cmd)
        if m:
            here = self.ground.get((int(m.group(1)), int(m.group(3))), "minecraft:grass_block")
            return "Test passed" if m.group(4) == here else "Test failed"
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
    assert r["players"]["Tyler"]["points"] == 60 and r["players"]["Gimli_Jr"]["points"] == 10       # 15 x 4 (20 blocks), 5 x 2 (10)
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
    assert r["state"] == "done" and r["result"].startswith("Tyler won Archery: most points with 60 points") and srv.blocks[(0, 65, 0)] == "air"


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


def test_archery_hot_zone_and_big_shot_flair(game):
    games, srv = game
    games.create(srv.id, {"game": "archery", "mode": "points", "target": {"x": 0, "y": 65, "z": 0}, "minutes": 5, "hot": True, "hot_bonus": 2, "hot_far": 30})
    asyncio.run(games.tick([srv]))
    _set(games, started=time.time() - 30)                               # the first zone opens 15 s in
    asyncio.run(games.tick([srv]))
    z = _run(games)["hot_zone"]
    assert z["on"] and 10 <= math.hypot(z["x"] - 0.5, z["z"] - 0.5) <= 31
    assert any("waypoint modify @e[tag=solhot_" in c and "color red" in c for c in srv.cmds)
    srv.add_log("shot", "Tyler", (z["x"] + 1, 65.0, z["z"])); srv.add_log("hit", "Tyler", (z["x"], 65, z["z"]), 10)
    asyncio.run(games.tick([srv]))
    d = math.dist((z["x"] + 1, 65.0, z["z"]), (0.5, 65.5, 0.5))
    assert _run(games)["players"]["Tyler"]["points"] == round(10 * games._multiplier(d) * 2)
    shout = next(c for c in srv.cmds if c.startswith("tellraw @a") and "ring 10" in c)
    assert "×2" in shout and "♨" in shout
    # close it: the marker and sign go, and the next one waits
    _set(games, hot_zone={**z, "until": time.time() - 1})
    asyncio.run(games.tick([srv]))
    assert not _run(games)["hot_zone"]["on"] and any(c.startswith("kill @e[tag=solhot_") for c in srv.cmds)


def test_hit_tiers():
    from app import games
    assert games._tier(2)[2] == "" and games._tier(4)[2] == "Nice shot! " and games._tier(12)[2] == "AMAZING SHOT! " and games._tier(30)[2] == "LEGENDARY SHOT! "
    assert [games._multiplier(x) for x in (10, 20, 30, 50, 70)] == [2.0, 4.0, 6.8, 14.1, 23.5]


def test_hot_zone_surface_tells_water_from_land():
    from app import hotzone

    class W:
        mc_version = "26.3"

        async def rcon(self, cmd):
            if "data get entity @e[tag=" in cmd:
                return "Marker has the following entity data: [10.5d, 63.0d, 4.5d]"
            if "if block 10 62 4 minecraft:water" in cmd:
                return "Test passed"
            if "if block" in cmd:
                return "Test failed"
            return ""
    w = W()
    assert asyncio.run(hotzone.surface(w, "minecraft:overworld", 10, 4, "t")) == (63, "water")
    assert asyncio.run(hotzone.surface(w, "minecraft:overworld", 11, 4, "t")) == (63, "land")


class SpleefServer(FakeServer):
    """Adds what spleef asks: dimensions, the pack's storage, fills, teleports."""
    def __init__(self, pack=10):
        super().__init__()
        self.pack, self.storage, self.fills, self.tps, self.hb = pack, None, [], [], None

    async def rcon(self, cmd):
        if re.match(r"data get entity \w+ Dimension", cmd):
            return 'Tyler has the following entity data: "minecraft:overworld"'
        if cmd == "data get storage solstone:games pack":
            return f"Storage solstone:games has the following contents: {{version: {self.pack}}}"
        if cmd.startswith("data modify storage solstone:games spleef set value"):
            self.storage = cmd
            return "Modified storage"
        if cmd == "data remove storage solstone:games spleef":
            self.storage = None
            return "Modified storage"
        if cmd == "data get storage solstone:games spleef.arena":
            return "Storage solstone:games has the following contents: {x1: \"0\"}" if self.storage else "Found no elements matching spleef.arena"
        m = re.match(r"scoreboard players set #spleef_hb solg_tmp (\d+)", cmd)
        if m:
            self.hb = int(m.group(1))
        if " run fill " in cmd:
            self.fills.append(cmd)
            return "Successfully filled 10 block(s)"
        m = re.search(r" run tp (\w+) (-?[\d.]+) (-?[\d.]+) (-?[\d.]+)", cmd)
        if m:
            if m.group(1) not in self.online:
                return "No entity was found"
            self.pos[m.group(1)] = [float(m.group(2)), float(m.group(3)), float(m.group(4))]
            self.tps.append(m.group(1))
            return f"Teleported {m.group(1)}"
        return await super().rcon(cmd)


@pytest.fixture()
def spleef_game(game, monkeypatch):
    games, _plain = game
    from app import servers as S
    srv = SpleefServer()

    async def online(_s):
        return list(srv.online), "rcon"

    async def live(_s, name):
        return {"gamemode": srv.gm.get(name, "survival")}
    monkeypatch.setattr(S, "online_players", online)
    monkeypatch.setattr(S, "live_player", live)
    return games, srv


def test_spleef_rounds_teams_and_everyone_goes_back(spleef_game):
    games, srv = spleef_game
    srv.pos.update({"Tyler": [10.0, 70.0, 10.0], "Gimli_Jr": [-5.0, 64.0, 3.0], "MomCrafts": [100.0, 80.0, 100.0]})
    srv.gm["MomCrafts"] = "creative"
    games.create(srv.id, {"game": "spleef", "center": {"x": 0, "y": 64, "z": 0}, "size": 8, "layers": 2, "best_of": 3, "shrink": True})
    asyncio.run(games.tick([srv]))
    r = _run(games)
    assert r["state"] == "countdown" and r["round"] == 1 and set(r["players"]) == {"Tyler", "Gimli_Jr", "MomCrafts"}
    assert srv.storage and 'n:"MomCrafts"' in srv.storage and 'g:"creative"' in srv.storage and srv.hb == 2400
    top = r["top"]
    assert top >= 64 + 35 and any("snow_block replace air" in f for f in srv.fills) and any("water replace air" in f for f in srv.fills)
    assert all(srv.pos[n][1] == top + 1 for n in r["players"])                      # everyone up on the arena
    _set(games, phase_ends=time.time() - 1)
    asyncio.run(games.tick([srv]))
    assert _run(games)["state"] == "running" and any("Spleef Shovel" in c for c in srv.cmds)
    # MomCrafts falls through both floors, then Gimli_Jr: Tyler wins round 1
    srv.pos["MomCrafts"][1] = top - 5 - 4
    asyncio.run(games.tick([srv]))
    assert not _run(games)["players"]["MomCrafts"]["alive"]
    srv.pos["Gimli_Jr"][1] = top - 12
    asyncio.run(games.tick([srv]))
    r = _run(games)
    assert r["players"]["Tyler"]["wins"] == 1 and r["round"] == 2 and r["state"] == "countdown"
    # round 2: Gimli_Jr logs off mid-game (out), MomCrafts falls: Tyler wins 2-0, best of 3 over
    _set(games, phase_ends=time.time() - 1)
    asyncio.run(games.tick([srv]))
    srv.online.remove("Gimli_Jr")
    srv.pos["MomCrafts"][1] = top - 20
    asyncio.run(games.tick([srv]))
    r = _run(games)
    assert r["state"] == "done" and r["result"] == "Tyler won spleef!"
    assert srv.pos["Tyler"] == [10.0, 70.0, 10.0] and srv.pos["MomCrafts"] == [100.0, 80.0, 100.0] and "gamemode creative MomCrafts" in srv.cmds
    assert srv.storage is None and srv.hb == 0
    assert any("air replace minecraft:snow_block" in f for f in srv.fills) and any("air replace minecraft:glass" in f for f in srv.fills)
    assert set(r["owed"]) == {"Gimli_Jr"}                                            # offline at the end
    srv.online.append("Gimli_Jr")
    asyncio.run(games.on_join(srv, "Gimli_Jr"))
    assert srv.pos["Gimli_Jr"] == [-5.0, 64.0, 3.0] and not _run(games)["owed"]


def test_spleef_stops_if_the_pack_safety_net_went_off(spleef_game):
    games, srv = spleef_game
    games.create(srv.id, {"game": "spleef", "center": {"x": 0, "y": 64, "z": 0}, "teams": True})
    asyncio.run(games.tick([srv]))
    r = _run(games)
    assert r["name"] == "Team spleef" and {p["team"] for p in r["players"].values()} == {"red", "blue"}
    srv.storage = None                                                   # Solstone was away; the pack cleaned up
    asyncio.run(games.tick([srv]))
    r = _run(games)
    assert r["state"] == "done" and "taken down" in r["result"]


def test_spleef_needs_the_newer_pack(spleef_game):
    games, srv = spleef_game
    srv.pack = 9
    games.create(srv.id, {"game": "spleef", "center": {"x": 0, "y": 64, "z": 0}})
    asyncio.run(games.tick([srv]))
    assert _run(games)["state"] == "skipped" and "version 10" in _run(games)["result"] and srv.storage is None


def test_pack_has_the_spleef_safety_net():
    from app import fishpack
    f = fishpack.pack_files(True)
    tick = f["data/solgames/function/tick.mcfunction"]
    assert "#spleef_hb solg_tmp matches 1.." in tick and "function solgames:spleef_failsafe" in tick
    assert all(line.startswith("$") for line in f["data/solgames/function/spleef_back1.mcfunction"].strip().splitlines())
    assert "replace minecraft:snow_block" in f["data/solgames/function/spleef_clear.mcfunction"]


def test_treasure_avoids_water_unless_allowed(game):
    games, srv = game
    srv.ground[(100, -41)] = "minecraft:water"
    games.create(srv.id, {"game": "treasure", "center": {"x": 0, "z": 0}, "radius": 150, "spot": {"x": 100, "z": -41},
                          "items": [{"item": "diamond", "count": 1}]})
    asyncio.run(games.tick([srv]))
    r = _run(games)
    assert (r["chest"]["x"], r["chest"]["z"]) != (100, -41) and not r["underwater_spot"]   # moved somewhere dry nearby
    assert abs(r["chest"]["x"] - 100) <= 9 and abs(r["chest"]["z"] + 41) <= 9


def test_treasure_on_the_bottom_when_underwater_is_allowed(game):
    games, srv = game
    srv.ground[(100, -41)] = "minecraft:water"
    srv.floor[(100, -41)] = 55
    games.create(srv.id, {"game": "treasure", "center": {"x": 0, "z": 0}, "radius": 150, "spot": {"x": 100, "z": -41}, "underwater": True,
                          "items": [{"item": "diamond", "count": 1}]})
    asyncio.run(games.tick([srv]))
    r = _run(games)
    assert r["chest"] == {"x": 100, "y": 55, "z": -41} and r["underwater_spot"]
    assert any("minecraft:chest[waterlogged=true]" in c for c in srv.cmds)
    asyncio.run(games.cancel(srv, r["id"]))
    assert any(c.endswith("setblock 100 55 -41 minecraft:water") for c in srv.cmds)        # the water put back, no air pocket
