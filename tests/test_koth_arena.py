"""King of the Hill and the mob arena: the rules, and a whole game against a pretend server (everyone's own things
kept safe and given back exactly)."""
import asyncio
import re

import pytest
from test_kits import U1, U2, FakeGame, own, setup_vault

from app import arena, battle, control, games, kits, koth, settings_store

HILL = {"x": 0, "y": 64, "z": 0}


class FightGame(FakeGame):
    """The vault's pretend server, plus game rules, scores and where everyone is."""

    def __init__(self):
        super().__init__()
        self.rules = {"keepInventory": "false", "doImmediateRespawn": "false", "mobGriefing": "true", "doDaylightCycle": "true"}
        self.daytime = 6000
        self.watching: set[str] = set()                 # in creative or spectator
        self.scores: dict[tuple, int] = {}
        self.pos = {"Alex": ("minecraft:overworld", 0.0, 64.0, 0.0), ".LongBedrockNameX": ("minecraft:overworld", 30.0, 64.0, 0.0)}

    async def rcon(self, cmd, wait=None):
        if m := re.fullmatch(r"gamerule (\S+)(?: (\S+))?", cmd):
            if m.group(1) not in self.rules:
                return "Unknown game rule"
            if m.group(2):
                self.rules[m.group(1)] = m.group(2)
                return f"Gamerule {m.group(1)} is now set to: {m.group(2)}"
            return f"Gamerule {m.group(1)} is currently set to: {self.rules[m.group(1)]}"
        if m := re.fullmatch(r"execute as (\S+) if entity @s\[gamemode=!spectator,gamemode=!creative\]", cmd):
            return "Test failed" if m.group(1) in self.watching else "Test passed"
        if m := re.fullmatch(r"execute in \S+ run spreadplayers (-?[\d.]+) (-?[\d.]+) 0 1 false (\S+)", cmd):
            self.pos[m.group(3)] = ("minecraft:overworld", float(m.group(1)), 64.0, float(m.group(2)))
            return "Spread 1 player"
        if cmd == "time query daytime":
            return f"The time is {self.daytime}"
        if m := re.fullmatch(r"time set (\d+)", cmd):
            self.daytime = int(m.group(1))
            return f"Set the time to {self.daytime}"
        if m := re.fullmatch(r"scoreboard players get (\S+) (\S+)", cmd):
            return f"x has {self.scores.get((m.group(1), m.group(2)), 0)} [{m.group(2)}]"
        return await super().rcon(cmd, wait)


@pytest.fixture
def fight(monkeypatch):
    setup_vault(monkeypatch)
    g = FightGame()
    control._rule_names.pop(g.id, None)
    names = {U1: "Alex", U2: ".LongBedrockNameX"}

    async def online(srv):
        return [names[u] for u in g.online], "rcon"

    async def everyone(srv):
        return {n: p for n, p in g.pos.items() if any(names[u] == n for u in g.online)}
    monkeypatch.setattr(battle.S, "online_players", online)
    monkeypatch.setattr(battle.S, "known_players", lambda srv: {U1: {"name": "Alex"}, U2: {"name": ".LongBedrockNameX"}})
    import app.adventures
    monkeypatch.setattr(app.adventures, "_everyone", everyone)

    async def nothing(*a, **k):
        return None
    for mod in (koth.hud, arena.hud):
        monkeypatch.setattr(mod, "scores", nothing)
        monkeypatch.setattr(mod, "status", nothing)
        monkeypatch.setattr(mod, "clear", nothing)
    monkeypatch.setattr(games, "_award", nothing)
    monkeypatch.setattr(games, "_finish", lambda srv, r, result: r.update(state="done", result=result))
    yield g
    control._rule_names.pop(g.id, None)
    settings_store.save_section(kits.SECTION, {})


def _koth(teams=0):
    r = {"id": "k1", "game": "koth", "name": "King of the Hill", "dim": "minecraft:overworld", "players": {}, "teams": {},
         "entrants": ["Alex", ".LongBedrockNameX"], "optin": False}
    r.update(koth.settings({"center": HILL, "radius": 5, "spawns": [{"x": 20, "y": 64, "z": 0}, {"x": -20, "y": 64, "z": 0}],
                            "team_count": teams, "minutes": 3, "kit": {"armour": "diamond"}}, games._num, games._point))
    return r


