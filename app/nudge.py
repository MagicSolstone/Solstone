"""Reminders in the game about the website, so it doesn't get forgotten: what's waiting there for a player (new
messages, a vote they haven't voted in). Never spam: nothing is sent when nothing's waiting.

- When they join: one line, a few seconds after the welcome message, at most once every few hours (12 to start).
- While they play: when an admin writes to them, a heads-up right away, at most once every half hour.

Admins write both texts (Website → Welcome in the game), with the welcome message's & colour codes, clickable web
addresses and fill-ins, plus {waiting} ("2 new messages and a vote"), {messages} and {votes}.
"""
from __future__ import annotations

import asyncio
import logging
import time

from . import auth, community, db, settings_store, welcome

log = logging.getLogger("solstone.nudge")

SECTION = "nudge"
DEFAULTS = {"join": True, "live": True, "hours": 12,
            "join_text": "&6✉ Waiting for you on the website:&r {waiting}. &7{site}",
            "live_text": "&6✉ An admin sent you a message!&r Read it on the website: &7{site}"}
LIVE_EVERY = 1800             # seconds: at most one heads-up per half hour
DELAY = 6.0                   # after the welcome message


def config() -> dict:
    saved = settings_store.load().get(SECTION) or {}
    out = {**DEFAULTS, **{k: v for k, v in saved.items() if k in DEFAULTS}}
    out["hours"] = max(1, min(72, int(out.get("hours") or 12)))
    return out


def save(body: dict) -> dict:
    cur = config()
    for k in ("join", "live"):
        if k in body:
            cur[k] = bool(body[k])
    for k in ("join_text", "live_text"):
        if k in body:
            cur[k] = welcome.clean(body[k])[:400] or DEFAULTS[k]
    if "hours" in body:
        try:
            cur["hours"] = max(1, min(72, int(body["hours"])))
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
    votes = 0
    for p in community.open_polls():
        own = set(community.own_entries(p, voter)) if p["kind"] == "build" else set()
        if community.my_vote(p["id"], voter) is None and len(own) < len(p["options"]):
            votes += 1
    return msgs, votes


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


def on_join(srv, player: str) -> None:
    """A player joined: tell them what's waiting, if anything, and not more often than every few hours."""
    cfg = config()
    if not cfg["join"] or not player:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:                         # the log reader's thread: the online check sends it instead
        return
    try:
        msgs, votes = waiting(player)
    except Exception:
        log.exception("reminder check failed for %s", player)
        return
    if not (msgs or votes):
        return
    if not db.alert_once(f"nudge:{player.lower()}:{int(time.time() // (cfg['hours'] * 3600))}"):
        return
    loop.create_task(welcome.send(srv, lines(cfg["join_text"], player, srv.display_name, msgs, votes), DELAY))


async def poke(user_id: int) -> None:
    """An admin just wrote to this player: if they're playing right now, a heads-up (at most every half hour)."""
    from . import servers as S
    cfg = config()
    u = auth.get_user(user_id)
    if not cfg["live"] or not u or not u.players:
        return
    names = {p["name"].lower(): p["name"] for p in u.players}
    for srv in [s for s in S.registry.servers.values() if s.is_java and s.rcon_conf()]:
        try:
            online, _src = await S.online_players(srv)
        except Exception:
            continue
        here = [n for n in online if n.lower() in names]
        if here:
            if not db.alert_once(f"nudgelive:{user_id}:{int(time.time() // LIVE_EVERY)}"):
                return
            msgs, votes = await asyncio.to_thread(waiting, here[0])
            await welcome.send(srv, lines(cfg["live_text"], here[0], srv.display_name, msgs, votes), 0)
            return
