"""Hot zones: a spot that opens for a while, marked in the world (a red dot on the locator bar,
a floating sign, flames and a smoke column), where whatever you do scores extra. Then it goes
out and another opens somewhere else.

Used by points archery (hits shot from inside the zone) and the fishing tournament (fish
hooked inside it). The game or contest keeps the state in its own dict:
    hot_bonus, hot_on, hot_off             the settings
    hot_zone, hot_prev                     the current zone and the one before
A `pick` coroutine chooses where the next one goes: (x, y, z, dim, where-text) or None to try
again next second.
"""
from __future__ import annotations

import math

from .control import component
from .races import _POS, _direction, _rcon, _text_nbt

ON_DEFAULT, OFF_DEFAULT = 45, 20              # seconds open, seconds between
FIRST_AFTER = 15                              # the first one opens this long after the start


def tag(st: dict) -> str:
    return f"solhot_{st['id']}"


def settings(body: dict, on_default: int = ON_DEFAULT, off_default: int = OFF_DEFAULT) -> dict:
    def num(k, lo, hi, d):
        try:
            return max(lo, min(hi, float(body.get(k))))
        except (TypeError, ValueError):
            return d
    return {"hot_bonus": round(num("hot_bonus", 1.5, 5, 2), 1), "hot_on": int(num("hot_on", 15, 300, on_default)),
            "hot_off": int(num("hot_off", 5, 600, off_default))}


def inside(st: dict, pos, now: float, r: float) -> bool:
    """Was this inside a hot zone: one open now, or one that closed in the last few seconds
    (what's being scored can arrive a moment late)?"""
    for z in (st.get("hot_zone"), st.get("hot_prev")):
        if z and (z.get("on") or now - z.get("closed", 0) < 6) and math.hypot(pos[0] - z["x"], pos[2] - z["z"]) <= r + 0.5:
            return True
    return False


async def surface(srv, dim: str, x: int, z: int, t: str, at: str | None = None) -> tuple[int, str] | None:
    """The top block at x, z (water counts): its y and what it is ('water', or 'land')."""
    where = f"execute at {at}" if at else f"execute in {dim}"
    await _rcon(srv, f"{where} positioned {x} 320 {z} positioned over motion_blocking_no_leaves run summon minecraft:marker ~ ~ ~ {{Tags:[\"{t}\"]}}")
    m = _POS.search(await _rcon(srv, f"data get entity @e[tag={t},limit=1] Pos"))
    await _rcon(srv, f"kill @e[tag={t}]")
    if not m:
        return None
    y = int(float(m.group(2)))
    wet = await _rcon(srv, f"{where} if block {x} {y - 1} {z} minecraft:water")
    return y, ("water" if "passed" in wet.lower() else "land")


async def _say(srv, parts, title: str = "", sub: str = "") -> None:
    await _rcon(srv, f"tellraw @a {component(parts)}")
    if title:
        await _rcon(srv, "title @a times 5 40 10")
        await _rcon(srv, f"title @a subtitle {component([(sub, 'yellow')])}")
        await _rcon(srv, f"title @a title {component([(title, 'gold')])}")


async def clear(srv, st: dict) -> None:
    await _rcon(srv, f"kill @e[tag={tag(st)}]")


async def tick(srv, st: dict, now: float, started: float, ends: float, r: float, what: str, pick) -> None:
    """Open, keep marked, and close hot zones. `what`: what scores extra, for the announcement
    ('Hits from inside', 'Fish hooked inside')."""
    z, t = st.get("hot_zone"), tag(st)
    on, off, bonus = st.get("hot_on") or ON_DEFAULT, st.get("hot_off") or OFF_DEFAULT, st.get("hot_bonus") or 2
    if z and z["on"] and now >= z["until"]:
        await clear(srv, st)
        z.update(on=False, closed=now, until=now + off)
        st["hot_prev"] = dict(z)
        await _say(srv, [("♨ ", "red"), ("The hot zone has gone out. ", "gold"), (f"Another opens in {off} seconds...", "gray")])
    elif (not z or not z["on"]) and now >= (z["until"] if z else started + FIRST_AFTER) and ends - now > 20:
        spot = await pick()
        if spot:
            x, y, zz, dim, where = spot
            st["hot_zone"] = {"on": True, "x": x + 0.5, "y": y, "z": zz + 0.5, "dim": dim, "until": now + on}
            # a dot on the locator bar (buried two blocks down, as for races) and a sign above it
            await _rcon(srv, f"execute in {dim} run summon minecraft:armor_stand {x + 0.5} {y - 2} {zz + 0.5} "
                             f"{{Tags:[\"{t}\",\"{t}_wp\"],Small:1b,Marker:1b,NoGravity:1b,Invulnerable:1b,Silent:1b,"
                             f"attributes:[{{id:\"minecraft:waypoint_transmit_range\",base:60000000d}}]}}")
            await _rcon(srv, f"waypoint modify @e[tag={t}_wp,limit=1] color red")
            label = _text_nbt(srv, f"♨ HOT ZONE ×{bonus:g} ♨", "red")
            await _rcon(srv, f"execute in {dim} run summon minecraft:text_display {x + 0.5} {y + 3} {zz + 0.5} "
                             f"{{Tags:[\"{t}\"],billboard:\"center\",see_through:1b,text:{label},transformation:{{left_rotation:[0f,0f,0f,1f],right_rotation:[0f,0f,0f,1f],translation:[0f,0f,0f],scale:[2.5f,2.5f,2.5f]}}}}")
            await _say(srv, [("♨ ", "red"), ("HOT ZONE! ", "red!"), (f"{where}. {what} score ×{bonus:g} for {on} seconds.", "gold")],
                       "♨ Hot zone!", where[:40])
    z = st.get("hot_zone")
    if z and z["on"]:
        dim = z.get("dim") or "minecraft:overworld"
        await _rcon(srv, f"execute in {dim} run particle minecraft:flame {z['x']} {z['y'] + 0.3} {z['z']} {r / 2} 0.1 {r / 2} 0.01 40 force")
        await _rcon(srv, f"execute in {dim} run particle minecraft:campfire_signal_smoke {z['x']} {z['y'] + 1} {z['z']} 0.3 2 0.3 0.01 4 force")


def bar(st: dict, pos, r: float) -> tuple[str, bool]:
    """The hotbar line for someone at `pos`: where the zone is, or that they're in it."""
    z = st.get("hot_zone")
    if not z or not z["on"] or not pos:
        return "", False
    d = math.hypot(pos[0] - z["x"], pos[2] - z["z"])
    if d <= r + 0.5:
        return f"♨ IN THE HOT ZONE ×{st.get('hot_bonus') or 2:g} · ", True
    return f"♨ hot zone {d:.0f} m {_direction(z['x'] - pos[0], z['z'] - pos[2])} · ", False
