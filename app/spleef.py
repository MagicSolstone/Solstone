"""Spleef: everyone on a snow floor high in the sky with a shovel; dig the snow out from under
the others; fall through and you're out. Last one (or last team) standing wins the round.

The arena is built in empty sky over the chosen spot (only ever filling air) and taken down
afterwards (only ever removing what it built: snow, barrier, glass, water). Below the floors
is a glass pool of water, so falling out is safe; everyone also has Resistance V while playing.

Safety nets, in case Solstone stops in the middle:
- the whole game (where everyone was standing, their game mode) is saved after every step,
  so a restarted Solstone carries on, and anyone offline at the end is sent back on joining;
- the Solstone data pack (v10+) keeps a copy of the arena and everyone's spot in storage,
  and Solstone sends a heartbeat every few seconds. If the heartbeat stops for two minutes,
  the pack itself sends everyone back, removes the arena, and from then on moves anyone found
  standing up there to spawn.
"""
from __future__ import annotations

import math
import random
import re
import time

from . import hud
from . import servers as S
from .races import _new_text, _pos, _rcon

GAP = 5                                 # blocks between floors
HEARTBEAT_TICKS = 2400                  # the pack waits this long (2 min) without a heartbeat before cleaning up
SHRINK_EVERY = 8                        # seconds between rings once the floor starts shrinking
ROUND_CAP = 300                         # without a shrinking floor, a round this long is a draw
SHOVEL = "minecraft:diamond_shovel"
SHOVEL_MATCH = f"{SHOVEL}[minecraft:custom_data={{solspleef:1b}}]"
DIM = "minecraft:overworld"
NEED_PACK = 10


def settings(body: dict, num) -> dict:
    best = int(num(body.get("best_of"), 1, 5, 3))
    return {"size": int(num(body.get("size") or body.get("radius"), 6, 20, 10)), "layers": int(num(body.get("layers"), 1, 3, 1)),
            "snowballs": bool(body.get("snowballs", False)),          # off: dug snow drops nothing to throw "shrink": bool(body.get("shrink", True)),
            "shrink_after": int(num(body.get("shrink_after"), 20, 300, 60)), "best_of": best if best % 2 else best + 1,
            "teams": bool(body.get("teams"))}


# ------------------------------------------------------------------ geometry
def _geo(r: dict) -> dict:
    c, R = r["center"], r["size"]
    x, z, top = int(math.floor(c["x"])), int(math.floor(c["z"])), r["top"]
    ys = [top - GAP * i for i in range(r["layers"])]
    bottom = ys[-1]
    return {"x": x, "z": z, "ys": ys, "bottom": bottom, "top": top,
            "x1": x - R, "x2": x + R, "z1": z - R, "z2": z + R,                       # the floors
            "bx1": x - R - 1, "bx2": x + R + 1, "bz1": z - R - 1, "bz2": z + R + 1,   # the barrier rim
            "px1": x - R - 2, "px2": x + R + 2, "pz1": z - R - 2, "pz2": z + R + 2,   # the pool
            "py1": bottom - 6, "py2": bottom - 3}


def _arena_nbt(g: dict) -> str:
    """What the pack needs to take the arena down by itself (strings: they go into macros)."""
    keys = {"x1": g["x1"], "x2": g["x2"], "z1": g["z1"], "z2": g["z2"], "yb": g["bottom"], "yt": g["top"], "yt2": g["top"] + 2,
            "bx1": g["bx1"], "bx2": g["bx2"], "bz1": g["bz1"], "bz2": g["bz2"],
            "px1": g["px1"], "px2": g["px2"], "pz1": g["pz1"], "pz2": g["pz2"], "py1": g["py1"], "py2": g["py2"]}
    return "{" + ",".join(f'{k}:"{v}"' for k, v in keys.items()) + f',d:"{DIM}"}}'