def test_koth_a_whole_game_and_everything_back(fight):
    before = {u: dict(s) for u, s in fight.slots.items()}
    r = _koth()
    asyncio.run(koth.start(fight, r))
    assert r["state"] == "running" and set(r["players"]) == {"Alex", ".LongBedrockNameX"}
    assert fight.rules["keepInventory"] == "true" and fight.rules["doImmediateRespawn"] == "true"
    assert not own(fight.slots[U1]) and not own(fight.slots[U2])                                # their own things are in the vault
    assert any("diamond_chestplate[minecraft:custom_data={solkit:1b}" in c for c in fight.said)   # the kit, marked as the game's
    for _ in range(3):                                                                 # Alex alone on the hill: 3 points
        asyncio.run(koth.tick(fight, r))
    assert r["players"]["Alex"]["score"] == 3 and r["players"][".LongBedrockNameX"]["score"] == 0
    fight.pos[".LongBedrockNameX"] = ("minecraft:overworld", 1.0, 64.0, 1.0)          # both on it: contested, nobody scores
    asyncio.run(koth.tick(fight, r))
    assert r["players"]["Alex"]["score"] == 3 and r["holder"] == "contested"
    fight.scores[(U1, "solkoth_d")] = 1                                                # Alex died: off the hill for the countdown
    asyncio.run(koth.tick(fight, r))
    assert r["players"]["Alex"].get("back_at") and r["players"][".LongBedrockNameX"]["score"] == 1
    assert any(c == f"gamemode spectator {U1}" for c in fight.said)
    r["phase_ends"] = 0
    asyncio.run(koth.tick(fight, r))
    assert r["state"] == "done" and "won King of the Hill" in r["result"]
    assert fight.slots == before                                                       # exactly as they were
    assert fight.rules["keepInventory"] == "false" and fight.rules["doImmediateRespawn"] == "false"
    assert not kits.waiting(fight.id)


def test_koth_teams_the_side_with_more_on_the_hill_scores():
    r = {"teams": {"red": 0, "blue": 0}, "players": {"a": {"team": "red"}, "b": {"team": "blue"}, "c": {"team": "blue"}, "d": {"team": "blue"}}}
    assert koth._holder(r, ["a", "b", "c", "d"]) == "blue"                              # one red can't hold off three blue
    assert koth._holder(r, ["a", "b"]) is None                                          # level: nobody scores
    assert koth._holder({"players": {"a": {}, "b": {}}}, ["a"]) == "a"
    assert koth._holder({"players": {"a": {}, "b": {}}}, ["a", "b"]) is None


def test_someone_who_leaves_mid_game_gets_their_things_back_when_they_return(fight):
    before = dict(fight.slots[U2])
    r = _koth()
    asyncio.run(koth.start(fight, r))
    del fight.online[U2]                                                               # gone
    asyncio.run(koth.tick(fight, r))
    assert r["players"][".LongBedrockNameX"]["out"] and kits.waiting(fight.id)
    fight.online[U2] = ".LongBedrockNameX"                                             # back while it's still on
    asyncio.run(koth.tick(fight, r))
    assert fight.slots[U2] == before


def test_arena_waves_and_settings():
    assert len(arena.preset("easy")) == 5 and len(arena.preset("hard")) == 10
    assert all(sum(w.values()) <= arena.MAX_PER_WAVE for lvl in ("easy", "normal", "hard") for w in arena.preset(lvl))
    assert arena.clean_waves([{"zombie": 3, "ender_dragon": 1, "skeleton": "two"}, {}]) == [{"zombie": 3}]
    with pytest.raises(ValueError):
        arena.settings({"center": HILL, "mob_spots": []}, games._num, games._point)
    s = arena.settings({"center": HILL, "mob_spots": [{"x": 5, "y": 64, "z": 5}], "level": "custom", "waves": [{"zombie": 2}], "coop": False},
                       games._num, games._point)
    assert s["waves"] == [{"zombie": 2}] and not s["coop"] and s["zone"]["r"] == 15


