"""What King of the Hill and the mob arena share: getting everyone ready (their things kept safe, a kit, teams),
coming back after a death (a few seconds watching, then back at their spawn), the zone drawn in the world, and
putting everything back afterwards.

During a game, keep inventory and instant respawn are switched on (nothing a player drops in a fight is theirs: their
own things are in the vault), and switched back to what they were when it ends. A player who dies respawns where they
always would, is put in spectator above the zone for the countdown, then sent to their spawn spot with full health.
"""
from __future__ import annotations

import math
import random
import re
import time

from . import control, kits
from . import servers as S

TEAM_COLOURS = ("red", "blue", "green", "yellow")
RULES_ON = {"keep_inventory": True, "immediate_respawn": True}


async def _rcon(srv, cmd: str) -> str:
    return (await srv.rcon(cmd)) or ""


def uuids_of(srv, names: list[str]) -> dict[str, str]:
    known = {p["name"].lower(): u for u, p in S.known_players(srv).items()}
    return {n: known[n.lower()] for n in names if n.lower() in known}


async def rules_on(srv, r: dict, extra: dict | None = None) -> None:
    """Switch on the rules a fight needs, remembering what they were."""
    want = {**RULES_ON, **(extra or {})}
    now = {x["key"]: x["value"] for x in await control.game_rules(srv)}
    r["rules_before"] = {k: now[k] for k in want if k in now}
    for k, v in want.items():
        if k in now and now[k] != v:
            await control.set_rule(srv, k, v)


async def rules_off(srv, r: dict) -> None:
    for k, v in (r.pop("rules_before", None) or {}).items():
        try:
            await control.set_rule(srv, k, v)
        except Exception:
            pass


async def ready(srv, r: dict, names: list[str], tag: str) -> list[str]:
    """Keep everyone's things safe and hand out the kit. Returns who's playing (anyone whose things couldn't be
    kept safe watches instead, untouched)."""
    ids = uuids_of(srv, names)
    kept_already = {x["name"].lower() for x in kits.waiting(srv.id)}
    playing = await kits.stash(srv, ids, r["id"])
    for n in names:
        if n not in playing:
            from .games import _say
            why = ("Some of your things are still kept safe from an earlier game, so you're watching this one. "
                   "An admin can sort it out on the Games page." if n.lower() in kept_already else
                   "Your things couldn't be kept safe just now, so you're watching this one.")
            await _say(srv, [("★ ", "gold"), (f"{why} Nothing of yours was touched.", "yellow")], who=n)
    for n in playing:
        r["players"][n] = {"uuid": ids[n], "score": 0, "deaths": 0, "kills": 0}
        await kits.give_kit(srv, ids[n], r["kit"])
        await _rcon(srv, f"gamemode {'adventure' if r.get('no_dig', True) else 'survival'} {ids[n]}")
        await _rcon(srv, f"effect give {ids[n]} minecraft:instant_health 1 10 true")
        await _rcon(srv, f"effect give {ids[n]} minecraft:saturation 1 10 true")
    await _rcon(srv, f"scoreboard objectives add {tag}_d deathCount")
    return playing


async def make_teams(srv, r: dict, n_teams: int, tag: str) -> None:
    order = list(r["players"])
    random.shuffle(order)
    teams = TEAM_COLOURS[:n_teams]
    r["teams"] = {t: 0 for t in teams}
    for i, n in enumerate(order):
        r["players"][n]["team"] = teams[i % n_teams]
    for t in teams:
        await _rcon(srv, f"team add {tag}_{t}")
        await _rcon(srv, f"team modify {tag}_{t} color {t}")
        await _rcon(srv, f"team modify {tag}_{t} friendlyFire false")
        await _rcon(srv, f"team modify {tag}_{t} seeFriendlyInvisibles true")
    for p in r["players"].values():
        await _rcon(srv, f"team join {tag}_{p['team']} {p['uuid']}")


def spawn_for(r: dict, n: str) -> dict:
    """Where this player comes in: their team's spot, or one of the spots at random (everyone for themselves)."""
    spots = r["spawns"]
    team = r["players"][n].get("team")
    if team and r.get("teams"):
        return spots[list(r["teams"]).index(team) % len(spots)]
    return random.choice(spots)