def _zone_nbt(g: dict, spawn: dict) -> str:
    dx, dz = g["px2"] - g["px1"] + 1, g["pz2"] - g["pz1"] + 1
    dy = g["top"] + 3 - g["py1"]
    return (f'{{d:"{DIM}",x:"{g["px1"]}",y:"{g["py1"]}",z:"{g["pz1"]}",dx:"{dx}",dy:"{dy}",dz:"{dz}",'
            f'sx:"{spawn["x"] + 0.5}",sy:"{spawn["y"] + 1}",sz:"{spawn["z"] + 0.5}"}}')


async def _fill(srv, a, b, block: str, only: str = "air") -> None:
    await _rcon(srv, f"execute in {DIM} run fill {a[0]} {a[1]} {a[2]} {b[0]} {b[1]} {b[2]} {block} replace {only}")


async def _build(srv, g: dict) -> None:
    for y in g["ys"]:                                                  # floors, then a rim so nobody walks off the edge
        await _fill(srv, (g["x1"], y, g["z1"]), (g["x2"], y, g["z2"]), "minecraft:snow_block")
        for a, b in (((g["bx1"], y, g["bz1"]), (g["bx2"], y + 2, g["bz1"])), ((g["bx1"], y, g["bz2"]), (g["bx2"], y + 2, g["bz2"])),
                     ((g["bx1"], y, g["bz1"]), (g["bx1"], y + 2, g["bz2"])), ((g["bx2"], y, g["bz1"]), (g["bx2"], y + 2, g["bz2"]))):
            await _fill(srv, a, b, "minecraft:barrier")
    py1, py2 = g["py1"], g["py2"]                                      # the pool: glass tub, water inside
    await _fill(srv, (g["px1"], py1, g["pz1"]), (g["px2"], py1, g["pz2"]), "minecraft:glass")
    for a, b in (((g["px1"], py1, g["pz1"]), (g["px2"], py2, g["pz1"])), ((g["px1"], py1, g["pz2"]), (g["px2"], py2, g["pz2"])),
                 ((g["px1"], py1, g["pz1"]), (g["px1"], py2, g["pz2"])), ((g["px2"], py1, g["pz1"]), (g["px2"], py2, g["pz2"]))):
        await _fill(srv, a, b, "minecraft:glass")
    await _fill(srv, (g["px1"] + 1, py1 + 1, g["pz1"] + 1), (g["px2"] - 1, py1 + 2, g["pz2"] - 1), "minecraft:water")


async def _refloor(srv, g: dict) -> None:
    for y in g["ys"]:
        await _fill(srv, (g["x1"], y, g["z1"]), (g["x2"], y, g["z2"]), "minecraft:snow_block")


async def _teardown(srv, g: dict) -> None:
    await _fill(srv, (g["x1"], g["bottom"], g["z1"]), (g["x2"], g["top"], g["z2"]), "minecraft:air", "minecraft:snow_block")
    await _fill(srv, (g["bx1"], g["bottom"], g["bz1"]), (g["bx2"], g["top"] + 2, g["bz2"]), "minecraft:air", "minecraft:barrier")
    await _fill(srv, (g["px1"], g["py1"], g["pz1"]), (g["px2"], g["py2"], g["pz2"]), "minecraft:air", "minecraft:water")
    await _fill(srv, (g["px1"], g["py1"], g["pz1"]), (g["px2"], g["py2"], g["pz2"]), "minecraft:air", "minecraft:glass")
    await _rcon(srv, f"execute in {DIM} run kill @e[type=item,x={g['px1']},y={g['py1']},z={g['pz1']},dx={g['px2'] - g['px1'] + 1},dy={g['top'] + 3 - g['py1']},dz={g['pz2'] - g['pz1'] + 1}]")
    await _rcon(srv, f"execute in {DIM} run forceload remove {g['px1']} {g['pz1']} {g['px2']} {g['pz2']}")


async def _shrink(srv, g: dict, ring: int) -> None:
    """Take away the outermost `ring`-th ring of snow on every floor."""
    x1, x2, z1, z2 = g["x1"] + ring - 1, g["x2"] - ring + 1, g["z1"] + ring - 1, g["z2"] - ring + 1
    for y in g["ys"]:
        for a, b in (((x1, y, z1), (x2, y, z1)), ((x1, y, z2), (x2, y, z2)), ((x1, y, z1), (x1, y, z2)), ((x2, y, z1), (x2, y, z2))):
            await _fill(srv, a, b, "minecraft:air", "minecraft:snow_block")


