"""Solstone — a family-friendly dashboard for Minecraft servers run by Crafty Controller."""
from __future__ import annotations

import asyncio
import contextvars
import functools
import hashlib
import json
import logging
import os
import re
import secrets
import time
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
import httpx

from . import adventures, auth, backups, forget, board, challenges, community, control, db, eventgroups, fishing, fishpack, games, mcname, modpack, modupdates, races, fireworks, fwshow, guard, notify, nudge, optin, playtime, recap, selfcheck, selfbackup, signup, site, skins, tide, upcoming, votegame, watchdog, maintenance, webmap, welcome, worldmap
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
VERSION = "1.12.6"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    watchdog.start()
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


def _allowed(srv: S.Server) -> bool:
    """The signed-in person may see this server (some logins are limited to one or two). Signed-out pages
    have their own rules (public servers only). A login linked to a Minecraft player also sees every server
    that player is on the whitelist of: let them in on a second server and it shows in their account too."""
    u = _viewer.get()
    if u is None or u.may_see(srv.id):
        return True
    return srv.is_java and any(S.whitelisted(srv, p["uuid"], p["name"]) for p in u.players)


def _visible(srv: S.Server) -> bool:
    """Shown to whoever is asking: not hidden, if private only to an admin, and one of theirs."""
    return not srv.settings.get("hidden") and (not _private(srv) or _admin_viewing()) and _allowed(srv)


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
    "/api/servers/{sid}/webmap": {"GET"},               # the web map through Solstone, if players may see the map
    "/api/servers/{sid}/adventures": {"GET"},             # only the sessions they played in (see adventures_list)
    "/api/servers/{sid}/adventures/timeline": {"GET"},    # their own trail; others' only with the map on for players
    "/api/servers/{sid}/icon.png": {"GET"},
    "/api/servers/{sid}/metrics": {"GET"},
    "/api/servers/{sid}/mods": {"GET"},
    "/api/servers/{sid}/recap": {"GET"},
    "/api/servers/{sid}/activity": {"GET"},            # which days people played (never how long, for non-admins)
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


# With "Players can see the map" on (Manage → Users), players also get the World tab: the map, with where everyone is.
PLAYER_MAP_ROUTES = {"/api/servers/{sid}/world": {"GET"}}


def _players_see_map() -> bool:
    return bool(settings_store.load().get("players", {}).get("see_map", False))


def _player_may(method: str, path: str) -> bool:
    if not path.startswith("/api/") or path.startswith(("/api/public/", "/api/auth/")):
        return True
    if path.startswith("/api/fireworks"):                      # fireworks are for everyone
        return True
    if path.startswith("/api/community/") and not path.startswith("/api/community/admin/"):   # votes, sign-ups, messages
        return True
    if method in PLAYER_MAP_ROUTES.get(path, ()) and _players_see_map():
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


def _shows_play_time() -> bool:
    """How long people play is for admins only (screen-time limits). Everyone else, and the public pages, see who
    played and which days, never for how long: nobody gets shamed for a long session, and nobody races to play longest."""
    u = _viewer.get()
    return u is not None and u.is_admin


_DURATION_KEYS = {"seconds", "total_seconds", "today_seconds", "play_time",
                  "minecraft:play_time", "minecraft:play_one_minute", "minecraft:total_world_time"}   # the last three: game statistics


def _no_durations(data):
    """The same data without any play-time length in it (for anyone but an admin)."""
    if isinstance(data, dict):
        return {k: _no_durations(v) for k, v in data.items() if k not in _DURATION_KEYS}
    if isinstance(data, list):
        return [_no_durations(x) for x in data]
    return data


def _recap_without_durations(data: dict) -> dict:
    """A recap for anyone but an admin: no lengths, and players in the order they joined (longest-first would tell)."""
    out = _no_durations(data)
    for rc in [out.get("recap"), out.get("yesterday"), *(out.get("on_this_day") or [])]:
        if isinstance(rc, dict) and isinstance(rc.get("players"), list):
            rc["players"].sort(key=lambda p: p.get("first") or 0)
    return out


def _own(uuid: str) -> bool:
    """For a player account: is this their own Minecraft player? (Everyone else may see anyone.)"""
    u = _viewer.get()
    return u is None or not u.is_player or S.norm_uuid(uuid) in {S.norm_uuid(x) for x in u.player_uuids}


_SUMMARY_FOR_PLAYERS = ("id", "name", "running", "crashed", "started", "cpu", "mem", "mem_percent", "world_size", "version", "motd",
                        "max_players", "online", "has_icon", "loader", "game", "game_label", "perf", "fishing", "error")


def _for_player(summary: dict) -> dict:
    """A server's summary without the running of it (folders, ports, RCON, backups, the web map)."""
    u = _viewer.get()
    if u is None or not u.is_player:
        return summary
    out = {k: summary[k] for k in _SUMMARY_FOR_PLAYERS if k in summary} | {"folder_found": True}
    if _players_see_map():
        # the map's own address only when it isn't shown through Solstone (then nobody needs it)
        out |= {"player_map": True, "map_url": None if summary.get("map_proxy") else summary.get("map_url"),
                "map_proxy": bool(summary.get("map_proxy") and summary.get("map_url"))}
    return out


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


# Anonymous visitors: at most this many public requests a minute from one address. An open home page makes about 35;
# this stops one machine (or a few) from hammering Solstone, the game or your connection. A crowd of machines is
# Cloudflare's job, in front of Solstone.
PUBLIC_PER_MINUTE = int(os.getenv("PUBLIC_REQUESTS_PER_MINUTE", "240"))
_public_hits: dict[str, list[float]] = {}


def _public_limited(request: Request) -> bool:
    if PUBLIC_PER_MINUTE <= 0:
        return False
    if not auth.TRUST_PROXY and (request.headers.get("x-forwarded-for") or request.headers.get("cf-connecting-ip")):
        return False            # behind a proxy we can't see visitors' addresses: everyone would share one limit
    ip, now = auth.client_ip(request), time.monotonic()
    hits = [t for t in _public_hits.get(ip, ()) if now - t < 60]
    if len(hits) >= PUBLIC_PER_MINUTE:
        _public_hits[ip] = hits
        return True
    hits.append(now)
    _public_hits[ip] = hits
    if len(_public_hits) > 20000:
        for k in [k for k, v in _public_hits.items() if not v or now - v[-1] > 60]:
            _public_hits.pop(k, None)
    return False


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
        if request.state.user is None and path.startswith("/api/public/") and _public_limited(request):
            return JSONResponse({"detail": "Too many requests. Slow down a little."}, status_code=429, headers={"Retry-After": "30"})
    if not auth.TRUST_PROXY and not _proxy_warned and (request.headers.get("x-forwarded-for") or request.headers.get("cf-connecting-ip")):
        _warn_proxy()
    started = time.monotonic()
    response = await call_next(request)
    took = time.monotonic() - started
    if took > watchdog.SLOW_REQUEST_SECONDS and not path.endswith(("/stream", "/sse")):
        log.warning("Slow answer: %s %s took %.1f s", request.method, path, took)
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
    if not srv or (_private(srv) and not _admin_viewing()) or not _allowed(srv):
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


# ------------------------------------------------------------------ live servers on the home page (no login needed)
# Off until an admin turns it on. Everything here is read-only and cached so anonymous
# visitors can't hammer RCON or Crafty, and chat is never included.
STATUS_DEFAULTS = {"enabled": False, "show_positions": False, "show_items": True,
                   "show_activity": True}       # the web map (BlueMap) is only on a server's World tab, signed in
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
        raise HTTPException(404, "Live server info is turned off")
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
        "world": None, "spawn": None, "players": [], "recent": [], "recently": [],
    }
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
        online = [p for p in overview["players"] if p["online"]]
        details = await asyncio.gather(*(_maybe_live(srv, p) for p in online))
        hidden = games.hidden_from_map(srv.id)
        for p, live in zip(online, details, strict=True):
            d = live
            if d is None and p.get("uuid"):
                d, _m = await asyncio.to_thread(S.player_file_data, srv, p["uuid"])
            row: dict = {"name": p["name"], "uuid": p.get("uuid"), "live": live is not None,   # never how long they've played
                         "doing": await asyncio.to_thread(adventures.lately, srv.id, p["name"])}   # "⛏️ Mining", from their statistics
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
        board["recently"] = await asyncio.to_thread(_recently, srv, online_l, cfg["show_positions"])
    return board


def _recently(srv: S.Server, online_l: set[str], positions: bool) -> list[dict]:
    """Who played this week but isn't on now (disk work: run off the main loop)."""
    week = time.time() - 7 * 86400
    recent = []
    for uuid, p in S.known_players(srv).items():
        if p["name"].lower() in online_l or S.removed(srv, p):
            continue
        seen = S.last_seen(srv, uuid)
        if seen and seen > week:
            recent.append({"name": p["name"], "uuid": uuid, "last_seen": seen})
    recent = sorted(recent, key=lambda r: -r["last_seen"])[:8]
    if positions:
        # where they were when they left, so the map has something to show with nobody on
        for r in recent:
            d, _m = S.player_file_data(srv, r["uuid"])
            if d and d.get("position"):
                r["position"] = {k: d["position"][k] for k in ("x", "y", "z")}
                r["dimension"] = d["position"].get("dimension") or "minecraft:overworld"
    return recent


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
        return {"enabled": True, "servers": _list_cache[1], "build": _asset_stamp()}
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
    main = site.config().get("main_server")
    out.sort(key=lambda x: x["id"] != main)       # the main server's tab first
    _list_cache = (time.monotonic(), out)
    return {"enabled": True, "servers": out, "build": _asset_stamp()}


