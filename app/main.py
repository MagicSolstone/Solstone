"""Solstone — a family-friendly dashboard for Minecraft servers run by Crafty Controller."""
from __future__ import annotations

import asyncio
import contextvars
import hashlib
import json
import logging
import os
import re
import time
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import adventures, auth, backups, board, challenges, control, db, fishing, fishpack, games, modpack, races, fireworks, fwshow, guard, notify, recap, selfcheck, signup, site, skins, tide, upcoming, worldmap
from . import servers as S
from . import settings_store
from .rcon import RconError
from .recorder import recorder
from .assets import assets_for, safe_texture_path, store
from .config import config
from .crafty import crafty

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("solstone")
STATIC = Path(__file__).parent / "static"
VERSION = "1.3.0"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await S.registry.refresh(force=True)
    log.info("Solstone %s — %d server(s) found", VERSION, len(S.registry.servers))
    db.conn()
    auth.bootstrap()
    if os.getenv("RECORDER_ENABLED", "true").lower() not in ("0", "false", "no"):
        recorder.start()
    yield
    await recorder.stop()
    await crafty.close()


app = FastAPI(title="Solstone", version=VERSION, lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=1024)

PUBLIC_API = {"/api/health", "/api/auth/login"}

# Scripts only from Solstone itself (no inline script, so injected HTML can't run code).
# Inline style attributes are used throughout, so styles allow them. Skins come from
# mc-heads.net; the World tab can embed a web map (BlueMap etc.) from wherever it's hosted.
CSP = "; ".join([
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob: https://mc-heads.net https://cdn.modrinth.com",      # Modrinth icons (family modpack)
    "media-src 'self' blob:",
    "font-src 'self'",
    "connect-src 'self'",
    "frame-src http: https:",
    "worker-src 'self' blob:",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'self'",
])
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


# The signed-in user of the request being handled (None when signed out), so server lookups can
# keep private servers to admins without every route passing the request along.
_viewer: contextvars.ContextVar = contextvars.ContextVar("solstone_viewer", default=None)


def _admin_viewing() -> bool:
    u = _viewer.get()
    return u is not None and u.is_admin


def _private(srv: S.Server) -> bool:
    """A private server (an admin's home server, say): only admins see it, never the public pages."""
    return bool(srv.settings.get("private"))


def _visible(srv: S.Server) -> bool:
    """Shown to whoever is asking: not hidden, and if private, only to an admin."""
    return not srv.settings.get("hidden") and (not _private(srv) or _admin_viewing())


# What a "player" account may use. Everything else under /api/ is refused, so a new page or route is
# closed to players until it's added here on purpose. (The public routes and sign-in are open to all.)
_ANY = {"GET", "POST", "PUT", "PATCH", "DELETE"}
PLAYER_ROUTES: dict[str, set[str]] = {
    "/api/health": {"GET"},
    "/api/servers": {"GET"},
    "/api/servers/{sid}": {"GET"},
    "/api/servers/{sid}/players": {"GET"},              # who's on; nobody else's whereabouts (see _for_player)
    "/api/servers/{sid}/players/{uuid}": {"GET"},       # their own page only
    "/api/servers/{sid}/players/{uuid}/history": {"GET"},
    "/api/servers/{sid}/leaderboard": {"GET"},
    "/api/servers/{sid}/icon.png": {"GET"},
    "/api/servers/{sid}/metrics": {"GET"},
    "/api/servers/{sid}/mods": {"GET"},
    "/api/servers/{sid}/recap": {"GET"},
    "/api/servers/{sid}/fishing/journal": {"GET"},
    "/api/servers/{sid}/fishing/tackle": {"GET"},
    "/api/servers/{sid}/assets/status": {"GET"},
    "/api/servers/{sid}/assets/lang": {"GET"},
    "/api/servers/{sid}/assets/items": {"GET"},
    "/api/servers/{sid}/assets/advancements": {"GET"},
    "/api/servers/{sid}/assets/item/{ns}/{name}.png": {"GET"},
    "/api/servers/{sid}/assets/texture/{path:path}": {"GET"},
    "/api/players/uuids": {"GET"},
    "/api/players/skins": {"GET"},
    "/api/skins/{uuid}.png": {"GET"},
    "/api/skins/{uuid}/body.png": {"GET"},
    "/api/upcoming": {"GET"},
    "/api/sounds": {"GET"},
}


def _player_may(method: str, path: str) -> bool:
    if not path.startswith("/api/") or path.startswith(("/api/public/", "/api/auth/")):
        return True
    if path.startswith("/api/fireworks"):                      # fireworks are for everyone
        return True
    return method in PLAYER_ROUTES.get(path, ()) or (method == "HEAD" and "GET" in PLAYER_ROUTES.get(path, ()))


async def _note_viewer(request: Request) -> None:
    """Run before every route, in the route's own context (unlike the middleware), so _viewer is set there.
    Also where a player account is kept to its own pages."""
    user = getattr(request.state, "user", None)
    _viewer.set(user)
    if user is not None and user.is_player:
        route = request.scope.get("route")
        if not _player_may(request.method, getattr(route, "path", request.url.path)):
            raise HTTPException(403, "Your account can't see that")


def _own(uuid: str) -> bool:
    """For a player account: is this their own Minecraft player? (Everyone else may see anyone.)"""
    u = _viewer.get()
    return u is None or not u.is_player or (u.player_uuid is not None and S.norm_uuid(uuid) == u.player_uuid)


_SUMMARY_FOR_PLAYERS = ("id", "name", "running", "crashed", "started", "cpu", "mem", "mem_percent", "world_size", "version", "motd",
                        "max_players", "online", "has_icon", "loader", "game", "game_label", "perf", "fishing", "error")


def _for_player(summary: dict) -> dict:
    """A server's summary without the running of it (folders, ports, RCON, backups, the web map)."""
    u = _viewer.get()
    if u is None or not u.is_player:
        return summary
    return {k: summary[k] for k in _SUMMARY_FOR_PLAYERS if k in summary} | {"folder_found": True}


app.router.dependencies.append(Depends(_note_viewer))


_proxy_warned = False


def _warn_proxy() -> None:
    """Once: requests come through a proxy or tunnel but its headers aren't trusted, so every visitor looks
    like the proxy (one wrong-password limit for everyone, and the sign-in cookie isn't marked secure)."""
    global _proxy_warned
    _proxy_warned = True
    log.warning("Requests arrive through a proxy (X-Forwarded-For / CF-Connecting-IP) but TRUST_PROXY_HEADERS is off: "
                "every visitor shares one address for the sign-in limit, and the cookie isn't marked Secure. "
                "Set TRUST_PROXY_HEADERS=true if Solstone is only reachable through that proxy.")


@app.middleware("http")
async def require_login(request: Request, call_next):
    """Every /api route needs a signed-in user except health and login. Changes also need
    the X-Solstone header, which cross-site pages can't send (CSRF protection)."""
    path = request.url.path
    if path.startswith("/api/"):
        if request.method not in SAFE_METHODS and request.headers.get("x-solstone") != "1":
            return JSONResponse({"detail": "Missing X-Solstone header"}, status_code=403)
        request.state.user = await asyncio.to_thread(auth.user_from_request, request)
        if request.state.user is None and path not in PUBLIC_API and not path.startswith("/api/public/"):
            return JSONResponse({"detail": "Sign in to continue"}, status_code=401)
    if not auth.TRUST_PROXY and not _proxy_warned and (request.headers.get("x-forwarded-for") or request.headers.get("cf-connecting-ip")):
        _warn_proxy()
    response = await call_next(request)
    if auth.is_https(request):
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Content-Security-Policy", CSP)
    if path.startswith("/static/") and response.status_code == 200:
        # Pages link CSS/JS with ?v=<build>, so those can be kept for good; a new build changes the link.
        if request.query_params.get("v"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        elif path.startswith("/static/fonts/"):
            response.headers["Cache-Control"] = "public, max-age=2592000"
        else:
            response.headers.setdefault("Cache-Control", "no-cache")
    return response


async def _server(sid: str) -> S.Server:
    srv = await S.registry.get(sid)
    if not srv or (_private(srv) and not _admin_viewing()):
        raise HTTPException(404, "Server not found")
    return srv


def _require_java(srv: S.Server) -> None:
    if not srv.is_java:
        raise HTTPException(409, f"This is a {srv.game} server; world details are only available for Minecraft Java")


def _assets(srv: S.Server):
    version = srv.mc_version
    if not version or not srv.is_java:
        return None
    jars = tuple(str(p) for p in S.mod_jars(srv))
    # Icons rendered from mods are cached per set of mod files, so updating a mod
    # re-renders its icons instead of showing the old ones.
    sig = hashlib.sha1("|".join(f"{Path(j).name}:{_size(j)}" for j in jars).encode()).hexdigest()[:10]
    return assets_for(version, jars, f"{srv.id}-{sig}" if jars else srv.id)


def _size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


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
    }


# ------------------------------------------------------------------ public status page (no login needed)
# Off until an admin turns it on. Everything here is read-only and cached so anonymous
# visitors can't hammer RCON or Crafty, and chat is never included.
STATUS_DEFAULTS = {"enabled": False, "show_positions": False, "show_items": True,
                   "show_activity": True, "show_web_map": False}
STATUS_TTL = 4.0
_board_cache: dict[str, tuple[float, dict]] = {}
_board_locks: dict[str, asyncio.Lock] = {}
_list_cache: tuple[float, list] | None = None
_SAFE_ID = re.compile(r"^[a-z0-9_.\-]{1,64}$")


def _status_cfg() -> dict:
    saved = settings_store.load().get("status", {})
    return {k: bool(saved.get(k, v)) for k, v in STATUS_DEFAULTS.items()}


def _require_status() -> dict:
    cfg = _status_cfg()
    if not cfg["enabled"]:
        raise HTTPException(404, "The public status page is turned off")
    return cfg


def _phase(t: int) -> str:
    return ("Morning" if t < 6000 else "Afternoon" if t < 12000 else "Sunset" if t < 13000
            else "Night" if t < 23000 else "Sunrise")


def _public_servers_list() -> list[S.Server]:
    return [s for s in S.registry.servers.values() if not s.settings.get("hidden") and not _private(s)]


async def _public_server(sid: str) -> S.Server:
    srv = await S.registry.get(sid)
    if not srv or srv.settings.get("hidden") or _private(srv):
        raise HTTPException(404, "Server not found")
    return srv


def _lang_name(lang: dict, kind: str, ident: str) -> str:
    ns, _, name = ident.partition(":") if ":" in ident else ("minecraft", "", ident)
    for k in (kind, "block") if kind == "item" else (kind,):
        v = lang.get(f"{k}.{ns}.{name}")
        if v:
            return v
    return name.replace("_", " ").title()


def _public_item(it: dict | None, lang: dict) -> dict | None:
    if not it:
        return None
    return {"id": it["id"], "name": it.get("name") or _lang_name(lang, "item", it["id"]), "count": it.get("count", 1),
            "glint": bool(it.get("enchantments") or it.get("glint"))}


async def _maybe_live(srv: S.Server, p: dict) -> dict | None:
    return await S.live_player(srv, p["name"]) if p.get("uuid") and srv.rcon_conf() else None


