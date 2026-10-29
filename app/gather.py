"""Gathering everyone for an event, and sending them home afterwards ("soft teleport").

- lead_in(): a 10-second countdown on everyone's screen before anything starts, even one
  started "right now", so nobody is caught off guard.
- send(): notes where everyone is (spot, dimension), then moves them to the event's spot,
  spread out around it on solid ground, facing the middle.
- line_up(): the same, but in a row across a direction (race starts).
- freeze()/unfreeze(): nobody can move or jump (race starts), with a safety net: anything
  still frozen after its time is let go, by Solstone and when a frozen player next joins.
- come_home(): after an event, a countdown, then everyone goes back where they were. Anyone
  offline then goes back when they next join.

All of it is saved as it happens, so a restarted Solstone carries on.
"""
from __future__ import annotations

import math
import re
import time

from . import servers as S
from . import settings_store
from .control import component
from .races import _POS, _pos, _rcon

SECTION = "gather"
LEAD = 10                                      # seconds of countdown before an event starts
HOME_AFTER = 10                                # seconds of countdown before everyone goes back
SAY_AT = (10, 5, 4, 3, 2, 1)
FREEZE_ID = "solstone:freeze"


def _load() -> dict:
    d = settings_store.load().get(SECTION) or {}
    return {"returns": list(d.get("returns") or []), "owed": dict(d.get("owed") or {}), "frozen": list(d.get("frozen") or [])}


def _save(d: dict) -> None:
    settings_store.save_section(SECTION, d)


def busy() -> bool:
    d = _load()
    return bool(d["returns"] or d["frozen"])


def clean_spot(v) -> dict | None:
    """Where to gather: {x, y, z, r (how far around it people are spread), dim}."""
    if not isinstance(v, dict) or v.get("x") is None or v.get("z") is None:
        return None
    try:
        x, y, z = float(v["x"]), float(v.get("y") or 64), float(v["z"])
        r = max(1, min(16, int(float(v.get("r") or 4))))
    except (TypeError, ValueError):
        return None
    dim = v.get("dim") if isinstance(v.get("dim"), str) and re.match(r"^[a-z0-9_.-]+:[a-z0-9_/.-]+$", v.get("dim")) else "minecraft:overworld"
    return {"x": round(x, 1), "y": round(y, 1), "z": round(z, 1), "r": r, "dim": dim}


# ------------------------------------------------------------------ before
async def lead_in(srv, item: dict, now: float, title: str, sub: str = "", who: list[str] | None = None) -> None:
    """Big numbers on screen for the last 10 seconds before `item["start"]`: everyone's, or just `who` (those
    who joined an event players choose to take part in)."""
    left = math.ceil(item["start"] - now)
    said = item.setdefault("lead_said", [])
    if left not in SAY_AT or left in said:
        return
    said.append(left)
    for t in (["@a"] if who is None else who):
        if left == LEAD:
            await _rcon(srv, f"tellraw {t} {component([('★ ', 'gold'), (title, 'yellow'), (f' starts in {LEAD} seconds! ', None), (sub, 'gray')])}")
        await _rcon(srv, f"title {t} times 0 25 5")
        await _rcon(srv, f"title {t} subtitle {component([(title + (' · ' + sub if sub else ''), 'yellow')])}")
        await _rcon(srv, f"title {t} title {component([(str(left), 'gold')])}")
        await _rcon(srv, f"execute as {t} at @s run playsound minecraft:block.note_block.hat master @s ~ ~ ~ 1 1.2")


async def _dim(srv, n: str) -> str:
    m = re.search(r'"([a-z0-9_.-]+:[a-z0-9_/.-]+)"', await _rcon(srv, f"data get entity {n} Dimension"))
    return m.group(1) if m else "minecraft:overworld"


async def _where(srv, names: list[str]) -> dict[str, dict]:
    out = {}
    for n in names:
        q = await _pos(srv, n)
        if q:
            out[n] = {"x": round(q[0], 2), "y": round(q[1], 2), "z": round(q[2], 2), "d": await _dim(srv, n)}
    return out