def test_arena_together_a_wave_then_everything_back(fight):
    before = {u: dict(s) for u, s in fight.slots.items()}
    mobs = {"n": 0}
    real = fight.rcon

    async def rcon(cmd, wait=None):
        if cmd.startswith("execute in minecraft:overworld run summon"):
            mobs["n"] += 1
        if cmd.startswith("execute if entity @e[tag=solarena_a1]"):
            return f"Test passed, count: {mobs['n']}" if mobs["n"] else "Test failed"
        return await real(cmd, wait)
    fight.rcon = rcon
    fight.pos[".LongBedrockNameX"] = ("minecraft:overworld", 2.0, 64.0, 2.0)
    r = {"id": "a1", "game": "arena", "name": "Mob arena", "dim": "minecraft:overworld", "players": {}, "entrants": ["Alex", ".LongBedrockNameX"]}
    r.update(arena.settings({"center": HILL, "mob_spots": [{"x": 5, "y": 64, "z": 5}], "level": "custom", "waves": [{"zombie": 2}]},
                            games._num, games._point))
    asyncio.run(arena.start(fight, r))
    assert fight.rules["mobGriefing"] == "false"                                       # no creeper holes while it runs
    assert fight.daytime == 18000 and fight.rules["doDaylightCycle"] == "false"        # midnight, held there (spiders fight)
    r["next_wave"] = 1                                                                 # (long past)
    asyncio.run(arena.tick(fight, r))                                                  # wave 1: two zombies
    assert mobs["n"] == 2 and r["wave"] == 1
    mobs["n"] = 0                                                                      # defeated
    asyncio.run(arena.tick(fight, r))
    assert r["state"] == "done" and "survived all 1 waves" in r["result"]
    assert fight.slots == before and fight.rules["mobGriefing"] == "true"
    assert fight.daytime == 6000 and fight.rules["doDaylightCycle"] == "true"          # the time of day back as it was


def test_setting_up_both_games(client, sid):
    base = f"/api/servers/{sid}/games"
    d = client.get(base).json()
    assert "zombie" in d["mobs"] and len(d["presets"]["hard"]) == 10 and "none" in d["kit_tiers"]["armour"]
    k = client.post(base, json={"game": "koth", "start": 9e9, "center": HILL, "radius": 4, "spawns": [{"x": 9, "y": 64, "z": 9}],
                                "team_count": 2, "kit": {"sword": "stone", "armour": "none"}}).json()
    assert k["game"] == "koth" and k["team_count"] == 2 and k["kit"]["armour"] == "none" and k["zone"]["r"] == 4
    assert client.post(base, json={"game": "koth", "start": 9e9, "center": HILL}).status_code == 400          # no spawn spot
    a = client.post(base, json={"game": "arena", "start": 9e9, "center": HILL, "mob_spots": [{"x": 3, "y": 64, "z": 3}], "level": "hard", "coop": False}).json()
    assert a["name"] == "Mob arena" and len(a["waves"]) == 10
    for r in (k, a):
        client.delete(f"{base}/{r['id']}")


def test_elytra_race_things_kept_safe_wings_then_everything_back(fight):
    from app import races
    before = {u: dict(s) for u, s in fight.slots.items()}
    r = {"id": "e1", "name": "Sky loop (elytra)", "minutes": 5, "vehicle": "elytra", "rockets": 16, "safe_flying": True}
    racing = asyncio.run(races._wings(fight, r, ["Alex", ".LongBedrockNameX"]))
    assert sorted(racing) == [".LongBedrockNameX", "Alex"] and not own(fight.slots[U1])             # their own things in the vault
    assert any(c.startswith(f"item replace entity {U1} armor.chest with minecraft:elytra[minecraft:custom_data={{solkit:1b}}") for c in fight.said)
    assert any(c.startswith(f"give {U2} minecraft:firework_rocket[") and c.endswith(" 16") for c in fight.said)
    assert fight.rules["keepInventory"] == "true"
    asyncio.run(races._gear_back(fight, r))
    assert fight.slots == before and fight.rules["keepInventory"] == "false" and not kits.waiting(fight.id)