async def _build_board(srv: S.Server, cfg: dict) -> dict:
    summ = await S.server_summary(srv)
    board: dict = {
        "id": srv.id, "name": summ["name"], "motd": summ["motd"], "running": summ["running"], "crashed": summ["crashed"],
        "online_count": len(summ["online"]), "max": summ["max_players"], "version": summ["version"],
        "loader": summ["loader"], "game": summ["game_label"], "java": srv.is_java, "has_icon": summ["has_icon"],
        "started": summ["started"] if summ["running"] else None,
        "tps": summ["perf"]["tps"] if summ.get("perf") and summ["running"] is not False else None,
        "world": None, "spawn": None, "players": [], "recent": [], "recently": [], "web_map": None,
    }
    if cfg["show_web_map"] and summ.get("map_url"):
        board["web_map"] = summ["map_url"]
    lang: dict = {}
    if srv.is_java:
        a = _assets(srv)
        if a and a.ready:
            lang = await asyncio.to_thread(a.lang_cached)
        try:
            w = await asyncio.to_thread(S.world_info, srv, False)
            if summ["running"] is not False and srv.rcon_conf():
                w.update(await S.live_world(srv))
            if w.get("time_of_day") is not None:
                board["world"] = {"day": w["day"], "time_of_day": w["time_of_day"], "phase": _phase(w["time_of_day"]),
                                  "raining": w.get("raining"), "thundering": w.get("thundering"), "as_of": w.get("as_of")}
            if cfg["show_positions"] and w.get("spawn"):
                board["spawn"] = {k: w["spawn"][k] for k in ("x", "y", "z")}
            if cfg["show_positions"]:
                board["race"] = races.live_for_map(srv.id)
        except Exception as e:
            log.debug("status page world info failed for %s: %s", srv.id, e)
    board["live"] = challenges.live(srv.id) + races.live(srv.id) + games.live(srv.id)
    if summ["running"] is not False and summ["online"]:
        overview = await S.players_overview(srv)
        sessions = {s["player"].lower(): s["start"] for s in db.sessions(srv.id, limit=50) if s["open"]}
        online = [p for p in overview["players"] if p["online"]]
        details = await asyncio.gather(*(_maybe_live(srv, p) for p in online))
        hidden = games.hidden_from_map(srv.id)
        for p, live in zip(online, details, strict=True):
            d = live
            if d is None and p.get("uuid"):
                d, _m = S.player_file_data(srv, p["uuid"])
            row: dict = {"name": p["name"], "uuid": p.get("uuid"), "live": live is not None,
                         "today_seconds": p.get("today_seconds", 0), "since": sessions.get(p["name"].lower())}
            if d:
                row.update(health=d["health"], max_health=d["max_health"], absorption=d.get("absorption", 0),
                           food=d["food"], xp_level=d["xp_level"], xp_progress=d["xp_progress"],
                           gamemode=d["gamemode"], dimension=d["position"]["dimension"],
                           effects=[{"id": e["id"], "name": _lang_name(lang, "effect", e["id"]), "amplifier": e["amplifier"]}
                                    for e in d.get("effects", []) if not e.get("ambient")][:6])
                if cfg["show_positions"] and p["name"] not in hidden:      # hiders stay hidden during hide and seek
                    row["position"] = {k: d["position"][k] for k in ("x", "y", "z")}
                if cfg["show_items"]:
                    inv = d["inventory"]
                    sel = d.get("selected_slot", 0)
                    row["held"] = _public_item(inv["hotbar"][sel] if 0 <= sel < 9 else None, lang)
                    row["armor"] = [_public_item(inv["armor"][k], lang) for k in ("head", "chest", "legs", "feet")]
            board["players"].append(row)
    if cfg["show_activity"]:
        evs = db.events(srv.id, ["join", "leave", "death", "advancement", "level", "server", "challenge", "race", "bigfish", "game"], None, 14)
        board["recent"] = [{"ts": e["ts"], "type": e["type"], "player": e["player"], "message": e["message"]} for e in evs]
    online_l = {n.lower() for n in summ["online"]}
    if srv.is_java:
        week = time.time() - 7 * 86400
        recent = []
        for uuid, p in S.known_players(srv).items():
            if p["name"].lower() in online_l:
                continue
            seen = S.last_seen(srv, uuid)
            if seen and seen > week:
                recent.append({"name": p["name"], "uuid": uuid, "last_seen": seen})
        board["recently"] = sorted(recent, key=lambda r: -r["last_seen"])[:8]
        if cfg["show_positions"]:
            # where they were when they left, so the map has something to show with nobody on
            for r in board["recently"]:
                d, _m = S.player_file_data(srv, r["uuid"])
                if d and d.get("position"):
                    r["position"] = {k: d["position"][k] for k in ("x", "y", "z")}
                    r["dimension"] = d["position"].get("dimension") or "minecraft:overworld"
    return board


async def _board(srv: S.Server, cfg: dict) -> dict:
    hit = _board_cache.get(srv.id)
    if hit and time.monotonic() - hit[0] < STATUS_TTL:
        return hit[1]
    lock = _board_locks.setdefault(srv.id, asyncio.Lock())
    async with lock:
        hit = _board_cache.get(srv.id)
        if hit and time.monotonic() - hit[0] < STATUS_TTL:
            return hit[1]
        board = await _build_board(srv, cfg)
        _board_cache[srv.id] = (time.monotonic(), board)
        return board


@app.get("/api/public/status")
async def public_status():
    """Whether the status page is on, and the list of servers it can show."""
    global _list_cache
    cfg = _status_cfg()
    if not cfg["enabled"]:
        return {"enabled": False, "servers": [], "build": _asset_stamp()}
    if _list_cache and time.monotonic() - _list_cache[0] < 15:
        return {"enabled": True, "servers": _list_cache[1], "tv": _tv_cfg(), "build": _asset_stamp()}
    await S.registry.refresh()
    out = []
    for srv in _public_servers_list():
        try:
            summ = await S.server_summary(srv)
        except Exception as e:
            log.warning("status list failed for %s: %s", srv.id, e)
            continue
        out.append({"id": srv.id, "name": summ["name"], "running": summ["running"], "crashed": summ["crashed"],
                    "online": len(summ["online"]), "max": summ["max_players"], "has_icon": summ["has_icon"]})
    _list_cache = (time.monotonic(), out)
    return {"enabled": True, "servers": out, "tv": _tv_cfg(), "build": _asset_stamp()}


@app.get("/api/public/status/{sid}")
async def public_board(sid: str):
    cfg = _require_status()
    board = await _board(await _public_server(sid), cfg)
    if board.get("world") and board["world"].get("as_of"):
        board = {**board, "world": {**board["world"], "age": round(max(0.0, time.time() - board["world"]["as_of"]), 1)}}
    return JSONResponse(board, headers={"Cache-Control": "no-store"})


# ---- the public website: site details (how to join) and posts (news, guides, FAQ)
_site_cache: tuple[float, list] | None = None


@app.get("/api/public/site")
async def public_site():
    global _site_cache
    cfg = site.config()
    servers = []
    if cfg["home_live"] and _site_cache and time.monotonic() - _site_cache[0] < 15:
        servers = _site_cache[1]          # every visitor's page asks; the servers are only checked every 15 s
    elif cfg["home_live"]:
        await S.registry.refresh()
        for srv in _public_servers_list():
            try:
                summ = await S.server_summary(srv)
            except Exception as e:
                log.warning("home list failed for %s: %s", srv.id, e)
                continue
            servers.append({"id": srv.id, "name": summ["name"], "running": summ["running"], "online": len(summ["online"]),
                            "max": summ["max_players"], "version": summ.get("version"), "has_icon": summ["has_icon"]})
        _site_cache = (time.monotonic(), servers)
    return JSONResponse({**cfg, "logo": site.logo_url(), "servers": servers, "status_page": _status_cfg()["enabled"], "build": _asset_stamp()},
                        headers={"Cache-Control": "no-cache"})


@app.get("/api/public/logo")
async def public_logo():
    lg = site.logo()
    if not lg:
        raise HTTPException(404)
    return FileResponse(lg["file"], media_type=lg["mime"], headers={"Cache-Control": "public, max-age=31536000, immutable",
                                                                   "X-Content-Type-Options": "nosniff"})


@app.post("/api/settings/site/logo")
async def put_logo(request: Request):
    """The site's logo: the picture is the request body (PNG, JPEG, WebP or GIF, under 1 MB)."""
    user = auth.require_admin(request)
    if int(request.headers.get("content-length") or 0) > site.LOGO_MAX:
        raise HTTPException(413, "Use a picture under 1 MB")
    data = await request.body()
    try:
        url = await asyncio.to_thread(site.save_logo, data)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    auth.audit(user, None, "site_logo", f"{len(data)} bytes")
    return {"logo": url}


@app.delete("/api/settings/site/logo")
async def delete_logo(request: Request):
    user = auth.require_admin(request)
    url = await asyncio.to_thread(site.remove_logo)
    auth.audit(user, None, "site_logo", "back to Solstone's")
    return {"logo": url}


@app.put("/api/settings/site")
async def put_site(request: Request):
    user = auth.require_admin(request)
    cfg = site.save_config(await _body(request))
    auth.audit(user, None, "site_settings", cfg["name"])
    return cfg


# ---- players making their own account (a code sent to them in the game)
def _signup_on() -> None:
    if not site.config()["signup"]:
        raise HTTPException(404, "Sign-up is turned off")


@app.post("/api/public/signup/start")
async def signup_start(request: Request):
    _signup_on()
    body = await _body(request)
    await S.registry.refresh()
    return {"message": await signup.start(request, str(body.get("player") or ""), _public_servers_list())}


@app.post("/api/public/signup/finish")
async def signup_finish(request: Request):
    _signup_on()
    body = await _body(request)
    password = str(body.get("password") or "")
    u = await asyncio.to_thread(signup.finish, str(body.get("player") or ""), str(body.get("code") or ""),
                                str(body.get("username") or ""), password)
    auth.audit(u, None, "signup", f"{u.username} as {u.player_name}")
    user, token = await asyncio.to_thread(auth.login, request, u.username, password)
    resp = JSONResponse({"user": _me(user)})
    auth.set_cookie(resp, request, token)
    return resp


@app.get("/api/public/posts")
async def public_posts(category: str = "", limit: int = 20):
    if category and category not in site.CATEGORIES:
        raise HTTPException(400, "Unknown category")
    return JSONResponse(site.posts(category or None, limit=limit), headers={"Cache-Control": "no-cache"})


@app.get("/api/public/posts/{slug}")
async def public_post(slug: str):
    p = site.post(slug)
    if not p:
        raise HTTPException(404, "No such post")
    return JSONResponse(p, headers={"Cache-Control": "no-cache"})


@app.get("/api/posts")
async def all_posts(request: Request):
    """Admin: every post, drafts included, with their text, for the Website page."""
    auth.require_admin(request)
    return {"posts": site.posts(drafts=True, limit=200), "site": site.config(), "logo": site.logo_url(), "categories": site.CATEGORIES}


@app.post("/api/posts")
async def new_post(request: Request):
    user = auth.require_admin(request)
    try:
        p = site.save(await _body(request), user.shown)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    auth.audit(user, None, "post_new", p["title"])
    return p


@app.put("/api/posts/{pid}")
async def edit_post(pid: int, request: Request):
    user = auth.require_admin(request)
    try:
        p = site.save(await _body(request), user.shown, pid)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except LookupError as e:
        raise HTTPException(404, str(e)) from e
    auth.audit(user, None, "post_edit", p["title"])
    return p


@app.delete("/api/posts/{pid}")
async def remove_post(pid: int, request: Request):
    user = auth.require_admin(request)
    if not site.delete(pid):
        raise HTTPException(404, "No such post")
    auth.audit(user, None, "post_delete", str(pid))
    return {"ok": True}


# ---- TV mode: the status page cycling through slides on a wall screen
TV_SLIDES = ("now", "map", "leaders", "recap", "feed", "news")
TV_DEFAULTS = {"seconds": 15, "slides": {k: True for k in TV_SLIDES}, "rotate": False}