async def _ground(srv, dim: str, x: float, z: float, fallback: float) -> float | None:
    """The standing height at x, z, or None if it's water, lava or nothing loaded."""
    xi, zi = int(math.floor(x)), int(math.floor(z))
    await _rcon(srv, f"execute in {dim} positioned {xi} 320 {zi} positioned over motion_blocking_no_leaves run summon minecraft:marker ~ ~ ~ {{Tags:[\"solgather\"]}}")
    m = _POS.search(await _rcon(srv, "data get entity @e[tag=solgather,limit=1] Pos"))
    await _rcon(srv, "kill @e[tag=solgather]")
    if not m:
        return None
    y = int(float(m.group(2)))
    for bad in ("minecraft:water", "minecraft:lava"):
        if "passed" in (await _rcon(srv, f"execute in {dim} if block {xi} {y - 1} {zi} {bad}")).lower():
            return None
    return float(y)


async def send(srv, spot: dict, names: list[str] | None = None) -> dict[str, dict]:
    """Move everyone (or `names`) to the spot, spread around it; returns where they were."""
    names = names if names is not None else (await S.online_players(srv))[0]
    back = await _where(srv, names)
    dim, cx, cz = spot["dim"], spot["x"], spot["z"]
    await _rcon(srv, f"execute in {dim} run forceload add {int(cx)} {int(cz)}")
    here = list(back)
    for i, n in enumerate(here):
        a = 2 * math.pi * i / max(1, len(here))
        rr = spot["r"] if len(here) > 1 else 0
        x, z = cx + math.cos(a) * rr, cz + math.sin(a) * rr
        y = await _ground(srv, dim, x, z, spot["y"]) if rr else None
        if y is None:                                      # water or unknown there: the middle itself
            x, z, y = cx, cz, spot["y"]
        await _rcon(srv, f"execute in {dim} run tp {n} {x:.1f} {y + 0.1:.1f} {z:.1f} facing {cx} {spot['y'] + 1} {cz}")
    await _rcon(srv, f"execute in {dim} run forceload remove {int(cx)} {int(cz)}")
    return back


async def line_up(srv, start: dict, toward: dict, dim: str, names: list[str]) -> dict[str, dict]:
    """A starting line: everyone side by side, 2 blocks apart, across the way to `toward`, facing it."""
    back = await _where(srv, names)
    dx, dz = toward["x"] - start["x"], toward["z"] - start["z"]
    ln = math.hypot(dx, dz) or 1
    px, pz = -dz / ln, dx / ln                                # across the direction of travel
    here = list(back)
    for i, n in enumerate(here):
        off = (i - (len(here) - 1) / 2) * 2
        x, z = start["x"] + px * off, start["z"] + pz * off
        y = await _ground(srv, dim, x, z, start["y"])
        if y is None:
            y = start["y"]
        await _rcon(srv, f"execute in {dim} run tp {n} {x:.1f} {y + 0.1:.1f} {z:.1f} facing {toward['x']} {toward['y'] + 1} {toward['z']}")
    return back


# ------------------------------------------------------------------ holding still
def _attrs(srv) -> tuple[str, str] | None:
    v = [int(x) for x in re.findall(r"\d+", srv.mc_version or "")[:3]] + [0, 0, 0]
    if v[0] == 1 and v[1] < 21:
        return None                                          # modifiers by name came in 1.21
    if v[0] == 1 and v[1] == 21 and v[2] < 2:
        return "minecraft:generic.movement_speed", "minecraft:generic.jump_strength"
    return "minecraft:movement_speed", "minecraft:jump_strength"


