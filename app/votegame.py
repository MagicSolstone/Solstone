"""Votes in the game: a new vote is announced in chat (each choice clickable on Java), "!vote 2" counts for the
newest open vote, and when a vote closes everyone hears who won. The votes themselves are in community.py."""
from __future__ import annotations

import json
import logging
import re

from . import auth, community, notify
from . import servers as S
from .rcon import RconError

log = logging.getLogger("solstone.votes")
VOTE = re.compile(r"^\s*!vote\s+(\d{1,2})\s*$", re.I)


def _voter(name: str) -> str:
    """An account's vote if the name is linked to one (so the website and the game share one vote), else the name's."""
    for u in auth.list_users():
        if any(p["name"].lower() == name.lower() for p in u["players"]):
            return f"u{u['id']}"
    return f"p:{name.lower()}"


def _say(parts: list[dict]) -> str:
    return json.dumps(parts, ensure_ascii=False)


async def _tell(srv: S.Server, who: str, parts: list[dict]) -> None:
    try:
        await srv.rcon(f"tellraw {who} {_say(parts)}")
    except RconError as e:
        log.debug("vote message not sent on %s: %s", srv.id, e)


def _java(servers: list[S.Server]) -> list[S.Server]:
    return [s for s in servers if s.is_java and s.rcon_conf()]


async def announce(p: dict, servers: list[S.Server]) -> None:
    lines: list[dict] = [{"text": "🗳 New vote: ", "color": "gold", "bold": True}, {"text": p["question"] + "\n"}]
    for i, o in enumerate(p["options"], 1):
        cmd = f"!vote {i}"
        by = f" (by {', '.join(o['builders'])})" if o.get("builders") else ""
        # both spellings of a click: clickEvent before 1.21.5, click_event after (each version ignores the other)
        lines.append({"text": f"  [{i}] {o['text']}{by}\n", "color": "aqua",
                      "clickEvent": {"action": "suggest_command", "value": cmd}, "click_event": {"action": "suggest_command", "command": cmd}})
    lines.append({"text": "Type !vote and the number in chat, or vote on the website.", "color": "gray"})
    for srv in _java(servers):
        await _tell(srv, "@a", lines)


async def announce_result(p: dict, servers: list[S.Server]) -> None:
    for srv in _java(servers):
        await _tell(srv, "@a", [{"text": "🗳 Vote closed: ", "color": "gold", "bold": True},
                                {"text": f"{p['question']}\n"}, {"text": community.result_text(p), "color": "green"}])


async def on_chat(srv: S.Server, player: str, text: str) -> None:
    m = VOTE.match(text or "")
    if not m:
        return
    open_ = community.open_polls()
    if not open_:
        await _tell(srv, player, [{"text": "There's no vote open right now.", "color": "gray"}])
        return
    p, n = open_[0], int(m.group(1))
    if not 1 <= n <= len(p["options"]):
        await _tell(srv, player, [{"text": f"Pick a number from 1 to {len(p['options'])}.", "color": "red"}])
        return
    option = p["options"][n - 1]
    try:
        community.vote(p["id"], _voter(player), option["id"])
    except ValueError as e:
        await _tell(srv, player, [{"text": str(e), "color": "red"}])
        return
    await _tell(srv, player, [{"text": "🗳 Thanks! ", "color": "gold"}, {"text": f"You voted for {option['text']}. "},
                              {"text": "You can change it until the vote closes.", "color": "gray"}])


async def tick(servers: list[S.Server]) -> None:
    """New votes announced, votes whose time is up closed (with their notices)."""
    for p in community.to_announce():
        await announce(p, servers)
    for p in community.close_due():
        await closed(p, servers)
    community.tidy()                                  # old notices go after a month


async def closed(p: dict, servers: list[S.Server]) -> None:
    community.closed_notices(p)
    await announce_result(p, servers)


def new_message(user_name: str, subject: str) -> None:
    """Tell the admins (ntfy / Discord), if they want to know about messages."""
    notify.maybe_notify("messages", "Solstone", f"✉️ {user_name}: {subject}")