def _may_see_map(user) -> bool:
    """Where everyone is (coordinates, the map, the web map) is for people signed in: Trusted and Admins, and Players when
    "Players can see the map" is on. Never for anonymous visitors, so nobody outside can watch where the kids are, and the
    map pictures (the heaviest thing Solstone sends) can't be pulled by strangers."""
    return user is not None and (not user.is_player or _players_see_map())


def _without_whereabouts(board: dict) -> dict:
    strip = lambda rows: [{k: v for k, v in r.items() if k != "position"} for r in rows]   # noqa: E731
    return {**board, "spawn": None, "race": None,
            "players": strip(board.get("players", [])), "recently": strip(board.get("recently", []))}


@app.get("/api/public/status/{sid}")
async def public_board(sid: str, request: Request):
    cfg = _require_status()
    srv = await _public_server(sid)
    board = await _board(srv, cfg)
    if not (_may_see_map(request.state.user) and _allowed(srv)):    # and only on servers their login may see
        board = _without_whereabouts(board)
    if board.get("world") and board["world"].get("as_of"):
        board = {**board, "world": {**board["world"], "age": round(max(0.0, time.time() - board["world"]["as_of"]), 1)}}
    return JSONResponse(board, headers={"Cache-Control": "no-store"})


# ---- the public website: site details (how to join) and posts (news, guides, FAQ)
_site_cache: tuple[float, list] | None = None


@app.get("/api/public/site")
async def public_site():
    global _site_cache
    site.move_guides_to_posts()
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
                            "max": summ["max_players"], "version": summ.get("version"), "has_icon": summ["has_icon"],
                            "started": summ.get("started") if summ["running"] else None, "tps": (summ.get("perf") or {}).get("tps")})
        _site_cache = (time.monotonic(), servers)
    # How to join, one card per public server: its own addresses (its ⚙ settings, or Website → Site details), with
    # Site details' addresses standing in for the first server that has none of its own (the main one, usually).
    await S.registry.refresh()
    status = {x["id"]: x for x in servers}
    joins, main_used = [], False
    # the main server first (starred), then the rest as they come
    ordered = sorted(_public_servers_list(), key=lambda x: x.id != cfg.get("main_server"))
    for srv in ordered:
        st = srv.settings
        java, bed, port = st.get("join_address") or "", st.get("join_bedrock_address") or "", st.get("join_bedrock_port") or ""
        if not (java or bed) and not main_used and (cfg["java_address"] or cfg["bedrock_address"]):
            java, bed, port, main_used = cfg["java_address"], cfg["bedrock_address"], cfg["bedrock_port"], True
        if not (java or bed):
            continue
        joins.append({"id": srv.id, "name": srv.display_name, "java": java, "bedrock": bed, "bedrock_port": port or 19132,
                      "note": st.get("join_note") or "", "mods": _mods_for_players(srv) if st.get("join_mods") or modpack.get(srv.id)["public_download"] else None,
                      "status": status.get(srv.id), "main": srv.id == cfg.get("main_server"),
                      "color": st.get("join_color") or "",
                      "version": srv.mc_version if srv.is_java else None})   # from the world's save: right even while it's off
    if joins and not (cfg["java_address"] or cfg["bedrock_address"]):     # the join guide's {java_address} and the like:
        cfg = {**cfg, "java_address": joins[0]["java"], "bedrock_address": joins[0]["bedrock"],  # the first server's
               "bedrock_port": joins[0]["bedrock_port"]}
    # the join guide's {java_version}: the main (first) server's Minecraft version, when it's known
    cfg = {**cfg, "java_version": next((j["version"] for j in joins if j["java"] and j["version"]), "")}
    asks = [{"id": s.id, "name": s.display_name, "main": s.id == cfg.get("main_server")} for s in ordered if s.is_java] if cfg["join_requests"] else []
    return JSONResponse({**cfg, "logo": site.logo_url(), "servers": servers, "joins": joins, "ask_servers": asks,
                         "guide_posts": site.guide_posts(), "roles": site.ROLES,
                         "live": _status_cfg()["enabled"], "build": _asset_stamp()},
                        headers={"Cache-Control": "no-cache"})


@app.get("/api/public/logo")
async def public_logo():
    lg = site.logo()
    if not lg:
        raise HTTPException(404)
    return FileResponse(lg["file"], media_type=lg["mime"], headers={"Cache-Control": "public, max-age=31536000, immutable",
                                                                   "X-Content-Type-Options": "nosniff"})


@app.get("/api/settings/site/offline-worker")
async def offline_worker(request: Request):
    """The Cloudflare Worker that shows a "website is down" page (app/offline_worker.js), with this site's name,
    contact and public servers' addresses filled in. Only what the home page already shows publicly."""
    auth.require_admin(request)
    await S.registry.refresh()
    pub = json.loads((await public_site()).body)
    cfg = {"name": pub["name"], "contact": pub.get("contact") or "", "discord": pub.get("discord") or "",
           "servers": [{"name": j["name"], "java": j["java"], "bedrock": j["bedrock"], "bedrock_port": j["bedrock_port"],
                        # the up/down check: the Java side only (one check covers the server for Bedrock too)
                        "check": (S.registry.servers[j["id"]].settings.get("join_check") if j["id"] in S.registry.servers else "") or j["java"] or ""}
                       for j in pub["joins"]],
           "key": maintenance.worker_key()}                 # so only Solstone can tell it about planned maintenance
    code = (Path(__file__).parent / "offline_worker.js").read_text(encoding="utf-8")
    code = code.replace("__SITE__", json.dumps(cfg, ensure_ascii=False, indent=2).replace("</", "<\\/"), 1)
    return Response(code, media_type="text/javascript; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="solstone-offline-worker.js"'})


@app.get("/api/settings/maintenance")
async def get_maintenance(request: Request):
    auth.require_admin(request)
    return {"maintenance": maintenance.current()}


@app.put("/api/settings/maintenance")
async def set_maintenance(request: Request):
    """Plan maintenance (start, end, message; empty start clears it): a countdown banner on every page, and the
    details handed to the Cloudflare Worker so its page says it's maintenance while everything's off."""
    user = auth.require_admin(request)
    body = await _body(request)
    if body.get("start"):
        try:
            m = await asyncio.to_thread(maintenance.plan, str(body.get("start")), str(body.get("end") or ""), str(body.get("message") or ""))
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
    else:
        m = None
        await asyncio.to_thread(maintenance.clear)
    problem = await maintenance.push(_public_base(request), m)
    auth.audit(user, None, "maintenance", f"{m['start']} to {m['end']}" if m else "cleared")
    return {"maintenance": m, "worker": problem or "ok"}


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


@app.post("/api/posts/images")
async def upload_post_image(request: Request):
    """A picture for a post: the request body (PNG, JPEG, WebP or GIF, under 4 MB). Answers with its address."""
    user = auth.require_admin(request)
    if int(request.headers.get("content-length") or 0) > site.IMAGE_MAX:
        raise HTTPException(413, "Use a picture under 4 MB")
    data = await request.body()
    try:
        url = await asyncio.to_thread(site.save_image, data)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    auth.audit(user, None, "post_image", f"{len(data)} bytes")
    return {"url": url}


@app.get("/api/site/images/unused")
async def unused_images(request: Request):
    """Website → Site details: pictures nothing uses any more (taken out of posts, or their post or vote deleted)."""
    auth.require_admin(request)
    found = await asyncio.to_thread(site.unused_images)
    return {"images": found, "bytes": sum(x["bytes"] for x in found)}


@app.delete("/api/site/images/unused")
async def remove_unused_images(request: Request):
    user = auth.require_admin(request)
    n = await asyncio.to_thread(site.remove_unused_images)
    auth.audit(user, None, "images_removed", f"{n} unused pictures")
    return {"removed": n}


@app.get("/api/public/images/{name}")
async def post_image(name: str):
    found = site.image_file(name)
    if not found:
        raise HTTPException(404)
    return FileResponse(found[0], media_type=found[1], headers={"Cache-Control": "public, max-age=31536000, immutable",
                                                                "X-Content-Type-Options": "nosniff"})


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


def _mods_for_players(srv: S.Server) -> dict | None:
    """What a player's own Minecraft needs to join a modded server: the family modpack's list when it's on (what the
    admin picked), otherwise the server's mods that aren't marked server-only. With the loader and Minecraft version."""
    if not srv.is_java:
        return None
    try:
        pack = modpack.get(srv.id)
        if pack.get("enabled") or pack.get("public_download"):
            mods = [{"name": m["name"], "version": m.get("version") or ""} for m in modpack.server_mods(srv) if m["included"]]
            mods += [{"name": e["title"], "version": e.get("version") or "", "kind": e.get("kind", "mod"),
                      "link": f"https://modrinth.com/{e.get('kind', 'mod')}/{e['slug']}"} for e in pack["extra"]]
        else:
            mods = [{"name": m.get("name") or m.get("id") or m["file"], "version": m.get("version") or ""}
                    for m in S.mods(srv) if m.get("environment") != "server"]
    except Exception as e:
        log.debug("mod list for %s failed: %s", srv.id, e)
        return None
    return {"loader": S.detect_loader(srv), "mc": srv.mc_version, "modpack": bool(pack.get("enabled")), "list": mods[:150],
            "download": f"/api/public/modpack/{quote(srv.id)}.mrpack" if pack.get("public_download") else None}


# ---- asking to join, from the join guide: a notification for the admins with the exact name to let in
_ASK_NAME = re.compile(r"^\.?[A-Za-z0-9_ ]{1,20}$")


@app.post("/api/public/join-request")
async def join_request(request: Request):
    if not site.config()["join_requests"]:
        raise HTTPException(404, "Asking to join isn't turned on")
    body = await _body(request)
    player = " ".join(str(body.get("player") or "").split())
    name = " ".join(str(body.get("name") or "").split())[:40]
    note = str(body.get("note") or "").strip()[:300]
    if not body.get("rules"):
        raise HTTPException(400, "Read the rules, then tick the box to say you will follow them")
    if not _ASK_NAME.match(player):
        raise HTTPException(400, "Type your Minecraft name (or Xbox gamertag) as it shows in the game")
    if body.get("edition") == "bedrock":         # their name on the server: Floodgate's dot, spaces as underscores
        player = "." + player.lstrip(".").replace(" ", "_")
    elif " " in player:
        raise HTTPException(400, "Java names don't have spaces. On Bedrock? Pick Bedrock above")
    player = player[:17]
    public = {s.id: s for s in _public_servers_list() if s.is_java}
    picked = [str(x) for x in (body.get("servers") or []) if str(x) in public]
    if not picked:
        if len(public) > 1:
            raise HTTPException(400, "Pick the server (or servers) you'd like to play on")
        picked = list(public)
    if signup._hit(f"ask:{auth.client_ip(request)}", 3):
        raise HTTPException(429, "You've asked a few times already. An admin will see it soon")
    token = secrets.token_urlsafe(18)              # only they get this: it shows them when they've been let in
    site.add_join_request(player, name, note, hashlib.sha256(token.encode()).hexdigest(), picked)
    where = ", ".join(public[x].display_name for x in picked)
    msg = f"{player} would like to join {where}" + (f" ({name})" if name else "") + (f": {note}" if note else "")
    await notify.send("Asking to join", msg + "\nTap to let them in (Manage → Whitelist).", "wave",
                      click=f"{_public_base(request)}/app#/manage/whitelist")
    return {"ok": True, "token": token, "player": player,
            "message": "Thanks! The admins have your request. This page shows here when you've been let in."}


@app.post("/api/public/join-request/status")
async def join_request_status(request: Request):
    """Has my request been answered? Only the person who asked can tell (with the private token their browser kept),
    so nobody can look up who's been let in. Each server they asked for: in yet or not (however they were let in:
    from Control, the game's console or Crafty)."""
    body = await _body(request)
    token = str(body.get("token") or "")[:64]
    th = hashlib.sha256(token.encode()).hexdigest() if token else ""
    found = site.request_for_token(th)
    if not found:
        return {"state": "unknown"}
    r, finished = found
    if r.get("denied"):
        return {"state": "denied", "player": r["player"], "servers": []}
    await S.registry.refresh()
    public = {s.id: s for s in _public_servers_list() if s.is_java}
    sids = [x for x in (r.get("servers") or []) if x in public] or ([] if finished else list(public)[:1])
    each = [{"name": public[x].display_name, "in": finished or x in (r.get("done") or []) or S.whitelisted(public[x], None, r["player"])}
            for x in sids]
    if not finished and each and all(e["in"] for e in each):
        site.finish_join_request(th)
        finished = True
    state = "in" if finished else "partly" if any(e["in"] for e in each) else "waiting"
    return {"state": state, "player": r["player"], "servers": each}


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
                                str(body.get("username") or ""), password, str(body.get("real_name") or "")[:60])
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
    site.move_guides_to_posts()
    nc = notify.get_config()
    return {"posts": site.posts(drafts=True, limit=200), "site": site.config(), "logo": site.logo_url(), "categories": site.CATEGORIES, "roles": site.ROLES,
            "notify_ready": bool(nc["ntfy_url"] or nc["discord_webhook"])}


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