# ------------------------------------------------------------------ the game
async def _dim(srv, n: str) -> str:
    m = re.search(r'"([a-z0-9_.-]+:[a-z0-9_/.-]+)"', await _rcon(srv, f"data get entity {n} Dimension"))
    return m.group(1) if m else DIM


async def _pack_version(srv) -> int:
    m = re.search(r"version:\s*(\d+)", await _rcon(srv, "data get storage solstone:games pack"))
    return int(m.group(1)) if m else 0


async def start(srv, r: dict) -> None:
    from .games import _gamemode, _say
    from .hotzone import surface
    names = r.get("entrants") or (await S.online_players(srv))[0]
    if len(names) < 2:
        r["state"], r["result"] = "skipped", "Spleef needs at least two players" + (" to join" if r.get("optin") else " online")
        return
    if await _pack_version(srv) < NEED_PACK:
        r["state"], r["result"] = "skipped", f"Spleef needs the Solstone data pack version {NEED_PACK} or newer (it holds the safety net)"
        return
    # high enough to be clear of everything under it
    c, R = r["center"], r["size"]
    x, z = int(math.floor(c["x"])), int(math.floor(c["z"]))
    await _rcon(srv, f"execute in {DIM} run forceload add {x - R - 2} {z - R - 2} {x + R + 2} {z + R + 2}")
    highest = 64
    for dx, dz in ((0, 0), (-R - 2, -R - 2), (R + 2, -R - 2), (-R - 2, R + 2), (R + 2, R + 2), (0, -R), (0, R), (-R, 0), (R, 0)):
        s = await surface(srv, DIM, x + dx, z + dz, f"solsp_{r['id']}_m")
        # a spot we couldn't measure (chunk not loaded yet): assume the worst and go high
        highest = max(highest, s[0] if s else 265)
    r["top"] = min(305, highest + 35 + GAP * (r["layers"] - 1))
    g = _geo(r)
    try:
        spawn = S.world_info(srv, False).get("spawn") or {"x": 0, "y": 64, "z": 0}
    except Exception:
        spawn = {"x": 0, "y": 64, "z": 0}
    # remember everyone's spot, here and in the pack's storage
    back = []
    for n in names:
        q = await _pos(srv, n)
        if not q:
            continue
        r["players"][n] = {"alive": True, "wins": 0, "gm": await _gamemode(srv, n), "back": {"x": round(q[0], 2), "y": round(q[1], 2), "z": round(q[2], 2), "d": await _dim(srv, n)}}
        b = r["players"][n]["back"]
        back.append(f'{{n:"{n}",x:"{b["x"]}",y:"{b["y"]}",z:"{b["z"]}",d:"{b["d"]}",g:"{r["players"][n]["gm"]}"}}')
    if len(r["players"]) < 2:
        r["state"], r["result"] = "skipped", "Spleef needs at least two players online"
        return
    await _rcon(srv, f"data modify storage solstone:games spleef set value {{arena:{_arena_nbt(g)},zone:{_zone_nbt(g, spawn)},back:[{','.join(back)}]}}")
    await heartbeat(srv, r, force=True)
    if r["teams"]:
        order = list(r["players"])
        random.shuffle(order)
        for i, n in enumerate(order):
            r["players"][n]["team"] = "red" if i % 2 == 0 else "blue"
        for t in ("red", "blue"):
            await _rcon(srv, f"team add solsp_{t}")
            await _rcon(srv, f"team modify solsp_{t} color {t}")
            await _rcon(srv, f"team modify solsp_{t} friendlyFire false")
        for n, p in r["players"].items():
            await _rcon(srv, f"team join solsp_{p['team']} {n}")
    await _build(srv, g)
    r["round"] = 0
    who = " vs ".join(", ".join(n for n, p in r["players"].items() if p.get("team") == t) for t in ("red", "blue")) if r["teams"] else ", ".join(r["players"])
    await _say(srv, [("★ ", "gold"), ("Spleef! ", "yellow"), (f"Best of {r['best_of']}. Dig the snow out from under everyone else; fall through and you're out. ", None), (who, "aqua")],
               "Spleef!", f"Best of {r['best_of']}")
    await _new_round(srv, r)


