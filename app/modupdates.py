"""Which of a server's mods have a newer build: asked of Modrinth by each jar's fingerprint (its SHA-512), for the
server's own Minecraft version and loader, so only builds that would actually run there are offered.

Geyser and Floodgate matter most: when Bedrock updates, they need updating too, or Bedrock players can't join. A
daily check can send a notification for new builds (Notifications → "Mod updates"), once per new version.
Mods that aren't on Modrinth (a jar built at home, like Tide+) are listed as such; they're checked by hand.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from pathlib import Path

import httpx

from . import servers as S
from . import settings_store

log = logging.getLogger("solstone.modupdates")

MODRINTH = "https://api.modrinth.com/v2"
UA = "MagicSolstone/Solstone (Minecraft server dashboard)"
CACHE_SECS = 3600
BEDROCK_MODS = ("geyser", "floodgate")          # Bedrock players can't join when these fall behind
_cache: dict[str, tuple[float, dict]] = {}


def important(mod: dict) -> bool:
    text = f"{mod.get('id', '')} {mod.get('name', '')}".lower()
    return any(k in text for k in BEDROCK_MODS)


def _sha512(path: Path) -> str:
    h = hashlib.sha512()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


async def _post(url: str, body: dict):
    async with httpx.AsyncClient(timeout=20, headers={"User-Agent": UA}) as c:
        r = await c.post(url, json=body)
        r.raise_for_status()
        return r.json()


def _loader(srv) -> str:
    name = (S.detect_loader(srv) or "").lower()
    return next((k for k in ("neoforge", "forge", "quilt", "fabric") if k in name), "fabric")


async def check(srv, force: bool = False) -> dict:
    """{"checked", "mc", "loader", "mods": {file: {status, current, latest, url, important}}, "error"}.
    status: "update" (a newer build for this server), "ok", or "unknown" (not on Modrinth)."""
    hit = _cache.get(srv.id)
    if hit and not force and time.time() - hit[0] < CACHE_SECS:
        return hit[1]
    mods = await asyncio.to_thread(S.mods, srv)
    mc, loader = srv.mc_version, _loader(srv)
    hashes: dict[str, dict] = {}
    for m in mods:
        jar = srv.dir / "mods" / m["file"]
        digest = await asyncio.to_thread(S._cache.get, ("sha512", str(jar)), jar, _sha512)
        if digest:
            hashes[digest] = m
    out = {"checked": time.time(), "mc": mc, "loader": loader, "mods": {}, "error": None}
    try:
        current = await _post(f"{MODRINTH}/version_files", {"hashes": list(hashes), "algorithm": "sha512"}) if hashes else {}
        newest = await _post(f"{MODRINTH}/version_files/update", {"hashes": list(hashes), "algorithm": "sha512", "loaders": [loader],
                                                                   **({"game_versions": [mc]} if mc else {})}) if hashes else {}
    except (httpx.HTTPError, ValueError) as e:
        out["error"] = f"Couldn't ask Modrinth: {e}"
        return out
    for digest, m in hashes.items():
        cur, new = current.get(digest), newest.get(digest)
        row = {"name": m.get("name") or m["file"], "current": m.get("version") or "", "important": important(m), "status": "unknown"}
        if cur:
            row["status"] = "ok"
            if new and new.get("id") != cur.get("id") and str(new.get("date_published", "")) > str(cur.get("date_published", "")):
                row.update(status="update", latest=new.get("version_number") or "", latest_id=new["id"],
                           url=f"https://modrinth.com/project/{new.get('project_id', cur.get('project_id'))}/version/{new['id']}")
        out["mods"][m["file"]] = row
    _cache[srv.id] = (time.time(), out)
    return out


def updates_line(result: dict, only_new: bool = True, server_id: str = "") -> str | None:
    """A notification line for builds not told about yet ("Geyser 2.6.1 → 2.7.0, Lithium …"), and remember them."""
    seen = settings_store.load().get("mod_updates_told") or {}
    told = set(seen.get(server_id, []))
    rows = [r for r in result["mods"].values() if r["status"] == "update" and (not only_new or r["latest_id"] not in told)]
    if not rows:
        return None
    rows.sort(key=lambda r: (not r["important"], r["name"].lower()))
    seen[server_id] = sorted(told | {r["latest_id"] for r in rows})[-200:]
    settings_store.save_section("mod_updates_told", seen)
    bedrock = any(r["important"] for r in rows)
    return (("Bedrock players need these: " if bedrock else "") +
            ", ".join(f"{r['name']} {r['current']} → {r['latest']}" for r in rows[:8]) + (f" and {len(rows) - 8} more" if len(rows) > 8 else ""))
