"""Messages an admin writes once and sends into the game (Website → Game messages), formatted like the welcome
message (& colours, {player}, clickable web addresses):

  - to everyone playing right now;
  - to everyone, each the next time they join (once each, until it's taken down);
  - to one player: right away if they're on, otherwise the next time they join (then it's done).

Each keeps who it reached and when, so the list shows what's waiting and what's been sent.
"""
from __future__ import annotations

import asyncio
import logging
import secrets
import time

from . import settings_store, welcome

log = logging.getLogger("solstone.gamemsg")

SECTION = "game_messages"
KEPT = 60                     # the newest this many are kept (sent ones drop off first)
TO = ("online", "next", "player")
_lock = asyncio.Lock()
_busy: set[tuple[str, str]] = set()     # a join noticed twice (the log and the online check) sends once


def _load() -> list[dict]:
    items = settings_store.load().get(SECTION)
    return [x for x in items if isinstance(x, dict) and x.get("id")] if isinstance(items, list) else []


def _save(items: list[dict]) -> None:
    items = sorted(items, key=lambda x: -x["created"])
    while len(items) > KEPT:
        done = [x for x in items if x.get("done")]
        items.remove(done[-1] if done else items[-1])
    settings_store.save_section(SECTION, items)


def listing(sid: str) -> list[dict]:
    return [x for x in _load() if x["server"] == sid]


async def _send(srv, player: str, text: str) -> bool:
    from . import control
    try:
        for cmd in welcome.commands(player, welcome.fill(text, player, srv.display_name)):
            await control.run(srv, cmd)
        return True
    except Exception as e:
        log.info("game message to %s on %s not sent: %s", player, srv.id, e)
        return False


async def create(srv, text: str, to: str, player: str, by: str, online: list[str]) -> dict:
    """Make one and send what can be sent now. `online`: who's playing right now."""
    text = welcome.clean(text)
    if not text:
        raise ValueError("Write the message first")
    if to not in TO:
        raise ValueError("Pick who it's for")
    player = (player or "").strip()
    if to == "player" and not player:
        raise ValueError("Type the player's name")
    item = {"id": secrets.token_hex(5), "server": srv.id, "text": text, "to": to, "player": player if to == "player" else "",
            "by": by, "created": time.time(), "sent": {}, "done": False}
    targets = online if to == "online" else [n for n in online if n.lower() == player.lower()] if to == "player" else online
    for n in targets:
        if await _send(srv, n, text):
            item["sent"][n] = time.time()
    if to == "online" or (to == "player" and item["sent"]):
        item["done"] = True
    async with _lock:
        _save([*_load(), item])
    return item


def remove(sid: str, mid: str) -> bool:
    items = _load()
    keep = [x for x in items if not (x["id"] == mid and x["server"] == sid)]
    if len(keep) == len(items):
        return False
    _save(keep)
    return True


def due(sid: str, player: str) -> list[dict]:
    """Messages waiting for this player on this server: to them, or to everyone and not yet seen by them."""
    p = player.lower()
    return [x for x in sorted(_load(), key=lambda x: x["created"]) if x["server"] == sid and not x["done"] and
            ((x["to"] == "player" and x["player"].lower() == p) or (x["to"] == "next" and p not in {k.lower() for k in x["sent"]}))]


async def deliver(srv, player: str, delay: float = welcome.DELAY + 4) -> int:
    """Send what's waiting for someone who just joined (after the welcome message). Returns how many went."""
    await asyncio.sleep(delay)
    n = 0
    for x in due(srv.id, player):
        if not await _send(srv, player, x["text"]):
            break
        n += 1
        async with _lock:
            items = _load()
            for y in items:
                if y["id"] == x["id"]:
                    y["sent"][player] = time.time()
                    if y["to"] == "player":
                        y["done"] = True
            _save(items)
    return n


def on_join(srv, player: str) -> None:
    key = (srv.id, (player or "").lower())
    if not player or key in _busy or not due(srv.id, player):
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:                       # the log reader's thread: the online check sends it instead
        return
    _busy.add(key)

    async def run():
        try:
            await deliver(srv, player)
        finally:
            _busy.discard(key)
    loop.create_task(run())