async def heartbeat(srv, r: dict, force: bool = False) -> None:
    """Tell the pack Solstone is still here (it cleans up by itself if this stops)."""
    if force or time.time() - r.get("hb", 0) >= 10:
        r["hb"] = time.time()
        await _rcon(srv, f"scoreboard players set #spleef_hb solg_tmp {HEARTBEAT_TICKS}")


async def _new_round(srv, r: dict) -> None:
    from .games import _say
    g = _geo(r)
    r["round"] += 1
    await _refloor(srv, g)
    online = set((await S.online_players(srv))[0])
    here = [n for n in r["players"] if n in online]
    rad = max(2, r["size"] * 0.6)
    for i, n in enumerate(here):
        a = 2 * math.pi * i / max(1, len(here))
        px, pz = g["x"] + 0.5 + math.cos(a) * rad, g["z"] + 0.5 + math.sin(a) * rad
        await _rcon(srv, f"execute in {DIM} run tp {n} {px:.1f} {g['top'] + 1} {pz:.1f} facing {g['x'] + 0.5} {g['top'] + 1} {g['z'] + 0.5}")
        await _rcon(srv, f"gamemode adventure {n}")
        await _rcon(srv, f"effect give {n} minecraft:resistance 1000000 4 true")
        await _rcon(srv, f"effect give {n} minecraft:saturation 1000000 0 true")
    for n, p in r["players"].items():
        p["alive"] = n in online
    r["state"], r["phase_ends"], r["ring"] = "countdown", time.time() + 5, 0
    r["round_started"] = None
    await _say(srv, [("★ ", "gold"), (f"Round {r['round']}", "yellow"), (" starts in 5 seconds...", None)], f"Round {r['round']}", "Get ready")


async def _go(srv, r: dict) -> None:
    from .games import _say
    for n, p in r["players"].items():
        if p["alive"]:
            await _rcon(srv, f"gamemode survival {n}")
            await _rcon(srv, f"clear {n} {SHOVEL_MATCH}")
            name = '"Spleef Shovel"' if _new_text(srv) else "'\"Spleef Shovel\"'"
            await _rcon(srv, f"give {n} {SHOVEL}[minecraft:custom_data={{solspleef:1b}},minecraft:unbreakable={{}},minecraft:item_name={name}]")
    r["state"], r["round_started"] = "running", time.time()
    r["phase_ends"] = time.time() + r["shrink_after"] if r["shrink"] else None
    await _say(srv, [("★ ", "gold"), ("Dig!", "yellow!")], "DIG!", "")


def _sides(r: dict) -> set[str]:
    """Who's still in it: player names, or team names in team mode."""
    alive = [n for n, p in r["players"].items() if p["alive"]]
    return {r["players"][n]["team"] for n in alive} if r["teams"] else set(alive)


