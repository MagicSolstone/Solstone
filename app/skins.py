"""Player skins straight from Mojang, cached on disk.

Third-party head services cache skins for a long time and sometimes hand back the
default Steve skin. Mojang's session server is the source of truth: the profile for
a UUID names the current skin file on textures.minecraft.net.
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import os
import re
import time
from urllib.parse import urlparse

import httpx

from .config import config

log = logging.getLogger("solstone.skins")

PROFILE_URL = "https://sessionserver.mojang.com/session/minecraft/profile/{uuid}"
FRESH = 3600              # re-check Mojang this often (skins can change; a join re-checks at once)
MISS_TTL = 30 * 60        # remember "no skin" (offline-mode UUIDs, outages) this long
_UUID = re.compile(r"^[0-9a-f]{32}$")
_dir = config.data_dir / "skins"
_misses: dict[str, float] = {}
_locks: dict[str, asyncio.Lock] = {}


def clean_uuid(u: str) -> str | None:
    u = str(u).replace("-", "").lower()
    return u if _UUID.match(u) else None


async def _fetch(uuid: str) -> tuple[bytes, bool] | None:
    async with httpx.AsyncClient(timeout=6, follow_redirects=False) as c:
        r = await c.get(PROFILE_URL.format(uuid=uuid))
        if r.status_code != 200:
            return None          # 204 = no such Mojang profile (offline-mode UUID)
        props = r.json().get("properties") or []
        tex = next((p.get("value") for p in props if p.get("name") == "textures"), None)
        if not tex:
            return None
        info = json.loads(base64.b64decode(tex)).get("textures", {}).get("SKIN") or {}
        url = info.get("url")
        slim = (info.get("metadata") or {}).get("model") == "slim"
        if not url or urlparse(url).hostname != "textures.minecraft.net":
            return None
        r = await c.get(url.replace("http://", "https://", 1))
        if r.status_code != 200 or not r.content.startswith(b"\x89PNG"):
            return None
        return r.content, slim


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
            data, slim = data
            _dir.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(data)
            tmp.replace(path)
            (_dir / f"{uuid}.json").write_text(json.dumps({"slim": slim}))
            _misses.pop(uuid, None)
            return data
        _misses[uuid] = time.monotonic()
        return path.read_bytes() if path.is_file() else None   # an older copy beats nothing


def stale(uuid: str) -> None:
    """Re-check this player's skin on the next request (they just joined, maybe in a new skin)."""
    uuid = clean_uuid(uuid)
    if not uuid:
        return
    _misses.pop(uuid, None)
    path = _dir / f"{uuid}.png"
    if path.is_file():
        try:
            os.utime(path, (0, 0))
        except OSError:
            pass


def _slim(uuid: str, img) -> bool:
    try:
        return bool(json.loads((_dir / f"{uuid}.json").read_text()).get("slim"))
    except (OSError, ValueError):
        # No note from Mojang: slim arms leave the last two columns of the arm's back face empty.
        return img.height == 64 and img.getpixel((55, 20))[3] == 0


# Front view of the whole player, 16x32 skin pixels: (source x, y, width, height, dest x, y).
def _parts(slim: bool, modern: bool) -> list[tuple]:
    a = 3 if slim else 4
    base = [(8, 8, 8, 8, 4, 0), (20, 20, 8, 12, 4, 8), (44, 20, a, 12, 4 - a, 8), (4, 20, 4, 12, 4, 20)]
    if modern:
        base += [(36, 52, a, 12, 12, 8), (20, 52, 4, 12, 8, 20)]
        over = [(40, 8, 8, 8, 4, 0), (20, 36, 8, 12, 4, 8), (44, 36, a, 12, 4 - a, 8), (4, 36, 4, 12, 4, 20),
                (52, 52, a, 12, 12, 8), (4, 52, 4, 12, 8, 20)]
        return base + over
    return base + [(40, 8, 8, 8, 4, 0)]


def body(skin_png: bytes, uuid: str, height: int = 256) -> bytes:
    """A flat front view of the player in their skin, scaled up without blurring."""
    from PIL import Image, ImageOps

    img = Image.open(io.BytesIO(skin_png)).convert("RGBA")
    modern = img.height == 64
    slim = _slim(clean_uuid(uuid) or "", img)
    out = Image.new("RGBA", (16, 32), (0, 0, 0, 0))
    for sx, sy, w, h, dx, dy in _parts(slim, modern):
        out.alpha_composite(img.crop((sx, sy, sx + w, sy + h)), (dx, dy))
    if not modern:                                  # old 64x32 skins: the left limbs mirror the right ones
        out.alpha_composite(ImageOps.mirror(img.crop((44, 20, 48, 32))), (12, 8))
        out.alpha_composite(ImageOps.mirror(img.crop((4, 20, 8, 32))), (8, 20))
    k = max(1, min(16, height // 32))
    buf = io.BytesIO()
    out.resize((16 * k, 32 * k), Image.NEAREST).save(buf, "PNG")
    return buf.getvalue()
