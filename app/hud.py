"""The standard screen for games and contests, so every one reads the same way:

- **Top:** the time left, on the boss bar (bossbar.py).
- **Right:** the scores, on the sidebar (`scores`): every player's number, best first.
- **Above the hotbar:** what just happened to you (`popup`: "+48 · ring 12 from 31 m"), shown for a
  couple of seconds; between popups, a short status line (`status`: where the hot zone is, "Hide!").

Chat is kept for the big moments (start, a legendary shot, the winner), so it doesn't fill up.
The game keeps the state in its own saved dict.
"""
from __future__ import annotations

import json
import time

from .control import component
from .rcon import RconError

POPUP_SECS = 2.5


async def _cmd(srv, cmd: str) -> str:
    try:
        return await srv.rcon(cmd) or ""
    except RconError:
        return ""


def _obj(st: dict) -> str:
    return f"solsb_{str(st['id'])[:8]}"


async def scores(srv, st: dict, title: str, rows: dict[str, int], text: dict[str, str] | None = None) -> None:
    """The sidebar: one line per player with their score (sorted by the game). `text` shows a
    player's line as words instead of the number ("41.2 m", "HO"), still sorted by the number."""
    obj = _obj(st)
    if st.get("sb") != obj:
        await _cmd(srv, f"scoreboard objectives add {obj} dummy {json.dumps(title, ensure_ascii=False)}")
        await _cmd(srv, f"scoreboard objectives setdisplay sidebar {obj}")
        st["sb"], st["sb_shown"] = obj, {}
    shown = st.setdefault("sb_shown", {})
    for name, value in rows.items():
        label = (text or {}).get(name)
        key = f"{value}|{label or ''}"
        if shown.get(name) == key:
            continue
        shown[name] = key
        await _cmd(srv, f"scoreboard players set {name} {obj} {int(value)}")
        if label is not None:
            await _cmd(srv, f"scoreboard players display numberformat {name} {obj} fixed {json.dumps(label, ensure_ascii=False)}")


async def clear(srv, st: dict) -> None:
    if st.get("sb"):
        await _cmd(srv, f"scoreboard objectives remove {st['sb']}")
        st["sb"] = None


async def popup(srv, st: dict, who: str, parts, color: str = "yellow") -> None:
    """Above `who`'s hotbar for a couple of seconds (the status line waits)."""
    parts = [(parts, color)] if isinstance(parts, str) else parts
    await _cmd(srv, f"title {who} actionbar {component(parts)}")
    st.setdefault("popup_until", {})[who] = time.time() + POPUP_SECS


async def status(srv, st: dict, who: str, text: str, color: str = "yellow") -> None:
    """The quiet line above the hotbar, unless a popup is showing."""
    if time.time() < st.get("popup_until", {}).get(who, 0):
        return
    if text:
        await _cmd(srv, f"title {who} actionbar {component([(text, color)])}")