@app.post("/api/posts/{pid}/move")
async def move_post(pid: int, request: Request):
    """A guide or question one place up or down (its order on the Help page and the home page)."""
    auth.require_admin(request)
    body = await _body(request)
    try:
        return await asyncio.to_thread(site.move, pid, -1 if body.get("up") else 1)
    except LookupError as e:
        raise HTTPException(404, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.delete("/api/posts/{pid}")
async def remove_post(pid: int, request: Request):
    user = auth.require_admin(request)
    if not site.delete(pid):
        raise HTTPException(404, "No such post")
    auth.audit(user, None, "post_delete", str(pid))
    return {"ok": True}


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
    data = await asyncio.to_thread(_recap_payload, srv.id, day)
    return data if _shows_play_time() else _recap_without_durations(data)


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
    data = _recap_without_durations(await asyncio.to_thread(_recap_payload, srv.id, None))     # the public never sees how long
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


# ---- announcements and countdowns
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
        raise HTTPException(404, "Live server info is turned off")
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
            "servers": [{"id": x.id, "name": x.display_name, "bedtime": bool(playtime.rules_for(playtime.config(), x.id))} for x in _board_servers()],
            "shows": [{"id": x["id"], "name": x["name"]} for x in fwshow.shows()], "now": time.time(),
            "status_enabled": _status_cfg()["enabled"]}


@app.put("/api/board")
async def put_board(request: Request):
    user = auth.require_admin(request)
    body = await _body(request)
    cfg = board.save(body)
    auth.audit(user, None, "announcements", f"{len(cfg['items'])} announcements")
    return await get_board(request)


# ---- the world map, drawn from region files (the live section on the home page)
async def _map_server(request: Request, sid: str) -> S.Server:
    if not _may_see_map(request.state.user):
        raise HTTPException(404, "Sign in to see the map")
    srv = await _server(sid)
    if not srv.is_java:
        raise HTTPException(404)
    return srv


@app.get("/api/public/map/{sid}/regions")
async def map_regions(sid: str, request: Request, dim: str = "minecraft:overworld"):
    srv = await _map_server(request, sid)
    regs = await asyncio.to_thread(worldmap.regions, srv.world_dir, dim)
    return {"dim": dim, "size": worldmap.TILE, "regions": regs, "drawn": await asyncio.to_thread(worldmap.drawn_count, srv.id, dim)}


@app.get("/api/public/map/{sid}/tile")
async def map_tile(sid: str, request: Request, x: int, z: int, dim: str = "minecraft:overworld", lod: int = 0):
    """One region's picture, or zoomed out (lod 1..5) one picture for 2**lod x 2**lod regions."""
    srv = await _map_server(request, sid)
    if lod:
        state, path = await asyncio.to_thread(worldmap.overview, srv.id, srv.world_dir, dim, lod, x, z, _assets(srv))
        if state == "none":
            raise HTTPException(404)
        if state == "working":
            return Response(status_code=202, headers={"Retry-After": "3", "Cache-Control": "no-store"})
        partial = worldmap.partial(path)                 # still filling in: the page asks again in a few seconds
        return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-store" if partial else "max-age=60",
                                                                   "X-Map-Partial": "1" if partial else "0"})
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
async def map_check(sid: str, request: Request, dim: str = "minecraft:overworld", x: float | None = None, z: float | None = None):
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
    at = (x, z) if x is not None and z is not None else None
    return await asyncio.to_thread(lambda: worldmap.check(srv.id, srv.world_dir, dim, [] if at else near(), _assets(srv), at))


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


def _with_makers(designs: list[dict], user: auth.User | None) -> list[dict]:
    """Who made each firework, by the name the site shows for them, and which are yours. Never for visitors who
    aren't signed in: makers' names would be a public list of players."""
    if user is None:
        return [{k: v for k, v in d.items() if k != "author"} for d in designs]
    names = auth.shown_names()
    return [{**d, "maker": names.get(str(d.get("author", "")).lower(), d.get("author", "")), "mine": d.get("author") == user.username}
            for d in designs]


@app.get("/api/public/fireworks")
async def public_fireworks(request: Request):
    custom = await asyncio.to_thread(_with_makers, _show_designs(), request.state.user)
    return JSONResponse({**_fireworks_cfg(), "custom": custom, **fwshow.today_state(), "base_shows": fwshow.base_shows_resolved()},
                        headers={"Cache-Control": "no-cache"})


@app.get("/api/fireworks/my-join")
async def my_join_firework(request: Request):
    """The firework that goes off when you join the server (your join firework), if join fireworks are on."""
    user = auth.require_user(request)
    sigs = fwshow.signatures()
    cfg = fwshow.events_cfg()["join"]
    mine = next((sigs[p["name"].lower()] for p in user.players if p["name"].lower() in sigs), "")
    return {"firework": mine, "players": [p["name"] for p in user.players],
            "active": bool(cfg["on"] and cfg["firework"] == "signature")}


@app.put("/api/fireworks/my-join")
async def set_my_join_firework(request: Request):
    """Pick your own join firework (any firework made in the editor), for each of your Minecraft accounts; empty
    goes back to a random one. An admin can still set anyone's in the firework show settings."""
    user = auth.require_user(request)
    if not user.players:
        raise HTTPException(400, "Link your Minecraft account first (My Minecraft accounts, in the menu under your name)")
    fid = str((await _body(request)).get("firework") or "")
    if fid and not fireworks.get(fid):
        raise HTTPException(404, "That firework doesn't exist any more")
    sigs = fwshow.signatures()
    for p in user.players:
        if fid:
            sigs[p["name"].lower()] = fid
        else:
            sigs.pop(p["name"].lower(), None)
    fwshow.save_signatures(sigs)
    auth.audit(user, None, "my_join_firework", fid or "random")
    return await my_join_firework(request)


