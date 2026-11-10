"""Hide and seek, treasure hunt and archery (incl. HORSE) against a pretend server."""
import asyncio
import re
import time

import pytest

import pytest as _pytest  # noqa: E402

pytestmark = _pytest.mark.usefixtures("easy_vault")      # games keep everyone's things safe: see test_kits

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
    from app import games, gather, settings_store
    from app import servers as S
    monkeypatch.setattr(gather, "LEAD", 0)               # "right now" means now here
    settings_store.save_section("games", {}); settings_store.save_section("challenges", {}); settings_store.save_section("gather", {})
    srv = FakeServer()

    async def online(_s):
        return list(srv.online), "rcon"

    async def live(_s, name):
        return {"gamemode": srv.gm.get(name, "survival")}
    monkeypatch.setattr(S, "online_players", online)
    monkeypatch.setattr(S, "live_player", live)
    monkeypatch.setattr(S, "known_players", lambda _s: {u: {"name": n} for n, u in UUID.items()})
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
    assert "execute in minecraft:overworld run tp MomCrafts -20.0 70.0 25.0" in srv.cmds     # back to her last spot inside
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
    assert r["state"] == "done" and r["result"].startswith("Gimli_Jr found the treasure!") and srv.blocks[(100, 71, -41)] == "air"
    assert r["finder"] == "Gimli_Jr"                    # the chest's things are their prize, once they're home


def test_games_api(client, viewer, sid):
    assert viewer.get(f"/api/servers/{sid}/games").status_code == 403
    assert client.get(f"/api/servers/{sid}/games").json()["runs"] == []
    r = client.post(f"/api/servers/{sid}/games", json={"game": "hideseek", "start": time.time() + 3600, "center": {"x": 0, "y": 64, "z": 0}})
    assert r.status_code == 200
    assert client.post(f"/api/servers/{sid}/games", json={"game": "treasure", "center": {"x": 0, "z": 0}}).status_code == 400   # empty chest
    assert client.delete(f"/api/servers/{sid}/games/{r.json()['id']}").json() == {"ok": True}
    from app import settings_store
    settings_store.save_section("games", {})


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


def test_hide_and_seek_best_of_three_and_no_monsters(game):
    games, srv = game
    real = srv.rcon

    async def rcon(cmd):                                   # the server is on Hard
        if cmd == "difficulty":
            srv.cmds.append(cmd)
            return "The difficulty is Hard"
        return await real(cmd)
    srv.rcon = rcon
    games.create(srv.id, {"game": "hideseek", "center": {"x": 0, "y": 64, "z": 0}, "radius": 40, "hide_secs": 30, "minutes": 5,
                          "seeker": "Tyler", "rounds": 3, "infect": False})
    asyncio.run(games.tick([srv]))
    assert "difficulty peaceful" in srv.cmds and _run(games)["difficulty"] == "hard"
    seekers = []
    for rnd in range(3):
        r = _run(games)
        seeker = next(n for n, p in r["players"].items() if p["role"] == "seeker")
        seekers.append(seeker)
        assert r["round"] == rnd + 1
        hiders = [n for n in r["players"] if n != seeker]
        for i, n in enumerate(r["players"]):
            srv.pos[n] = [5.0 * i, 64.0, 5.0 * i]
        _set(games, phase_ends=time.time() - 1)
        asyncio.run(games.tick([srv]))                     # hiding over
        srv.pos[seeker] = [srv.pos[hiders[0]][0] + 1, 64.0, srv.pos[hiders[0]][2]]       # finds the first hider
        asyncio.run(games.tick([srv]))
        _set(games, phase_ends=time.time() - 1)
        asyncio.run(games.tick([srv]))                     # time's up: the other hider stayed hidden
    assert sorted(seekers) == ["Gimli_Jr", "MomCrafts", "Tyler"]                         # everyone sought once
    r = _run(games)
    assert r["state"] == "done" and sum(p["points"] for p in r["players"].values()) == 9   # each round: 1 for the find, 2 for staying hidden
    top = max(p["points"] for p in r["players"].values())
    assert f"won hide and seek with {top} points" in r["result"]
    assert "difficulty hard" in srv.cmds                                                   # monsters back afterwards
    assert any(c.startswith("scoreboard objectives add solsb_") for c in srv.cmds)
    assert any(c.startswith("scoreboard objectives remove solsb_") for c in srv.cmds)


def test_treasure_hints_fit_the_area_and_where_you_face():
    from app import games
    small, big = games._bands(100), games._bands(500)
    word = lambda bands, d: next(w for lim, w, _c in bands if d < lim)     # noqa: E731
    assert word(small, 5) == word(big, 5) == "Burning hot!" and word(small, 15) == "Hot"
    assert word(small, 200) == "Freezing" and word(big, 200) == "Cool" and word(big, 300) == "Cold" and word(big, 90) == "Warm"
    # yaw 0 faces south (+z); turning right is towards west (-x)
    assert games._relative(0, 0, 10) == "⬆ straight ahead"
    assert games._relative(0, -10, 0).endswith("to your right") and games._relative(0, 10, 0).endswith("to your left")
    assert games._relative(0, 0, -10) == "⬇ behind you" and "ahead, to your right" in games._relative(0, -10, 10)
    assert games._relative(180, 0, -10) == "⬆ straight ahead"           # facing north


def test_the_treasure_compass_points_at_the_chest():
    from types import SimpleNamespace

    from app import games
    srv = SimpleNamespace(mc_version="26.3")
    c = games._treasure_compass(srv, {"dim": "minecraft:overworld", "chest": {"x": 10, "y": 64, "z": -5}})
    assert "lodestone_tracker" in c and "pos:[I;10,64,-5]" in c and "solkit:1b" in c and "tracked:false" in c