async def freeze(srv, names: list[str], seconds: float) -> None:
    attrs = _attrs(srv)
    if not attrs:
        return
    d = _load()
    for n in names:
        for a in attrs:
            await _rcon(srv, f"attribute {n} {a} modifier add {FREEZE_ID} -1 add_multiplied_total")
        d["frozen"] = [f for f in d["frozen"] if not (f["server"] == srv.id and f["n"] == n)]
        d["frozen"].append({"server": srv.id, "n": n, "until": time.time() + seconds + 5})
    _save(d)


async def unfreeze(srv, names: list[str] | None = None) -> None:
    attrs = _attrs(srv)
    d = _load()
    mine = [f for f in d["frozen"] if f["server"] == srv.id and (names is None or f["n"] in names)]
    online = set((await S.online_players(srv))[0])
    for f in mine:
        if f["n"] not in online:
            continue                                         # let go when they next join
        for a in attrs or ():
            await _rcon(srv, f"attribute {f['n']} {a} modifier remove {FREEZE_ID}")
        d["frozen"].remove(f)
    _save(d)


# ------------------------------------------------------------------ after
def come_home(srv, back: dict[str, dict], label: str, delay: int = HOME_AFTER) -> None:
    """Send these people back where they were, after a countdown."""
    if not back:
        return
    d = _load()
    d["returns"].append({"server": srv.id, "label": label, "at": time.time() + delay, "back": back, "said": []})
    _save(d)


async def _send_back(srv, n: str, b: dict) -> bool:
    out = (await _rcon(srv, f"execute in {b['d']} run tp {n} {b['x']} {b['y']} {b['z']}")).lower()
    return not ("no player" in out or "no entity" in out or "not found" in out)


async def tick(servers: list) -> None:
    """Every second: countdowns to going home, going home, and the freeze safety net."""
    d = _load()
    if not d["returns"] and not d["frozen"]:
        return
    by_id = {s.id: s for s in servers}
    now, changed = time.time(), False
    for r in list(d["returns"]):
        srv = by_id.get(r["server"])
        if not srv:
            continue
        who = list(r["back"])
        left = math.ceil(r["at"] - now)
        if left > 0:
            if left in SAY_AT and left not in r["said"]:
                r["said"].append(left)
                changed = True
                for n in who:
                    await _rcon(srv, f"title {n} times 0 25 5")
                    await _rcon(srv, f"title {n} subtitle {component([('Heading back to where you were', 'yellow')])}")
                    await _rcon(srv, f"title {n} title {component([(str(left), 'aqua')])}")
            continue
        online = set((await S.online_players(srv))[0])
        for n, b in r["back"].items():
            if not (n in online and await _send_back(srv, n, b)):
                d["owed"].setdefault(srv.id, {})[n] = b
        d["returns"].remove(r)
        changed = True
    for f in list(d["frozen"]):                              # still frozen past its time (Solstone was away?)
        srv = by_id.get(f["server"])
        if srv and now >= f["until"]:
            online = set((await S.online_players(srv))[0])
            if f["n"] in online:
                for a in _attrs(srv) or ():
                    await _rcon(srv, f"attribute {f['n']} {a} modifier remove {FREEZE_ID}")
                d["frozen"].remove(f)
                changed = True
    if changed:
        _save(d)


async def on_join(srv, player: str) -> None:
    """Back from somewhere they were taken while offline, and never left frozen."""
    d = _load()
    changed = False
    b = d["owed"].get(srv.id, {}).get(player)
    if b and await _send_back(srv, player, b):
        del d["owed"][srv.id][player]
        await _rcon(srv, f"tellraw {player} {component([('★ ', 'gold'), ('An event ended while you were away, so you are back where you were.', 'yellow')])}")
        changed = True
    for f in [f for f in d["frozen"] if f["server"] == srv.id and f["n"] == player and time.time() >= f["until"]]:
        for a in _attrs(srv) or ():
            await _rcon(srv, f"attribute {player} {a} modifier remove {FREEZE_ID}")
        d["frozen"].remove(f)
        changed = True
    if changed:
        _save(d)