def _tv_cfg(v: dict | None = None) -> dict:
    saved = v if v is not None else settings_store.load().get("tv") or {}
    slides = saved.get("slides") if isinstance(saved.get("slides"), dict) else {}
    try:
        secs = max(6, min(120, int(saved.get("seconds", 15))))
    except (TypeError, ValueError):
        secs = 15
    return {"seconds": secs, "slides": {k: bool(slides.get(k, True)) for k in TV_SLIDES}, "rotate": bool(saved.get("rotate", False))}


@app.get("/api/settings/tv")
async def get_tv_settings(request: Request):
    auth.require_admin(request)
    return _tv_cfg()


@app.put("/api/settings/tv")
async def put_tv_settings(request: Request):
    global _list_cache
    user = auth.require_admin(request)
    cfg = _tv_cfg({**_tv_cfg(), **await _body(request)})
    if not any(cfg["slides"].values()):
        raise HTTPException(400, "Leave at least one slide on")
    settings_store.save_section("tv", cfg)
    _list_cache = None
    auth.audit(user, None, "tv_settings", f"{cfg['seconds']} s, {sum(cfg['slides'].values())} slides")
    return cfg


_lb_cache: dict[str, tuple[float, dict]] = {}


@app.get("/api/public/leaderboard/{sid}")
async def public_leaderboard(sid: str):
    _require_status()
    srv = await _public_server(sid)
    if not srv.is_java:
        return {"players": []}
    hit = _lb_cache.get(srv.id)
    if hit and time.monotonic() - hit[0] < 120:
        return hit[1]
    data = await S.leaderboard(srv)
    _lb_cache[srv.id] = (time.monotonic(), data)
    return data


# ---- daily recaps and "on this day"
def _recap_payload(sid: str, day_s: str | None) -> dict:
    today = datetime.now(db.tz()).date()
    try:
        day = min(today, date.fromisoformat(day_s)) if day_s else today
    except ValueError:
        raise HTTPException(400, "Use a date like 2026-10-20") from None
    out = {"day": day.isoformat(), "today": today.isoformat(), "recap": recap.day_recap(sid, day),
           "on_this_day": recap.on_this_day(sid, day), **recap.neighbours(sid, day)}
    if day == today:
        out["yesterday"] = recap.day_recap(sid, today - timedelta(days=1))
    return out


@app.get("/api/servers/{sid}/recap")
async def get_recap(sid: str, day: str | None = None):
    srv = await _server(sid)
    return await asyncio.to_thread(_recap_payload, srv.id, day)


_recap_cache: dict[str, tuple[float, dict]] = {}


@app.get("/api/public/recap/{sid}")
async def public_recap(sid: str):
    cfg = _require_status()
    if not cfg["show_activity"]:
        raise HTTPException(404, "Activity is hidden on the status page")
    srv = await _public_server(sid)
    hit = _recap_cache.get(srv.id)
    if hit and time.monotonic() - hit[0] < 60:
        return hit[1]
    data = await asyncio.to_thread(_recap_payload, srv.id, None)
    _recap_cache[srv.id] = (time.monotonic(), data)
    return data


@app.post("/api/recap/backfill")
async def recap_backfill(request: Request):
    """Read every server's old logs again for days before Solstone (normally done once, automatically)."""
    user = auth.require_admin(request)
    await S.registry.refresh()
    total = 0
    for srv in S.registry.servers.values():
        if not srv.is_java:
            continue
        await asyncio.to_thread(recap.finalize, srv.id)
        known = {p["name"].lower(): u for u, p in S.known_players(srv).items()}
        total += await asyncio.to_thread(recap.backfill, srv.id, srv.dir, known)
    auth.audit(user, None, "recap_backfill", f"{total} days")
    return {"days": total}


# ---- announcements, birthdays and countdowns
def _board_servers() -> list[S.Server]:
    return [x for x in S.registry.servers.values() if not x.settings.get("hidden")]


@app.get("/api/public/board")
async def public_board_items(request: Request, where: str = "status", sid: str = ""):
    if where not in board.WHERE:
        raise HTTPException(400, "Unknown place")
    signed_in = request.state.user is not None
    status_on = _status_cfg()["enabled"]
    if where == "app" and not signed_in:
        raise HTTPException(401, "Sign in to continue")
    if where == "status" and not status_on:
        raise HTTPException(404, "The public status page is turned off")
    await S.registry.refresh()
    servers = [x for x in _board_servers() if _visible(x)]     # a private server's announcements stay private
    if sid and not any(x.id == sid for x in servers):
        sid = ""
    items = await asyncio.to_thread(board.active, where, sid or None, signed_in or status_on, None, servers)
    return JSONResponse({"now": time.time(), "items": items}, headers={"Cache-Control": "no-store"})


@app.get("/api/board")
async def get_board(request: Request):
    auth.require_admin(request)
    await S.registry.refresh()
    players: dict[str, str] = {}
    uuids: dict[str, str] = {}                     # for faces from the world's own skin copy
    for srv in S.registry.servers.values():
        for u, p in S.known_players(srv).items():
            players.setdefault(p["name"].lower(), p["name"])
            uuids.setdefault(p["name"].lower(), u)
    return {**board.config(), "players": sorted(players.values(), key=str.lower), "uuids": uuids,
            "servers": [{"id": x.id, "name": x.display_name, "bedtime": guard.bedtime_config(x)["enabled"]} for x in _board_servers()],
            "shows": [{"id": x["id"], "name": x["name"]} for x in fwshow.shows()], "now": time.time(),
            "status_enabled": _status_cfg()["enabled"]}


@app.put("/api/board")
async def put_board(request: Request):
    user = auth.require_admin(request)
    body = await _body(request)
    cfg = board.save(body)
    auth.audit(user, None, "announcements", f"{len(cfg['items'])} announcements, {len(cfg['birthdays'])} birthdays")
    return await get_board(request)


# ---- the world map, drawn from region files (status page, TV mode)
async def _map_server(request: Request, sid: str) -> S.Server:
    if request.state.user is not None:
        srv = await _server(sid)
    else:
        if not _require_status()["show_positions"]:
            raise HTTPException(404, "The map is hidden on the status page")
        srv = await _public_server(sid)
    if not srv.is_java:
        raise HTTPException(404)
    return srv


@app.get("/api/public/map/{sid}/regions")
async def map_regions(sid: str, request: Request, dim: str = "minecraft:overworld"):
    srv = await _map_server(request, sid)
    return {"dim": dim, "size": worldmap.TILE, "regions": await asyncio.to_thread(worldmap.regions, srv.world_dir, dim)}


@app.get("/api/public/map/{sid}/tile")
async def map_tile(sid: str, request: Request, x: int, z: int, dim: str = "minecraft:overworld"):
    srv = await _map_server(request, sid)
    state, path = await asyncio.to_thread(worldmap.tile, srv.id, srv.world_dir, dim, x, z, _assets(srv))
    if state == "none":
        raise HTTPException(404)
    if state == "working":
        return Response(status_code=202, headers={"Retry-After": "3", "Cache-Control": "no-store"})
    info = worldmap.tile_info(path)
    head = {"Cache-Control": "max-age=60", "X-Map-Chunks": f"{info.get('drawn', '?')}/{info.get('chunks', '?')}"}
    if info.get("error"):
        head["X-Map-Error"] = info["error"][:200].encode("ascii", "replace").decode()
    return FileResponse(path, media_type="image/png", headers=head)


@app.get("/api/servers/{sid}/map/check")
async def map_check(sid: str, request: Request, dim: str = "minecraft:overworld"):
    """Admin: what the map sees and why a picture might come out empty."""
    auth.require_admin(request)
    srv = await _server(sid)
    _require_java(srv)
    def near() -> list[tuple[float, float]]:                 # where players last saved, in this dimension
        out = []
        for uuid in S.known_players(srv):
            data, _m = S.player_file_data(srv, uuid)
            pos = (data or {}).get("position") or {}
            if pos and (pos.get("dimension") or "minecraft:overworld") == dim:
                out.append((pos.get("x", 0), pos.get("z", 0)))
        return out
    return await asyncio.to_thread(lambda: worldmap.check(srv.id, srv.world_dir, dim, near(), _assets(srv)))


@app.get("/api/servers/{sid}/check")
async def get_selfcheck(sid: str, request: Request):
    """Admin: the last compatibility check for this server."""
    auth.require_admin(request)
    srv = await _server(sid)
    return {"last": (settings_store.load().get("selfcheck") or {}).get(srv.id), "rcon": bool(srv.rcon_conf()), "version": srv.mc_version}


@app.post("/api/servers/{sid}/check")
async def run_selfcheck(sid: str, request: Request):
    """Admin: try every kind of command and file Solstone relies on, on this server."""
    user = auth.require_admin(request)
    srv = await _server(sid)
    _require_java(srv)
    if not srv.rcon_conf():
        raise HTTPException(409, "RCON is off for this server, so Solstone can't talk to it")

    def near() -> list[tuple[float, float]]:
        out = []
        for uuid in S.known_players(srv):
            data, _m = S.player_file_data(srv, uuid)
            pos = (data or {}).get("position") or {}
            if pos and (pos.get("dimension") or "minecraft:overworld") == "minecraft:overworld":
                out.append((pos.get("x", 0), pos.get("z", 0)))
        return out
    result = await selfcheck.run(srv, await asyncio.to_thread(near), _assets(srv))
    saved = settings_store.load().get("selfcheck") or {}
    saved[srv.id] = result
    settings_store.save_section("selfcheck", saved)
    auth.audit(user, srv.id, "selfcheck", f"{sum(1 for r in result['rows'] if r['ok'] is False)} problems")
    return result


@app.get("/api/public/icon/{sid}.png")
async def public_icon(sid: str):
    _require_status()
    data = S.server_icon_bytes(await _public_server(sid))
    if not data:
        raise HTTPException(404)
    return Response(data, media_type="image/png", headers={"Cache-Control": "max-age=300"})