async def send_in(srv, r: dict, n: str) -> None:
    p, s = r["players"][n], spawn_for(r, n)
    await _rcon(srv, f"execute in {r['dim']} run tp {p['uuid']} {s['x']} {s['y']} {s['z']}")
    await _rcon(srv, f"gamemode {'adventure' if r.get('no_dig', True) else 'survival'} {p['uuid']}")
    await _rcon(srv, f"effect give {p['uuid']} minecraft:instant_health 1 10 true")
    await _rcon(srv, f"effect give {p['uuid']} minecraft:resistance 3 4 true")          # a moment's grace at the spawn


async def deaths(srv, r: dict, tag: str, now: float) -> list[str]:
    """Who died since last time: watching from above the zone for the countdown."""
    died = []
    for n, p in r["players"].items():
        if p.get("out") or p.get("back_at"):
            continue
        m = re.search(r"has (\d+) \[", await _rcon(srv, f"scoreboard players get {p['uuid']} {tag}_d"))
        count = int(m.group(1)) if m else 0
        if count > p["deaths"]:
            p["deaths"] = count
            died.append(n)
            if r.get("respawn_secs", 0) >= 0:
                p["back_at"] = now + r.get("respawn_secs", 5)
                c = r["zone"]
                await _rcon(srv, f"gamemode spectator {p['uuid']}")
                await _rcon(srv, f"execute in {r['dim']} run tp {p['uuid']} {c['x']} {c['y'] + 12} {c['z']}")
    return died


async def comebacks(srv, r: dict, now: float) -> None:
    """The respawn countdown on screen, then back in at their spawn."""
    for n, p in r["players"].items():
        if not p.get("back_at") or p.get("out"):
            continue
        left = math.ceil(p["back_at"] - now)
        if left > 3600:                                   # (the arena, together: back when the wave's cleared)
            await _rcon(srv, f"title {p['uuid']} actionbar {control.component([('Down! Back in when the wave is cleared', 'red')])}")
        elif left <= 0:
            p.pop("back_at", None)
            await send_in(srv, r, n)
        else:
            await _rcon(srv, "title {u} times 0 25 5".format(u=p["uuid"]))
            await _rcon(srv, f"title {p['uuid']} title {control.component([(str(left), 'gold')])}")
            await _rcon(srv, f"title {p['uuid']} subtitle {control.component([('Back in...', 'yellow')])}")


async def ring(srv, r: dict, particle: str = "minecraft:end_rod") -> None:
    """The zone's edge, in sparkles, every other second (a plain particle: the same on every version)."""
    if int(r.get("ticks", 0)) % 2:
        return
    c = r["zone"]
    n = max(16, min(48, round(2 * math.pi * c["r"] / 3)))      # about every 3 blocks, so a big arena's edge is easy to see
    for i in range(n):
        a = 2 * math.pi * i / n
        x, z = c["x"] + c["r"] * math.cos(a), c["z"] + c["r"] * math.sin(a)
        await _rcon(srv, f"execute in {r['dim']} run particle {particle} {x:.1f} {c['y'] + 1} {z:.1f} 0.1 0.6 0.1 0 4 force")


async def tidy_ground(srv, r: dict, monster_drops: bool = False) -> None:
    """Each second of a fight: the kit's things thrown down go at once (so they can't be picked up after). In the mob
    arena, every few seconds, what the monsters dropped in the arena goes too: it would only pile up, and anything
    picked up in a game is left behind at the end anyway."""
    await kits.sweep(srv)
    if monster_drops and (int(r.get("ticks", 0)) % 5 == 0 or r.get("wrap_at") is not None):
        c = r["zone"]
        await _rcon(srv, f"execute in {r['dim']} run kill @e[type=minecraft:item,x={c['x']},y={c['y']},z={c['z']},distance=..{c['r'] + 12}]")


async def left_and_back(srv, r: dict, where: dict) -> None:
    """Anyone who left mid-game is out of it; back online while it's still on, their things come straight back.
    "Left" means really not on the server, two looks in a row: a position lookup that failed or came back empty (the
    server busy with a wave of monsters, say), or someone on the death screen, never counts. That once ended a game
    for everyone and handed things back in the middle of it."""
    if not where:
        return                                         # the game didn't answer: nothing to go on this time
    online = {x.lower() for x in (await S.online_players(srv))[0]}
    for n, p in r["players"].items():
        here = n.lower() in where or n.lower() in online
        if here:
            p.pop("missing", None)
        if not here and not p.get("out"):
            p["missing"] = p.get("missing", 0) + 1
            if p["missing"] >= 2:
                p["out"] = True                        # their things wait in the vault
        elif here and p.get("out") and not p.get("returned"):
            if await kits.give_back(srv, p["uuid"]):
                p["returned"] = True
                from .games import _say
                await _say(srv, [("★ ", "gold"), ("You left the game, so here are your things back, just as they were.", "yellow")], who=p["uuid"])


