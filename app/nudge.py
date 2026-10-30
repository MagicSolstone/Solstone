"""Reminders in the game about the website, so it doesn't get forgotten: what's waiting there for a player (new
messages, a vote they haven't voted in). Nothing is ever sent when nothing's waiting. Three moments, two texts:

- When they join (every time), if something's waiting: the "waiting" text, a few seconds after the welcome message.
- While they play, when a new message reaches them (from an admin, or a notice like a vote's result): the "new
  message" text, straight away.
- While they keep playing with something still waiting: the "waiting" text again, every so often (an hour to start;
  0 switches it off).

Admins write both texts (Website → Welcome in the game), with the welcome message's & colour codes, clickable web
addresses and fill-ins, plus {waiting} ("2 new messages and a vote"), {messages} and {votes}.

And for players without a website account (while sign-up is open): an invitation to make one, when they join (the
first time, once a day, or every time), so voting, events and messages aren't missed. Never forced.
"""
from __future__ import annotations

import asyncio
import logging
import time

from datetime import datetime

from . import auth, community, db, settings_store, welcome

log = logging.getLogger("solstone.nudge")

SECTION = "nudge"
DEFAULTS = {"join": True, "live": True, "repeat_minutes": 60,
            "join_text": "&6✉ Waiting for you on the website:&r {waiting}. &7{site}",
            "live_text": "&6✉ You've got a new message on the website!&r Read it: &7{site}",
            # players with no account yet
            "signup": "day",
            "signup_text": "&6★ Make a free account on the website&r to vote, see what's coming up and say you're coming: &7{site}&r "
                           "(sign up with your Minecraft name; a code shows up here in chat)"}
SIGNUP_WHEN = ("off", "first", "day", "every")
SIGNUP_DELAY = 9.0            # after the welcome message and the "waiting for you" line
DELAY = 6.0                   # after the welcome message
REJOIN = 120                  # seconds: joining again this soon (a dropped connection) doesn't repeat it
CHECK_EVERY = 10              # seconds between looks at who's playing


def config() -> dict:
    saved = settings_store.load().get(SECTION) or {}
    out = {**DEFAULTS, **{k: v for k, v in saved.items() if k in DEFAULTS}}
    out["repeat_minutes"] = max(0, min(24 * 60, int(out.get("repeat_minutes") or 0)))
    if out["signup"] not in SIGNUP_WHEN:
        out["signup"] = DEFAULTS["signup"]
    return out


def save(body: dict) -> dict:
    cur = config()
    for k in ("join", "live"):
        if k in body:
            cur[k] = bool(body[k])
    if body.get("signup") in SIGNUP_WHEN:
        cur["signup"] = body["signup"]
    for k in ("join_text", "live_text", "signup_text"):
        if k in body:
            cur[k] = welcome.clean(body[k])[:400] or DEFAULTS[k]
    if "repeat_minutes" in body:
        try:
            cur["repeat_minutes"] = max(0, min(24 * 60, int(body["repeat_minutes"])))
        except (TypeError, ValueError):
            pass
    settings_store.save_section(SECTION, cur)
    return cur


def _account(name: str) -> dict | None:
    for u in auth.list_users():
        if any(p["name"].lower() == name.lower() for p in u["players"]):
            return u
    return None


def waiting(name: str) -> tuple[int, int]:
    """(new messages, votes they haven't voted in) for a Minecraft name."""
    u = _account(name)
    msgs = community.unread(u["id"]) if u else 0
    voter = f"u{u['id']}" if u else f"p:{name.lower()}"
    return msgs, len(community.unvoted(voter))


def describe(msgs: int, votes: int) -> str:
    bits = []
    if msgs:
        bits.append(f"{msgs} new message{'s' if msgs != 1 else ''}")
    if votes:
        bits.append("a vote" if votes == 1 else f"{votes} votes")
    return " and ".join(bits)


def lines(text: str, player: str, server: str, msgs: int = 0, votes: int = 0) -> list[str]:
    text = (text.replace("{waiting}", describe(msgs, votes)).replace("{messages}", str(msgs)).replace("{votes}", str(votes)))
    return welcome.commands(player, welcome.fill(text, player, server))


# what each player online has heard: name (lowercase) -> {"msgs": unread when last looked, "at": last reminder}
_seen: dict[str, dict] = {}
_checked = 0.0


def on_join(srv, player: str) -> None:
    """A player joined: tell them what's waiting, if anything (every time they join)."""
    cfg = config()
    if not player:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:                         # the log reader's thread: the online check sends it instead
        return
    key = player.lower()
    if time.time() - _seen.get(key, {}).get("joined", 0) < REJOIN:
        return
    try:
        msgs, votes = waiting(player)
    except Exception:
        log.exception("reminder check failed for %s", player)
        return
    _seen[key] = {"msgs": msgs, "at": time.time(), "joined": time.time()}
    if cfg["join"] and (msgs or votes):
        loop.create_task(welcome.send(srv, lines(cfg["join_text"], player, srv.display_name, msgs, votes), DELAY))
    if signup_due(cfg, player):
        loop.create_task(welcome.send(srv, lines(cfg["signup_text"], player, srv.display_name, msgs, votes), SIGNUP_DELAY))


def signup_due(cfg: dict, player: str) -> bool:
    """The invitation to make an account: only for players without one, only while sign-up is open, as often as set."""
    from . import site
    if cfg["signup"] == "off" or not site.config().get("signup") or _account(player):
        return False
    key = player.lower()
    if cfg["signup"] == "first":
        return db.alert_once(f"nudge-signup:{key}")
    if cfg["signup"] == "day":
        return db.alert_once(f"nudge-signup:{key}:{datetime.now(db.tz()).date().isoformat()}")
    return True


async def tick(servers: list) -> None:
    """Every few seconds: a new message for someone playing gets a heads-up; something still waiting gets the
    reminder again once the set time has gone by."""
    from . import servers as S
    global _checked
    cfg = config()
    now = time.time()
    if now - _checked < CHECK_EVERY or not (cfg["live"] or cfg["repeat_minutes"]):
        return
    _checked = now
    online: set[str] = set()
    for srv in [s for s in servers if s.is_java and s.rcon_conf()]:
        try:
            names, src = await S.online_players(srv)
        except Exception:
            continue
        if src != "rcon":
            continue
        for name in names:
            key = name.lower()
            online.add(key)
            msgs, votes = await asyncio.to_thread(waiting, name)
            seen = _seen.get(key)
            if seen is None:                     # on before Solstone started, or the join was missed: start from now
                _seen[key] = {"msgs": msgs, "at": now, "joined": now}
                continue
            if cfg["live"] and msgs > seen["msgs"]:
                await welcome.send(srv, lines(cfg["live_text"], name, srv.display_name, msgs, votes), 0)
                seen["at"] = now
            elif cfg["repeat_minutes"] and (msgs or votes) and now - seen["at"] >= cfg["repeat_minutes"] * 60:
                await welcome.send(srv, lines(cfg["join_text"], name, srv.display_name, msgs, votes), 0)
                seen["at"] = now
            seen["msgs"] = msgs
    for key in [k for k in _seen if k not in online and now - _seen[k].get("joined", 0) > REJOIN]:
        del _seen[key]                           # left: next time they join, it starts over