@app.get("/api/public/item/{sid}/{ns}/{name}.png")
async def public_item_icon(sid: str, ns: str, name: str):
    cfg = _require_status()
    if not cfg["show_items"] or not _SAFE_ID.match(ns) or not _SAFE_ID.match(name):
        raise HTTPException(404)
    a = _assets(await _public_server(sid))
    data = await asyncio.to_thread(a.icon, f"{ns}:{name}") if a and a.ready else None
    if not data:
        raise HTTPException(404)
    return Response(data, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/api/public/skin/{sid}/{uuid}.png")
async def public_skin(sid: str, uuid: str, request: Request):
    """Skins for the status page: only players who have joined a visible server."""
    _require_status()
    srv = await _public_server(sid)
    if S.norm_uuid(uuid) not in S.known_players(srv):
        raise HTTPException(404)
    return await _skin_response(request, uuid, "public")


@app.get("/api/public/skin/{sid}/{uuid}/body.png")
async def public_body(sid: str, uuid: str, request: Request, size: int = 256):
    _require_status()
    srv = await _public_server(sid)
    if S.norm_uuid(uuid) not in S.known_players(srv):
        raise HTTPException(404)
    return await _skin_response(request, uuid, "public", size)


async def _skin_response(request: Request, uuid: str, scope: str, body_size: int | None = None) -> Response:
    """The skin (or a front view of the player in it). Browsers ask again each time and get a
    "not changed" answer until the skin really changes, so a new skin shows up right away."""
    data = await skins.skin(uuid)
    if not data:
        raise HTTPException(404)
    tag = '"' + hashlib.sha1(data).hexdigest()[:16] + (f"-b{body_size}" if body_size else "") + '"'
    headers = {"Cache-Control": f"{scope}, no-cache", "ETag": tag}
    if request.headers.get("if-none-match") == tag:
        return Response(status_code=304, headers=headers)
    if body_size:
        data = await asyncio.to_thread(skins.body, data, uuid, max(32, min(512, body_size)))
    return Response(data, media_type="image/png", headers=headers)


# Fireworks: which kinds go off, their colours and pace. Public so the sign-in and
# status pages can use them; only admins can change them.
FIREWORK_KINDS = ["ball", "large", "star", "burst", "ring", "crossette", "spiral", "willow", "saturn", "pair",
                  "cube", "pickaxe", "axe", "creeper", "heart", "candle", "cake", "fountain", "wheel", "sparkler",
                  "shootingstar", "dragon", "bow", "tree"]
FIREWORK_COLORS = ["#ff5a4f", "#ffa13d", "#ffe45c", "#9be34a", "#4fd7e6", "#5d8bff", "#c46cf0", "#ff8fc0", "#ffffff", "#3fd1b0"]
FIREWORK_PACE = ("calm", "normal", "lively")
FIREWORK_SPECIALS = ("rare", "sometimes", "often")


# How often each kind comes up relative to the others: 0 off, 0.5 rare, 1 normal, 2 often, 4 lots.
FIREWORK_WEIGHTS = (0, 0.5, 1, 2, 4)
FIREWORK_DEFAULT_WEIGHTS = {k: 2 if k in ("ball", "crossette", "spiral", "willow") else 1 for k in FIREWORK_KINDS}


def _weight(v, default: float = 1) -> float:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return default
    return min(FIREWORK_WEIGHTS, key=lambda w: abs(w - v))


def _fireworks_cfg() -> dict:
    saved = settings_store.load().get("fireworks", {})
    kinds = saved.get("kinds") if isinstance(saved.get("kinds"), dict) else {}
    weights = saved.get("weights") if isinstance(saved.get("weights"), dict) else {}
    colors = [c for c in saved.get("colors", []) if c in FIREWORK_COLORS] if isinstance(saved.get("colors"), list) else []
    w = {k: _weight(weights[k]) if k in weights else (0 if kinds.get(k) is False else FIREWORK_DEFAULT_WEIGHTS[k]) for k in FIREWORK_KINDS}
    return {
        "weights": w,
        "kinds": {k: v > 0 for k, v in w.items()},   # older pages read this
        "colors": colors or list(FIREWORK_COLORS),
        "pace": saved.get("pace") if saved.get("pace") in FIREWORK_PACE else "normal",
        "showpieces": saved.get("showpieces") if saved.get("showpieces") in FIREWORK_SPECIALS else "sometimes",
        "sky": _sky_cfg(saved.get("sky")),
    }


SKY_MODES = ("game", "night")
SKY_DAYTIME = ("smoke", "normal", "pause")


def _sky_cfg(v) -> dict:
    v = v if isinstance(v, dict) else {}
    return {"mode": v.get("mode") if v.get("mode") in SKY_MODES else "game",
            "server": str(v.get("server") or "auto")[:64],
            "daytime": v.get("daytime") if v.get("daytime") in SKY_DAYTIME else "smoke"}


def _creator_weights() -> dict[str, float]:
    saved = settings_store.load().get("fw_creators") or {}
    return {str(k): _weight(v) for k, v in saved.items()}


def _show_designs() -> list[dict]:
    """Editor fireworks in the show, each with how often it comes up (its own frequency
    times its maker's). Anything at 0 is left out."""
    creators = _creator_weights()
    out = []
    for d in fireworks.in_show():
        w = _weight(d.get("weight", 1)) * creators.get(d.get("author", ""), 1)
        if w > 0:
            out.append({**d, "weight": w})
    return out


@app.get("/api/public/fireworks")
async def public_fireworks(request: Request):
    return JSONResponse({**_fireworks_cfg(), "custom": _show_designs(), **fwshow.today_state(), "base_shows": fwshow.base_shows_resolved()},
                        headers={"Cache-Control": "no-cache"})


@app.get("/api/public/fireworks/feed")
async def firework_feed(request: Request, since: int = -1):
    """Fireworks set off by things happening in the game. Player names only for people
    signed in, or when the public status page (which shows them anyway) is on."""
    names = request.state.user is not None or _status_cfg()["enabled"]
    feed = fwshow.feed_since(since, names)
    if not _admin_viewing():      # nothing from a private server, not even that something happened there
        hidden = {x.id for x in S.registry.servers.values() if _private(x)}
        feed = {**feed, "items": [i for i in feed.get("items", []) if i.get("server_id") not in hidden]}
    return JSONResponse(feed, headers={"Cache-Control": "no-store"})


@app.get("/api/fireworks/show")
async def get_firework_show(request: Request):
    auth.require_admin(request)
    await S.registry.refresh()
    players: dict[str, str] = {}
    for srv in S.registry.servers.values():
        for p in S.known_players(srv).values():
            players.setdefault(p["name"].lower(), p["name"])
    return {"events": fwshow.events_cfg(), "signatures": fwshow.signatures(), "calendar": fwshow.calendar(),
            "players": sorted(players.values(), key=str.lower), "today": fwshow.today_state(),
            "calendar_defaults": [fwshow._clean_entry(e) for e in fwshow.DEFAULT_CALENDAR],
            "creators": _creators_summary(),
            "shows": fwshow.shows(), "base_shows": fwshow.base_shows(), "overlaps": await asyncio.to_thread(fwshow.overlaps),
            "servers": [{"id": x.id, "name": x.display_name} for x in S.registry.servers.values() if x.is_java and not x.settings.get("hidden")]}


@app.put("/api/fireworks/show")
async def put_firework_show(request: Request):
    user = auth.require_admin(request)
    body = await _body(request)
    if isinstance(body.get("events"), dict):
        fwshow.save_events(body["events"])
    if isinstance(body.get("signatures"), dict):
        fwshow.save_signatures(body["signatures"])
    if isinstance(body.get("calendar"), list):
        fwshow.save_calendar(body["calendar"])
    if isinstance(body.get("shows"), list):
        fwshow.save_shows(body["shows"])
    if isinstance(body.get("base_shows"), dict):
        fwshow.save_base_shows(body["base_shows"])
    if isinstance(body.get("creators"), dict):
        cw = _creator_weights()
        cw.update({str(k)[:32]: _weight(v) for k, v in body["creators"].items()})
        settings_store.save_section("fw_creators", cw)
    auth.audit(user, None, "fireworks_show", ", ".join(sorted(k for k in body if k in ("events", "signatures", "calendar", "creators", "shows", "base_shows"))))
    return await get_firework_show(request)


def _creators_summary() -> list[dict]:
    cw = _creator_weights()
    by: dict[str, int] = {}
    for d in fireworks.all_designs():
        by[d.get("author", "")] = by.get(d.get("author", ""), 0) + 1
    return [{"name": n, "designs": c, "weight": cw.get(n, 1)} for n, c in sorted(by.items(), key=lambda x: x[0].lower())]


@app.post("/api/fireworks/test-event")
async def test_firework_event(request: Request):
    """Pretend an event happened, to see what it sets off."""
    auth.require_admin(request)
    body = await _body(request)
    ev = body.get("event")
    if ev not in fwshow.EVENT_DEFAULTS:
        raise HTTPException(400, "Unknown event")
    player = str(body.get("player") or "") or None
    if body.get("preview"):               # just say what it would launch; the page plays it in a preview
        return {"ok": True, "show": fwshow._resolve(ev, player)}
    fwshow.push("test", "Test", ev, player, f"Test: {ev}" + (f" for {player}" if player else ""))
    return {"ok": True}


# ---- the sky follows a server's in-game time and weather
_sky_cache: dict[str, tuple[float, dict]] = {}


async def _sky_server(sid: str | None) -> S.Server | None:
    await S.registry.refresh()
    visible = [x for x in S.registry.servers.values() if x.is_java and not x.settings.get("hidden") and not _private(x)]
    want = sid if sid and sid != "auto" else _fireworks_cfg()["sky"]["server"]
    srv = next((x for x in visible if x.id == want), None)
    if srv:
        return srv
    # Auto: a running server with people on it, else any running one, else the first.
    running = [x for x in visible if (x.crafty or {}).get("_stats", {}).get("running")]
    return next((x for x in running if (x.crafty or {}).get("_stats", {}).get("online")), None) or (running or visible or [None])[0]


@app.get("/api/public/sky")
async def public_sky(sid: str = ""):
    """In-game time and weather for the sky behind every page (nothing private)."""
    cfg = _fireworks_cfg()["sky"]
    if cfg["mode"] != "game":
        return {"mode": "night"}
    srv = await _sky_server(sid)
    if not srv:
        return {"mode": "night"}
    hit = _sky_cache.get(srv.id)
    if hit and time.monotonic() - hit[0] < 10:
        return _with_age(hit[1])
    out: dict = {"mode": "game", "server": srv.id}
    try:
        w = await asyncio.to_thread(S.world_info, srv, False)
        online = []
        if srv.rcon_conf():
            w.update(await S.live_world(srv))
            online, _src = await S.online_players(srv)
        if w.get("time_of_day") is not None:
            day = w.get("day") or 1
            out.update(time_of_day=w["time_of_day"], day=day, moon=(day - 1) % 8, raining=bool(w.get("raining")),
                       thundering=bool(w.get("thundering")), ticking=bool(online), as_of=w.get("as_of") or time.time())
        else:
            out = {"mode": "night"}
    except Exception as e:
        log.debug("sky info failed for %s: %s", srv.id, e)
        out = {"mode": "night"}
    _sky_cache[srv.id] = (time.monotonic(), out)
    return _with_age(out)


def _with_age(sky: dict) -> dict:
    """How old the time reading is, so the page can count on from it instead of jumping back."""
    return {**sky, "age": round(max(0.0, time.time() - sky["as_of"]), 1)} if sky.get("as_of") else sky


@app.get("/api/players/skins")
async def player_skin_list():
    """Everyone who has joined, with their UUID, for the painter's face stamp."""
    await S.registry.refresh()
    seen: dict[str, dict] = {}
    for srv in [x for x in S.registry.servers.values() if _visible(x)]:
        for u, p in S.known_players(srv).items():
            seen.setdefault(p["name"].lower(), {"name": p["name"], "uuid": u})
    return sorted(seen.values(), key=lambda x: x["name"].lower())


# ---- the Firework editor: anyone signed in can make fireworks; people can change their
# own, and admins can change or remove anyone's.
def _can_edit(user, d: dict) -> bool:
    return user.role == "admin" or d.get("author") == user.username


@app.get("/api/upcoming")
async def get_upcoming(request: Request):
    """Everything coming up, for the Coming up page (anyone signed in)."""
    await S.registry.refresh()
    names = {sid: srv.display_name for sid, srv in S.registry.servers.items() if _visible(srv)}
    return {"items": upcoming.items(names), "days": upcoming.DAYS, "now": time.time()}


@app.get("/api/fireworks")
async def list_fireworks(request: Request):
    user = request.state.user
    return [{**d, "mine": d.get("author") == user.username, "can_edit": _can_edit(user, d)} for d in fireworks.all_designs()]


@app.get("/api/sounds")
async def list_sounds(request: Request):
    user = request.state.user
    return [{**x, "can_delete": user.role == "admin" or x.get("author") == user.username} for x in fireworks.sounds()]


@app.post("/api/sounds")
async def save_sound(request: Request):
    user = request.state.user
    body = await _body(request)
    try:
        item = fireworks.add_sound(body.get("name"), body.get("sfx"), user.username)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    auth.audit(user, None, "sound_save", item["name"])
    return item


@app.delete("/api/sounds/{sound_id}")
async def remove_sound(sound_id: str, request: Request):
    user = request.state.user
    if not fireworks.delete_sound(sound_id, user.username, user.role == "admin"):
        raise HTTPException(404, "No such sound, or it isn't yours")
    auth.audit(user, None, "sound_delete", sound_id)
    return {"ok": True}


@app.get("/api/fireworks/limit")
async def firework_limit(request: Request):
    user = request.state.user
    return {"per_person": fireworks.per_person(), "mine": fireworks.count_by(user.username), "limited": user.role != "admin"}


@app.put("/api/fireworks/limit")
async def set_firework_limit(request: Request):
    user = request.state.user
    if user.role != "admin":
        raise HTTPException(403, "Only admins can change this")
    try:
        n = fireworks.set_per_person((await _body(request)).get("per_person"))
    except (TypeError, ValueError) as e:
        raise HTTPException(400, "Give a number") from e
    auth.audit(user, None, "firework_limit", str(n))
    return {"per_person": n}


@app.post("/api/fireworks")
async def create_firework(request: Request):
    user = request.state.user
    try:
        d = fireworks.create(await _body(request), user.username, None if user.role == "admin" else fireworks.per_person())
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    auth.audit(user, None, "firework_create", d["name"])
    return d


@app.put("/api/fireworks/{fid}")
async def update_firework(fid: str, request: Request):
    user = request.state.user
    d = fireworks.get(fid)
    if not d:
        raise HTTPException(404, "Firework not found")
    if not _can_edit(user, d):
        raise HTTPException(403, "Only its maker or an admin can change this firework")
    body = await _body(request)
    if user.role != "admin":
        body.pop("weight", None)                  # how often it shows is the admins' call
    elif "weight" in body:
        body["weight"] = _weight(body["weight"])
    return fireworks.update(fid, body)


@app.delete("/api/fireworks/{fid}")
async def delete_firework(fid: str, request: Request):
    user = request.state.user
    d = fireworks.get(fid)
    if not d:
        raise HTTPException(404, "Firework not found")
    if not _can_edit(user, d):
        raise HTTPException(403, "Only its maker or an admin can delete this firework")
    fireworks.delete(fid)
    auth.audit(user, None, "firework_delete", d["name"])
    return {"ok": True}


@app.put("/api/settings/fireworks")
async def put_fireworks(request: Request):
    user = auth.require_admin(request)
    body = await _body(request)
    cur = _fireworks_cfg()
    if isinstance(body.get("kinds"), dict):        # on/off from older pages
        cur["weights"].update({k: (FIREWORK_DEFAULT_WEIGHTS[k] if v else 0) for k, v in body["kinds"].items() if k in FIREWORK_KINDS})
    if isinstance(body.get("weights"), dict):
        cur["weights"].update({k: _weight(v) for k, v in body["weights"].items() if k in FIREWORK_KINDS})
    cur["kinds"] = {k: v > 0 for k, v in cur["weights"].items()}
    if isinstance(body.get("colors"), list):
        picked = [c for c in FIREWORK_COLORS if c in body["colors"]]
        if not picked:
            raise HTTPException(400, "Pick at least one colour")
        cur["colors"] = picked
    if body.get("pace") in FIREWORK_PACE:
        cur["pace"] = body["pace"]
    if body.get("showpieces") in FIREWORK_SPECIALS:
        cur["showpieces"] = body["showpieces"]
    if isinstance(body.get("sky"), dict):
        cur["sky"] = _sky_cfg({**cur["sky"], **body["sky"]})
    if not any(cur["kinds"].values()):
        raise HTTPException(400, "Leave at least one kind of firework on")
    settings_store.save_section("fireworks", cur)
    auth.audit(user, None, "fireworks_settings", f"{sum(cur['kinds'].values())} kinds on, {len(cur['colors'])} colours, {cur['pace']}")
    return cur


@app.get("/api/settings/status")
async def get_status_settings(request: Request):
    auth.require_admin(request)
    return _status_cfg()


@app.put("/api/settings/status")
async def put_status_settings(request: Request):
    global _list_cache
    user = auth.require_admin(request)
    body = await _body(request)
    cfg = {k: bool(body.get(k, v)) for k, v in _status_cfg().items()}
    settings_store.save_section("status", cfg)
    _list_cache = None
    _board_cache.clear()
    auth.audit(user, None, "status_page_settings", ", ".join(f"{k}={v}" for k, v in cfg.items()))
    return cfg


# ------------------------------------------------------------------ accounts
async def _body(request: Request) -> dict:
    try:
        body = await request.json()
    except Exception:
        body = None
    if not isinstance(body, dict):
        raise HTTPException(400, "Expected a JSON object")
    return body


@app.post("/api/auth/login")
async def login(request: Request):
    body = await _body(request)
    user, token = await asyncio.to_thread(auth.login, request, str(body.get("username", "")), str(body.get("password", "")))
    resp = JSONResponse({"user": _me(user)})
    auth.set_cookie(resp, request, token)
    return resp


@app.post("/api/auth/logout")
async def logout(request: Request):
    auth.logout(request.cookies.get(auth.COOKIE))
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(auth.COOKIE, path="/")
    return resp


@app.get("/api/auth/me")
async def me(request: Request):
    return {"user": _me(auth.require_user(request)), "version": VERSION}


def _me(u: auth.User) -> dict:
    """The signed-in user as the app needs them."""
    return u.public()


@app.post("/api/auth/profile")
async def change_profile(request: Request):
    """Your display name (shown in chat and the activity feed instead of your login)."""
    user = auth.require_user(request)
    body = await _body(request)
    u = await asyncio.to_thread(auth.set_display_name, user.id, str(body.get("display_name") or ""))
    auth.audit(user, None, "display_name", u.shown)
    return {"user": u.public()}


@app.post("/api/auth/password")
async def change_password(request: Request):
    user = auth.require_user(request)
    body = await _body(request)
    row = db.q("SELECT password_hash FROM users WHERE id=?", (user.id,))[0]
    if not auth.verify_password(str(body.get("current", "")), row["password_hash"]):
        raise HTTPException(400, "Your current password is wrong")
    auth.update_user(user.id, password=str(body.get("new", "")))
    auth.audit(user, None, "change_password", user.username)
    user2, token = await asyncio.to_thread(auth.login, request, user.username, str(body.get("new", "")))
    resp = JSONResponse({"ok": True})
    auth.set_cookie(resp, request, token)
    return resp


@app.get("/api/users")
async def users(request: Request):
    auth.require_admin(request)
    return auth.list_users()


@app.post("/api/users")
async def add_user(request: Request):
    admin = auth.require_admin(request)
    body = await _body(request)
    u = auth.create_user(str(body.get("username", "")).strip(), str(body.get("password", "")), str(body.get("role", "trusted")))
    auth.audit(admin, None, "add_user", f"{u.username} ({u.role})")
    return u.public()


@app.patch("/api/users/{uid}")
async def edit_user(uid: int, request: Request):
    admin = auth.require_admin(request)
    body = await _body(request)
    u = auth.update_user(uid, role=body.get("role") or None, password=body.get("password") or None)
    if "player" in body:                    # link the account to a Minecraft player ("" unlinks)
        name = str(body.get("player") or "").strip().lower()
        found = None
        if name:
            await S.registry.refresh()
            found = next(((uu, p["name"]) for srv in S.registry.servers.values() for uu, p in S.known_players(srv).items()
                          if p["name"].lower() in (name, "." + name.lstrip("."))), None)
            if not found:
                raise HTTPException(400, "No player by that name has joined any server")
        u = auth.link_player(uid, found)
    changes = ", ".join(k for k in ("role", "password", "player") if k in body and (body.get(k) or k == "player"))
    auth.audit(admin, None, "edit_user", f"{u.username}: {changes}")
    return u.public()


@app.delete("/api/users/{uid}")
async def remove_user(uid: int, request: Request):
    admin = auth.require_admin(request)
    if uid == admin.id:
        raise HTTPException(400, "You can't delete your own account")
    u = auth.get_user(uid)
    auth.delete_user(uid)
    auth.audit(admin, None, "delete_user", u.username if u else str(uid))
    return {"ok": True}


@app.get("/api/audit")
async def audit_all(request: Request, limit: int = 200):
    auth.require_admin(request)
    return auth.audit_log(None, max(1, min(limit, 1000)))


@app.get("/api/servers")
async def list_servers():
    await S.registry.refresh()
    visible = [s for s in S.registry.servers.values() if _visible(s)]
    results = await asyncio.gather(*(S.server_summary(s) for s in visible), return_exceptions=True)
    out = []
    for srv, r in zip(visible, results, strict=True):
        if isinstance(r, Exception):
            log.warning("summary failed for %s: %s", srv.id, r)
            out.append({"id": srv.id, "name": srv.display_name, "error": str(r)})
        else:
            out.append(_for_player(r))
    return out


@app.get("/api/players/uuids")
async def player_uuids():
    """Every known player name (lowercase) -> UUID, so heads can use the world's own skin copy
    wherever only a name is at hand."""
    out: dict[str, str] = {}
    for srv in [x for x in S.registry.servers.values() if _visible(x)]:
        for u, p in S.known_players(srv).items():
            out.setdefault(p["name"].lower(), u)
    return JSONResponse(out, headers={"Cache-Control": "private, max-age=300"})


@app.get("/api/servers-hidden")
async def hidden_servers(request: Request):
    """Admin: servers hidden from Solstone, so they can be brought back."""
    auth.require_admin(request)
    await S.registry.refresh()
    return [{"id": s.id, "name": s.display_name, "game": s.game} for s in S.registry.servers.values() if s.settings.get("hidden")]


@app.get("/api/servers/{sid}")
async def get_server(sid: str):
    return _for_player(await S.server_summary(await _server(sid)))


@app.get("/api/servers/{sid}/world")
async def get_world(sid: str):
    srv = await _server(sid)
    _require_java(srv)
    info = await asyncio.to_thread(S.world_info, srv)
    if srv.rcon_conf():
        info.update(await S.live_world(srv))
    if info.get("time_source") == "unknown":
        info["debug"] = await asyncio.to_thread(S.world_debug, srv)
    if info.get("as_of"):
        info["age"] = round(max(0.0, time.time() - info["as_of"]), 1)
    return info


@app.get("/api/servers/{sid}/mods")
async def get_mods(sid: str):
    srv = await _server(sid)
    return {"loader": S.detect_loader(srv), "mods": await asyncio.to_thread(S.mods, srv)}


# ---- the family modpack (packwiz): Prism updates every PC's mods from here
def _public_base(request: Request) -> str:
    """The address the person (or Prism) used to reach Solstone: PUBLIC_URL if set, else this request's,
    corrected by a reverse proxy's X-Forwarded-Proto/Host (so it's https://playsolstone.com behind
    Cloudflare or a proxy, not the container's own http address)."""
    if config.public_url:
        return config.public_url
    proto = (request.headers.get("x-forwarded-proto") or request.url.scheme).split(",")[0].strip()
    host = (request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc).split(",")[0].strip()
    return f"{proto}://{host}"


def _pack_view(srv, request: Request) -> dict:
    cfg = modpack.get(srv.id)
    base = _public_base(request)
    url = f"{base}/api/public/pack/{cfg['token']}/pack.toml" if cfg["token"] else ""
    return {"enabled": cfg["enabled"], "url": url, "command": modpack.prism_command(url) if url else "",
            "bootstrap": "/api/public/packwiz-installer-bootstrap.jar", "mc": srv.mc_version,       # same site as the page
            "loader": modpack.fabric_loader_version(srv), "server_mods": modpack.server_mods(srv),
            "extra": [{k: e.get(k) for k in ("slug", "title", "kind", "version", "filename", "icon")} for e in cfg["extra"]]}


@app.get("/api/servers/{sid}/modpack")
async def get_modpack(sid: str, request: Request):
    auth.require_admin(request)
    srv = await _server(sid)
    return await asyncio.to_thread(_pack_view, srv, request)


@app.put("/api/servers/{sid}/modpack")
async def put_modpack(sid: str, request: Request):
    user = auth.require_admin(request)
    srv = await _server(sid)
    body = await request.json()
    cfg = modpack.get(srv.id)
    if "enabled" in body:
        cfg["enabled"] = bool(body["enabled"])
    if isinstance(body.get("server_mods"), list):
        cfg["server_mods"] = [str(x) for x in body["server_mods"]][:200]
    if body.get("new_token"):
        cfg["token"] = ""                       # a new address (the old one stops working)
    modpack.save(srv.id, cfg)
    auth.audit(user, srv.id, "modpack", f"enabled={cfg['enabled']}")
    return await asyncio.to_thread(_pack_view, srv, request)


@app.get("/api/servers/{sid}/modpack/search")
async def search_modpack(sid: str, request: Request, q: str = "", kind: str = "mod"):
    auth.require_admin(request)
    srv = await _server(sid)
    if kind not in modpack.KINDS or not q.strip():
        return {"hits": []}
    try:
        return {"hits": await modpack.search(q.strip()[:80], srv.mc_version or "", kind)}
    except Exception as e:
        raise HTTPException(502, f"Couldn't reach Modrinth: {e}") from e


@app.post("/api/servers/{sid}/modpack/add")
async def add_to_modpack(sid: str, request: Request):
    user = auth.require_admin(request)
    srv = await _server(sid)
    body = await request.json()
    try:
        if body.get("names"):
            res = await modpack.add_names(srv, str(body["names"])[:4000])
        else:
            kind = str(body.get("kind") or "mod")
            got = await modpack.add(srv, str(body.get("slug") or ""), kind if kind in modpack.KINDS else "mod")
            res = {"added": [{"title": e["title"], "slug": e["slug"]} for e in got], "missing": []}
    except Exception as e:
        raise HTTPException(502, f"Couldn't reach Modrinth: {e}") from e
    auth.audit(user, srv.id, "modpack:add", ", ".join(a["slug"] for a in res["added"]))
    return {**res, "pack": await asyncio.to_thread(_pack_view, srv, request)}


@app.delete("/api/servers/{sid}/modpack/extra/{slug}")
async def remove_from_modpack(sid: str, slug: str, request: Request):
    user = auth.require_admin(request)
    srv = await _server(sid)
    modpack.remove(srv.id, slug)
    auth.audit(user, srv.id, "modpack:remove", slug)
    return await asyncio.to_thread(_pack_view, srv, request)


@app.post("/api/servers/{sid}/modpack/{action}")
async def modpack_updates(sid: str, action: str, request: Request):
    user = auth.require_admin(request)
    srv = await _server(sid)
    if action == "check":
        return {"updates": await modpack.check_updates(srv.id, srv.mc_version or "")}
    if action == "update-all":
        changed = await modpack.update_all(srv.id, srv.mc_version or "")
        auth.audit(user, srv.id, "modpack:update", ", ".join(c["slug"] for c in changed))
        return {"changed": changed, "pack": await asyncio.to_thread(_pack_view, srv, request)}
    raise HTTPException(404, "Unknown action")


@app.get("/api/public/packwiz-installer-bootstrap.jar")
async def pack_bootstrap():
    try:
        data = await modpack.bootstrap_jar()
    except Exception as e:
        raise HTTPException(502, f"Couldn't download the installer from GitHub: {e}") from e
    return Response(data, media_type="application/java-archive",
                    headers={"Content-Disposition": 'attachment; filename="packwiz-installer-bootstrap.jar"'})


@app.get("/api/public/pack/{token}/{path:path}")
async def pack_file(token: str, path: str, request: Request):
    """What packwiz-installer reads: pack.toml, index.toml, the metafiles, and the server's own jars."""
    found = modpack.by_token(token)
    if not found:
        raise HTTPException(404, "No such pack")
    srv = await S.registry.get(found[0])          # the pack's secret link is the permission (a private server's pack still installs)
    if not srv:
        raise HTTPException(404, "No such pack")
    if path.startswith("jar/"):
        jar = await asyncio.to_thread(modpack.server_jar, srv, token, path[4:])
        if not jar:
            raise HTTPException(404, "Not in the pack")
        return FileResponse(jar, media_type="application/java-archive", filename=jar.name)
    files = await asyncio.to_thread(modpack.files, srv, _public_base(request))
    if path not in files:
        raise HTTPException(404, "Not in the pack")
    return Response(files[path], media_type="application/toml", headers={"Cache-Control": "no-cache"})


@app.get("/api/servers/{sid}/players")
async def get_players(sid: str):
    data = await S.players_overview(await _server(sid))
    for p in data["players"]:
        if not _own(p.get("uuid") or ""):          # a player account doesn't see where anyone else is
            p.pop("position", None)
            p.pop("dimension", None)
    return data


@app.get("/api/servers/{sid}/players/{uuid}")
async def get_player(sid: str, uuid: str):
    if not _own(uuid):
        raise HTTPException(404, "Player not found")
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
async def put_settings(sid: str, request: Request):
    user = auth.require_admin(request)
    srv = await _server(sid)
    body = await _body(request)
    if "bedtime" in body:
        try:
            body["bedtime"] = guard.validate_bedtime(body["bedtime"] or {})
        except (ValueError, TypeError) as e:
            raise HTTPException(400, "Bedtime needs times like 21:00") from e
    saved = settings_store.update_server(srv.id, body)
    auth.audit(user, srv.id, "settings", ", ".join(sorted(k for k in body if k != "rcon_password")) +
               (", rcon_password" if "rcon_password" in body else ""))
    safe = {k: v for k, v in saved.items() if k != "rcon_password"}
    safe["rcon_password_set"] = "rcon_password" in saved
    return safe


@app.get("/api/servers/{sid}/settings")
async def get_settings(sid: str, request: Request):
    auth.require_admin(request)
    srv = await _server(sid)
    s = dict(srv.settings)
    s["rcon_password_set"] = "rcon_password" in s
    s.pop("rcon_password", None)
    return s


# ------------------------------------------------------------------ history
@app.get("/api/servers/{sid}/activity")
async def activity(sid: str, days: int = 14):
    srv = await _server(sid)
    days = max(1, min(days, 90))
    return {
        "daily": db.daily_playtime(srv.id, days),
        "sessions": db.sessions(srv.id, limit=40),
        "recorder_since": (db.q("SELECT MIN(ts) AS t FROM metrics WHERE server_id=?", (srv.id,))[0]["t"]),
    }


@app.get("/api/servers/{sid}/events")
async def events(sid: str, types: str = "", player: str = "", limit: int = 100, before: float | None = None):
    srv = await _server(sid)
    tlist = [t for t in types.split(",") if t] or None
    return db.events(srv.id, tlist, player or None, limit, before)


@app.get("/api/servers/{sid}/timeline")
async def timeline(sid: str, player: str = "", before: float | None = None, sessions: int = 20, chat: bool = True):
    srv = await _server(sid)
    return db.timeline(srv.id, player or None, before, max(1, min(sessions, 100)), chat)


@app.get("/api/servers/{sid}/metrics")
async def server_metrics(sid: str, range: str = "24h"):  # noqa: A002 - query param name
    srv = await _server(sid)
    try:
        data = db.metrics(srv.id, range)
    except Exception as e:  # surface storage problems on the page instead of a blank chart
        log.exception("metrics query failed")
        raise HTTPException(500, f"Couldn't read performance history: {type(e).__name__}: {e}") from e
    data["recorder"] = recorder.status(srv.id)
    return data


@app.get("/api/servers/{sid}/players/{uuid}/history")
async def player_history(sid: str, uuid: str, days: int = 30):
    if not _own(uuid):
        raise HTTPException(404, "Player not found")
    srv = await _server(sid)
    p = S.known_players(srv).get(S.norm_uuid(uuid))
    if not p:
        raise HTTPException(404, "Player not found")
    days = max(1, min(days, 90))
    daily = db.daily_playtime(srv.id, days, p["name"])
    return {
        "daily": [{"date": d["date"], "seconds": sum(d["players"].values())} for d in daily],
        "sessions": db.sessions(srv.id, p["name"], limit=30),
        "events": db.events(srv.id, None, p["name"], 60),
    }


# ------------------------------------------------------------------ notifications
@app.get("/api/settings/notifications")
async def get_notifications(request: Request):
    auth.require_admin(request)
    return notify.public_config()


@app.put("/api/settings/notifications")
async def put_notifications(request: Request):
    user = auth.require_admin(request)
    body = await _body(request)
    auth.audit(user, None, "notification_settings", ", ".join(sorted(k for k in body if "token" not in k and "webhook" not in k)))
    return notify.save_config(body)


@app.post("/api/settings/notifications/digest")
async def digest_preview(request: Request, send: bool = False):
    auth.require_admin(request)
    await S.registry.refresh()
    text = recorder.digest(list(S.registry.servers.values()))
    result = {"text": text}
    if send:
        errors = await notify.send("Solstone weekly digest", text, notify.TAGS["digest"], force=True)
        result.update(ok=not errors, errors=errors)
    return result


@app.get("/api/players/all")
async def all_players():
    """Everyone who has joined any server (for per-player settings like screen-time limits)."""
    await S.registry.refresh()
    names: dict[str, str] = {}
    for srv in [x for x in S.registry.servers.values() if _visible(x)]:
        for p in S.known_players(srv).values():
            names.setdefault(p["name"].lower(), p["name"])
    return sorted(names.values(), key=str.lower)


@app.get("/api/servers/{sid}/backups")
async def server_backups(sid: str):
    return await asyncio.to_thread(backups.status, await _server(sid))


@app.post("/api/settings/notifications/test")
async def test_notifications(request: Request):
    auth.require_admin(request)
    errors = await notify.send("Solstone", "Test notification. Join alerts will look like this.", force=True)
    return {"ok": not errors, "errors": errors}


# ------------------------------------------------------------------ assets
@app.get("/api/servers/{sid}/assets/status")
async def assets_status(sid: str):
    srv = await _server(sid)
    if not srv.is_java:
        return {"state": "not-minecraft"}
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


@app.get("/api/servers/{sid}/assets/items")
async def assets_items(sid: str):
    """Items that can be given, with display names (for the give-item picker)."""
    a = _assets(await _server(sid))
    if not a or not a.ready:
        return []
    return JSONResponse(await asyncio.to_thread(a.items), headers={"Cache-Control": "private, max-age=600"})


@app.get("/api/servers/{sid}/assets/describe")
async def assets_describe(sid: str, item: str, request: Request):
    """What an item does (its tooltip), for the give-item and prize pickers."""
    auth.require_admin(request)
    srv = await _server(sid)
    a = _assets(srv)
    lang = (await asyncio.to_thread(a.lang_cached)) if a and a.ready else {}
    return await tide.describe_item(srv, item.strip().lower()[:200], lang)


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
    return Response(data, media_type="image/png", headers={"Cache-Control": "private, max-age=604800"})


@app.get("/api/skins/{uuid}.png")
async def player_skin(uuid: str, request: Request):
    return await _skin_response(request, uuid, "private")


@app.get("/api/skins/{uuid}/body.png")
async def player_body(uuid: str, request: Request, size: int = 256):
    return await _skin_response(request, uuid, "private", size)


@app.get("/api/servers/{sid}/assets/texture/{path:path}")
async def texture(sid: str, path: str):
    a = _assets(await _server(sid))
    rel = safe_texture_path(path.removesuffix(".png"))
    if not a or not rel:
        raise HTTPException(404)
    data = a.read(rel)
    if not data:
        raise HTTPException(404)
    return Response(data, media_type="image/png", headers={"Cache-Control": "private, max-age=604800"})


# ------------------------------------------------------------------ control (admins)
@app.get("/api/servers/{sid}/control")
async def control_info(sid: str, request: Request):
    auth.require_admin(request)
    srv = await _server(sid)
    rules = await control.game_rules(srv) if srv.is_java else []
    online, source = await S.online_players(srv)
    return {
        "can_rcon": srv.rcon_conf() is not None,
        "can_crafty": bool(srv.crafty and crafty.enabled),
        "is_java": srv.is_java,
        "game_rules": rules,
        "online": online,
        "online_source": source,
        "known_players": sorted((p["name"] for p in S.known_players(srv).values()), key=str.lower) if srv.is_java else [],
        "lists": await control.whitelist(srv) if srv.is_java else None,
        "bedtime": guard.bedtime_config(srv),
        "audit": auth.audit_log(srv.id, 40),
    }


async def _act(request: Request, sid: str, action: str, detail: str, coro_fn):
    user = auth.require_admin(request)
    srv = await _server(sid)
    try:
        result = await coro_fn(srv, user)
    except HTTPException as e:
        auth.audit(user, srv.id, action, detail, f"failed: {e.detail}")
        raise
    outputs = result if isinstance(result, list) else [result]
    summary = " | ".join((r.get("output") or "").strip() for r in outputs if isinstance(r, dict) and r.get("output"))
    auth.audit(user, srv.id, action, detail, summary or "ok")
    return {"results": outputs}


@app.post("/api/servers/{sid}/control/command")
async def control_command(sid: str, request: Request):
    body = await _body(request)
    cmd = str(body.get("command", ""))
    return await _act(request, sid, "command", cmd, lambda srv, _u: control.run(srv, cmd))


@app.post("/api/servers/{sid}/control/quick")
async def control_quick(sid: str, request: Request):
    body = await _body(request)
    action, value = str(body.get("action", "")), str(body.get("value", ""))
    return await _act(request, sid, f"quick:{action}", value,
                      lambda srv, u: control.quick(srv, action, value, u.username))


@app.post("/api/servers/{sid}/control/gamerule")
async def control_gamerule(sid: str, request: Request):
    body = await _body(request)
    key = str(body.get("key", ""))
    return await _act(request, sid, "gamerule", f"{key}={body.get('value')}",
                      lambda srv, _u: control.set_rule(srv, key, body.get("value")))


@app.post("/api/servers/{sid}/control/broadcast")
async def control_broadcast(sid: str, request: Request):
    body = await _body(request)
    msg = str(body.get("message", ""))
    return await _act(request, sid, "broadcast", msg,
                      lambda srv, u: control.broadcast(srv, msg, u.username, bool(body.get("on_screen"))))


def _rcon_echo(srv: S.Server) -> bool:
    """True when the server shows every RCON command to operators in chat (the default), which
    turns contests, races and games into a stream of "[Rcon: ...]" lines for any op playing."""
    return bool(srv.rcon_conf()) and srv.props.get("broadcast-rcon-to-ops", "true").strip().lower() != "false"


# ---- challenges: timed contests with prizes
@app.get("/api/servers/{sid}/challenges")
async def get_challenges(sid: str, request: Request):
    auth.require_admin(request)
    srv = await _server(sid)
    try:
        spawn = (await asyncio.to_thread(S.world_info, srv, False)).get("spawn")
    except Exception:
        spawn = None
    return {"kinds": challenges.kinds(), "items": challenges.list_for(srv.id), "gifts": challenges.gifts_for(srv.id),
            "rcon": bool(srv.rcon_conf()), "now": time.time(), "rcon_echo": _rcon_echo(srv), "spawn": spawn}


@app.post("/api/servers/{sid}/challenges")
async def add_challenge(sid: str, request: Request):
    user = auth.require_admin(request)
    srv = await _server(sid)
    try:
        c = challenges.create(srv.id, await _body(request))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    auth.audit(user, srv.id, "challenge", f"{c['name']} at {datetime.fromtimestamp(c['start'], db.tz()):%Y-%m-%d %H:%M}")
    return c


@app.put("/api/servers/{sid}/challenges/{cid}")
async def edit_challenge(sid: str, cid: str, request: Request):
    auth.require_admin(request)
    srv = await _server(sid)
    try:
        return challenges.update(srv.id, cid, await _body(request))
    except KeyError:
        raise HTTPException(404, "Challenge not found") from None
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.delete("/api/servers/{sid}/challenges/{cid}")
async def delete_challenge(sid: str, cid: str, request: Request):
    user = auth.require_admin(request)
    srv = await _server(sid)
    if not await challenges.cancel(srv, cid):
        raise HTTPException(404, "Challenge not found")
    auth.audit(user, srv.id, "challenge", f"cancelled {cid}")
    return {"ok": True}


# ---- the Solstone Fishing data pack
@app.get("/api/servers/{sid}/fishing/journal")
async def fishing_journal(sid: str, request: Request):
    """Everyone's fishing journal (anyone signed in)."""
    srv = await _server(sid)
    if await asyncio.to_thread(tide.installed, srv):
        return await asyncio.to_thread(tide.journal, srv)
    return await asyncio.to_thread(fishing.journal, srv.id)


@app.get("/api/servers/{sid}/fishing/tackle")
async def fishing_tackle(sid: str, request: Request):
    """The tackle guide (anyone signed in): every rod, line, hook, bobber, lure, bait and piece of gear."""
    srv = await _server(sid)
    a = _assets(srv)
    lang = (await asyncio.to_thread(a.lang_cached)) if a and a.ready else {}
    return await tide.guide(srv, lang)


# ---- Adventures: replays of play sessions
@app.get("/api/servers/{sid}/adventures")
async def adventures_list(sid: str, request: Request, days: int = 30):
    auth.require_user(request)
    srv = await _server(sid)
    return {"sessions": await asyncio.to_thread(adventures.sessions, srv.id, max(1, min(365, days)))}


@app.get("/api/servers/{sid}/adventures/timeline")
async def adventures_timeline(sid: str, request: Request, start: float, end: float):
    auth.require_user(request)
    srv = await _server(sid)
    return await asyncio.to_thread(adventures.timeline, srv.id, start, end)


@app.post("/api/servers/{sid}/adventures")
async def adventures_save(sid: str, request: Request):
    """Save (or, with an id, change) an adventure: a stretch of play with a title and a note. Anyone signed in."""
    user = auth.require_user(request)
    srv = await _server(sid)
    body = await _body(request)
    aid = int(body["id"]) if body.get("id") else None
    if aid:
        a = adventures.get(aid)
        if not a or a["server_id"] != srv.id:
            raise HTTPException(404, "Adventure not found")
        if not user.is_admin and a["created_by"] != user.username:
            raise HTTPException(403, "Only whoever saved it (or an admin) can change it")
    try:
        saved = await asyncio.to_thread(adventures.save, srv.id, float(body.get("start", 0)), float(body.get("end", 0)),
                                        str(body.get("title") or ""), str(body.get("note") or ""), user.username, aid)
    except (TypeError, ValueError) as e:
        raise HTTPException(400, str(e)) from e
    auth.audit(user, srv.id, "adventure", saved["title"])
    return saved


@app.post("/api/servers/{sid}/adventures/hide")
async def adventures_hide(sid: str, request: Request):
    """Hide a session from the list, or show it again ({start, end, hidden}). Anyone signed in."""
    user = auth.require_user(request)
    srv = await _server(sid)
    body = await _body(request)
    try:
        start, end = float(body["start"]), float(body["end"])
    except (KeyError, TypeError, ValueError) as e:
        raise HTTPException(400, "Which session?") from e
    await asyncio.to_thread(adventures.hide, srv.id, start, end, user.username, bool(body.get("hidden", True)))
    return {"ok": True}


@app.post("/api/servers/{sid}/adventures/erase")
async def adventures_erase(sid: str, request: Request):
    """Admins: delete a session's trail and statistics lines for good (and any saved adventure over it)."""
    user = auth.require_admin(request)
    srv = await _server(sid)
    body = await _body(request)
    try:
        start, end = float(body["start"]), float(body["end"])
    except (KeyError, TypeError, ValueError) as e:
        raise HTTPException(400, "Which session?") from e
    r = await asyncio.to_thread(adventures.erase, srv.id, start, end)
    auth.audit(user, srv.id, "adventure_erased", f"{start:.0f}-{end:.0f}: {r['positions']} positions")
    return r


@app.delete("/api/servers/{sid}/adventures/{aid}")
async def adventures_delete(sid: str, aid: int, request: Request):
    user = auth.require_user(request)
    srv = await _server(sid)
    a = adventures.get(aid)
    if not a or a["server_id"] != srv.id:
        raise HTTPException(404, "Adventure not found")
    if not user.is_admin and a["created_by"] != user.username:
        raise HTTPException(403, "Only whoever saved it (or an admin) can delete it")
    adventures.delete(aid)
    auth.audit(user, srv.id, "adventure_deleted", a["title"])
    return {"ok": True}


@app.get("/api/servers/{sid}/fishing")
async def get_fishing(sid: str, request: Request):
    auth.require_admin(request)
    srv = await _server(sid)
    if srv.is_java and srv.rcon_conf():
        try:
            await fishing.check(srv, force=not (fishing._state.get(srv.id) or {}).get("version"))
        except Exception as e:
            log.debug("fishing check failed: %s", e)
    evs = db.events(srv.id, ["fish", "bigfish"], None, 40)
    return {"status": fishing.status(srv), "rcon": bool(srv.rcon_conf()), "guide": fishpack.guide(), "qualities": fishpack.qualities(),
            "tide": await asyncio.to_thread(tide.installed, srv),
            "recent": [{"ts": e["ts"], "player": e["player"], "message": e["message"]} for e in evs]}


@app.get("/api/fishing/" + fishpack.PACK_FILE)
async def fishing_pack(request: Request, server: str = ""):
    auth.require_admin(request)
    srv = await S.registry.get(server) if server else None
    new = fishing.new_format(srv) if srv else request.query_params.get("format") == "26.3"
    with_fishing = not (srv and await asyncio.to_thread(tide.installed, srv))      # Tide does fishing its own way
    return Response(fishpack.build_zip(new, fishing=with_fishing), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{fishpack.PACK_FILE}"', "Cache-Control": "no-store"})


@app.post("/api/servers/{sid}/fishing/reset")
async def fishing_reset(sid: str, request: Request):
    """Tide: back to fishing level 1 (and, with everything, an empty journal, tackle log and Solstone catch
    history). The player has to be online: the mod changes their save itself."""
    user = auth.require_admin(request)
    srv = await _server(sid)
    body = await _body(request)
    player = str(body.get("player", "")).strip()
    everything = bool(body.get("everything"))
    level = body.get("level")
    if not re.fullmatch(r"[A-Za-z0-9_]{1,16}", player):
        raise HTTPException(400, "That isn't a Minecraft name")
    if level is not None and (not isinstance(level, int) or isinstance(level, bool) or not 1 <= level <= 99):
        raise HTTPException(400, "Pick a level from 1 to 99")
    if not srv.rcon_conf():
        raise HTTPException(409, "Turn on RCON for this server first")
    try:
        cmd = f"fishinglevel set {player} {level}" if level is not None else f"fishinglevel reset {player}{' everything' if everything else ''}"
        reply = await srv.rcon(cmd) or ""
    except RconError as e:
        raise HTTPException(502, f"The server didn't answer: {e}") from e
    if "No player was found" in reply or "Unknown or incomplete command" in reply or "Incorrect argument" in reply:
        raise HTTPException(409, f"{player} needs to be online for this (the fishing mod changes their save itself)"
                            if "No player" in reply else "This server's Tide is too old for resets; update the mod")
    removed = await asyncio.to_thread(db.clear_fishing, srv.id, player) if everything and level is None else 0
    try:
        await srv.rcon("save-all")          # so this page shows the fresh start straight away
    except RconError:
        pass
    auth.audit(user, srv.id, "fishing:reset", f"{player} " + (f"set level {level}" if level is not None else "everything" if everything else "level"))
    return {"ok": True, "reply": reply, "catches_removed": removed}


@app.post("/api/servers/{sid}/fishing/{action}")
async def fishing_action(sid: str, action: str, request: Request):
    user = auth.require_admin(request)
    srv = await _server(sid)
    if action not in ("install", "reload", "test"):
        raise HTTPException(404)
    if not srv.rcon_conf():
        raise HTTPException(409, "Turn on RCON for this server first")
    try:
        if action == "test":
            return await fishing.test_catch(srv)
        st = await (fishing.install(srv) if action == "install" else fishing.reload(srv))
    except RuntimeError as e:
        raise HTTPException(502, f"The server didn't answer: {e}") from e
    auth.audit(user, srv.id, f"fishing:{action}", f"pack version {st.get('version')}")
    return {**fishing.status(srv), "listed": st.get("listed"), "reload_reply": st.get("reload_reply", ""), "problems": st.get("problems", [])}


# ---- games: hide and seek, treasure hunt, archery
@app.get("/api/servers/{sid}/games")
async def get_games(sid: str, request: Request):
    auth.require_admin(request)
    srv = await _server(sid)
    pack = None
    if srv.is_java and srv.rcon_conf():
        try:
            pack = (await fishing.check(srv, force=not (fishing._state.get(srv.id) or {}).get("version"))).get("version")
        except Exception:
            pack = None
    w = await asyncio.to_thread(S.world_info, srv, False) if srv.is_java else {}
    return {"runs": games.runs_for(srv.id), "rcon": bool(srv.rcon_conf()), "pack": pack, "pack_needed": 2, "pack_needed_spleef": 10,
            "spawn": w.get("spawn"), "now": time.time(), "rcon_echo": _rcon_echo(srv)}


@app.post("/api/servers/{sid}/games")
async def add_game(sid: str, request: Request):
    user = auth.require_admin(request)
    srv = await _server(sid)
    try:
        r = games.create(srv.id, await _body(request))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    auth.audit(user, srv.id, "game", f"{r['name']} at {datetime.fromtimestamp(r['start'], db.tz()):%Y-%m-%d %H:%M}")
    return r


@app.delete("/api/servers/{sid}/games/{rid}")
async def stop_game(sid: str, rid: str, request: Request):
    auth.require_admin(request)
    srv = await _server(sid)
    if not await games.cancel(srv, rid):
        raise HTTPException(404, "Game not found")
    return {"ok": True}


@app.get("/api/servers/{sid}/games/target")
async def game_target(sid: str, request: Request, player: str):
    auth.require_admin(request)
    srv = await _server(sid)
    try:
        return await games.target_under(srv, player)
    except ValueError as e:
        raise HTTPException(409, str(e)) from e


# ---- races: courses of waypoints, run with markers in the game
@app.get("/api/servers/{sid}/races")
async def get_races(sid: str, request: Request):
    auth.require_admin(request)
    srv = await _server(sid)
    runs = races.runs_for(srv.id)
    for r in runs:
        r["standings"] = races.standings(r)
    w = await asyncio.to_thread(S.world_info, srv, False) if srv.is_java else {}
    return {"courses": races.courses_for(srv.id), "runs": runs, "rcon": bool(srv.rcon_conf()), "now": time.time(),
            "spawn": w.get("spawn"), "version": srv.mc_version, "rcon_echo": _rcon_echo(srv)}


@app.post("/api/servers/{sid}/races/courses")
async def add_course(sid: str, request: Request):
    auth.require_admin(request)
    srv = await _server(sid)
    try:
        return races.save_course(srv.id, await _body(request))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.put("/api/servers/{sid}/races/courses/{cid}")
async def edit_course(sid: str, cid: str, request: Request):
    auth.require_admin(request)
    srv = await _server(sid)
    try:
        return races.save_course(srv.id, await _body(request), cid)
    except KeyError:
        raise HTTPException(404, "Course not found") from None
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.delete("/api/servers/{sid}/races/courses/{cid}")
async def remove_course(sid: str, cid: str, request: Request):
    auth.require_admin(request)
    srv = await _server(sid)
    if not races.delete_course(srv.id, cid):
        raise HTTPException(404, "Course not found")
    return {"ok": True}


@app.post("/api/servers/{sid}/races/runs")
async def start_race(sid: str, request: Request):
    user = auth.require_admin(request)
    srv = await _server(sid)
    try:
        r = races.schedule(srv.id, await _body(request))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    auth.audit(user, srv.id, "race", f"{r['name']} at {datetime.fromtimestamp(r['start'], db.tz()):%Y-%m-%d %H:%M}")
    return r


@app.delete("/api/servers/{sid}/races/runs/{rid}")
async def stop_race(sid: str, rid: str, request: Request):
    auth.require_admin(request)
    srv = await _server(sid)
    if not await races.cancel(srv, rid):
        raise HTTPException(404, "Race not found")
    return {"ok": True}


@app.get("/api/servers/{sid}/races/spot")
async def race_spot(sid: str, request: Request, player: str = "", x: float = 0, z: float = 0, dim: str = "minecraft:overworld"):
    """A point for a course: where a player is standing now, or the ground height at x, z."""
    auth.require_admin(request)
    srv = await _server(sid)
    if player:
        try:
            return await races.player_spot(srv, player)
        except ValueError as e:
            raise HTTPException(409, str(e)) from e
    y = await asyncio.to_thread(worldmap.surface_y, srv.world_dir, dim, x, z)
    return {"x": round(x, 1), "y": y if y is not None else 64, "z": round(z, 1), "guessed": y is None}


# ---- chat: what's said in the game, and messages from here
CHAT_TYPES = ["chat", "webchat", "webdm", "join", "leave", "death", "advancement", "challenge", "race", "fish", "bigfish", "game"]


@app.get("/api/servers/{sid}/chat")
async def get_chat(sid: str, request: Request, after: int = 0):
    auth.require_user(request)                                 # everyone signed in can read and send chat
    srv = await _server(sid)
    rows = db.events_after(srv.id, CHAT_TYPES, max(0, after), 300 if not after else 200)
    out = []
    for e in rows:
        row = {"id": e["id"], "ts": e["ts"], "type": e["type"], "player": e["player"], "message": e["message"]}
        if e["type"] == "webdm":
            to, _, text = (e["message"] or "").partition("\x1f")
            row.update(to=to, message=text)
        out.append(row)
    names, _src = await S.online_players(srv) if srv.is_java else ([], "")
    return {"items": out, "online": names, "can_send": bool(srv.rcon_conf() or srv.crafty)}


@app.post("/api/servers/{sid}/chat")
async def send_chat(sid: str, request: Request):
    user = auth.require_user(request)
    name = user.shown
    srv = await _server(sid)
    body = await _body(request)
    text = control.clean_text(str(body.get("message") or ""))
    if not text:
        raise HTTPException(400, "Type a message")
    to = str(body.get("to") or "").strip()
    if to:
        to = control.check_name(to)
        cmd = f"tellraw {to} {control.component([(f'{name} whispers to you: ', 'light_purple'), (text, 'light_purple')])}"
    else:
        cmd = f"tellraw @a {control.component([('<', None), (name, 'aqua'), ('> ', None), (text, None)])}"
    r = await control.run(srv, cmd)
    if r.get("ok") is False:
        raise HTTPException(409, (r.get("output") or "The game said no")[:200])
    if to and r.get("output") and "no player" in r["output"].lower():
        raise HTTPException(409, f"{to} isn't online")
    eid = db.add_event(srv.id, time.time(), "webdm" if to else "webchat", f"{to}\x1f{text}" if to else text, name)
    return {"ok": True, "id": eid}


@app.post("/api/servers/{sid}/control/player/{player}/{action}")
async def control_player(sid: str, player: str, action: str, request: Request):
    body = await _body(request)
    detail = f"{player} {json.dumps({k: v for k, v in body.items()}, ensure_ascii=False)}" if body else player
    return await _act(request, sid, f"player:{action}", detail,
                      lambda srv, u: control.player_action(srv, player, action, body, u.username))


@app.post("/api/servers/{sid}/control/power/{action}")
async def control_power(sid: str, action: str, request: Request):
    return await _act(request, sid, f"power:{action}", "", lambda srv, _u: control.power(srv, action))


@app.get("/api/servers/{sid}/console/stream")
async def console_stream(sid: str, request: Request):
    auth.require_admin(request)
    srv = await _server(sid)
    return StreamingResponse(control.console_stream(srv, request.is_disconnected), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ------------------------------------------------------------------ frontend
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/status", include_in_schema=False)
@app.get("/status/{sid}", include_in_schema=False)
async def status_page(sid: str = ""):
    if not _status_cfg()["enabled"]:
        return HTMLResponse(_page("status-off.html"), status_code=404, headers={"Cache-Control": "no-cache"})
    return HTMLResponse(_page("status.html"), headers={"Cache-Control": "no-cache"})


@app.get("/", include_in_schema=False)
@app.get("/news", include_in_schema=False)
@app.get("/guides", include_in_schema=False)
@app.get("/guides/{slug}", include_in_schema=False)
@app.get("/faq", include_in_schema=False)
@app.get("/post/{slug}", include_in_schema=False)
async def home_page(slug: str = ""):
    """The public website: home, news, guides, FAQ and posts. No sign-in."""
    return HTMLResponse(_page("home.html"), headers={"Cache-Control": "no-cache"})


@app.get("/app", include_in_schema=False)
@app.get("/app/{full_path:path}", include_in_schema=False)
async def app_page(full_path: str = ""):
    """The signed-in app (it routes by #/... after this)."""
    return HTMLResponse(_page("index.html"), headers={"Cache-Control": "no-cache"})


@app.get("/{full_path:path}", include_in_schema=False)
async def not_found_page(full_path: str):
    if full_path.startswith("api/"):
        raise HTTPException(404)
    return HTMLResponse(_page("home.html"), status_code=404, headers={"Cache-Control": "no-cache"})


ASSET_NAMES = ("app.css", "sky.js", "showbar.js", "hud.js", "board.js", "recap.js", "login.js", "app.js", "history.js", "control.js", "play.js", "editor.js", "fwsettings.js", "announce.js", "status.js", "home.js", "website.js")


def _asset_stamp() -> str:
    files = [STATIC / n for n in ASSET_NAMES]
    return format(int(max(f.stat().st_mtime for f in files if f.exists())), "x")


def _html_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#39;")


def _page(name: str) -> str:
    """An HTML page with ?v= on the CSS/JS links so browsers pick up new versions after an update."""
    stamp = _asset_stamp()
    html = (STATIC / name).read_text(encoding="utf-8")
    for n in ASSET_NAMES:
        html = html.replace(f"/static/{n}\"", f"/static/{n}?v={stamp}\"")
    return html.replace("{{SITE_NAME}}", _html_escape(site.config()["name"])).replace("{{SITE_LOGO}}", _html_escape(site.logo_url()))