def test_boat_and_elytra_races_are_set_up(client, sid):
    from app import races
    c = races.save_course(sid, {"name": "Loop", "points": [{"x": 0, "y": 64, "z": 0}, {"x": 30, "y": 90, "z": 0}]})
    try:
        b = races.schedule(sid, {"course": c["id"], "start": 9e9, "vehicle": "boat"})
        e = races.schedule(sid, {"course": c["id"], "start": 9e9, "vehicle": "elytra", "rockets": 200})
        w = races.schedule(sid, {"course": c["id"], "start": 9e9, "vehicle": "hovercraft"})
        assert b["name"] == "Loop (by boat)" and e["name"] == "Loop (elytra)" and e["rockets"] == 64 and w["vehicle"] == "none"
    finally:
        for r in races.runs_for(sid):
            asyncio.run(races.cancel(type("S", (), {"id": sid})(), r["id"]))
        races.delete_course(sid, c["id"])


def test_arena_monsters_come_with_their_gear_and_specials():
    class New:
        mc_version = "1.21.11"

    class Old:
        mc_version = "1.21.4"
    what, nbt = arena.summon_nbt(New(), "skeleton", "solarena_t")                  # a plain skeleton still has its bow
    assert what == "minecraft:skeleton" and 'mainhand:{id:"minecraft:bow"' in nbt and "drop_chances:{mainhand:0f}" in nbt
    what, nbt = arena.summon_nbt(New(), "spider_jockey", "solarena_t")             # the rider's the arena's too
    assert what == "minecraft:spider" and nbt.count('Tags:["solarena_t"]') == 2 and 'Passengers:[{id:"minecraft:skeleton"' in nbt
    assert "spear_zombie" in arena.specials_for(New()) and "spear_zombie" not in arena.specials_for(Old())
    _w, nbt = arena.summon_nbt(Old(), "spear_zombie", "t")                        # an older server: a sword, the old way
    assert 'HandItems:[{id:"minecraft:iron_sword",count:1},{}]' in nbt and "ArmorDropChances" in nbt
    assert arena.clean_waves([{"baby_zombie": 2, "charged_creeper": 1}]) == [{"baby_zombie": 2, "charged_creeper": 1}]
    assert arena.battle_name("spear_zombie", 3) == "zombies with spears" and arena.battle_name("baby_zombie", 1) == "baby zombie"


def test_people_not_playing_are_moved_out_of_the_arena(fight):
    r = {"id": "a2", "game": "arena", "name": "Mob arena", "dim": "minecraft:overworld", "players": {"Alex": {"uuid": U1}}}
    r.update(arena.settings({"center": HILL, "radius": 10, "mob_spots": [{"x": 5, "y": 64, "z": 5}], "level": "easy"}, games._num, games._point))
    where = {"Alex": ("minecraft:overworld", 1.0, 64.0, 1.0), "Sam": ("minecraft:overworld", 0.0, 64.0, 6.0),
             "Admin": ("minecraft:overworld", 2.0, 64.0, 2.0), "Far": ("minecraft:overworld", 200.0, 64.0, 0.0)}
    fight.pos.update(where)
    fight.watching.add("Admin")
    asyncio.run(battle.keep_out(fight, r, where))
    import math
    _d, x, _y, z = fight.pos["Sam"]
    assert math.hypot(x, z) > 12 and z > 0                                  # just outside, on the side they were on
    assert fight.pos["Alex"] == where["Alex"] and fight.pos["Admin"] == where["Admin"] and fight.pos["Far"] == where["Far"]
    assert sum("moved just outside" in c for c in fight.said) == 1
    fight.pos["Sam"] = ("minecraft:overworld", 0.0, 64.0, -3.0)                     # wandered back in, the other side
    asyncio.run(battle.keep_out(fight, r, {"Sam": fight.pos["Sam"]}))
    assert fight.pos["Sam"][3] < -12 and sum("moved just outside" in c for c in fight.said) == 1      # out again; told once