@app.get("/api/public/fireworks/feed")
async def firework_feed(request: Request, since: int = -1):
    """Fireworks set off by things happening in the game. Player names only for people
    signed in, or when the public status page (which shows them anyway) is on."""
    names = request.state.user is not None or _status_cfg()["enabled"]
    feed = fwshow.feed_since(since, names)
    if not _admin_viewing():      # nothing from a private server, not even that something happened there
        hidden = {x.id for x in S.registry.servers.values() if _private(x) or not _allowed(x)}
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
    items = upcoming.items(names)
    user = request.state.user
    every = [i for i in items if i["key"]] + [p for i in items for p in i.get("parts") or []]
    signed = await asyncio.to_thread(community.signups, [i["key"] for i in every])
    shown = await asyncio.to_thread(lambda: {u["id"]: u["shown"] for u in auth.list_users()})
    for i in every:                                  # who's coming: names for everyone signed in (never on the public page)
        ids = signed.get(i["key"], [])
        i["coming"], i["me"] = len(ids), user.id in ids
        if shown:
            i["who"] = sorted((shown.get(x, "?") for x in ids), key=str.lower)
    return {"items": items, "days": upcoming.DAYS, "now": time.time()}


@app.get("/api/public/upcoming")
async def public_upcoming():
    """What's planned, for the public Events page: no player's name anywhere (nobody's sign-up)."""
    await S.registry.refresh()
    names = {sid: srv.display_name for sid, srv in S.registry.servers.items() if _visible(srv) and not _private(srv)}
    items = [{k: v for k, v in i.items() if k not in ("link", "key")} for i in upcoming.items(names)
             if i.get("server") is None or i["server"] in names.values()]
    for i in items:
        if i.get("parts"):
            i["parts"] = [{k: v for k, v in p.items() if k != "key"} for p in i["parts"]]
    return JSONResponse({"items": items, "days": upcoming.DAYS, "now": time.time()}, headers={"Cache-Control": "no-cache"})


@app.get("/api/fireworks")
async def list_fireworks(request: Request):
    user = request.state.user
    names = await asyncio.to_thread(auth.shown_names)
    return [{**d, "mine": d.get("author") == user.username, "can_edit": _can_edit(user, d),
             "maker": names.get(str(d.get("author", "")).lower(), d.get("author", ""))} for d in fireworks.all_designs()]


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
    return {"per_person": fireworks.per_person(), "mine": fireworks.count_by(user.username), "limited": user.role != "admin",
            "show_per_person": fireworks.show_per_person(), "mine_in_show": fireworks.count_in_show(user.username)}


@app.put("/api/fireworks/limit")
async def set_firework_limit(request: Request):
    user = request.state.user
    if user.role != "admin":
        raise HTTPException(403, "Only admins can change this")
    body = await _body(request)
    try:
        if "per_person" in body:
            fireworks.set_per_person(body["per_person"])
        if "show_per_person" in body:
            fireworks.set_show_per_person(body["show_per_person"])
    except (TypeError, ValueError) as e:
        raise HTTPException(400, "Give a number") from e
    auth.audit(user, None, "firework_limit", f"keep {fireworks.per_person()}, in the show {fireworks.show_per_person()}")
    return {"per_person": fireworks.per_person(), "show_per_person": fireworks.show_per_person()}


@app.post("/api/fireworks")
async def create_firework(request: Request):
    user = request.state.user
    try:
        admin = user.role == "admin"
        d = fireworks.create(await _body(request), user.username, None if admin else fireworks.per_person(),
                             None if admin else fireworks.show_per_person())
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
    cap = fireworks.show_per_person()
    full = user.role != "admin" and body.get("in_show") and not d.get("in_show") and cap \
        and fireworks.count_in_show(d.get("author", "")) >= cap
    if full and set(body) == {"in_show"}:       # just the Show tick: say why it can't
        raise HTTPException(400, f"You already have {cap} fireworks in the show, the most each person can. Take one out of the show first.")
    if full:                                     # saving the whole firework: keep the changes, out of the show
        body["in_show"] = False
    if user.role != "admin":
        body.pop("weight", None)                  # how often it shows is the admins' call
    elif "weight" in body:
        body["weight"] = _weight(body["weight"])
    saved = fireworks.update(fid, body)
    return {**saved, "show_full": True} if full and saved else saved


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


@app.get("/api/settings/players")
async def get_player_settings(request: Request):
    auth.require_admin(request)
    return {"see_map": _players_see_map()}


@app.put("/api/settings/players")
async def put_player_settings(request: Request):
    user = auth.require_admin(request)
    body = await _body(request)
    cfg = {"see_map": bool(body.get("see_map", False))}
    settings_store.save_section("players", cfg)
    auth.audit(user, None, "player_settings", f"see_map={cfg['see_map']}")
    return cfg


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
    typed = str(body.get("username", ""))
    user, token = await asyncio.to_thread(auth.login, request, typed, str(body.get("password", "")))
    auth.audit(user, None, "login", f"as {typed} from {auth.client_ip(request)}" if typed.lower() != user.username.lower()
               else f"from {auth.client_ip(request)}")
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


@app.post("/api/auth/players/start")
async def link_start(request: Request):
    """Link another of your Minecraft accounts: a code is sent to that player in the game, if they're on now."""
    user = auth.require_user(request)
    body = await _body(request)
    await S.registry.refresh()
    servers = [s for s in S.registry.servers.values() if s.is_java and (not _private(s) or user.is_admin)]
    return {"message": await signup.start_link(request, user, str(body.get("player") or ""), servers)}


@app.post("/api/auth/players/finish")
async def link_finish(request: Request):
    user = auth.require_user(request)
    body = await _body(request)
    u = await asyncio.to_thread(signup.finish_link, user, str(body.get("player") or ""), str(body.get("code") or ""))
    auth.audit(user, None, "link_player", ", ".join(p["name"] for p in u.players))
    return {"user": u.public()}


@app.post("/api/auth/players/{uuid}/main")
async def link_main(uuid: str, request: Request):
    """Which of your Minecraft accounts you're shown as on the website (a player's name everywhere)."""
    user = auth.require_user(request)
    mine = next((x for x in user.player_uuids if S.norm_uuid(x) == S.norm_uuid(uuid)), None)
    if not mine:
        raise HTTPException(404, "That player isn't linked to your login")
    u = await asyncio.to_thread(auth.set_main_player, user.id, mine)
    auth.audit(user, None, "main_player", u.shown)
    return {"user": _me(u)}


@app.delete("/api/auth/players/{uuid}")
async def link_remove(uuid: str, request: Request):
    """Unlink one of your own Minecraft accounts (a Player login keeps at least one: it's how it sees anything)."""
    user = auth.require_user(request)
    if S.norm_uuid(uuid) not in {S.norm_uuid(x) for x in user.player_uuids}:
        raise HTTPException(404, "That player isn't linked to your login")
    if user.is_player and len(user.players) <= 1:
        raise HTTPException(400, "Your login needs at least one Minecraft player. Ask an admin to change it")
    u = auth.remove_player(user.id, next(x for x in user.player_uuids if S.norm_uuid(x) == S.norm_uuid(uuid)))
    auth.audit(user, None, "unlink_player", uuid)
    return {"user": u.public()}


@app.post("/api/auth/profile")
async def change_profile(request: Request):
    """Your display name (shown in chat and the activity feed instead of your login)."""
    user = auth.require_user(request)
    body = await _body(request)
    u = await asyncio.to_thread(auth.set_display_name, user.id, str(body.get("display_name") or ""))
    auth.audit(user, None, "display_name", u.shown)
    return {"user": u.public()}


@app.post("/api/auth/use-minecraft-name")
async def use_minecraft_name(request: Request):
    """Sign in with (and be shown as) one of your linked Minecraft names: the old login stops working and everything
    kept under it moves over."""
    user = auth.require_user(request)
    body = await _body(request)
    old = user.username
    u = await asyncio.to_thread(auth.use_player_name, user.id, str(body.get("name") or "") or None)
    auth.audit(u, None, "login_renamed", f"{old} → {u.username}")
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


async def _known_player(typed: str) -> tuple[str, str] | None:
    """(uuid, exact name) for someone who has joined a server, or is on a whitelist (Java names; Floodgate's dot optional)."""
    name = typed.strip().lower()
    if not name:
        return None
    want = {name, "." + name.lstrip("."), name.lstrip(".")}
    await S.registry.refresh()
    for srv in S.registry.servers.values():
        for uu, p in S.known_players(srv).items():
            if p["name"].lower() in want:
                return S.norm_uuid(uu), p["name"]
    for srv in S.registry.servers.values():
        try:
            rows = json.loads((srv.dir / "whitelist.json").read_text()) or []
        except (OSError, ValueError):
            continue
        for r in rows:
            if str(r.get("name", "")).lower() in want and r.get("uuid"):
                return S.norm_uuid(str(r["uuid"])), str(r["name"])
    return None


@app.get("/api/users/players")
async def players_to_link(request: Request):
    """Admins: everyone who has joined a server or is on a whitelist, and the login they're linked to, for linking."""
    auth.require_admin(request)
    await S.registry.refresh()
    seen: dict[str, dict] = {}
    for srv in S.registry.servers.values():
        for uu, p in S.known_players(srv).items():
            seen.setdefault(S.norm_uuid(uu), {"uuid": S.norm_uuid(uu), "name": p["name"]})
        try:
            rows = json.loads((srv.dir / "whitelist.json").read_text()) or []
        except (OSError, ValueError):
            rows = []
        for r in rows:
            if r.get("uuid") and r.get("name"):
                seen.setdefault(S.norm_uuid(str(r["uuid"])), {"uuid": S.norm_uuid(str(r["uuid"])), "name": str(r["name"])})
    for p in seen.values():
        p["linked_to"] = auth.user_for_player(p["uuid"])
        p["bedrock"] = mcname.is_bedrock(p["name"])
    return sorted(seen.values(), key=lambda p: p["name"].lower())


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
    if body.get("add_player"):              # one more Minecraft account (a Java and a Bedrock one, say)
        found = await _known_player(str(body["add_player"]))
        if not found:
            raise HTTPException(400, "No player by that name has joined a server or is on a whitelist")
        u = auth.add_player(uid, found)
    if body.get("remove_player"):
        u = auth.remove_player(uid, str(body["remove_player"]))
    if "servers" in body:                   # the servers this login sees: a list of ids, or null for all of them
        v = body.get("servers")
        u = auth.set_servers(uid, [str(x) for x in v] if isinstance(v, list) else None)
    if "real_name" in body:
        u = auth.set_real_name(uid, str(body.get("real_name") or ""))
    changes = ", ".join(k for k in ("role", "password", "player", "servers", "real_name") if k in body and (body.get(k) or k in ("player", "servers", "real_name")))
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


