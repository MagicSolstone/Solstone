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

from . import adventures, auth, backups, forget, board, challenges, community, control, db, eventgroups, fishing, fishpack, gamemsg, remote, connections, games, holidaygifts, kits, stacks, storage, mcname, modpack, modupdates, races, fireworks, fwshow, guard, notify, nudge, optin, playtime, recap, selfcheck, selfbackup, signup, site, skins, tide, upcoming, votegame, watchdog, maintenance, movehistory, servercheck, welcome, worldmap, xboxwatch, serverstats, traffic
from . import reading, twostep
from . import servers as S
from . import settings_store
from .rcon import RconError
from .recorder import recorder
from .assets import assets_for, safe_texture_path, store
from .config import config

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("solstone")
STATIC = Path(__file__).parent / "static"
VERSION = "1.21.4"


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
    await connections.close_all()


app = FastAPI(title="Solstone", version=VERSION, lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=1024)

PUBLIC_API = {"/api/health", "/api/auth/login", "/api/auth/login/code"}

# Scripts only from Solstone itself (no inline script, so injected HTML can't run code).
# Inline style attributes are used throughout, so styles allow them. Skins come from
# mc-heads.net.
CSP = "; ".join([
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob: https://mc-heads.net https://cdn.modrinth.com",      # Modrinth icons (family modpack)
    "media-src 'self' blob:",
    "font-src 'self'",
    "connect-src 'self'",
    "frame-src 'none'",
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
    "/api/servers/{sid}/players/{uuid}/travels": {"GET"},   # their own only (see _own)
    "/api/servers/{sid}/leaderboard": {"GET"},
    "/api/servers/{sid}/stats/history": {"GET"},        # the whole server's totals over time (no names)
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


# With "Players can see the map" on (Manage → Players), players also get the World tab: the map, with where everyone is.
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


_SUMMARY_FOR_PLAYERS = ("id", "name", "running", "crashed", "started", "cpu", "cpu_cores", "mem", "mem_percent", "world_size", "version", "motd",
                        "max_players", "online", "has_icon", "loader", "game", "game_label", "perf", "fishing", "error")


def _for_player(summary: dict) -> dict:
    """A server's summary without the running of it (folders, ports, RCON, backups, the web map)."""
    u = _viewer.get()
    if u is None or not u.is_player:
        return summary
    out = {k: summary[k] for k in _SUMMARY_FOR_PLAYERS if k in summary} | {"folder_found": True}
    if _players_see_map():
        out |= {"player_map": True}
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
    # counted for Manage → Solstone → Website traffic (who, what, how much, how quick): traffic.py
    if not path.endswith(("/stream", "/sse")) and path != "/api/health":
        try:
            user = getattr(request.state, "user", None)
            if user is None and not path.startswith("/api/") and request.cookies.get(auth.COOKIE):
                user = await asyncio.to_thread(auth.user_from_request, request)
            traffic.record(path, user, auth.client_ip(request), int(response.headers.get("content-length") or 0),
                           int(request.headers.get("content-length") or 0), took)
            if took >= 1:          # which route was slow (its pattern, so no names or ids), for Website traffic
                route = request.scope.get("route")
                traffic.note_slow(f"{request.method} {getattr(route, 'path', None) or path}", took, response.status_code)
        except Exception:
            log.debug("traffic count failed", exc_info=True)
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
        "crafty": [{"id": cid, "configured": c.enabled, "url": c.base or None, "error": c.last_error} for cid, c in connections.crafties()],
        "servers_dir": str(config.servers_dir),
        "servers_dir_found": config.servers_dir.is_dir(),
        "server_count": len(S.registry.servers),
    }


_SAFE_ID = re.compile(r"^[a-z0-9_.\-]{1,64}$")








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








@app.get("/api/public/status")
async def public_status():
    """The build Solstone is running, so open pages can offer a reload after an update."""
    return {"build": _asset_stamp()}


def _up_since(sid: str, started) -> float | None:
    """When the server last started, as a timestamp. Crafty's start time has no time zone (it's read in this
    container's, which can differ from Crafty's or the visitor's) and can be stale (left over from before a restart),
    so it's used only when it lands in the past and after the last stop or start Solstone saw; otherwise it's when
    Solstone's checks have seen it running since."""
    rows = db.q("SELECT ts FROM metrics WHERE server_id=? AND running=0 ORDER BY ts DESC LIMIT 1", (sid,))
    stopped = rows[0]["ts"] if rows else 0
    after = db.q("SELECT MIN(ts) AS t FROM metrics WHERE server_id=? AND running=1 AND ts>?", (sid, stopped))
    seen = after[0]["t"] if after and after[0]["t"] else None
    ev = db.q("SELECT MAX(ts) AS t FROM events WHERE server_id=? AND type='server'", (sid,))
    changed = max(stopped, (ev[0]["t"] if ev and ev[0]["t"] else 0))       # the last stop or start Solstone saw
    try:
        from datetime import datetime
        t = datetime.fromisoformat(str(started).replace("T", " ")).replace(tzinfo=db.tz()).timestamp() if started else None
    except (TypeError, ValueError):
        t = None
    now = time.time()
    if t and t <= now + 60 and t >= changed - 300 and (seen is None or t <= seen + 900):
        return min(t, now)
    if seen and changed > seen:                     # a start Solstone saw after its checks began (a quick restart)
        return changed
    return seen


def _uptime(sid: str, days: int) -> float | None:
    """The share of the last few days the server was up (from Solstone's own checks), 0..1."""
    r = db.q("SELECT COUNT(*) AS n, SUM(running) AS r FROM metrics WHERE server_id=? AND ts>=?", (sid, time.time() - days * 86400))[0]
    return round((r["r"] or 0) / r["n"], 4) if r["n"] else None


def _require_signed_in(request: Request) -> None:
    """Who's playing, who was, where, leaderboards and recaps: for people signed in only (never strangers)."""
    if request.state.user is None:
        raise HTTPException(401, "Sign in to see this")


def _may_see_map(user) -> bool:
    """Where everyone is (coordinates, the map, the web map) is for people signed in: Trusted and Admins, and Players when
    "Players can see the map" is on. Never for anonymous visitors, so nobody outside can watch where the kids are, and the
    map pictures (the heaviest thing Solstone sends) can't be pulled by strangers."""
    return user is not None and (not user.is_player or _players_see_map())






# ---- the public website: site details (how to join) and posts (news, guides, FAQ)
_site_cache: tuple[float, list] | None = None
_site_task: asyncio.Task | None = None


async def _site_status() -> list:
    """How each public server is doing, never who's on it: a count of players, its health, its uptime."""
    global _site_cache
    await S.registry.refresh()
    servers = []
    for srv in _public_servers_list():
        try:
            summ = await asyncio.wait_for(S.server_summary(srv), 6)
        except Exception as e:
            log.warning("home list failed for %s: %s", srv.id, e)
            continue
        perf = summ.get("perf") or {}
        servers.append({"id": srv.id, "name": summ["name"], "running": summ["running"], "online": len(summ["online"]),
                        "on_bedrock": sum(1 for n in summ["online"] if mcname.is_bedrock(str(n))),     # a count, never names
                        "max": summ["max_players"], "version": summ.get("version"), "has_icon": summ["has_icon"],
                        "started": summ.get("started") if summ["running"] else None, "tps": perf.get("tps"),
                        "up_since": _up_since(srv.id, summ.get("started")) if summ["running"] else None,
                        "mspt": perf.get("mspt"), "cpu": summ.get("cpu") if summ["running"] else None, "cpu_cores": summ.get("cpu_cores"),
                        "mem": summ.get("mem") if summ["running"] else None,
                        "mem_percent": summ.get("mem_percent") if summ["running"] else None,
                        "loader": summ.get("loader"), "uptime_7d": _uptime(srv.id, 7), "trend": _trend(srv.id),
                        "today": _today(srv.id), "world": await _world_now(srv, len(summ["online"])) if summ["running"] else None})
    _site_cache = (time.monotonic(), servers)
    return servers


async def _world_now(srv, online: int) -> dict | None:
    """The time of day and the weather in the game, for the home page (nothing about anyone). The clock counts on in
    the page while people are on (with nobody on, the server pauses after a minute, and so does its clock)."""
    if not srv.is_java or not srv.rcon_conf():
        return None
    try:
        w = await asyncio.to_thread(S.world_info, srv, False)
        w.update(await S.live_world(srv))
    except Exception:
        return None
    if w.get("time_of_day") is None:
        return None
    return {"t": int(w["time_of_day"]), "rain": bool(w.get("raining")), "thunder": bool(w.get("thundering")),
            "as_of": w.get("as_of") or time.time(), "ticking": online > 0}


SITE_STALE = 60                 # seconds: an older saved status isn't shown without trying for a fresh one first


async def _site_servers() -> list:
    """The status for the home page without making anyone wait: the last check (up to 15 s old) straight away, a
    fresh one started in the background when it's older. Older than a minute (nobody's looked in a while), it waits
    for the fresh one (at most 3 s): an hours-old copy once showed old graphs beside today's numbers."""
    global _site_task
    age = time.monotonic() - _site_cache[0] if _site_cache else None
    if (age is None or age >= 15) and (_site_task is None or _site_task.done()):
        _site_task = asyncio.get_running_loop().create_task(_site_status())
    if _site_cache and age < SITE_STALE:
        return _site_cache[1]
    if _site_cache:
        try:
            return await asyncio.wait_for(asyncio.shield(_site_task), 3)
        except Exception:
            return _site_cache[1]
    try:
        return await asyncio.wait_for(asyncio.shield(_site_task), 3)
    except Exception:
        return []


def _today(sid: str) -> dict:
    """What everyone did on a server today, added up, never who: for the home page, so it feels alive."""
    start = datetime.now(db.tz()).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    out: dict[str, float] = {}
    for r in db.q("SELECT type, message FROM events WHERE server_id=? AND ts>=? AND type IN ('progress', 'fish', 'bigfish', 'advancement')",
                  (sid, start)):
        add = adventures.tally(r["message"]) if r["type"] == "progress" else {"fish": 1} if r["type"] in ("fish", "bigfish") else {"advancements": 1}
        for k, v in add.items():
            out[k] = out.get(k, 0) + v
    out["players"] = db.q("SELECT COUNT(DISTINCT lower(player)) AS n FROM sessions WHERE server_id=? AND COALESCE(end_ts, last_seen_ts) >= ?",
                          (sid, start))[0]["n"]
    keep = ("players", "mobs", "mined", "logs", "crops", "placed", "fish", "advancements", "travelled")
    return {k: round(out[k]) for k in keep if out.get(k)}


HISTORY_WHAT = ("players", "tps", "cpu", "mem_mb", "uptime")
HISTORY_SPANS = {1: 96, 7: 84, 30: 60}            # days -> points: every 15 minutes, 2 hours, 12 hours
CHECK_GAP = 180                                   # longer than this between Solstone's checks: it wasn't watching


def _history(sid: str, what: str, days: int, now: float | None = None) -> dict:
    """A card's story on the home page: the line further back, or (uptime) the share of each day it was up, every time
    it went down and for how long, and when Solstone itself wasn't watching (not counted against the server)."""
    now = now or time.time()
    start = now - days * 86400
    rows = db.q("SELECT ts, running, players, cpu, tps, mem_mb FROM metrics WHERE server_id=? AND ts>=? ORDER BY ts", (sid, start))
    if what != "uptime":
        points = HISTORY_SPANS[days]
        step = days * 86400 / points
        sums: list[list[float]] = [[] for _ in range(points)]
        for r in rows:
            if r["running"] and r[what] is not None:
                sums[min(points - 1, int((r["ts"] - start) // step))].append(r[what])
        vals = [None if not b else round(max(b) if what == "players" else sum(b) / len(b), 1) for b in sums]
        seen = [v for b in sums for v in b]
        return {"what": what, "days": days, "start": start, "step": step, "values": vals,
                "low": round(min(seen), 1) if seen else None, "high": round(max(seen), 1) if seen else None,
                "average": round(sum(seen) / len(seen), 1) if seen else None}
    # uptime: each day's share, and the times it was down
    zone = db.tz()
    first_day = datetime.fromtimestamp(start, zone).replace(hour=0, minute=0, second=0, microsecond=0)
    per_day: dict[str, list[int]] = {}
    for r in rows:
        k = datetime.fromtimestamp(r["ts"], zone).date().isoformat()
        d = per_day.setdefault(k, [0, 0])
        d[0] += 1
        d[1] += 1 if r["running"] else 0
    bars = []
    for i in range(days + 1):
        day = (first_day + timedelta(days=i)).date()
        if day > datetime.fromtimestamp(now, zone).date():
            break
        n, up = per_day.get(day.isoformat(), [0, 0])
        bars.append({"day": day.isoformat(), "up": round(up / n, 4) if n else None})
    bars = bars[-days:]
    # restarts the server's log noted (a quick one finishes between two checks, so the checks never saw it down)
    evs = db.q("SELECT ts, message FROM events WHERE server_id=? AND type='server' AND ts>=? ORDER BY ts", (sid, start - 900))
    downs, prev, down_at = [], None, None
    for r in rows:
        if prev is not None and r["ts"] - prev["ts"] > CHECK_GAP:      # Solstone wasn't running (or couldn't look)
            # Was the game server down too? (The whole machine restarted.) It started again in the gap, or Solstone
            # found it still down: down from Solstone's last look (or its stop, if the log saw one) until it started.
            began = [e["ts"] for e in evs if e["message"] in db.STARTS and prev["ts"] < e["ts"] <= r["ts"] + 60]
            if began or not r["running"]:
                if down_at is None:
                    stops = [e["ts"] for e in evs if e["message"] in db.STOPS and prev["ts"] - 60 <= e["ts"] <= (began or [r["ts"]])[0]]
                    down_at = stops[0] if stops else prev["ts"]
                if began and r["running"]:
                    downs.append({"from": down_at, "to": began[0], "kind": "down"})
                    down_at = None
                prev = r
                continue
            if down_at is not None:
                downs.append({"from": down_at, "to": prev["ts"], "kind": "down"})
                down_at = None
            downs.append({"from": prev["ts"], "to": r["ts"], "kind": "unwatched"})
        if not r["running"] and down_at is None:
            down_at = r["ts"]
        elif r["running"] and down_at is not None:
            downs.append({"from": down_at, "to": r["ts"], "kind": "down"})
            down_at = None
        prev = r
    if down_at is not None:
        downs.append({"from": down_at, "to": None, "kind": "down"})          # down right now
    stop_at = None
    for e in evs:
        if e["message"] in db.STOPS:
            stop_at = e["ts"]
        elif e["message"] in db.STARTS and e["ts"] >= start:
            frm = stop_at if stop_at and e["ts"] - stop_at < 900 else e["ts"]
            if not any(d["from"] - 60 <= e["ts"] <= (d["to"] or now) + 60 for d in downs):
                downs.append({"from": frm, "to": e["ts"], "kind": "restart"})
            stop_at = None
    downs.sort(key=lambda d: d["from"])
    for x in downs:
        x["secs"] = round(((x["to"] or now) - x["from"]))
        if x["kind"] == "down" and x["secs"] <= 300 and x["to"]:
            x["kind"] = "restart"                                             # back within 5 minutes
    # each day's real downtime (quick restarts don't count), split at midnight: the bar's colour goes by it
    down_by_day: dict[str, float] = {}
    for x in downs:
        if x["kind"] != "down":
            continue
        a, b = x["from"], x["to"] or now
        while a < b:
            d0 = datetime.fromtimestamp(a, zone)
            nxt = (d0.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)).timestamp()
            down_by_day[d0.date().isoformat()] = down_by_day.get(d0.date().isoformat(), 0) + min(b, nxt) - a
            a = min(b, nxt)
    for bar in bars:
        bar["down_secs"] = round(down_by_day.get(bar["day"], 0))
    share = lambda d: _uptime(sid, d)                                         # noqa: E731
    return {"what": "uptime", "days": days, "bars": bars, "outages": downs[::-1][:60],
            "percent": {"24h": share(1), "7d": share(7), "30d": share(30)}, "now": now}


@app.get("/api/public/site/history")
async def public_site_history(sid: str, what: str, days: int = 1):
    """The history behind a card on the home page's status (counts and times only: nothing about anyone)."""
    if what not in HISTORY_WHAT or days not in HISTORY_SPANS:
        raise HTTPException(400, "Pick what and how far back")
    await S.registry.refresh()
    if not any(s.id == sid for s in _public_servers_list()):
        raise HTTPException(404, "Server not found")
    return JSONResponse(await asyncio.to_thread(_history, sid, what, days), headers={"Cache-Control": "public, max-age=60"})


def _trend(sid: str, hours: int = 6, points: int = 36) -> dict:
    """The last few hours of Solstone's own checks, for the little graphs on the home page: players, TPS and CPU,
    averaged into even slices (None where the server was off or nothing was seen)."""
    now = time.time()
    start, step = now - hours * 3600, hours * 3600 / points
    rows = db.q("SELECT ts, running, players, cpu, tps, mem_mb FROM metrics WHERE server_id=? AND ts>=? ORDER BY ts", (sid, start))
    out = {"players": [None] * points, "tps": [None] * points, "cpu": [None] * points, "mem_mb": [None] * points}
    sums = [{"players": [], "tps": [], "cpu": [], "mem_mb": []} for _ in range(points)]
    for r in rows:
        i = min(points - 1, int((r["ts"] - start) // step))
        if not r["running"]:
            continue
        for k in ("players", "tps", "cpu", "mem_mb"):
            if r[k] is not None:
                sums[i][k].append(r[k])
    for i, b in enumerate(sums):
        for k, v in b.items():
            if v:
                out[k][i] = round(max(v) if k == "players" else sum(v) / len(v), 1)
    if sums[-1]["players"]:                       # now: how many are on right now, not the most in the last 10 minutes
        out["players"][-1] = sums[-1]["players"][-1]
    return {**out, "hours": hours}


@app.get("/api/public/site")
async def public_site():
    site.move_guides_to_posts()
    cfg = site.config()
    servers = await _site_servers() if cfg["home_live"] else []
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
        xbox = st.get("join_xbox") or ""          # MCXboxBroadcast: Bedrock players add this gamertag as a friend and join through it
        if not (java or bed) and not main_used and (cfg["java_address"] or cfg["bedrock_address"]):
            java, bed, port, main_used = cfg["java_address"], cfg["bedrock_address"], cfg["bedrock_port"], True
        if not (java or bed or xbox):
            continue
        joins.append({"id": srv.id, "name": srv.display_name, "java": java, "bedrock": bed, "bedrock_port": port or 19132, "xbox": xbox,
                      "note": st.get("join_note") or "", "mods": _mods_for_players(srv) if st.get("join_mods") or modpack.get(srv.id)["public_download"] else None,
                      "status": status.get(srv.id), "main": srv.id == cfg.get("main_server"),
                      "color": st.get("join_color") or "",
                      # is the Xbox friend working right now (xboxwatch.py)
                      "xbox_status": xboxwatch.status(srv.id, bool(recorder._running_state.get(srv.id)), bool(xbox)) if xbox else None,
                      "version": srv.mc_version if srv.is_java else None})   # from the world's save: right even while it's off
    if joins and not (cfg["java_address"] or cfg["bedrock_address"]):     # the join guide's {java_address} and the like:
        cfg = {**cfg, "java_address": joins[0]["java"], "bedrock_address": joins[0]["bedrock"],  # the first server's
               "bedrock_port": joins[0]["bedrock_port"]}
    # the join guide's {java_version}: the main (first) server's Minecraft version, when it's known
    cfg = {**cfg, "java_version": next((j["version"] for j in joins if j["java"] and j["version"]), ""),
           "xbox_friend": next((j["xbox"] for j in joins if j["xbox"]), "")}
    asks = [{"id": s.id, "name": s.display_name, "main": s.id == cfg.get("main_server")} for s in ordered if s.is_java] if cfg["join_requests"] else []
    return JSONResponse({**cfg, "logo": site.logo_url(), "servers": servers, "joins": joins, "ask_servers": asks,
                         "guide_posts": site.guide_posts(), "roles": site.ROLES, "build": _asset_stamp()},
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
                        "xbox": j.get("xbox") or "", "note": j.get("note") or "", "version": j.get("version") or "",
                        "main": bool(j.get("main")), "color": j.get("color") or "",
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
    if signup._hit(f"ask:{auth.client_ip(request)}", 8):  # (a family on one connection can each ask, back to back)
        raise HTTPException(429, "You've asked a few times already. An admin will see it soon")
    token = secrets.token_urlsafe(18)              # only they get this: it shows them when they've been let in
    site.add_join_request(player, name, note, hashlib.sha256(token.encode()).hexdigest(), picked)
    where = ", ".join(public[x].display_name for x in picked)
    msg = f"{player} would like to join {where}" + (f" ({name})" if name else "") + (f": {note}" if note else "")
    await notify.send("Asking to join", msg + "\nTap to let them in (Manage → Players → Whitelist).", "wave",
                      click=f"{_public_base(request)}/app#/manage/whitelist", kind="requests")
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
        _saw_answer(th)
        return {"state": "denied", "player": r["player"], "servers": [], "reason": r.get("reason") or ""}
    await S.registry.refresh()
    public = {s.id: s for s in _public_servers_list() if s.is_java}
    sids = [x for x in (r.get("servers") or []) if x in public] or ([] if finished else list(public)[:1])
    each = [{"name": public[x].display_name, "in": finished or x in (r.get("done") or []) or S.whitelisted(public[x], None, r["player"])}
            for x in sids]
    if not finished and each and all(e["in"] for e in each):
        site.finish_join_request(th)
        finished = True
    state = "in" if finished else "partly" if any(e["in"] for e in each) else "waiting"
    if state == "in":
        _saw_answer(th)
    return {"state": state, "player": r["player"], "servers": each}


@app.post("/api/public/join-request/withdraw")
async def join_request_withdraw(request: Request):
    """Take back your own request to join (only you can: with the private token your browser kept)."""
    body = await _body(request)
    token = str(body.get("token") or "")[:64]
    r = site.withdraw_join_request(hashlib.sha256(token.encode()).hexdigest() if token else "")
    if r:
        log.info("join request for %s withdrawn by the person who asked", r.get("player"))
    return {"ok": True, "withdrawn": bool(r)}         # (gone already: fine either way, their page drops it)


def _saw_answer(token_hash: str) -> None:
    """They've seen their answer: noted for Manage → Whitelist, and a notification the first time."""
    r = site.mark_seen(token_hash)
    if r:
        said = "saw that their request wasn't accepted" if r.get("denied") else "saw that they're in"
        notify.maybe_notify("blocked", site.config().get("name") or "Solstone", f"{r['player']} {said}")


# ---- players making their own account (a code sent to them in the game)
def _signup_on() -> None:
    if not site.config()["signup"]:
        raise HTTPException(404, "Sign-up is turned off")


@app.post("/api/public/signup/start")
async def signup_start(request: Request):
    _signup_on()
    body = await _body(request)
    await S.registry.refresh()
    return await signup.start(request, str(body.get("player") or ""), _public_servers_list())


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






# ---- daily recaps and "on this day"
def _recap_payload(sid: str, day_s: str | None) -> dict:
    today = datetime.now(db.tz()).date()
    try:
        day = min(today, date.fromisoformat(day_s)) if day_s else today
    except ValueError:
        raise HTTPException(400, "Use a date like 2026-10-20") from None
    out = {"day": day.isoformat(), "today": today.isoformat(), "recap": stacks.recap(recap.day_recap(sid, day)),
           "on_this_day": recap.on_this_day(sid, day), **recap.neighbours(sid, day)}
    if day == today:
        out["yesterday"] = stacks.recap(recap.day_recap(sid, today - timedelta(days=1)))
    return out


@app.get("/api/servers/{sid}/recap")
async def get_recap(sid: str, day: str | None = None):
    srv = await _server(sid)
    data = await asyncio.to_thread(_recap_payload, srv.id, day)
    return data if _shows_play_time() else _recap_without_durations(data)






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
    if where == "app" and not signed_in:
        raise HTTPException(401, "Sign in to continue")
    if where == "status":                            # the old status page, gone (its servers are on the home page)
        raise HTTPException(404, "There's no status page any more")
    await S.registry.refresh()
    servers = [x for x in _board_servers() if _visible(x)]     # a private server's announcements stay private
    if sid and not any(x.id == sid for x in servers):
        sid = ""
    items = await asyncio.to_thread(board.active, where, sid or None, signed_in, None, servers)   # names only for people signed in
    if signed_in:                                    # signed in, on every page: the votes they haven't voted in yet
        items += await asyncio.to_thread(board.vote_banners, f"u{request.state.user.id}")
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
            "now": time.time()}


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


@app.post("/api/servers/{sid}/map/redraw")
async def map_redraw(sid: str, request: Request):
    """Admin: forget every picture of this server's map: drawn again from the world's files as they're looked at (and
    the rest in the background). For pictures left over from another world at the same spot."""
    user = auth.require_admin(request)
    srv = await _server(sid)
    n = await asyncio.to_thread(worldmap.clear_tiles, srv.id)
    auth.audit(user, sid, "map:redraw", f"{n} pictures")
    return {"cleared": n}


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
    """A public server's icon, for its card on the home page."""
    data = S.server_icon_bytes(await _public_server(sid))
    if not data:
        raise HTTPException(404)
    return Response(data, media_type="image/png", headers={"Cache-Control": "max-age=300"})




@app.get("/api/public/reward-item/{ns}/{name}.png")
async def public_reward_icon(ns: str, name: str):
    """A holiday reward's picture for the Events page and its banner (anyone can see what the reward is). Only items
    set as a reward, drawn from the first public Java server's game."""
    if not _SAFE_ID.match(ns) or not _SAFE_ID.match(name) or f"{ns}:{name}" not in holidaygifts.rewarded_items():
        raise HTTPException(404, "Not a holiday reward", headers={"Cache-Control": "no-store"})
    await S.registry.refresh()
    # Drawn from any Java server's game that can: the public ones first, then the rest (only the picture is shared).
    # A server whose game files aren't here yet starts fetching them, so it can next time.
    public = [x for x in _public_servers_list() if x.is_java]
    tried: set[str] = set()
    states = []
    for srv in [*public, *(x for x in S.registry.servers.values() if x.is_java and x not in public)]:
        a = _assets(srv)
        if not a or a.cache_key in tried:
            continue
        tried.add(a.cache_key)
        if not a.ready and a.vs.state == "missing":    # fetch them once; a failed fetch isn't retried on every request
            a.vs.ensure()
        states.append(a.vs.state)
        # Like the app's own item pictures: one already drawn is used even while the game files aren't ready
        data = await asyncio.to_thread(a.icon, f"{ns}:{name}")
        if data:
            return Response(data, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})
    # Not drawable yet: never let a browser or Cloudflare keep the "not found"; say why (no names, just states)
    why = "no Java server" if not states else f"couldn't draw it (game files: {', '.join(sorted(set(states)))})"
    raise HTTPException(404, f"No picture: {why}", headers={"Cache-Control": "no-store"})






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
    return JSONResponse({**_fireworks_cfg(), "custom": custom, **fwshow.today_state()},
                        headers={"Cache-Control": "no-cache"})


@app.get("/api/fireworks/my-join")
async def my_join_firework(request: Request):
    """The firework that goes off when you join the server (your join firework), if join fireworks are on."""
    user = auth.require_user(request)
    sigs = fwshow.signatures()
    mine = next((sigs[p["name"].lower()] for p in user.players if p["name"].lower() in sigs), "")
    return {"firework": mine, "players": [p["name"] for p in user.players], "active": fwshow.join_cfg()["on"]}


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
    if fid and not fireworks.approved(fireworks.get(fid)):
        raise HTTPException(400, "That picture firework is still waiting for an admin to look at it")
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
    """Join fireworks: someone joined the game. Player names only for people signed in."""
    names = request.state.user is not None
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
    return {"join": fwshow.join_cfg(), "signatures": fwshow.signatures(), "calendar": fwshow.with_next(fwshow.calendar()),
            "players": sorted(players.values(), key=str.lower), "today": fwshow.today_state(),
            "calendar_defaults": [fwshow._clean_entry(e) for e in fwshow.DEFAULT_CALENDAR],
            "creators": _creators_summary(),
            "overlaps": await asyncio.to_thread(fwshow.overlaps),
            "servers": [{"id": x.id, "name": x.display_name} for x in S.registry.servers.values() if x.is_java and not x.settings.get("hidden")]}


@app.put("/api/fireworks/show")
async def put_firework_show(request: Request):
    user = auth.require_admin(request)
    body = await _body(request)
    if isinstance(body.get("join"), dict):
        fwshow.save_join(body["join"])
    if isinstance(body.get("signatures"), dict):
        fwshow.save_signatures(body["signatures"])
    if isinstance(body.get("calendar"), list):
        fwshow.save_calendar(body["calendar"])
    if isinstance(body.get("creators"), dict):
        cw = _creator_weights()
        cw.update({str(k)[:32]: _weight(v) for k, v in body["creators"].items()})
        settings_store.save_section("fw_creators", cw)
    auth.audit(user, None, "fireworks_show", ", ".join(sorted(k for k in body if k in ("join", "signatures", "calendar", "creators"))))
    return await get_firework_show(request)


def _creators_summary() -> list[dict]:
    cw = _creator_weights()
    by: dict[str, int] = {}
    for d in fireworks.all_designs():
        by[d.get("author", "")] = by.get(d.get("author", ""), 0) + 1
    return [{"name": n, "designs": c, "weight": cw.get(n, 1)} for n, c in sorted(by.items(), key=lambda x: x[0].lower())]


@app.get("/api/fireworks/calendar/{eid}/rewarded")
async def holiday_rewarded(eid: str, request: Request):
    """Who's had an event's reward, each server and each time round (admins only: it names players)."""
    auth.require_admin(request)
    await S.registry.refresh()
    return {"given": await asyncio.to_thread(holidaygifts.given_to, eid)}


@app.post("/api/fireworks/test-join")
async def test_join_firework(request: Request):
    """What goes off when this player joins (the page plays it in a preview)."""
    auth.require_admin(request)
    player = str((await _body(request)).get("player") or "") or None
    return {"ok": True, "show": fwshow.resolve_join(player, check_on=False)}


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
    running = [x for x in visible if (x.crafty or {}).get("_stats", {}).get("running") or S._online_cache.get(x.id, (0, ([], "")))[1][1] == "rcon"]
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
    return {"items": items, "days": upcoming.DAYS, "now": time.time(), "past": upcoming.past(names)}


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
    return JSONResponse({"items": items, "days": upcoming.DAYS, "now": time.time(), "past": upcoming.past(names)},
                        headers={"Cache-Control": "no-cache"})


@app.get("/api/fireworks")
async def list_fireworks(request: Request):
    user = request.state.user
    names = await asyncio.to_thread(auth.shown_names)
    # A picture waiting for an admin (or turned down) is only seen by its maker and the admins.
    return [{**d, "mine": d.get("author") == user.username, "can_edit": _can_edit(user, d),
             "maker": names.get(str(d.get("author", "")).lower(), d.get("author", ""))} for d in fireworks.all_designs()
            if fireworks.approved(d) or _can_edit(user, d)]


@app.get("/api/fireworks/review")
async def fireworks_to_review(request: Request):
    """Picture fireworks waiting for an admin to look at them."""
    user = request.state.user
    if user.role != "admin":
        raise HTTPException(403, "Only admins can approve fireworks")
    names = await asyncio.to_thread(auth.shown_names)
    return [{**d, "maker": names.get(str(d.get("author", "")).lower(), d.get("author", ""))} for d in fireworks.waiting()]


@app.post("/api/fireworks/{fid}/review")
async def review_firework(fid: str, request: Request):
    """Approve a picture firework (it goes live), or not, with an optional reason its maker sees."""
    user = request.state.user
    if user.role != "admin":
        raise HTTPException(403, "Only admins can approve fireworks")
    body = await _body(request)
    d = fireworks.review(fid, bool(body.get("approve")), str(body.get("reason") or ""), user.username)
    if not d:
        raise HTTPException(404, "Firework not found")
    auth.audit(user, None, "firework_review", f"{d.get('name', '')}: {'approved' if body.get('approve') else 'not approved'}")
    return d


async def _tell_admins_picture(request: Request, d: dict, user) -> None:
    if d.get("review") != "pending":
        return
    who = auth.shown_names().get(user.username.lower(), user.username)
    await notify.send("Firework to look at", f"{who} drew a picture firework, \"{d.get('name') or 'Firework'}\". "
                      "It's hidden until an admin approves it (Fireworks → Waiting for approval).", "art",
                      click=f"{_public_base(request)}/app#/fireworks", kind="fireworks")


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


@app.put("/api/sounds/{sound_id}")
async def update_sound(sound_id: str, request: Request):
    user = request.state.user
    body = await _body(request)
    item = fireworks.update_sound(sound_id, body.get("name"), body.get("sfx"), user.username, user.role == "admin")
    if not item:
        raise HTTPException(404, "No such sound, or it isn't yours")
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
                             None if admin else fireworks.show_per_person(), trusted=admin)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    auth.audit(user, None, "firework_create", d["name"])
    await _tell_admins_picture(request, d, user)
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
    saved = fireworks.update(fid, body, trusted=user.role == "admin")
    if saved and d.get("review") != "pending":
        await _tell_admins_picture(request, saved, user)
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
    user = await asyncio.to_thread(auth.check_login, request, typed, str(body.get("password", "")))
    if twostep.is_on(user.id) and not twostep.is_trusted(user.id, request.cookies.get(twostep.TRUST_COOKIE)):
        # the password's right; now the code from their app (no session until then)
        return {"two_step": True, "ticket": twostep.ticket_for(user.id, auth.client_ip(request))}
    return _signed_in(request, user, typed)


def _signed_in(request: Request, user: auth.User, typed: str, how: str = "", trust: bool = False) -> JSONResponse:
    token = auth.new_session(request, user)
    auth.audit(user, None, "login", (f"as {typed} " if typed.lower() != user.username.lower() else "") + f"from {auth.client_ip(request)}{how}")
    resp = JSONResponse({"user": _me(user)})
    auth.set_cookie(resp, request, token)
    if trust:
        resp.set_cookie(twostep.TRUST_COOKIE, twostep.trust_device(user.id), max_age=twostep.TRUST_DAYS * 86400, httponly=True,
                        samesite="lax", secure=auth.is_https(request), path="/")
    return resp


@app.post("/api/auth/login/code")
async def login_code(request: Request):
    """Two-step sign-in: the code from their authenticator app (or a backup code), after the password."""
    body = await _body(request)
    if signup._hit(f"2fa:{auth.client_ip(request)}", 30):
        raise HTTPException(429, "Too many tries. Wait a while and try again")
    uid = await asyncio.to_thread(twostep.use_ticket, str(body.get("ticket") or ""), str(body.get("code") or ""))
    user = auth.get_user(uid)
    return _signed_in(request, user, user.username, " (two-step)", trust=bool(body.get("trust")))


@app.post("/api/public/password-reset/start")
async def password_reset_start(request: Request):
    """Forgot the password: a code to that player in the game chat (only whoever's playing as them sees it)."""
    body = await _body(request)
    await S.registry.refresh()
    servers = [x for x in S.registry.servers.values() if x.is_java]
    return await signup.start_reset(request, str(body.get("player") or ""), servers)


@app.post("/api/public/password-reset/finish")
async def password_reset_finish(request: Request):
    body = await _body(request)
    u = await asyncio.to_thread(signup.finish_reset, str(body.get("player") or ""), str(body.get("code") or ""),
                                str(body.get("password") or ""))
    auth.audit(u, None, "password_reset", f"{u.username}, proved in the game")
    return {"ok": True, "username": u.username}


@app.get("/api/auth/two-step")
async def two_step_status(request: Request):
    user = auth.require_user(request)
    return twostep.status(user.id)


@app.post("/api/auth/two-step/begin")
async def two_step_begin(request: Request):
    user = auth.require_user(request)
    return twostep.begin(user, str((site.config() or {}).get("name") or "Solstone"))


@app.post("/api/auth/two-step/confirm")
async def two_step_confirm(request: Request):
    user = auth.require_user(request)
    codes = twostep.confirm(user, str((await _body(request)).get("code") or ""))
    auth.audit(user, None, "two_step_on", user.username)
    return {"ok": True, "backup_codes": codes, **twostep.status(user.id)}


@app.post("/api/auth/two-step/backup-codes")
async def two_step_backups(request: Request):
    user = auth.require_user(request)
    codes = twostep.new_backups(user, str((await _body(request)).get("code") or ""))
    auth.audit(user, None, "two_step_backup_codes", user.username)
    return {"backup_codes": codes, **twostep.status(user.id)}


@app.post("/api/auth/two-step/off")
async def two_step_off(request: Request):
    """Turning it off takes the password and a code: a session left open somewhere can't do it."""
    user = auth.require_user(request)
    body = await _body(request)
    row = db.q("SELECT password_hash FROM users WHERE id=?", (user.id,))[0]
    if not auth.verify_password(str(body.get("password", "")), row["password_hash"]):
        raise HTTPException(400, "Your password is wrong")
    if not twostep.check(user.id, str(body.get("code") or "")):
        raise HTTPException(400, "That code isn't right")
    twostep.turn_off(user.id)
    auth.audit(user, None, "two_step_off", user.username)
    return twostep.status(user.id)


@app.post("/api/users/{uid}/two-step-off")
async def admin_two_step_off(uid: int, request: Request):
    """Another admin turns it off for someone who lost their phone and backup codes."""
    admin = auth.require_admin(request)
    u = auth.get_user(uid)
    if not u:
        raise HTTPException(404, "No such login")
    twostep.turn_off(uid)
    db.x("DELETE FROM sessions_auth WHERE user_id=?", (uid,))
    auth.audit(admin, None, "two_step_off", f"{u.username} (by an admin)")
    return {"ok": True}


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


@app.get("/api/manage/servers")
async def manage_servers(request: Request):
    """Admin: every server Solstone has found, shown or hidden, with how it's reached (Manage → Servers)."""
    auth.require_admin(request)
    await S.registry.refresh()
    out = []
    for s in sorted(S.registry.servers.values(), key=lambda x: (bool(x.settings.get("hidden")), x.display_name.lower())):
        st = s.settings
        out.append({"id": s.id, "name": s.display_name, "found_as": s.name, "game": s.game, "java": s.is_java,
                    "hidden": bool(st.get("hidden")), "private": bool(st.get("private")), "new": bool(st.get("new")),
                    "crafty": bool(s.crafty), "folder": s.dir.name, "rcon": bool(s.rcon_conf()), "rcon_error": s.rcon_error or "",
                    "version": s.mc_version or ""})
        if s.crafty:
            out[-1]["crafty_name"] = (connections.get(s.crafty.get("_conn")) or {}).get("name", "Crafty")
        if s.remote:                                  # somewhere else: how its files and panel are doing
            m, p = remote.mirror(s.id), s.panel
            out[-1].update(remote=True, files=dict(m.status) if m else {}, backup=m.backup_status() if m else None,
                           panel=bool(p), panel_error=(p.error if p else ""),
                           where=(remote.get(s.id) or {}).get("host", ""),
                           map=bool((remote.get(s.id) or {}).get("map", True)))
    return out


@app.get("/api/manage/connections")
async def list_connections(request: Request):
    """Admin: Crafty and the hosts' panels Solstone asks about running servers (Manage → Server setup)."""
    auth.require_admin(request)
    await S.registry.refresh()
    out = []
    for cid, cfg in connections.all_cfg().items():
        row = {"id": cid, **connections.public(cfg)}
        if cfg["type"] == "crafty":
            c = connections.crafty_client(cid)
            row["servers"] = [s.display_name for s in S.registry.servers.values() if s.crafty and s.crafty.get("_conn") == cid]
            row["error"] = (c.last_error or "") if c else ""
            row["unreachable"] = any(s.crafty and s.crafty.get("_conn") == cid and s.crafty.get("_unreachable") for s in S.registry.servers.values())
        else:
            row["servers"] = [S.registry.servers[sid].display_name for sid, r in remote.all_cfg().items()
                              if r.get("conn") == cid and sid in S.registry.servers]
            row["error"] = next((p.error for sid, r in remote.all_cfg().items() if r.get("conn") == cid and (p := remote.panel(sid)) and p.error), "")
        out.append(row)
    return out


@app.post("/api/manage/connections/test")
async def test_connection(request: Request):
    """Admin: does it answer, and which servers does it have? Nothing is saved."""
    auth.require_admin(request)
    body = await _body(request)
    old = connections.get(str(body.get("id") or "")) if body.get("id") else None
    try:
        cfg = connections.clean(body, old)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return await connections.test(cfg)


@app.put("/api/manage/connections")
@app.put("/api/manage/connections/{cid}")
async def save_connection(request: Request, cid: str | None = None):
    user = auth.require_admin(request)
    body = await _body(request)
    try:
        cid = connections.save(cid, body)
    except KeyError:
        raise HTTPException(404, "No such connection") from None
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    await S.registry.refresh(force=True)
    auth.audit(user, "", "connection", f"{connections.get(cid)['type']} {connections.get(cid)['url']}")
    return {"id": cid, **connections.public(connections.get(cid))}


@app.delete("/api/manage/connections/{cid}")
async def delete_connection(cid: str, request: Request):
    """Admin: remove one. Crafty's servers go from the list (their history in Solstone stays); servers elsewhere on a
    panel keep working over SFTP, just without start, stop, CPU and memory."""
    user = auth.require_admin(request)
    if not connections.get(cid):
        raise HTTPException(404, "No such connection")
    connections.remove(cid)
    data = remote.all_cfg()
    for r in data.values():
        if r.get("conn") == cid:
            r["conn"] = ""
    settings_store.save_section(remote.SECTION, data)
    await S.registry.refresh(force=True)
    auth.audit(user, "", "connection:removed", cid)
    return {"ok": True}


@app.get("/api/manage/connections/{cid}/servers")
async def connection_servers(cid: str, request: Request):
    """Admin: the servers a panel's API key can see, to pick one for a server elsewhere."""
    auth.require_admin(request)
    cfg = connections.get(cid)
    if not cfg:
        raise HTTPException(404, "No such connection")
    res = await connections.test(cfg)
    if not res.get("ok"):
        raise HTTPException(502, res.get("error") or "It didn't answer")
    return res["servers"]


@app.get("/api/manage/remote/{sid}")
async def get_remote(sid: str, request: Request):
    """Admin: how a server elsewhere is reached (its secrets stay in Solstone: just whether each is set)."""
    auth.require_admin(request)
    cfg = remote.get(sid)
    if not cfg:
        raise HTTPException(404, "No such server")
    return remote.public(cfg)


@app.post("/api/manage/remote/test")
async def test_remote(request: Request):
    """Admin, setting one up: try the SFTP login and the folder, and the panel if one's given. Nothing is saved."""
    auth.require_admin(request)
    body = await _body(request)
    old = remote.get(str(body.get("id") or "")) if body.get("id") else None
    try:
        cfg = remote.clean(body, old)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    out = {"files": await remote.test(cfg)}
    if cfg.get("conn") and cfg.get("panel_id"):
        kind = (connections.get(cfg["conn"]) or {}).get("type")
        out["panel"] = await (remote.PrismPanel if kind == "serverprism" else remote.Panel)("_test", cfg).test()
    return out


@app.put("/api/manage/remote")
@app.put("/api/manage/remote/{sid}")
async def save_remote(request: Request, sid: str | None = None):
    """Admin: add a server elsewhere, or change how it's reached."""
    user = auth.require_admin(request)
    body = await _body(request)
    if sid and not remote.get(sid):
        raise HTTPException(404, "No such server")
    try:
        sid = remote.save(sid, body)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    data = remote.all_cfg()
    if not data[sid].get("host_pub"):                 # its identity: learned now, the admin having just tested it
        res = await remote.test(data[sid])
        if res.get("host_pub"):
            data[sid]["host_key"], data[sid]["host_pub"] = res["host_key"], res["host_pub"]
            settings_store.save_section(remote.SECTION, data)
    if body.get("rcon_password") or body.get("rcon_port"):
        upd = {k: body[k] for k in ("rcon_password", "rcon_port", "rcon_host") if body.get(k)}
        if upd.get("rcon_port"):
            try:
                upd["rcon_port"] = max(1, min(65535, int(upd["rcon_port"])))
            except (TypeError, ValueError):
                raise HTTPException(400, "The RCON port is a number") from None
        settings_store.update_server(sid, upd)
    m = remote.mirror(sid)
    if m:
        m.close()                                     # (new settings: a fresh connection)
        m.last = dict.fromkeys(m.last, 0.0)          # (every one of its timers: the map's too)
    await S.registry.refresh(force=True)
    auth.audit(user, sid, "remote_server", f"{body.get('name') or sid} at {body.get('host') or ''}")
    return {"id": sid, **remote.public(remote.get(sid))}


@app.post("/api/manage/remote/{sid}/forget-key")
async def remote_forget_key(sid: str, request: Request):
    """Admin: the host moved the server to another machine, so its SFTP identity changed: learn the new one."""
    user = auth.require_admin(request)
    data = remote.all_cfg()
    if sid not in data:
        raise HTTPException(404, "No such server")
    data[sid]["host_key"] = data[sid]["host_pub"] = ""
    settings_store.save_section(remote.SECTION, data)
    res = await remote.test(data[sid])
    if res.get("host_pub"):
        data[sid]["host_key"], data[sid]["host_pub"] = res["host_key"], res["host_pub"]
        settings_store.save_section(remote.SECTION, data)
    auth.audit(user, sid, "remote_server:new_key", res.get("host_key", ""))
    return res


@app.post("/api/manage/remote/{sid}/backup")
async def remote_backup_now(sid: str, request: Request):
    """Admin: the full copy of a server elsewhere, now (whether or not the nightly one is on)."""
    user = auth.require_admin(request)
    m = remote.mirror(sid)
    if not m:
        raise HTTPException(404, "No such server")
    if not m.start_backup("asked"):
        raise HTTPException(409, "A full copy is already running")
    auth.audit(user, sid, "remote_server:full_copy", "started")
    return m.backup_status()


@app.post("/api/manage/remote/{sid}/backup/stop")
async def remote_backup_stop(sid: str, request: Request):
    """Admin: stop a full copy that's running (what it fetched so far stays; saving is turned back on if it was paused)."""
    user = auth.require_admin(request)
    m = remote.mirror(sid)
    if not m:
        raise HTTPException(404, "No such server")
    if not m.backup_running:
        raise HTTPException(409, "No full copy is running")
    m.backup_task.cancel()
    try:
        await asyncio.wait_for(asyncio.shield(m.backup_task), 30)
    except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
        pass
    auth.audit(user, sid, "remote_server:full_copy", "stopped")
    return m.backup_status()


@app.get("/api/manage/remote/{sid}/backup")
async def remote_backup_status(sid: str, request: Request):
    auth.require_admin(request)
    m = remote.mirror(sid)
    if not m:
        raise HTTPException(404, "No such server")
    return m.backup_status()


@app.post("/api/manage/servers/{sid}/check")
async def check_server(sid: str, request: Request):
    """Admin: 🩺 Check: everything a server needs, tried now (its files, the world, start and stop, RCON, the log, the
    map, the full copy, room). Nothing is changed."""
    auth.require_admin(request)
    srv = await _server(sid)
    lines = await servercheck.check(srv)
    worst = "bad" if any(x["state"] == "bad" for x in lines) else "warn" if any(x["state"] == "warn" for x in lines) else "ok"
    return {"at": time.time(), "state": worst, "lines": lines}


@app.get("/api/manage/history/move")
async def move_history_preview(request: Request, src: str, dst: str):
    """Admin: what moving one server's history to another would move (Manage → History & data → Move history)."""
    auth.require_admin(request)
    if src == dst:
        raise HTTPException(400, "Pick two different servers")
    return await asyncio.to_thread(movehistory.preview, src, dst)


@app.post("/api/manage/history/move")
async def move_history(request: Request):
    """Admin: give one server's history to another (a server moved to a game host is a new server to Solstone)."""
    user = auth.require_admin(request)
    body = await _body(request)
    src, dst = str(body.get("src") or ""), str(body.get("dst") or "")
    await S.registry.refresh()
    names = {s.id: s.display_name for s in S.registry.servers.values()}
    if dst not in names:
        raise HTTPException(400, "Pick the server to move it to")
    try:
        res = await asyncio.to_thread(movehistory.move, src, dst)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    total = sum(v for k, v in res["moved"].items() if not k.endswith("_same"))
    auth.audit(user, dst, "history:move", f"from {names.get(src, src)} to {names[dst]}: {total} records", f"backup {res['backup']}")
    return res


@app.get("/api/manage/remote/{sid}/backup/history")
async def remote_backup_history(sid: str, request: Request, started: float | None = None):
    """Admin: the last full copies (newest first); with started, that one with every file it fetched and removed."""
    auth.require_admin(request)
    m = remote.mirror(sid)
    if not m:
        raise HTTPException(404, "No such server")
    runs = await asyncio.to_thread(m.history)
    if started is not None:
        run = next((r for r in runs if abs((r.get("started") or 0) - started) < 0.001), None)
        if not run:
            raise HTTPException(404, "No such copy")
        return run
    return [{k: v for k, v in r.items() if k not in ("changed", "removed_files")} for r in runs]


@app.get("/api/manage/remote/{sid}/backup/files")
async def remote_backup_files(sid: str, request: Request, path: str = ""):
    """Admin: one folder of the full copy: what's in it, how big, when the server last changed each."""
    auth.require_admin(request)
    m = remote.mirror(sid)
    if not m:
        raise HTTPException(404, "No such server")
    try:
        return await asyncio.to_thread(m.browse, path)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(404, "No such folder in the copy") from e


@app.delete("/api/manage/remote/{sid}")
async def delete_remote(sid: str, request: Request):
    """Admin: stop looking after a server elsewhere (its history in Solstone stays; the mirror's files go)."""
    import shutil
    user = auth.require_admin(request)
    if not remote.get(sid):
        raise HTTPException(404, "No such server")
    m = remote.mirror(sid)
    if m:
        if m.backup_running:
            m.backup_task.cancel()                    # (a full copy running: stopped, its saving pause put right first)
        m.close()
    remote.forget(sid)
    shutil.rmtree(remote.mirror_dir(sid), ignore_errors=True)
    await S.registry.refresh(force=True)
    auth.audit(user, sid, "remote_server:removed", sid)
    return {"ok": True}


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


@app.put("/api/servers/{sid}/mods/updates/skip")
async def mod_update_skip(sid: str, request: Request):
    """Admins: {project, version} skips that build (no badge, no notification) until a different one comes out;
    {project, version: null} stops skipping."""
    user = auth.require_admin(request)
    srv = await _server(sid)
    body = await request.json()
    project = str(body.get("project") or "").strip()
    if not project:
        raise HTTPException(400, "Which mod?")
    modupdates.set_skip(srv.id, project, body.get("version") or None)
    auth.audit(user, srv.id, "mod_update_skip", f"{project} {body.get('version') or '(not skipped)'}")
    return await modupdates.check(srv)


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
    st = await asyncio.to_thread(stacks.stacks)       # an account's other Minecraft names go under its main one
    for p in data["players"]:
        info = st.get(p["name"].lower())
        if info and info["name"].lower() != p["name"].lower():
            p["under"] = info["name"]
        elif info:
            p["linked"] = [n for n in info["names"] if n.lower() != p["name"].lower()]
        if not see_map and not _own(p.get("uuid") or ""):          # a player account doesn't see where anyone else is (unless the map is on for them)
            p.pop("position", None)
            p.pop("dimension", None)
    return data


@app.get("/api/servers/{sid}/players/{uuid}")
async def get_player(sid: str, uuid: str):
    if not _own(uuid):
        raise HTTPException(404, "Player not found")
    srv = await _server(sid)
    data = await S.player_detail(srv, uuid)
    if data:                                     # their other Minecraft accounts, and everyone's progress added up
        data["together"] = await asyncio.to_thread(stacks.together, srv, data["name"])
    if data and not _shows_play_time():
        data = _no_durations(data)
    if not data:
        raise HTTPException(404, "Player not found")
    return data


@app.get("/api/servers/{sid}/players/{uuid}/travels")
async def get_player_travels(sid: str, uuid: str, span: str = "all"):
    """Where a player (all their accounts) has been: the chunks, how often, and their records. Their own page only, for
    a player account, like the rest of it."""
    if not _own(uuid):
        raise HTTPException(404, "Player not found")
    srv = await _server(sid)
    p = S.known_players(srv).get(S.norm_uuid(uuid))
    if not p:
        raise HTTPException(404, "Player not found")
    tog = await asyncio.to_thread(stacks.together, srv, p["name"])
    names = [a["name"] for a in (tog or {}).get("accounts", [])] or [p["name"]]
    data = await asyncio.to_thread(adventures.travels if span == "recent" else adventures.travels_all, srv.id, names)
    spawn = (await asyncio.to_thread(S.world_info, srv, False)).get("spawn")
    data = adventures.farthest_from(data, spawn)
    return {**data, "names": names, "span": "recent" if span == "recent" else "all"}


@app.get("/api/servers/{sid}/leaderboard")
async def get_leaderboard(sid: str):
    return stacks.leaderboard(await S.leaderboard(await _server(sid)))


def _board_rows(srv: S.Server, uuid: str) -> list[dict]:
    raw = S.player_board_values(srv, uuid)
    minus = S.board_adjustments(srv.id).get(uuid) or {}
    return [{"key": k, "title": t, "kind": f, "real": raw.get(k, 0), "minus": minus.get(k, 0),
             "shown": max(0, raw.get(k, 0) - minus.get(k, 0))} for k, t, f in S.LEADERBOARDS if k not in S.NOT_ADJUSTABLE]


@app.get("/api/servers/{sid}/leaderboard/adjust/{uuid}")
async def get_board_adjust(sid: str, uuid: str, request: Request):
    """Admin: a player's numbers on the boards that can be adjusted: the game's, what's taken off, what shows."""
    auth.require_admin(request)
    srv = await _server(sid)
    return await asyncio.to_thread(_board_rows, srv, uuid)


@app.put("/api/servers/{sid}/leaderboard/adjust/{uuid}")
async def put_board_adjust(sid: str, uuid: str, request: Request):
    """Admin: what a player's board shows from now on: a number (0: don't count what's happened so far), or null to
    show the game's own number again. keys: one board or several. The game's statistics aren't touched."""
    user = auth.require_admin(request)
    srv = await _server(sid)
    body = await _body(request)
    keys = body.get("keys") or ([body["key"]] if body.get("key") else [])
    allowed = {k for k, _t, _f in S.LEADERBOARDS if k not in S.NOT_ADJUSTABLE}
    if not keys or any(k not in allowed for k in keys):
        raise HTTPException(400, "Pick a board that can be adjusted")
    to = body.get("to")
    raw = await asyncio.to_thread(S.player_board_values, srv, uuid)
    for k in keys:
        if to is None:
            S.set_board_adjustment(sid, uuid, k, None)
            continue
        try:
            n = int(to)
        except (TypeError, ValueError):
            raise HTTPException(400, "A whole number") from None
        if n < 0 or n > raw.get(k, 0):
            raise HTTPException(400, f"Between 0 and the game's own number ({raw.get(k, 0)})")
        S.set_board_adjustment(sid, uuid, k, raw.get(k, 0) - n)
    name = S.known_players(srv).get(uuid, {}).get("name", uuid)
    auth.audit(user, sid, "leaderboard:adjust", f"{name}: {', '.join(keys)} " + ("back to the game's numbers" if to is None else f"shown as {to}"))
    return await asyncio.to_thread(_board_rows, srv, uuid)


@app.get("/api/traffic")
async def traffic_report(request: Request, days: int = 1):
    """Manage → Solstone: what the website answered, by who, by hour, how quick; and the container's own network."""
    user = auth.require_admin(request)
    return await asyncio.to_thread(traffic.report, user.username, max(1, min(30, days)))


@app.post("/api/public/read")
async def public_read(request: Request):
    """A website page reporting itself: opened, read to the end, how long it was on screen (reading.py). Admins'
    own visits aren't counted; nobody's named."""
    body = await _body(request)
    page = str(body.get("page") or "")[:120]
    if not reading.page_ok(page) or reading.is_bot(request.headers.get("user-agent", "")):
        return {"ok": True, "counted": False}
    title = str(body.get("title") or "")[:120]
    if page.startswith("/post/"):                     # a post's own title (and only posts that are really there)
        p = await asyncio.to_thread(site.post, page[6:])
        if not p:
            return {"ok": True, "counted": False}
        title = p["title"]
    try:
        secs = float(body.get("secs") or 0)
    except (TypeError, ValueError):
        secs = 0
    ok = await asyncio.to_thread(reading.note, page, title, str(body.get("event") or ""), str(body.get("id") or ""),
                                 getattr(request.state, "user", None), auth.client_ip(request), secs)
    return {"ok": True, "counted": ok}


@app.get("/api/reading")
async def reading_report(request: Request, days: int = 30):
    """Manage → Solstone: what people read on the website (views, people, read to the end, time on it)."""
    auth.require_admin(request)
    return await asyncio.to_thread(reading.report, max(1, min(730, days)))


@app.get("/api/servers/{sid}/stats/history")
async def stats_history(sid: str, since: float = 0):
    """The Stats tab: each day's totals (kept for good) and hours played by weekday and hour. Server-wide only."""
    srv = await _server(sid)
    return await asyncio.to_thread(serverstats.history, srv.id, max(0.0, since))


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
    if "hidden" in body:                     # shown or hidden by an admin: no longer "new"
        body["new"] = ""
    if "join_color" in body:                 # a border colour for its card: #rrggbb, or nothing
        c = str(body["join_color"] or "").strip().lower()
        body["join_color"] = c if re.fullmatch(r"#[0-9a-f]{6}", c) else ""
    for k, n in (("join_address", 80), ("join_bedrock_address", 80), ("join_note", 300), ("join_check", 80), ("join_xbox", 20)):
        if k in body:
            body[k] = " ".join(str(body[k] or "").split())[:n]
    if body.get("join_xbox") and not re.fullmatch(r"[A-Za-z0-9 #]{1,20}", body["join_xbox"]):
        raise HTTPException(400, "An Xbox gamertag is letters, numbers and spaces")
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


@app.get("/api/solstone-storage")
async def solstone_storage(request: Request):
    """How much room Solstone takes, and what in it grows (storage.py)."""
    auth.require_admin(request)
    return await asyncio.to_thread(storage.cached_report)


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


# ---- messages an admin sends into the game (Website → Game messages): now, at everyone's next join, or to one player
@app.get("/api/servers/{sid}/game-messages")
async def list_game_messages(sid: str, request: Request):
    auth.require_admin(request)
    srv = await _server(sid)
    return {"messages": gamemsg.listing(srv.id)}


@app.post("/api/servers/{sid}/game-messages")
async def send_game_message(sid: str, request: Request):
    user = auth.require_admin(request)
    srv = await _server(sid)
    body = await _body(request)
    player = str(body.get("player") or "").strip()
    if player and not mcname.is_name(player):
        raise HTTPException(400, "That isn't a Minecraft name")
    try:
        online = (await S.online_players(srv))[0] if srv.rcon_conf() else []
    except Exception:
        online = []
    if body.get("to") == "online" and not online:
        raise HTTPException(400, "Nobody's playing right now. Send it to everyone the next time they join instead")
    try:
        item = await gamemsg.create(srv, str(body.get("text") or ""), str(body.get("to") or ""), player, user.username, online)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    auth.audit(user, srv.id, "game_message", item["to"] + (f" {item['player']}" if item["player"] else ""))
    return item


@app.delete("/api/servers/{sid}/game-messages/{mid}")
async def remove_game_message(sid: str, mid: str, request: Request):
    user = auth.require_admin(request)
    srv = await _server(sid)
    if not gamemsg.remove(srv.id, mid):
        raise HTTPException(404, "No such message")
    auth.audit(user, srv.id, "game_message_removed", mid)
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
        daily = [{"date": d["date"], "players": {n: 1 for n, v in d["players"].items() if v > 0}}
                 for d in stacks.daily([{**d, "players": {n: v for n, v in d["players"].items() if n.lower() not in gone}}
                                        for d in db.daily_playtime(srv.id, days)])]
        return {"daily": daily, "sessions": [], "durations": False,
                "recorder_since": (db.q("SELECT MIN(ts) AS t FROM metrics WHERE server_id=?", (srv.id,))[0]["t"])}
    return {
        "durations": True,
        "daily": stacks.daily([{**d, "players": {n: v for n, v in d["players"].items() if n.lower() not in gone}} for d in db.daily_playtime(srv.id, days)]),
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
        reqs.append({**{k: r.get(k) for k in ("player", "name", "note", "ts", "asked_as")}, "bedrock": mcname.is_bedrock(r["player"]), "servers": each})
    return reqs


# ---- forgetting a player (Manage → Players → Whitelist → Removing a player): forget.py
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
    """Manage → Players → Whitelist: everyone who asked to join (with each server they asked for, in or not yet), everyone the
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
    # answered lately: let in or denied, and whether they've seen it. Someone let in whose page hasn't checked back
    # yet is still in the requests (it moves over when they look): shown here too, as not seen yet.
    by_id = {s.id: s for s in servers}
    let_in = []
    for r in site.join_requests():
        want = [x for x in (r.get("servers") or list(by_id)) if x in by_id]
        if r.get("admin_cleared"):
            continue
        if want and all(x in (r.get("done") or []) or S.whitelisted(by_id[x], None, r["player"]) for x in want):
            let_in.append({"player": r["player"], "name": r.get("name"), "ts": r.get("ts"), "ts_in": r.get("let_in_at") or r.get("ts"),
                           "denied": False, "reason": "", "seen": None})
    answered = sorted(let_in + site.answered_lately(), key=lambda a: -(a.get("ts_in") or 0))[:20]
    return {"servers": out_servers, "requests": reqs, "blocked": sorted(blocked.values(), key=lambda b: -b["ts"]),
            "answered": answered}


@app.post("/api/whitelist/answered/clear")
async def clear_answered(request: Request):
    """Take one player (or everyone) off Answered lately: only the admins' list; their own page still knows."""
    auth.require_admin(request)
    body = await _body(request)
    player = str(body.get("player") or "").strip() or None
    return {"cleared": await asyncio.to_thread(site.clear_answered, player)}


@app.post("/api/whitelist/rename")
async def rename_request(request: Request):
    """Fix the name on a request to join (typed wrong). They still hear they're in on the page where they asked."""
    user = auth.require_admin(request)
    body = await _body(request)
    old, to = str(body.get("player") or ""), str(body.get("to") or "").strip()
    if not mcname.is_name(to):
        raise HTTPException(400, "That isn't a Minecraft name: letters, numbers and _ (and a . in front for Bedrock)")
    if not site.rename_join_request(old, to):
        raise HTTPException(404, "That request isn't there any more")
    auth.audit(user, None, "join_request_renamed", f"{old} → {to}")
    return {"ok": True, "player": to}


@app.get("/api/whitelist/whois")
async def whitelist_whois(sid: str, name: str, request: Request):
    """Who a name on a server's whitelist really is: its id there, the Xbox gamertag or Java name that id belongs to
    now, and whether that player has played on the server (and under what name)."""
    auth.require_admin(request)
    srv = await _server(sid)
    def read():
        try:
            return json.loads((srv.dir / "whitelist.json").read_text()) or []
        except (OSError, ValueError):
            return []
    entry = next((e for e in await asyncio.to_thread(read) if str(e.get("name", "")).lower() == name.lower()), None)
    if not entry or not entry.get("uuid"):
        raise HTTPException(404, f"{name} isn't on {srv.display_name}'s whitelist")
    out = await control.whose(str(entry["uuid"]))
    kp = await asyncio.to_thread(S.known_players, srv)
    want = str(entry["uuid"]).replace("-", "").lower()
    known = next((p for u, p in kp.items() if u.replace("-", "").lower() == want), None)
    out.update(name=entry.get("name"), played=bool(known), played_as=(known or {}).get("name"))
    return out


@app.post("/api/whitelist/deny")
async def deny_request(request: Request):
    """Say no to someone who asked to join: off the Asked to join list, and their page says it wasn't accepted."""
    user = auth.require_admin(request)
    body = await _body(request)
    player = str(body.get("player") or "")
    if not site.deny_join_request(player, str(body.get("reason") or "")):
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
    # the activity lines (every few minutes, per player) as counts, so the page can add them up into one row per
    # player instead of a line each time ("⚔️ 34 monsters · ⛏️ 1,240 dug")
    for it in data.get("items") or []:
        for e in it.get("events") or ([it] if it.get("kind") == "event" else []):
            if e.get("type") == "progress":
                e["tally"] = adventures.tally(e.get("message") or "")
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
async def player_history(sid: str, uuid: str, days: int = 30, together: bool = False):
    """One player's days, sessions and activity; with together=1, all of their person's linked accounts at once
    (each day's time split by account, so the chart can show whose it was)."""
    if not _own(uuid):
        raise HTTPException(404, "Player not found")
    srv = await _server(sid)
    p = S.known_players(srv).get(S.norm_uuid(uuid))
    if not p:
        raise HTTPException(404, "Player not found")
    days = max(1, min(days, 90))
    t = await asyncio.to_thread(stacks.together, srv, p["name"]) if together else None
    names = [a["name"] for a in t["accounts"]] if t else [p["name"]]
    daily: dict[str, dict[str, float]] = {}
    for n in names:
        for d in db.daily_playtime(srv.id, days, n):
            daily.setdefault(d["date"], {})[n] = sum(d["players"].values())
    days_list = [{"date": k, "players": v} for k, v in sorted(daily.items())]
    events = sorted((e for n in names for e in db.events(srv.id, None, n, 60)), key=lambda e: -e["ts"])[:60]
    if not _shows_play_time():             # which days they played, not for how long
        return {"daily": [{"date": d["date"], "played": sum(d["players"].values()) > 0} for d in days_list], "sessions": [],
                "events": events, "durations": False, "names": names}
    return {
        "daily": [{"date": d["date"], "seconds": sum(d["players"].values()), "players": d["players"]} for d in days_list],
        "sessions": sorted((x for n in names for x in db.sessions(srv.id, n, limit=30)), key=lambda x: -x["start"])[:30],
        "events": events,
        "durations": True,
        "names": names,
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
            "admin": await asyncio.to_thread(community.unread_admin) if user.role == "admin" else 0, "requests": requests,
            "votes": len(await asyncio.to_thread(community.unvoted, f"u{user.id}"))}


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
        raise HTTPException(400, "You're an admin: players' messages are in Manage → Community → Messages, and you write to them from there")
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
        errors = await notify.send("Solstone weekly digest", text, notify.TAGS["digest"], force=True, kind="digest")
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


@app.get("/api/settings/notifications/log")
async def notifications_log(request: Request, limit: int = 200):
    """Admins: the notifications sent (or held back by quiet hours), newest first, and how many of each kind."""
    auth.require_admin(request)
    out = await asyncio.to_thread(notify.history, limit)
    names = {s.id: s.display_name for s in S.registry.servers.values()}
    for e in out["entries"]:
        e["server"] = names.get(e.get("sid") or "", "")
    return out


@app.delete("/api/settings/notifications/log")
async def notifications_log_clear(request: Request):
    user = auth.require_admin(request)
    await asyncio.to_thread(notify.clear_history)
    auth.audit(user, None, "notifications_log_cleared", "")
    return {"ok": True}


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
        "can_crafty": bool((c := connections.for_server(srv)) and c.enabled) or srv.panel is not None,
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
        "xbox": xboxwatch.status(srv.id, bool(recorder._running_state.get(srv.id)), bool(srv.settings.get("join_xbox")), admin=True),
        "xbox_gamertag": srv.settings.get("join_xbox") or "",
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
    return {"kinds": challenges.kinds(await asyncio.to_thread(tide.installed, srv)), "items": eventgroups.tag(optin.annotate("contest", challenges.list_for(srv.id))), "gifts": challenges.gifts_for(srv.id),
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
    evs = db.events(srv.id, ["fish", "bigfish"], None, 40)
    return {"rcon": bool(srv.rcon_conf()), "guide": fishpack.guide(), "qualities": fishpack.qualities(),
            "tide": await asyncio.to_thread(tide.installed, srv),
            "recent": [{"ts": e["ts"], "player": e["player"], "message": e["message"]} for e in evs]}


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


# ---- games: hide and seek and the treasure hunt
@app.get("/api/servers/{sid}/games")
async def get_games(sid: str, request: Request):
    auth.require_admin(request)
    srv = await _server(sid)
    w = await asyncio.to_thread(S.world_info, srv, False) if srv.is_java else {}
    return {"runs": eventgroups.tag(optin.annotate("game", games.runs_for(srv.id))), "rcon": bool(srv.rcon_conf()),
            "spawn": w.get("spawn"), "now": time.time(), "rcon_echo": _rcon_echo(srv),
            "in_vault": [s["name"] for s in kits.waiting(srv.id)]}                  # players whose things are kept safe


@app.post("/api/servers/{sid}/kits/give-back")
async def kit_give_back(sid: str, request: Request):
    """An admin, by hand: give a player their own things back from the vault now (they need to be online)."""
    user = auth.require_admin(request)
    srv = await _server(sid)
    name = str((await _body(request)).get("player") or "").lower()
    s = next((x for x in kits.waiting(srv.id) if x["name"].lower() == name), None)
    if not s:
        raise HTTPException(404, "Nothing of theirs is in the vault")
    if not await kits.give_back(srv, s["uuid"]):
        raise HTTPException(409, f"{s['name']} needs to be online (they'll get everything back automatically when they are)")
    auth.audit(user, srv.id, "kit_give_back", s["name"])
    return {"ok": True}


@app.post("/api/servers/{sid}/kits/discard")
async def kit_discard(sid: str, request: Request):
    """An admin, by hand: throw away what's kept for a player (leftover copies of things they already have)."""
    user = auth.require_admin(request)
    srv = await _server(sid)
    name = str((await _body(request)).get("player") or "").lower()
    s = next((x for x in kits.waiting(srv.id) if x["name"].lower() == name), None)
    if not s or not await kits.discard(srv, s["uuid"]):
        raise HTTPException(404, "Nothing of theirs is in the vault")
    auth.audit(user, srv.id, "kit_discard", s["name"])
    return {"ok": True}


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
    return {"items": out, "online": names, "can_send": bool(srv.rcon_conf() or srv.managed)}


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
    """The old status page: how each server is doing is at the top of the home page now."""
    return RedirectResponse("/", status_code=301)


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


ASSET_NAMES = ("app.css", "sky.js", "showbar.js", "hud.js", "board.js", "recap.js", "login.js", "app.js", "history.js", "control.js", "play.js", "editor.js", "fwsettings.js", "announce.js", "home.js", "postfmt.js", "guides.js", "website.js", "adventures.js", "playtime.js", "community.js", "stats.js")


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
    cfg = site.config()
    return (_template(name).replace("{{VERSION}}", VERSION).replace("{{SITE_NAME}}", _html_escape(cfg["name"]))
            .replace("{{SITE_LOGO}}", _html_escape(site.logo_url())).replace("{{UNITS}}", cfg.get("units") or "km"))


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
