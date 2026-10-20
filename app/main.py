"""Lodestone — a family-friendly dashboard for Minecraft servers run by Crafty Controller."""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import servers as S
from . import settings_store
from .assets import assets_for, safe_texture_path, store
from .config import config
from .crafty import crafty

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("lodestone")
STATIC = Path(__file__).parent / "static"
VERSION = "1.0.0"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await S.registry.refresh(force=True)
    log.info("Lodestone %s — %d server(s) found", VERSION, len(S.registry.servers))
    yield
    await crafty.close()


app = FastAPI(title="Lodestone", version=VERSION, lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=1024)


async def _server(sid: str) -> S.Server:
    srv = await S.registry.get(sid)
    if not srv:
        raise HTTPException(404, "Server not found")
    return srv


def _assets(srv: S.Server):
    version = srv.mc_version
    if not version:
        return None
    return assets_for(version, tuple(str(p) for p in S.mod_jars(srv)), srv.id)


# ------------------------------------------------------------------ overview
@app.get("/api/health", include_in_schema=False)
async def health():
    return {"status": "ok", "version": VERSION}


@app.get("/api/status")
async def status():
    await S.registry.refresh()
    return {
        "version": VERSION,
        "crafty": {"configured": crafty.enabled, "url": config.crafty_url or None, "error": crafty.last_error},
        "servers_dir": str(config.servers_dir),
        "servers_dir_found": config.servers_dir.is_dir(),
        "server_count": len(S.registry.servers),
        "settings_locked": bool(config.admin_token),
    }


@app.get("/api/servers")
async def list_servers():
    await S.registry.refresh()
    visible = [s for s in S.registry.servers.values() if not s.settings.get("hidden")]
    results = await asyncio.gather(*(S.server_summary(s) for s in visible), return_exceptions=True)
    out = []
    for srv, r in zip(visible, results, strict=True):
        if isinstance(r, Exception):
            log.warning("summary failed for %s: %s", srv.id, r)
            out.append({"id": srv.id, "name": srv.display_name, "error": str(r)})
        else:
            out.append(r)
    return out


@app.get("/api/servers/{sid}")
async def get_server(sid: str):
    return await S.server_summary(await _server(sid))


@app.get("/api/servers/{sid}/world")
async def get_world(sid: str):
    srv = await _server(sid)
    return await asyncio.to_thread(S.world_info, srv)


@app.get("/api/servers/{sid}/mods")
async def get_mods(sid: str):
    srv = await _server(sid)
    return {"loader": S.detect_loader(srv), "mods": await asyncio.to_thread(S.mods, srv)}


@app.get("/api/servers/{sid}/players")
async def get_players(sid: str):
    return await S.players_overview(await _server(sid))


@app.get("/api/servers/{sid}/players/{uuid}")
async def get_player(sid: str, uuid: str):
    data = await S.player_detail(await _server(sid), uuid)
    if not data:
        raise HTTPException(404, "Player not found")
    return data


@app.get("/api/servers/{sid}/leaderboard")
async def get_leaderboard(sid: str):
    return await S.leaderboard(await _server(sid))


@app.get("/api/servers/{sid}/icon.png")
async def server_icon(sid: str):
    data = S.server_icon_bytes(await _server(sid))
    if not data:
        raise HTTPException(404)
    return Response(data, media_type="image/png", headers={"Cache-Control": "max-age=300"})


@app.put("/api/servers/{sid}/settings")
async def put_settings(sid: str, request: Request, x_admin_token: str | None = Header(default=None)):
    if config.admin_token and x_admin_token != config.admin_token:
        raise HTTPException(403, "Admin token required to change settings")
    srv = await _server(sid)
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(400, "Expected a JSON object")
    saved = settings_store.update_server(srv.id, body)
    safe = {k: v for k, v in saved.items() if k != "rcon_password"}
    safe["rcon_password_set"] = "rcon_password" in saved
    return safe


@app.get("/api/servers/{sid}/settings")
async def get_settings(sid: str):
    srv = await _server(sid)
    s = dict(srv.settings)
    s["rcon_password_set"] = "rcon_password" in s
    s.pop("rcon_password", None)
    return s


# ------------------------------------------------------------------ assets
@app.get("/api/servers/{sid}/assets/status")
async def assets_status(sid: str):
    srv = await _server(sid)
    version = srv.mc_version
    if not version:
        return {"state": "unknown", "error": "Couldn't work out the Minecraft version for this server"}
    vs = store(version)
    vs.ensure()
    return vs.status()


@app.get("/api/servers/{sid}/assets/lang")
async def assets_lang(sid: str):
    a = _assets(await _server(sid))
    if not a:
        return {}
    data = await asyncio.to_thread(a.lang)
    return JSONResponse(data, headers={"Cache-Control": "max-age=600"})


@app.get("/api/servers/{sid}/assets/advancements")
async def assets_advancements(sid: str):
    a = _assets(await _server(sid))
    if not a or not a.ready:
        return []
    return await asyncio.to_thread(a.advancements)


@app.get("/api/servers/{sid}/assets/item/{ns}/{name}.png")
async def item_icon(sid: str, ns: str, name: str):
    a = _assets(await _server(sid))
    if not a:
        raise HTTPException(404)
    data = await asyncio.to_thread(a.icon, f"{ns}:{name}")
    if not data:
        raise HTTPException(404)
    return Response(data, media_type="image/png", headers={"Cache-Control": "public, max-age=604800"})


@app.get("/api/servers/{sid}/assets/texture/{path:path}")
async def texture(sid: str, path: str):
    a = _assets(await _server(sid))
    rel = safe_texture_path(path.removesuffix(".png"))
    if not a or not rel:
        raise HTTPException(404)
    data = a.read(rel)
    if not data:
        raise HTTPException(404)
    return Response(data, media_type="image/png", headers={"Cache-Control": "public, max-age=604800"})


# ------------------------------------------------------------------ frontend
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/{full_path:path}", include_in_schema=False)
async def spa(full_path: str):
    if full_path.startswith("api/"):
        raise HTTPException(404)
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})