@app.get("/api/audit/search")
async def audit_search(request: Request, server: str = "", action: str = "", who: str = "", q: str = "", since: float = 0,
                       until: float = 0, failed: bool = False, oldest: bool = False, offset: int = 0, limit: int = 50):
    """Manage → Activity: filtered by server, kind, person, words and dates; newest or oldest first; a page at a time."""
    auth.require_admin(request)
    return auth.audit_search(server_id=server or None, action=action or None, who=who or None, text=q.strip()[:100] or None,
                             since=since or None, until=until or None, failed=failed, oldest_first=oldest, offset=offset, limit=limit)


@app.get("/api/audit/facets")
async def audit_facets(request: Request):
    auth.require_admin(request)
    return auth.audit_facets()


@app.put("/api/audit/keep")
async def audit_keep(request: Request):
    user = auth.require_admin(request)
    try:
        days = auth.set_audit_keep_days(int((await _body(request)).get("days")))
    except (TypeError, ValueError) as e:
        raise HTTPException(400, "Pick how long to keep it") from e
    auth.audit(user, None, "audit_keep", "forever" if not days else f"{days} days")
    return auth.audit_facets()


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


@app.get("/api/servers/{sid}/mods/updates")
async def mod_updates(sid: str, request: Request, force: bool = False):
    """Admins: which mods have a newer build on Modrinth for this server's Minecraft version and loader."""
    auth.require_admin(request)
    return await modupdates.check(await _server(sid), force=force)


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
    return {"enabled": cfg["enabled"], "public_download": cfg["public_download"], "url": url,
            "mrpack": f"/api/servers/{quote(srv.id)}/modpack.mrpack", "command": modpack.prism_command(url) if url else "",
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
    if "public_download" in body:
        cfg["public_download"] = bool(body["public_download"])
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


async def _mrpack_response(srv) -> FileResponse:
    try:
        path = await modpack.mrpack(srv)
    except ValueError as e:
        raise HTTPException(409, str(e)) from e
    except httpx.HTTPError as e:
        raise HTTPException(502, f"Couldn't reach Modrinth to finish the pack: {e}") from e
    return FileResponse(path, media_type="application/x-modrinth-modpack+zip", filename=modpack.mrpack_name(srv))


@app.get("/api/servers/{sid}/modpack.mrpack")
async def admin_mrpack(sid: str, request: Request):
    """The pack as one file to import (admins, to hand to someone, whether or not it's on the website)."""
    auth.require_admin(request)
    return await _mrpack_response(await _server(sid))


@app.get("/api/public/modpack/{sid}.mrpack")
async def public_mrpack(sid: str):
    """The pack on the website, when the admin chose to offer it there (public servers only)."""
    srv = next((s for s in _public_servers_list() if s.id == sid), None)
    if not srv or not modpack.get(srv.id)["public_download"]:
        raise HTTPException(404, "No modpack to download here")
    return await _mrpack_response(srv)


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
async def get_players(sid: str, removed: bool = False):
    """Everyone who has played, minus those taken off the whitelist (admins can ask for them with ?removed=1)."""
    srv = await _server(sid)
    data = await S.players_overview(srv, with_removed=removed and _admin_viewing())
    if _admin_viewing():
        data["removed_count"] = len(S.removed_names(srv))
    if not _shows_play_time():
        data = _no_durations(data)
    see_map = _players_see_map()
    for p in data["players"]:
        if not see_map and not _own(p.get("uuid") or ""):          # a player account doesn't see where anyone else is (unless the map is on for them)
            p.pop("position", None)
            p.pop("dimension", None)
    return data


@app.get("/api/servers/{sid}/players/{uuid}")
async def get_player(sid: str, uuid: str):
    if not _own(uuid):
        raise HTTPException(404, "Player not found")
    data = await S.player_detail(await _server(sid), uuid)
    if data and not _shows_play_time():
        data = _no_durations(data)
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
    if "join_mods" in body:
        body["join_mods"] = True if body["join_mods"] else ""
    if "map_proxy" in body:                  # the web map through Solstone (webmap.py)
        body["map_proxy"] = True if body["map_proxy"] else ""
    if "map_url" in body:
        u = str(body["map_url"] or "").strip()
        if u and not re.fullmatch(r"https?://[^\s/]+(/\S*)?", u):
            raise HTTPException(400, "The map address starts with http:// or https://")
        body["map_url"] = u
    if "join_color" in body:                 # a border colour for its card: #rrggbb, or nothing
        c = str(body["join_color"] or "").strip().lower()
        body["join_color"] = c if re.fullmatch(r"#[0-9a-f]{6}", c) else ""
    for k, n in (("join_address", 80), ("join_bedrock_address", 80), ("join_note", 300), ("join_check", 80)):
        if k in body:
            body[k] = " ".join(str(body[k] or "").split())[:n]
    if "welcome" in body:                    # the message when someone joins (welcome.py)
        body["welcome"] = welcome.clean(body["welcome"])
        settings_store.save_section("welcome_site", _public_base(request))      # for {rules} and {site} in the game
    if "fishing_journal" in body:            # the fishing journal on the website (fishing.journal_on)
        body["fishing_journal"] = True if body["fishing_journal"] else ""
    if "welcome_when" in body:
        body["welcome_when"] = body["welcome_when"] if body["welcome_when"] in welcome.WHEN else "off"
    if "join_bedrock_port" in body:
        try:
            body["join_bedrock_port"] = max(1, min(65535, int(body["join_bedrock_port"]))) if body["join_bedrock_port"] not in ("", None) else ""
        except (TypeError, ValueError):
            raise HTTPException(400, "The Bedrock port is a number, like 19132") from None
    saved = settings_store.update_server(srv.id, body)
    auth.audit(user, srv.id, "settings", ", ".join(sorted(k for k in body if k != "rcon_password")) +
               (", rcon_password" if "rcon_password" in body else ""))
    safe = {k: v for k, v in saved.items() if k != "rcon_password"}
    safe["rcon_password_set"] = "rcon_password" in saved
    return safe


@app.get("/api/solstone-backups")
async def list_self_backups(request: Request):
    auth.require_admin(request)
    return {"folder": str(selfbackup.folder()), "keep": selfbackup.KEEP, "every_hours": selfbackup.EVERY_HOURS,
            "backups": selfbackup.backups()}


@app.post("/api/solstone-backups")
async def make_self_backup(request: Request):
    user = auth.require_admin(request)
    try:
        b = await asyncio.to_thread(selfbackup.make)
    except OSError as e:
        raise HTTPException(500, f"Couldn't write the backup: {e}") from e
    auth.audit(user, None, "solstone_backup", b["name"])
    return b


@app.get("/api/solstone-backups/{name}")
async def download_self_backup(name: str, request: Request):
    """A backup holds every account (passwords hashed) and the RCON passwords: admins only."""
    auth.require_admin(request)
    p = selfbackup.path_of(name)
    if not p:
        raise HTTPException(404, "No such backup")
    return FileResponse(p, media_type="application/zip", filename=p.name)


@app.post("/api/servers/{sid}/clear")
async def clear_saved(sid: str, request: Request):
    """Clear what Solstone kept about a server (chat, activity, play history, map pictures...). The game isn't touched."""
    user = auth.require_admin(request)
    srv = await _server(sid)
    kinds = {str(k) for k in ((await _body(request)).get("what") or [])}
    unknown = kinds - set(db.CLEAR_KINDS) - {"map"}
    if not kinds or unknown:
        raise HTTPException(400, "Pick what to clear")
    out = await asyncio.to_thread(db.clear_server, srv.id, kinds)
    if "map" in kinds:
        out["map"] = await asyncio.to_thread(worldmap.clear_tiles, srv.id)
    if "play" in kinds:
        welcomed = settings_store.load().get("welcomed") or {}
        if welcomed.pop(srv.id, None) is not None:
            settings_store.save_section("welcomed", welcomed)
    _board_cache.pop(srv.id, None)
    auth.audit(user, srv.id, "clear_saved", ", ".join(sorted(kinds)))
    return {"ok": True, "cleared": out}


@app.post("/api/servers/{sid}/welcome/try")
async def try_welcome(sid: str, request: Request):
    """Send a welcome message (as typed, saved or not) to one player who's on now, to see how it looks."""
    user = auth.require_admin(request)
    srv = await _server(sid)
    body = await _body(request)
    player, text = str(body.get("player") or ""), welcome.clean(body.get("text") or "")
    if not text:
        raise HTTPException(400, "Type a message first")
    if not mcname.is_name(player) or player.lower() not in {n.lower() for n in (await S.online_players(srv))[0]}:
        raise HTTPException(400, "Pick someone who's on the server now")
    for cmd in welcome.commands(player, welcome.fill(text, player, srv.display_name)):
        await control.run(srv, cmd)
    auth.audit(user, srv.id, "welcome", f"tried on {player}")
    return {"ok": True}


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
    gone = S.removed_names(srv)                  # taken off the whitelist: left out of who played
    if not _shows_play_time():
        daily = [{"date": d["date"], "players": {n: 1 for n, v in d["players"].items() if v > 0 and n.lower() not in gone}}
                 for d in db.daily_playtime(srv.id, days)]
        return {"daily": daily, "sessions": [], "durations": False,
                "recorder_since": (db.q("SELECT MIN(ts) AS t FROM metrics WHERE server_id=?", (srv.id,))[0]["t"])}
    return {
        "durations": True,
        "daily": [{**d, "players": {n: v for n, v in d["players"].items() if n.lower() not in gone}} for d in db.daily_playtime(srv.id, days)],
        "sessions": [x for x in db.sessions(srv.id, limit=40) if (x.get("player") or "").lower() not in gone],
        "recorder_since": (db.q("SELECT MIN(ts) AS t FROM metrics WHERE server_id=?", (srv.id,))[0]["t"]),
    }


def _turned_away(srv: S.Server, days: int = 14) -> list[dict]:
    """Who the whitelist turned away lately (newest first, once each), leaving out anyone let in since."""
    listed = {n.lower() for n in control.whitelist_names(srv)}
    seen: dict[str, dict] = {}
    for e in db.events(srv.id, ["blocked"], None, 200):
        if e["ts"] < time.time() - days * 86400:
            break
        n = e["player"] or ""
        if n and n.lower() not in seen and n.lower() not in listed and n.lower().lstrip(".") not in listed:
            seen[n.lower()] = {"name": n, "ts": e["ts"], "bedrock": mcname.is_bedrock(n)}
    return list(seen.values())


def _open_requests(servers: list) -> list[dict]:
    """Asks to join still waiting on an admin: not yet on the whitelist of every server they asked for."""
    by_id = {s.id: s for s in servers}
    reqs = []
    for r in site.join_requests()[::-1]:
        want = [x for x in (r.get("servers") or list(by_id)) if x in by_id]
        each = [{"id": x, "name": by_id[x].display_name,
                 "in": x in (r.get("done") or []) or S.whitelisted(by_id[x], None, r["player"])} for x in want]
        if each and all(e["in"] for e in each):
            continue                                  # done everywhere: their own page says so
        reqs.append({**{k: r.get(k) for k in ("player", "name", "note", "ts")}, "bedrock": mcname.is_bedrock(r["player"]), "servers": each})
    return reqs


# ---- forgetting a player (Manage → Whitelist → Removing a player): forget.py
@app.get("/api/players/forget")
async def forget_preview(name: str, request: Request):
    """What forgetting this player would remove (nothing is changed)."""
    auth.require_admin(request)
    await S.registry.refresh()
    p = await asyncio.to_thread(forget.plan, name)
    if not p:
        raise HTTPException(400, "Type a Minecraft name")
    p["online"] = await _online_on(p["names"])
    return p


async def _online_on(names: list[str]) -> list[str]:
    """Servers where any of these names is playing right now."""
    out = []
    for srv in [s for s in S.registry.servers.values() if s.is_java]:
        try:
            on, _src = await S.online_players(srv)
        except Exception:
            continue
        if any(n.lower() in names for n in on):
            out.append(srv.display_name)
    return out


@app.post("/api/players/forget")
async def forget_player(request: Request):
    """Forget a player for good. Guarded: their exact name typed again, a server backup confirmed, not online
    anywhere; a Solstone backup is made first."""
    user = auth.require_admin(request)
    body = await _body(request)
    name = str(body.get("name") or "").strip()
    if not name or str(body.get("confirm") or "").strip() != name:
        raise HTTPException(400, "Type the player's name exactly, to be sure")
    if not body.get("backed_up"):
        raise HTTPException(400, "Take a server backup first, and tick the box to say you have")
    await S.registry.refresh()
    p = await asyncio.to_thread(forget.plan, name)
    if not p:
        raise HTTPException(400, "Type a Minecraft name")
    on = await _online_on(p["names"])
    if on:
        raise HTTPException(409, f"{name} is playing on {', '.join(on)} right now. Wait until they've left.")
    done = await asyncio.to_thread(forget.wipe, name)
    auth.audit(user, None, "forget_player", f"{name}: {done['total']} things removed ({', '.join(done['names'])})")
    return done


@app.get("/api/whitelist")
async def whitelist_overview(request: Request):
    """Manage → Whitelist: everyone who asked to join (with each server they asked for, in or not yet), everyone the
    whitelist turned away lately, and each server's list, all in one place."""
    auth.require_admin(request)
    await S.registry.refresh()
    servers = [s for s in S.registry.servers.values() if s.is_java and not s.settings.get("hidden")]
    out_servers = [{"id": s.id, "name": s.display_name, "private": _private(s), "enabled": s.props.get("white-list", "false") == "true",
                    "whitelist": control.whitelist_names(s)} for s in servers]
    reqs = _open_requests(servers)
    blocked: dict[str, dict] = {}
    for s in servers:
        for b in _turned_away(s):
            e = blocked.setdefault(b["name"].lower(), {"name": b["name"], "bedrock": b["bedrock"], "ts": b["ts"], "servers": []})
            e["ts"] = max(e["ts"], b["ts"])
            e["servers"].append({"id": s.id, "name": s.display_name})
    return {"servers": out_servers, "requests": reqs, "blocked": sorted(blocked.values(), key=lambda b: -b["ts"])}


@app.post("/api/whitelist/deny")
async def deny_request(request: Request):
    """Say no to someone who asked to join: off the Asked to join list, and their page says it wasn't accepted."""
    user = auth.require_admin(request)
    player = str((await _body(request)).get("player") or "")
    if not site.deny_join_request(player):
        raise HTTPException(404, "That request isn't there any more")
    auth.audit(user, None, "join_request_denied", player)
    return {"ok": True}


@app.get("/api/servers/{sid}/events")
async def events(sid: str, types: str = "", player: str = "", limit: int = 100, before: float | None = None):
    srv = await _server(sid)
    tlist = [t for t in types.split(",") if t] or None
    evs = db.events(srv.id, tlist, player or None, limit, before)
    u = _viewer.get()
    if not (u and u.is_admin):                     # who the whitelist turned away is for admins (Control)
        evs = [e for e in evs if e["type"] != "blocked"]
    return evs


@app.get("/api/servers/{sid}/timeline")
async def timeline(sid: str, player: str = "", before: float | None = None, sessions: int = 20, chat: bool = True):
    srv = await _server(sid)
    data = db.timeline(srv.id, player or None, before, max(1, min(sessions, 100)), chat)
    return data if _shows_play_time() else _no_durations(data)


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
    if not _shows_play_time():             # which days they played, not for how long
        return {"daily": [{"date": d["date"], "played": sum(d["players"].values()) > 0} for d in daily], "sessions": [],
                "events": db.events(srv.id, None, p["name"], 60), "durations": False}
    return {
        "daily": [{"date": d["date"], "seconds": sum(d["players"].values())} for d in daily],
        "sessions": db.sessions(srv.id, p["name"], limit=30),
        "events": db.events(srv.id, None, p["name"], 60),
        "durations": True,
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


# ------------------------------------------------------------------ votes, event sign-ups, messages (community.py)
@app.get("/api/community/votes")
async def community_votes(request: Request):
    user = request.state.user
    me = community.voter_key(user)
    def build():
        ps = community.polls(40)
        return {"open": [community.view(p, me, user.role == "admin") for p in ps if community.is_open(p)],
                "closed": [community.view(p, me, user.role == "admin") for p in ps if not community.is_open(p)][:10]}
    return await asyncio.to_thread(build)


@app.post("/api/community/votes/{pid}")
async def community_vote(pid: int, request: Request):
    user = request.state.user
    body = await _body(request)
    try:
        p = await asyncio.to_thread(community.vote, pid, community.voter_key(user), str(body.get("option") or ""))
    except KeyError:
        raise HTTPException(404, "No such vote") from None
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    return await asyncio.to_thread(community.view, p, community.voter_key(user), user.role == "admin")


@app.post("/api/community/signup")
async def community_signup(request: Request):
    user = request.state.user
    body = await _body(request)
    try:
        await asyncio.to_thread(community.sign_up, str(body.get("event") or ""), user.id, bool(body.get("coming")))
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    return {"ok": True}


@app.get("/api/community/unread")
async def community_unread(request: Request):
    user = request.state.user
    requests = 0
    if user.role == "admin":                          # asks to join waiting on an admin count too
        await S.registry.refresh()
        servers = [s for s in S.registry.servers.values() if s.is_java and not s.settings.get("hidden")]
        requests = len(await asyncio.to_thread(_open_requests, servers))
    return {"mine": await asyncio.to_thread(community.unread, user.id),
            "admin": await asyncio.to_thread(community.unread_admin) if user.role == "admin" else 0, "requests": requests}


@app.get("/api/community/messages")
async def community_my_messages(request: Request):
    user = request.state.user
    return {"threads": await asyncio.to_thread(community.threads_for, user.id), "kinds": community.KINDS}


def _may_read(user: auth.User, t: dict | None) -> dict:
    if not t or (t["user_id"] != user.id and user.role != "admin"):
        raise HTTPException(404, "No such message")
    return t


@app.get("/api/community/messages/{tid}")
async def community_thread(tid: int, request: Request):
    user = request.state.user
    t = _may_read(user, await asyncio.to_thread(community.thread, tid))
    if t["user_id"] == user.id:
        await asyncio.to_thread(community.mark_read, tid, False)
    if user.role == "admin":                         # an admin reading it has read it for the admins
        await asyncio.to_thread(community.mark_read, tid, True)
    who = auth.get_user(t["user_id"])
    return {**t, "with": who.shown if who else "?", "messages": await asyncio.to_thread(community.thread_messages, tid)}


@app.post("/api/community/messages")
async def community_send(request: Request):
    """A player writes to the admins: a new message (an idea, something wrong, a question)."""
    user = request.state.user
    if user.role == "admin":
        raise HTTPException(400, "You're an admin: players' messages are in Manage → Messages, and you write to them from there")
    body = await _body(request)
    if await asyncio.to_thread(community.recent_from, user.id) >= 10:
        raise HTTPException(429, "That's a lot of messages! Wait a little before sending more.")
    kind = body.get("kind") if body.get("kind") in community.KINDS else "other"
    typed = community._line(body.get("subject"), community.SUBJECT_MAX)
    subject = f"{community.KINDS[kind]}: {typed}" if typed else community.KINDS[kind]
    try:
        tid = await asyncio.to_thread(community.start, user.id, "suggestion", subject, body.get("body"), False, user.shown)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    votegame.new_message(user.shown, subject)
    return {"id": tid}


@app.post("/api/community/messages/{tid}")
async def community_reply(tid: int, request: Request):
    user = request.state.user
    t = _may_read(user, await asyncio.to_thread(community.thread, tid))
    admin = user.role == "admin"
    if not admin and await asyncio.to_thread(community.recent_from, user.id) >= 10:
        raise HTTPException(429, "That's a lot of messages! Wait a little before sending more.")
    body = await _body(request)
    try:
        await asyncio.to_thread(community.reply, tid, body.get("body"), admin, user.shown)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    if not admin:
        votegame.new_message(user.shown, t["subject"])
    return {"ok": True}


@app.delete("/api/community/messages/{tid}")
async def community_remove(tid: int, request: Request):
    """A player removes a conversation from their list (the admins keep it). An admin deletes it for everyone."""
    user = request.state.user
    t = _may_read(user, await asyncio.to_thread(community.thread, tid))
    if user.role == "admin":
        await asyncio.to_thread(community.delete_thread, tid)
        auth.audit(user, None, "message_delete", t["subject"])
    else:
        await asyncio.to_thread(community.hide_for_user, tid)
    return {"ok": True}


@app.post("/api/community/admin/messages/{tid}/archive")
async def admin_message_archive(tid: int, request: Request):
    auth.require_admin(request)
    if not await asyncio.to_thread(community.thread, tid):
        raise HTTPException(404, "No such message")
    body = await _body(request)
    await asyncio.to_thread(community.set_archived, tid, bool(body.get("archived", True)))
    return {"ok": True}


@app.get("/api/community/admin/votes")
async def admin_votes(request: Request):
    user = auth.require_admin(request)
    return [community.view(p, community.voter_key(user), True) for p in await asyncio.to_thread(community.polls, 100)]


@app.post("/api/community/admin/votes")
async def admin_vote_create(request: Request):
    user = auth.require_admin(request)
    try:
        p = await asyncio.to_thread(community.create_poll, await _body(request))
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    auth.audit(user, None, "vote_create", p["question"])
    return p


@app.put("/api/community/admin/votes/{pid}")
async def admin_vote_update(pid: int, request: Request):
    user = auth.require_admin(request)
    try:
        p = await asyncio.to_thread(community.update_poll, pid, await _body(request))
    except KeyError:
        raise HTTPException(404, "No such vote") from None
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    auth.audit(user, None, "vote_edit", p["question"])
    return p


@app.post("/api/community/admin/votes/{pid}/close")
async def admin_vote_close(pid: int, request: Request):
    user = auth.require_admin(request)
    p = await asyncio.to_thread(community.close_now, pid)
    if not p:
        raise HTTPException(404, "No such vote, or it's closed already")
    await S.registry.refresh()
    await votegame.closed(p, list(S.registry.servers.values()))
    auth.audit(user, None, "vote_close", p["question"])
    return {"ok": True, "result": community.result_text(p)}


@app.delete("/api/community/admin/votes/{pid}")
async def admin_vote_delete(pid: int, request: Request):
    user = auth.require_admin(request)
    await asyncio.to_thread(community.delete_poll, pid)
    auth.audit(user, None, "vote_delete", str(pid))
    return {"ok": True}


@app.get("/api/community/admin/messages")
async def admin_messages(request: Request):
    auth.require_admin(request)
    def build():
        shown = {u["id"]: u["shown"] for u in auth.list_users()}
        return {"threads": [{**t, "with": shown.get(t["user_id"], "?")} for t in community.all_threads()],
                "players": sorted(({"id": u["id"], "name": u["shown"]} for u in auth.list_users() if u["role"] == "player"),
                                  key=lambda x: x["name"].lower())}
    return await asyncio.to_thread(build)


@app.post("/api/community/admin/messages")
async def admin_message_send(request: Request):
    """An admin writes to one or more players (or all of them)."""
    user = auth.require_admin(request)
    body = await _body(request)
    to = body.get("to")
    players = [u["id"] for u in auth.list_users() if u["role"] == "player"]
    ids = players if to == "all" else [int(x) for x in (to or []) if str(x).isdigit() and int(x) in players]
    if not ids:
        raise HTTPException(400, "Pick who it's for")
    try:
        for uid in ids:
            await asyncio.to_thread(community.start, uid, "message", body.get("subject"), body.get("body"), True, user.shown)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    auth.audit(user, None, "message_send", f"{len(ids)} player(s): {community._line(body.get('subject'), 80)}")
    return {"sent": len(ids)}


# ------------------------------------------------------------------ play time (bedtimes and screen time)
def _playtime_view() -> dict:
    cfg = playtime.config()
    servers = list(S.registry.servers.values())
    known: dict[str, str] = {}
    for srv in servers:
        for pl in S.known_players(srv).values():
            known.setdefault(pl["name"].lower(), pl["name"])
    played = playtime.totals_by_person(cfg, playtime.today_totals([x.id for x in servers]))
    rows = []
    for person in playtime.people(list(known.values())):
        r = playtime.row_for(cfg, person["key"], person["names"]) or {"bedtime": True, "limit": 0, "weekend_limit": 0}
        rows.append({**person, **r, "today": played.get(person["key"], 0)})
    return {**cfg, "rows": rows, "servers": [{"id": x.id, "name": x.display_name, "java": x.is_java} for x in servers],
            "banner": board.config()["bedtime"], "notify_set": playtime.notify_channels()}


@app.get("/api/settings/nudge")
async def get_nudge(request: Request):
    """Admins: the reminders in the game about what's waiting on the website (nudge.py)."""
    auth.require_admin(request)
    return {**nudge.config(), "defaults": nudge.DEFAULTS}


@app.get("/api/settings/optin")
async def get_optin(request: Request):
    """Admins: joining events in the game, the countdown alerts, and every message about them (optin.py)."""
    auth.require_admin(request)
    return {**optin.config(), "defaults": optin.DEFAULTS, "labels": optin.LABELS, "choices": optin.ALERT_CHOICES}


@app.put("/api/settings/optin")
async def put_optin(request: Request):
    user = auth.require_admin(request)
    cfg = optin.save(await _body(request))
    settings_store.save_section("welcome_site", _public_base(request))      # for {site} in the game
    auth.audit(user, None, "optin_settings", "")
    return {**cfg, "defaults": optin.DEFAULTS, "labels": optin.LABELS, "choices": optin.ALERT_CHOICES}


@app.put("/api/settings/nudge")
async def put_nudge(request: Request):
    user = auth.require_admin(request)
    cfg = nudge.save(await _body(request))
    settings_store.save_section("welcome_site", _public_base(request))      # for {site} in the game
    auth.audit(user, None, "nudge_settings", "")
    return {**cfg, "defaults": nudge.DEFAULTS}


@app.get("/api/settings/playtime")
async def get_playtime(request: Request):
    """Admins: bedtimes, screen-time limits and each person's settings (with today's time played)."""
    auth.require_admin(request)
    await S.registry.refresh()
    return await asyncio.to_thread(_playtime_view)


@app.put("/api/settings/playtime")
async def put_playtime(request: Request):
    user = auth.require_admin(request)
    body = await _body(request)
    cur = playtime.config()
    if isinstance(body.get("people"), dict):          # the rows sent replace those people's settings
        body["people"] = {**cur["people"], **body["people"]}
    await asyncio.to_thread(playtime.save, {**cur, **{k: v for k, v in body.items() if k != "banner"}})
    if isinstance(body.get("banner"), dict):
        board.save({"bedtime": body["banner"]})
    auth.audit(user, None, "playtime_settings", ", ".join(sorted(body)))
    await S.registry.refresh()
    return await asyncio.to_thread(_playtime_view)


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
        "blocked": _turned_away(srv),
        "asked": [r for r in site.join_requests()[::-1] if site.wants(r, srv.id) and srv.id not in (r.get("done") or [])
                  and not S.whitelisted(srv, None, r["player"])] if srv.is_java else [],
        "bedtime": playtime.rules_for(playtime.config(), srv.id),
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
    return {"kinds": challenges.kinds(), "items": eventgroups.tag(optin.annotate("contest", challenges.list_for(srv.id))), "gifts": challenges.gifts_for(srv.id),
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


# ---- events: a named lineup of contests, races and games, one after another (eventgroups.py)
def _eg_call(fn, *a):
    try:
        return fn(*a)
    except KeyError:
        raise HTTPException(404, "Event not found") from None
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.get("/api/servers/{sid}/eventgroups")
async def list_eventgroups(sid: str, request: Request):
    auth.require_admin(request)
    srv = await _server(sid)
    gs = eventgroups.list_for(srv.id)
    st = optin._state()
    for g in gs:                                   # who has joined each challenge so far (in the game)
        for p in g["parts"]:
            if p["ref"] and g["optin"]:
                p["joined"] = optin.joined(f"{p['type']}:{p['ref']}", st)
    return {"groups": gs, "now": time.time()}


@app.post("/api/servers/{sid}/eventgroups")
async def add_eventgroup(sid: str, request: Request):
    user = auth.require_admin(request)
    srv = await _server(sid)
    g = _eg_call(eventgroups.create, srv.id, await _body(request))
    auth.audit(user, srv.id, "event_add", g["title"])
    return g


@app.put("/api/servers/{sid}/eventgroups/{gid}")
async def put_eventgroup(sid: str, gid: str, request: Request):
    user = auth.require_admin(request)
    srv = await _server(sid)
    g = _eg_call(eventgroups.update, srv.id, gid, await _body(request))
    auth.audit(user, srv.id, "event_change", g["title"])
    return g


@app.post("/api/servers/{sid}/eventgroups/{gid}/items")
async def add_eventgroup_items(sid: str, gid: str, request: Request):
    auth.require_admin(request)
    srv = await _server(sid)
    return _eg_call(eventgroups.add_items, srv.id, gid, await _body(request))


@app.put("/api/servers/{sid}/eventgroups/{gid}/items/{iid}")
async def put_eventgroup_item(sid: str, gid: str, iid: str, request: Request):
    auth.require_admin(request)
    srv = await _server(sid)
    return _eg_call(eventgroups.change_item, srv.id, gid, iid, await _body(request))


@app.delete("/api/servers/{sid}/eventgroups/{gid}")
async def delete_eventgroup(sid: str, gid: str, request: Request):
    """Call an event off (whatever of it is on now stops) or, once it's over, take it off the list."""
    user = auth.require_admin(request)
    srv = await _server(sid)
    for kind, rid in _eg_call(eventgroups.running_refs, srv.id, gid):
        await {"contest": challenges.cancel, "race": races.cancel, "game": games.cancel}[kind](srv, rid)
    if not eventgroups.remove(srv.id, gid):
        raise HTTPException(404, "Event not found")
    auth.audit(user, srv.id, "event_remove", gid)
    return {"ok": True}


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
    user = auth.require_user(request)
    srv = await _server(sid)
    sessions = await asyncio.to_thread(adventures.sessions, srv.id, max(1, min(365, days)))
    if user.is_player:                         # a player sees the adventures they were in
        mine = {p["name"].lower() for p in user.players}
        sessions = [s for s in sessions if mine & {n.lower() for n in s["players"]} and not s["hidden"]]
    return {"sessions": sessions}


@app.get("/api/servers/{sid}/adventures/timeline")
async def adventures_timeline(sid: str, request: Request, start: float, end: float):
    user = auth.require_user(request)
    srv = await _server(sid)
    data = await asyncio.to_thread(adventures.timeline, srv.id, start, end)
    if user.is_player:
        mine = {p["name"].lower() for p in user.players}
        if not mine & {n.lower() for n in await asyncio.to_thread(adventures._players_between, srv.id, data["start"], data["end"])}:
            raise HTTPException(404, "Not one of your adventures")
        # their own trail and lines; everyone else's only what's public anyway (joins, deaths, advancements,
        # contests, fish), and where they went only when players can see the map. Never anyone else's chat.
        public = {"join", "leave", "death", "advancement", "challenge", "race", "fish", "bigfish", "game"}
        data["events"] = [e for e in data["events"] if (e["player"] or "").lower() in mine or e["type"] in public]
        if not _players_see_map():
            data["trails"] = {n: t for n, t in data["trails"].items() if n.lower() in mine}
    return data


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
    if not mcname.is_name(player):
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
    if action not in ("install", "reload"):
        raise HTTPException(404)
    if not srv.rcon_conf():
        raise HTTPException(409, "Turn on RCON for this server first")
    try:
        st = await (fishing.install(srv) if action == "install" else fishing.reload(srv))
    except RuntimeError as e:
        raise HTTPException(502, f"The server didn't answer: {e}") from e
    auth.audit(user, srv.id, f"fishing:{action}", f"pack version {st.get('version')}")
    return {**fishing.status(srv), "listed": st.get("listed"), "reload_reply": st.get("reload_reply", ""), "problems": st.get("problems", []),
            "started_by_solstone": st.get("started_by_solstone", False), "load_reply": st.get("load_reply", "")}


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
    return {"runs": eventgroups.tag(optin.annotate("game", games.runs_for(srv.id))), "rcon": bool(srv.rcon_conf()), "pack": pack, "pack_needed": 2, "pack_needed_spleef": 10,
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
    runs = eventgroups.tag(optin.annotate("race", races.runs_for(srv.id)))
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
    """The live status is on the home page now; old links and wall screens land there."""
    return RedirectResponse("/#live", status_code=301)


# ---- the web map (BlueMap etc.) through Solstone: see webmap.py
def _may_see_web_map(user: auth.User | None, srv: S.Server | None) -> bool:
    if user is None or srv is None or not srv.settings.get("map_url") or not srv.settings.get("map_proxy"):
        return False
    if srv.settings.get("hidden") or (_private(srv) and not user.is_admin):
        return False
    token = _viewer.set(user)
    try:
        allowed = _allowed(srv)
    finally:
        _viewer.reset(token)
    return allowed and (not user.is_player or _players_see_map())


@app.get("/api/servers/{sid}/webmap")
async def web_map_pass(sid: str, request: Request):
    """Where to open this server's web map through Solstone: an address with a pass for whoever's asking."""
    user = auth.require_user(request)
    srv = await _server(sid)
    if not _may_see_web_map(user, srv):
        raise HTTPException(404, "No web map here")
    return {"url": f"/map/{quote(srv.id)}/{webmap.make_pass(user.id, srv.id)}/"}


@app.api_route("/map/{sid}/{token}", methods=["GET", "HEAD"], include_in_schema=False)
async def web_map_root(sid: str, token: str):
    return RedirectResponse(f"/map/{quote(sid)}/{quote(token)}/", status_code=307)


@app.api_route("/map/{sid}/{token}/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
async def web_map(sid: str, token: str, path: str, request: Request):
    uid = webmap.read_pass(token, sid)
    user = await asyncio.to_thread(auth.get_user, uid) if uid is not None else None
    srv = await S.registry.get(sid)
    if not _may_see_web_map(user, srv):
        return Response("This map link has run out, or isn't yours. Open the map again from the World tab.",
                        status_code=403, media_type="text/plain", headers={"Content-Security-Policy": webmap.SANDBOX_CSP})
    return await webmap.proxy(srv.settings["map_url"], path, request, f"/map/{quote(sid)}/{quote(token)}/")


@app.get("/", include_in_schema=False)
@app.get("/news", include_in_schema=False)
@app.get("/guides", include_in_schema=False)
@app.get("/guides/{slug}", include_in_schema=False)
@app.get("/faq", include_in_schema=False)
@app.get("/help", include_in_schema=False)
@app.get("/events", include_in_schema=False)
@app.get("/post/{slug}", include_in_schema=False)
async def home_page(request: Request, slug: str = ""):
    """The public website: home, news, guides, FAQ and posts. No sign-in."""
    return HTMLResponse(await _page_for("home.html", request), headers={"Cache-Control": "no-cache", "Vary": "Cookie"})


@app.get("/app", include_in_schema=False)
@app.get("/app/{full_path:path}", include_in_schema=False)
async def app_page(request: Request, full_path: str = ""):
    """The signed-in app (it routes by #/... after this)."""
    return HTMLResponse(await _page_for("index.html", request), headers={"Cache-Control": "no-cache", "Vary": "Cookie"})


@app.get("/{full_path:path}", include_in_schema=False)
async def not_found_page(full_path: str):
    if full_path.startswith("api/"):
        raise HTTPException(404)
    return HTMLResponse(_page("home.html"), status_code=404, headers={"Cache-Control": "no-cache"})


ASSET_NAMES = ("app.css", "sky.js", "showbar.js", "hud.js", "board.js", "recap.js", "login.js", "app.js", "history.js", "control.js", "play.js", "editor.js", "fwsettings.js", "announce.js", "live.js", "home.js", "postfmt.js", "guides.js", "website.js", "adventures.js", "playtime.js", "community.js")


@functools.cache
def _asset_stamp() -> str:
    """The app's own files only change with a new build (a new container), so this is worked out once."""
    files = [STATIC / n for n in ASSET_NAMES]
    return format(int(max(f.stat().st_mtime for f in files if f.exists())), "x")


@functools.cache
def _template(name: str) -> str:
    html = (STATIC / name).read_text(encoding="utf-8")
    for n in ASSET_NAMES:
        html = html.replace(f"/static/{n}\"", f"/static/{n}?v={_asset_stamp()}\"")
    return html


def _html_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#39;")


def _page(name: str) -> str:
    """An HTML page with ?v= on the CSS/JS links so browsers pick up new versions after an update."""
    return _template(name).replace("{{VERSION}}", VERSION).replace("{{SITE_NAME}}", _html_escape(site.config()["name"])).replace("{{SITE_LOGO}}", _html_escape(site.logo_url()))


async def _page_for(name: str, request: Request) -> str:
    """The page with the top bar already right for whoever's signed in: Events, Servers (and Manage for admins)
    and their name, instead of those popping in a moment later. Only what the bar shows; every API route still
    checks the sign-in itself."""
    html, user = await asyncio.to_thread(lambda: (_page(name), auth.user_from_request(request)))   # off the main loop
    if not user:
        return html
    html = html.replace(" data-signed-in hidden", " data-signed-in").replace(" data-signed-out>", " data-signed-out hidden>")
    if user.role == "admin":
        html = html.replace(" data-admin hidden", " data-admin")
    return html.replace('<a class="btn sm" href="/app" id="hp-signin">Sign in</a>',       # the home page's corner
                        f'<a class="btn sm" href="/app" id="hp-signin">👤 {_html_escape(user.shown)}</a>')