async def tick(srv, r: dict) -> None:
    from .games import _say
    now = time.time()
    g = _geo(r)
    await heartbeat(srv, r)
    # the pack's safety net went off (Solstone was away too long): it already sent everyone back
    if "found no elements" in (await _rcon(srv, "data get storage solstone:games spleef.arena")).lower():
        await _end(srv, r, "Spleef was stopped: Solstone lost touch for a while, so the arena was taken down.", [], pack_did_it=True)
        return
    if r["state"] == "countdown":
        if now >= r["phase_ends"]:
            await _go(srv, r)
        return
    online = set((await S.online_players(srv))[0])
    if not r["snowballs"]:
        await _rcon(srv, f"execute in {DIM} run kill @e[type=snowball,x={g['px1']},y={g['py1']},z={g['pz1']},dx={g['px2'] - g['px1'] + 1},dy={g['top'] + 3 - g['py1']},dz={g['pz2'] - g['pz1'] + 1}]")
        await _rcon(srv, f"execute in {DIM} run kill @e[type=item,x={g['px1']},y={g['py1']},z={g['pz1']},dx={g['px2'] - g['px1'] + 1},dy={g['top'] + 3 - g['py1']},dz={g['pz2'] - g['pz1'] + 1}]")
    for n, p in r["players"].items():
        if not p["alive"]:
            continue
        q = await _pos(srv, n) if n in online else None
        if not r["snowballs"] and q:
            await _rcon(srv, f"clear {n} minecraft:snowball")
        if q is None or q[1] < g["bottom"] - 0.5 or abs(q[0] - g["x"]) > r["size"] + 6 or abs(q[2] - g["z"]) > r["size"] + 6:
            p["alive"] = False
            await _rcon(srv, f"clear {n} {SHOVEL_MATCH}")
            await _rcon(srv, f"gamemode adventure {n}")
            left = len([x for x in r["players"].values() if x["alive"]])
            why = "left the game" if q is None else "fell through"
            await _say(srv, [("✘ ", "red"), (n, "aqua"), (f" {why}! ", None), (f"{left} left", "gray")])
    sides = _sides(r)
    alive = [n for n, p in r["players"].items() if p["alive"]]
    await _scores(srv, r)
    for n in alive:
        await hud.status(srv, r, n, f"Round {r['round']} of {r['best_of']} · {len(alive)} left" + (f" · team {r['players'][n]['team']}" if r["teams"] else ""), "aqua")
    if len(sides) <= 1:
        await _round_over(srv, r, next(iter(sides)) if sides else None)
        return
    if not r["shrink"] and r["round_started"] and now - r["round_started"] >= ROUND_CAP:
        await _round_over(srv, r, None)
        return
    if r["shrink"] and r["round_started"] and now - r["round_started"] >= r["shrink_after"]:
        if r["ring"] < r["size"] - 1 and now - r.get("shrunk_at", 0) >= SHRINK_EVERY:
            r["ring"] += 1
            r["shrunk_at"] = now
            await _shrink(srv, g, r["ring"])
            if r["ring"] == 1:
                await _say(srv, [("★ ", "gold"), ("The floor is shrinking!", "red")])


async def _scores(srv, r: dict) -> None:
    """Round wins on the sidebar (per team in team spleef)."""
    if r["teams"]:
        wins = r.get("team_wins", {"red": 0, "blue": 0})
        await hud.scores(srv, r, f"❄ Spleef · best of {r['best_of']}", {"Red team": wins.get("red", 0), "Blue team": wins.get("blue", 0)})
    else:
        await hud.scores(srv, r, f"❄ Spleef · best of {r['best_of']}", {n: p["wins"] for n, p in r["players"].items()})


async def _round_over(srv, r: dict, winner: str | None) -> None:
    from .games import _say
    if winner is None:
        await _say(srv, [("★ ", "gold"), (f"Round {r['round']} is a draw!", "yellow")], "Draw!", "")
    else:
        if r["teams"]:
            r.setdefault("team_wins", {"red": 0, "blue": 0})[winner] += 1
            score = f"Red {r['team_wins']['red']} · Blue {r['team_wins']['blue']}"
            await _say(srv, [("★ ", "gold"), (f"Team {winner}", winner), (f" wins round {r['round']}! ", "yellow"), (score, "gray")], f"Team {winner}!", score)
        else:
            r["players"][winner]["wins"] += 1
            score = " · ".join(f"{n} {p['wins']}" for n, p in sorted(r["players"].items(), key=lambda kv: -kv[1]["wins"]))
            await _say(srv, [("★ ", "gold"), (winner, "aqua"), (f" wins round {r['round']}! ", "yellow"), (score, "gray")], f"{winner}!", f"wins round {r['round']}")
    need = r["best_of"] // 2 + 1
    tally = r.get("team_wins", {}) if r["teams"] else {n: p["wins"] for n, p in r["players"].items()}
    champ = next((k for k, v in tally.items() if v >= need), None)
    online = set((await S.online_players(srv))[0])
    still = [n for n in r["players"] if n in online]
    if champ or r["round"] >= r["best_of"] + 2 or len(still) < 2:
        if not champ and tally:
            top = max(tally.values())
            leaders = [k for k, v in tally.items() if v == top and v > 0]
            champ = leaders[0] if len(leaders) == 1 else None
        if champ and r["teams"]:
            winners = [n for n, p in r["players"].items() if p.get("team") == champ]
            result = f"Team {champ} ({', '.join(winners)}) won spleef!"
        elif champ:
            winners, result = [champ], f"{champ} won spleef!"
        else:
            winners, result = [], "Spleef is over: nobody came out on top."
        await _end(srv, r, result, winners)
        return
    for n in r["players"]:
        await _rcon(srv, f"clear {n} {SHOVEL_MATCH}")
    await _new_round(srv, r)                         # its 5-second countdown is the break between rounds


