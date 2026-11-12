"""Bedrock accounts linked to Java ones (Floodgate's global linking, run by GeyserMC).

A Bedrock player who has linked their Xbox account to a Java account (once, on GeyserMC's link server) joins as that
Java player: the same name, inventory and progress. Solstone only reads the link, from GeyserMC's public API, to say so
on the player pages; it never makes or changes one (that's done by the player, on both editions, so only they can).
"""
from __future__ import annotations

import asyncio
import logging
import time

import httpx

from .skins import bedrock_xuid

log = logging.getLogger("solstone.bedrocklink")

LINK_URL = "https://api.geysermc.org/v2/link/bedrock/{xuid}"
KEEP_LINKED = 6 * 3600          # a link is looked up again after this long (an unlink shows within the day)
KEEP_NOT = 3600                 # not linked: asked again sooner, so a new link shows soon after it's made
_cache: dict[int, tuple[float, dict | None]] = {}


async def _fetch(xuid: int) -> dict | None:
    async with httpx.AsyncClient(timeout=8, headers={"User-Agent": "Solstone (Minecraft server dashboard)"}) as c:
        r = await c.get(LINK_URL.format(xuid=xuid))
        r.raise_for_status()
        data = r.json() or {}
    if not data.get("java_id"):
        return None
    jid = str(data["java_id"]).replace("-", "").lower()
    return {"java_uuid": f"{jid[:8]}-{jid[8:12]}-{jid[12:16]}-{jid[16:20]}-{jid[20:]}" if len(jid) == 32 else data["java_id"],
            "java_name": data.get("java_name") or ""}


async def linked_java(uuid: str) -> dict | None:
    """The Java account a Bedrock player (by their Floodgate UUID) is linked to: {java_uuid, java_name}, or None (not
    linked, or not a Bedrock player). Raises when GeyserMC can't be asked and nothing is remembered."""
    xuid = bedrock_xuid(uuid)
    if xuid is None:
        return None
    hit = _cache.get(xuid)
    if hit and time.time() - hit[0] < (KEEP_LINKED if hit[1] else KEEP_NOT):
        return hit[1]
    try:
        found = await _fetch(xuid)
    except (httpx.HTTPError, ValueError):
        if hit:                                       # (GeyserMC down: what was known)
            return hit[1]
        raise
    _cache[xuid] = (time.time(), found)
    return found


async def bedrock_for(java_uuid: str, bedrock_uuids: list[str]) -> list[str]:
    """Which of these Bedrock players are linked to this Java account (looked up together; ones that fail are left out)."""
    want = java_uuid.replace("-", "").lower()

    async def one(u: str) -> str | None:
        try:
            link = await linked_java(u)
        except Exception:
            return None
        return u if link and link["java_uuid"].replace("-", "").lower() == want else None
    found = await asyncio.gather(*(one(u) for u in bedrock_uuids[:30]))
    return [u for u in found if u]