def inside(r: dict, pos) -> bool:
    """Standing in the zone: within its radius, and not far above or below it."""
    c = r["zone"]
    dim, x, y, z = pos
    return dim == r["dim"] and math.hypot(x - c["x"], z - c["z"]) <= c["r"] and abs(y - c["y"]) <= c.get("h", 6)


async def keep_out(srv, r: dict, where: dict, margin: float = 2) -> None:
    """Anyone not playing who's in the zone (there when it started, or wandering in) is moved just outside its edge,
    on the side they're on, onto solid ground, and told why once. Not anyone in creative or spectator (an admin
    watching). Monsters can still see out, and arrows can fly over the edge: it's a game zone, not a wall."""
    c = r["zone"]
    playing = {n.lower() for n in r["players"]}
    for name, pos in where.items():
        if name.lower() in playing or not inside({**r, "zone": {**c, "r": c["r"] + margin}}, pos):
            continue
        if "passed" not in (await _rcon(srv, f"execute as {name} if entity @s[gamemode=!spectator,gamemode=!creative]")).lower():
            continue
        _dim, x, _y, z = pos
        a = math.atan2(z - c["z"], x - c["x"]) if (x, z) != (c["x"], c["z"]) else 0.0
        out = c["r"] + margin + 3
        await _rcon(srv, f"execute in {r['dim']} run spreadplayers {c['x'] + out * math.cos(a):.1f} {c['z'] + out * math.sin(a):.1f} 0 1 false {name}")
        told = r.setdefault("kept_out", [])
        if name.lower() not in told:
            told.append(name.lower())
            await _rcon(srv, f"tellraw {name} " + control.component([("★ ", "gold"), (f"{r['name']} is on here, so you've been moved just outside. ", "yellow"),
                                                                     ("You can watch from there, or join the next one!", "white")]))


WRAP_SECS = 8                          # from the result to everyone going home: a moment to take it in


async def wrap_start(srv, r: dict) -> None:
    """The game's over: a few seconds before anyone's moved, safe from everything while they wait."""
    r["wrap_at"] = time.time() + WRAP_SECS
    for p in r["players"].values():
        if not p.get("out"):
            await _rcon(srv, f"effect give {p['uuid']} minecraft:resistance {WRAP_SECS + 2} 4 true")
            await _rcon(srv, f"effect give {p['uuid']} minecraft:regeneration {WRAP_SECS + 2} 2 true")


async def wrap_wait(srv, r: dict) -> bool:
    """While the end's pause is on: the countdown on everyone's screen. True while still waiting."""
    left = math.ceil(r["wrap_at"] - time.time())
    if left <= 0:
        return False
    for p in r["players"].values():
        if not p.get("out"):
            await _rcon(srv, f"title {p['uuid']} actionbar {control.component([(f'Heading back in {left}…', 'gold')])}")
    return True


async def finish(srv, r: dict, tag: str) -> None:
    """Everyone's things back, exactly, and where they were; the rules, teams and scores as they were before.
    Anything picked up in the game (mob drops, say) is left behind: they get back exactly their own things."""
    online = {n.lower() for n in (await S.online_players(srv))[0]}
    for n, p in r["players"].items():
        if n.lower() in online:
            # The game's kit never outlives the game, whatever happened along the way (even with nothing in the vault)
            await kits.strip_kit(srv, p["uuid"])
            await kits.give_back(srv, p["uuid"])         # anyone offline gets theirs when they're next on (kits.on_join)
    await kits.sweep(srv)                              # the kit's things left on the ground: thrown down, or dropped
    await rules_off(srv, r)
    await _rcon(srv, f"scoreboard objectives remove {tag}_d")
    for t in r.get("teams") or {}:
        await _rcon(srv, f"team remove {tag}_{t}")