async def send_back(srv, n: str, p: dict) -> bool:
    """Put one player back where they were, as they were. False if they're offline."""
    b = p["back"]
    out = (await _rcon(srv, f"execute in {b['d']} run tp {n} {b['x']} {b['y']} {b['z']}")).lower()
    if "no player" in out or "no entity" in out or "not found" in out:
        return False
    await _rcon(srv, f"gamemode {p.get('gm') or 'survival'} {n}")
    await _rcon(srv, f"clear {n} {SHOVEL_MATCH}")
    await _rcon(srv, f"effect clear {n} minecraft:resistance")
    await _rcon(srv, f"effect clear {n} minecraft:saturation")
    await _rcon(srv, f"team leave {n}")
    return True


async def _end(srv, r: dict, result: str, winners: list[str], pack_did_it: bool = False) -> None:
    await hud.clear(srv, r)
    from .games import _award, _finish, _say
    g = _geo(r)
    if not pack_did_it:
        await _say(srv, [("★ ", "gold"), (result, "yellow")], "Spleef over", (" & ".join(winners) + " won")[:40] if winners else "")
    online = set((await S.online_players(srv))[0])
    for n, p in r["players"].items():
        # online: back now (if the pack already moved them, this just finishes tidying up);
        # offline: put back and tidied up when they next join
        if not (n in online and await send_back(srv, n, p)):
            r.setdefault("owed", {})[n] = p
    if not pack_did_it:
        await _teardown(srv, g)
    await _rcon(srv, "data remove storage solstone:games spleef")
    await _rcon(srv, "scoreboard players set #spleef_hb solg_tmp 0")
    if r["teams"]:
        await _rcon(srv, "team remove solsp_red")
        await _rcon(srv, "team remove solsp_blue")
    _finish(srv, r, result)
    await _award(srv, r, winners)


async def cancel(srv, r: dict) -> None:
    await hud.clear(srv, r)
    await _end(srv, r, "Spleef was called off.", [])


def live_rows(r: dict) -> tuple[list[dict], str]:
    if r["teams"]:
        tw = r.get("team_wins") or {"red": 0, "blue": 0}
        rows = [{"name": n, "value": ("in" if p["alive"] else "out"), "note": f"team {p.get('team')}"} for n, p in
                sorted(r["players"].items(), key=lambda kv: (kv[1].get("team", ""), not kv[1]["alive"], kv[0].lower()))]
        return rows, f"Round {r.get('round', 1)} · Red {tw['red']} · Blue {tw['blue']} · best of {r['best_of']}"
    rows = [{"name": n, "value": f"{p['wins']} won", "note": "in" if p["alive"] else "out"} for n, p in
            sorted(r["players"].items(), key=lambda kv: (-kv[1]["wins"], not kv[1]["alive"], kv[0].lower()))]
    left = sum(1 for p in r["players"].values() if p["alive"])
    return rows, f"Round {r.get('round', 1)} · {left} still standing · best of {r['best_of']}"
