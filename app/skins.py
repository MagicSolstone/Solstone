"""Player skins straight from Mojang, cached on disk.

Third-party head services cache skins for a long time and sometimes hand back the
default Steve skin. Mojang's session server is the source of truth: the profile for
a UUID names the current skin file on textures.minecraft.net.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import time
from urllib.parse import urlparse

import httpx

from .config import config

log = logging.getLogger("solstone.skins")

PROFILE_URL = "https://sessionserver.mojang.com/session/minecraft/profile/{uuid}"
FRESH = 3 * 3600          # re-check Mojang this often (skins can change)
MISS_TTL = 30 * 60        # remember "no skin" (offline-mode UUIDs, outages) this long
_UUID = re.compile(r"^[0-9a-f]{32}$")
_dir = config.data_dir / "skins"
_misses: dict[str, float] = {}
_locks: dict[str, asyncio.Lock] = {}


def clean_uuid(u: str) -> str | None:
    u = str(u).replace("-", "").lower()
    return u if _UUID.match(u) else None


async def _fetch(uuid: str) -> bytes | None:
    async with httpx.AsyncClient(timeout=6, follow_redirects=False) as c:
        r = await c.get(PROFILE_URL.format(uuid=uuid))
        if r.status_code != 200:
            return None          # 204 = no such Mojang profile (offline-mode UUID)
        props = r.json().get("properties") or []
        tex = next((p.get("value") for p in props if p.get("name") == "textures"), None)
        if not tex:
            return None
        url = (json.loads(base64.b64decode(tex)).get("textures", {}).get("SKIN") or {}).get("url")
        if not url or urlparse(url).hostname != "textures.minecraft.net":
            return None
        r = await c.get(url.replace("http://", "https://", 1))
        if r.status_code != 200 or not r.content.startswith(b"\x89PNG"):
            return None
        return r.content


async def skin(uuid: str) -> bytes | None:
    """The player's current skin PNG, or None if Mojang has none for this UUID."""
    uuid = clean_uuid(uuid)
    if not uuid:
        return None
    path = _dir / f"{uuid}.png"
    if path.is_file() and time.time() - path.stat().st_mtime < FRESH:
        return path.read_bytes()
    if time.monotonic() - _misses.get(uuid, -1e9) < MISS_TTL:
        return path.read_bytes() if path.is_file() else None
    async with _locks.setdefault(uuid, asyncio.Lock()):
        if path.is_file() and time.time() - path.stat().st_mtime < FRESH:
            return path.read_bytes()
        try:
            data = await _fetch(uuid)
        except Exception as e:
            log.debug("skin fetch failed for %s: %s", uuid, e)
            data = None
        if data:
            _dir.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(data)
            tmp.replace(path)
            _misses.pop(uuid, None)
            return data
        _misses[uuid] = time.monotonic()
        return path.read_bytes() if path.is_file() else None   # an older copy beats nothing
