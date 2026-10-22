"""A countdown at the top of everyone's screen: a vanilla boss bar named "Fishing contest · 6:32
left" that empties as time runs out. Used by contests, races and games.

The name and fill are updated every second (two RCON commands), and the bar is removed when
the thing ends. Ids are solstone:<kind>_<id>."""
from __future__ import annotations

import json
import time

from .rcon import RconError

EVERY = 1                                   # seconds between updates (a steady count, like a clock)
JOIN_EVERY = 10                             # how often the bar is offered to people who joined since


def _fmt(sec: float) -> str:
    sec = max(0, int(sec))
    return f"{sec // 60}:{sec % 60:02d}"


async def _cmd(srv, cmd: str) -> None:
    try:
        await srv.rcon(cmd)
    except RconError:
        pass


async def show(srv, state: dict, key: str, title: str, ends_at: float, total: float, color: str = "yellow", force: bool = False) -> None:
    """Create the bar the first time, then keep its name and fill up to date. `state` is the
    thing's own saved dict (remembers whether the bar exists and when it was last updated)."""
    bid = f"solstone:{key}"
    now = time.time()
    left = max(0.0, ends_at - now)
    name = json.dumps([{"text": title, "color": "gold"}, {"text": f"  {_fmt(left)} left", "color": "white"}], ensure_ascii=False)
    if not state.get("bar"):
        await _cmd(srv, f"bossbar add {bid} {name}")
        await _cmd(srv, f"bossbar set {bid} color {color}")
        await _cmd(srv, f"bossbar set {bid} style notched_10")
        await _cmd(srv, f"bossbar set {bid} max {max(1, int(total))}")
        await _cmd(srv, f"bossbar set {bid} players @a")
        state["bar"], state["bar_at"] = bid, 0
    if not force and now - state.get("bar_at", 0) < EVERY and left > 10:
        return
    state["bar_at"] = now
    await _cmd(srv, f"bossbar set {bid} value {int(left)}")
    await _cmd(srv, f"bossbar set {bid} name {name}")
    if now - state.get("bar_join", 0) >= JOIN_EVERY:
        state["bar_join"] = now
        await _cmd(srv, f"bossbar set {bid} players @a")      # people who joined since


async def hide(srv, state: dict) -> None:
    if state.get("bar"):
        await _cmd(srv, f"bossbar remove {state['bar']}")
        state["bar"] = None


WARN_AT = (600, 300, 60)                     # 10, 5 and 1 minutes left


def due_warning(state: dict, ends_at: float, total: float) -> int | None:
    """Minutes left to announce now (10, 5 or 1), once each, and only if the thing is longer."""
    left = ends_at - time.time()
    warned = state.setdefault("warned", [])
    due = [s for s in WARN_AT if total > s + 30 and 0 < left <= s and s not in warned]
    if not due:
        return None
    warned.extend(due)                      # only the nearest is said: no "10 minutes left" with 4 to go
    return min(due) // 60
