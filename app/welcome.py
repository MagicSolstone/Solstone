"""A welcome message in the game's chat when someone joins a server, written by an admin for each server.

The text is plain, with a few extras that work the same on Java and Bedrock:
  - colours and styles with the game's own & codes: &a green, &6 gold, &l bold, &o italic, &n underline, &r back to plain
  - {player}, {server}, {site} (the website's address) and {rules} (the rules page's address)
  - a web address (https://…) can be clicked on Java; Bedrock players see it written out
It's sent with tellraw only to the player who joined: on their first time, every time, or not at all.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time

from . import db, settings_store
from .config import config

log = logging.getLogger("solstone.welcome")

WHEN = ("off", "first", "every")
MAX_LEN = 800
MAX_LINES = 8
LINE_LEN = 200           # each line is its own tellraw, so a long message still fits in one command
DELAY = 3.0               # let the join messages go by first
COLOURS = {"0": "black", "1": "dark_blue", "2": "dark_green", "3": "dark_aqua", "4": "dark_red", "5": "dark_purple",
           "6": "gold", "7": "gray", "8": "dark_gray", "9": "blue", "a": "green", "b": "aqua", "c": "red",
           "d": "light_purple", "e": "yellow", "f": "white"}
STYLES = {"l": "bold", "o": "italic", "n": "underlined", "m": "strikethrough"}
_TOKEN = re.compile(r"&([0-9a-fklmnor])|(https?://[^\s<>\"']+)", re.I)
_recent: dict[tuple[str, str], float] = {}


def clean(text: str) -> str:
    lines = str(text or "").replace("\r", "").split("\n")
    return "\n".join(line.rstrip()[:LINE_LEN] for line in lines[:MAX_LINES]).strip()[:MAX_LEN]


def site_url() -> str:
    """PUBLIC_URL, or else the address the admin used when they saved a welcome message (the game has no page to ask)."""
    return config.public_url or str(settings_store.load().get("welcome_site") or "")


def fill(text: str, player: str, server: str) -> str:
    base = site_url()
    vals = {"player": player, "server": server, "site": base or "", "rules": f"{base}/guides/rules" if base else "the rules page"}
    return re.sub(r"\{(\w+)\}", lambda m: vals.get(m.group(1).lower(), m.group(0)), text)


def components(text: str) -> list[dict]:
    """The message as chat components: colours and styles carry on until changed or &r."""
    out: list[dict] = [{"text": ""}]          # a plain first part, so the rest don't inherit from each other
    style: dict = {}
    pos = 0

    def add(t: str, extra: dict | None = None):
        if t:
            out.append({"text": t, **style, **(extra or {})})
    for m in _TOKEN.finditer(text):
        add(text[pos:m.start()])
        pos = m.end()
        code, url = m.group(1), m.group(2)
        if url:
            url = url.rstrip(".,!?;:)")
            pos = m.start() + len(url)
            # both spellings of a click: clickEvent before 1.21.5, click_event after (each version ignores the other)
            add(url, {"underlined": True, **({} if "color" in style else {"color": "aqua"}),
                      "clickEvent": {"action": "open_url", "value": url}, "click_event": {"action": "open_url", "url": url}})
            continue
        code = code.lower()
        if code == "r":
            style = {}
        elif code in COLOURS:
            style = {"color": COLOURS[code]}        # a colour clears the styles, as in the game
        elif code in STYLES:
            style = {**style, STYLES[code]: True}
    add(text[pos:])
    return out


def commands(player: str, text: str) -> list[str]:
    """One tellraw per line (colours carry on to the next line, as they would in one message)."""
    out, carry = [], ""
    for line in text.split("\n"):
        codes = "".join(re.findall(r"&[0-9a-fklmnor]", carry + line, re.I))
        out.append(f"tellraw {player} {json.dumps(components(carry + line) if line.strip() else [{'text': ''}], ensure_ascii=False)}")
        last_colour = max((codes.lower().rfind(f"&{c}") for c in "0123456789abcdefr"), default=-1)
        carry = codes[last_colour:] if last_colour >= 0 else codes
    return out


def _returning(sid: str, player: str) -> bool:
    """Played here before (a session that started more than ten minutes ago)."""
    return bool(db.q("SELECT 1 FROM sessions WHERE server_id=? AND lower(player)=? AND start_ts < ? LIMIT 1",
                     (sid, player.lower(), time.time() - 600)))


def due(srv, player: str) -> list[str] | None:
    """The commands to send now, or None (off, already welcomed this time, or not their first time)."""
    st = srv.settings
    when, text = st.get("welcome_when") or "off", clean(st.get("welcome") or "")
    if when not in ("first", "every") or not text or not player:
        return None
    key = (srv.id, player.lower())
    if time.time() - _recent.get(key, 0) < 600:     # the log and the online check both notice a join
        return None
    welcomed = settings_store.load().get("welcomed") or {}
    if when == "first" and (player.lower() in welcomed.get(srv.id, []) or _returning(srv.id, player)):
        return None
    _recent[key] = time.time()
    if when == "first":
        welcomed.setdefault(srv.id, []).append(player.lower())
        settings_store.save_section("welcomed", welcomed)
    return commands(player, fill(text, player, srv.display_name))


async def send(srv, cmds: list[str], delay: float = DELAY) -> None:
    from . import control
    await asyncio.sleep(delay)
    try:
        for cmd in cmds:
            await control.run(srv, cmd)
    except Exception as e:                          # offline again, or no RCON: nothing to do
        log.info("welcome message for %s not sent: %s", srv.id, e)


def on_join(srv, player: str) -> None:
    cmds = due(srv, player)
    if cmds:
        try:
            asyncio.get_running_loop().create_task(send(srv, cmds))
        except RuntimeError:
            pass
