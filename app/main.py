"""Solstone — a family-friendly dashboard for Minecraft servers run by Crafty Controller."""
from __future__ import annotations

import asyncio
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

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import auth, backups, board, control, db, fireworks, fwshow, guard, music, notify, recap, skins, worldmap
from . import servers as S
from . import settings_store
from .recorder import recorder
from .assets import assets_for, safe_texture_path, store
from .config import config
from .crafty import crafty

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("solstone")
STATIC = Path(__file__).parent / "static"
VERSION = "1.0.0"


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
class _GZipExceptMusic(GZipMiddleware):
    """Compress API and page responses, but stream music as-is (it's already compressed,
    and the browser needs byte ranges to seek)."""

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"].startswith("/api/public/music/"):
            await self.app(scope, receive, send)
            return
        await super().__call__(scope, receive, send)


app.add_middleware(_GZipExceptMusic, minimum_size=1024)

PUBLIC_API = {"/api/health", "/api/auth/login"}
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


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
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    return response


async def _server(sid: str) -> S.Server:
    srv = await S.registry.get(sid)
    if not srv:
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
STATUS_DEFAULTS = {"enabled": False, "show_positions": True, "show_items": True,
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
    return [s for s in S.registry.servers.values() if not s.settings.get("hidden")]


async def _public_server(sid: str) -> S.Server:
    srv = await S.registry.get(sid)
    if not srv or srv.settings.get("hidden"):
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
        except Exception as e:
            log.debug("status page world info failed for %s: %s", srv.id, e)
    if summ["running"] is not False and summ["online"]:
        overview = await S.players_overview(srv)
        sessions = {s["player"].lower(): s["start"] for s in db.sessions(srv.id, limit=50) if s["open"]}
        online = [p for p in overview["players"] if p["online"]]
        details = await asyncio.gather(*(_maybe_live(srv, p) for p in online))
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
                if cfg["show_positions"]:
                    row["position"] = {k: d["position"][k] for k in ("x", "y", "z")}
                if cfg["show_items"]:
                    inv = d["inventory"]
                    sel = d.get("selected_slot", 0)
                    row["held"] = _public_item(inv["hotbar"][sel] if 0 <= sel < 9 else None, lang)
                    row["armor"] = [_public_item(inv["armor"][k], lang) for k in ("head", "chest", "legs", "feet")]
            board["players"].append(row)
    if cfg["show_activity"]:
        evs = db.events(srv.id, ["join", "leave", "death", "advancement", "level", "server"], None, 14)
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
    servers = _board_servers()
    if sid and not any(x.id == sid for x in servers):
        sid = ""
    items = await asyncio.to_thread(board.active, where, sid or None, signed_in or status_on, None, servers)
    return JSONResponse({"now": time.time(), "items": items}, headers={"Cache-Control": "no-store"})


@app.get("/api/board")
async def get_board(request: Request):
    auth.require_admin(request)
    await S.registry.refresh()
    players: dict[str, str] = {}
    for srv in S.registry.servers.values():
        for p in S.known_players(srv).values():
            players.setdefault(p["name"].lower(), p["name"])
    return {**board.config(), "players": sorted(players.values(), key=str.lower),
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
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "max-age=60"})


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
async def public_skin(sid: str, uuid: str):
    """Skins for the status page: only players who have joined a visible server."""
    _require_status()
    srv = await _public_server(sid)
    if S.norm_uuid(uuid) not in S.known_players(srv):
        raise HTTPException(404)
    return await _skin_response(uuid, "public, max-age=3600")


async def _skin_response(uuid: str, cache: str) -> Response:
    data = await skins.skin(uuid)
    if not data:
        raise HTTPException(404)
    return Response(data, media_type="image/png", headers={"Cache-Control": cache})


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
    signed_in = request.state.user is not None
    return JSONResponse({**_fireworks_cfg(), "custom": _show_designs(), **fwshow.today_state(), "base_shows": fwshow.base_shows_resolved(),
                         "music": signed_in or (music.public() and _status_cfg()["enabled"])},
                        headers={"Cache-Control": "no-cache"})


@app.get("/api/public/fireworks/feed")
async def firework_feed(request: Request, since: int = -1):
    """Fireworks set off by things happening in the game. Player names only for people
    signed in, or when the public status page (which shows them anyway) is on."""
    names = request.state.user is not None or _status_cfg()["enabled"]
    return JSONResponse(fwshow.feed_since(since, names), headers={"Cache-Control": "no-store"})


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
            "servers": [{"id": x.id, "name": x.display_name} for x in S.registry.servers.values() if x.is_java and not x.settings.get("hidden")],
            "music": {"tracks": music.main_tracks(), "public": music.public()}}


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
    visible = [x for x in S.registry.servers.values() if x.is_java and not x.settings.get("hidden")]
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
    for srv in S.registry.servers.values():
        for u, p in S.known_players(srv).items():
            seen.setdefault(p["name"].lower(), {"name": p["name"], "uuid": u})
    return sorted(seen.values(), key=lambda x: x["name"].lower())


# ---- music: the main library, an external library, playlists and the radio
def _music_allowed(request: Request) -> None:
    if request.state.user is None and not (music.public() and _status_cfg()["enabled"]):
        raise HTTPException(404)


def _is_admin(request: Request) -> bool:
    return request.state.user is not None and request.state.user.role == "admin"


def _radio_payload() -> dict:
    r = music.radio()
    return {"radio": {"id": r["id"], "name": r["name"], "why": r["why"]}, "tracks": r["tracks"]}


@app.get("/api/public/music")
async def music_radio(request: Request):
    """What plays by default (everyone, and the public status page)."""
    _music_allowed(request)
    return await asyncio.to_thread(_radio_payload)


def _track_for(request: Request, tid: str) -> dict:
    """A track this visitor may play: anything visible when signed in, only the radio when not."""
    _music_allowed(request)
    if request.state.user is not None:
        t = music.get(tid, include_hidden=_is_admin(request))
        if t and (t.get("status", "ok") != "blocked"):
            return t
        raise HTTPException(404)
    t = next((x for x in music.radio()["tracks"] if x["id"] == tid), None)
    if not t:
        raise HTTPException(404)
    return t


@app.get("/api/public/music/{tid}")
async def music_file(tid: str, request: Request):
    t = await asyncio.to_thread(_track_for, request, tid)
    found = music.file_of(t)
    if not found:
        raise HTTPException(404)
    path, media = found
    return FileResponse(path, media_type=media, headers={"Cache-Control": "private, max-age=86400"})


@app.get("/api/public/music/{tid}/art")
async def music_art(tid: str, request: Request):
    t = await asyncio.to_thread(_track_for, request, tid)
    art = await asyncio.to_thread(music.art_of, t)
    if art is None:
        raise HTTPException(404)
    if isinstance(art, Path):
        return FileResponse(art, headers={"Cache-Control": "private, max-age=86400"})
    data, mime = art
    return Response(data, media_type=mime if mime.startswith("image/") else "image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


@app.get("/api/music/library")
async def music_library(request: Request, q: str = "", artist: str = "", album: str = "", source: str = "", status: str = "",
                        offset: int = 0, limit: int = 100):
    admin = _is_admin(request)
    return await asyncio.to_thread(music.search, q, artist, album, source, admin, status if admin else "", max(0, offset), limit)


@app.get("/api/music/albums")
async def music_albums(request: Request, q: str = ""):
    return await asyncio.to_thread(music.albums, q, _is_admin(request))


@app.get("/api/music/artists")
async def music_artists(request: Request, q: str = ""):
    return await asyncio.to_thread(music.artists, q, _is_admin(request))


def _playlist_out(p: dict, user, with_tracks: bool = False) -> dict:
    out = {**p, "count": len(p["tracks"]), "can_edit": music.can_edit(p, user), "mine": p["owner"] == user.username}
    if with_tracks:
        out["items"] = music.by_id(p["tracks"])
    if not with_tracks:
        out.pop("tracks")
    return out


@app.get("/api/music/playlists")
async def music_playlists(request: Request):
    user = request.state.user
    radio = await asyncio.to_thread(music.radio)
    return {"playlists": [_playlist_out(p, user) for p in music.playlists() if music.can_see(p, user)],
            "radio": {"id": radio["id"], "name": radio["name"], "why": radio["why"]}, "radio_default": music.radio_settings()["default"]}


@app.get("/api/music/playlists/{pid}")
async def music_playlist(pid: str, request: Request):
    p = music.playlist(pid)
    if not p or not music.can_see(p, request.state.user):
        raise HTTPException(404)
    return await asyncio.to_thread(_playlist_out, p, request.state.user, True)


@app.post("/api/music/playlists")
async def music_playlist_create(request: Request):
    user = request.state.user
    body = await _body(request)
    body["_admin"] = user.role == "admin"
    try:
        p = music.create_playlist(body, user.username)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return _playlist_out(p, user)


@app.put("/api/music/playlists/{pid}")
async def music_playlist_update(pid: str, request: Request):
    user = request.state.user
    p = music.playlist(pid)
    if not p or not music.can_edit(p, user):
        raise HTTPException(404, "No such playlist, or it isn't yours")
    body = await _body(request)
    new = music.update_playlist(pid, body, user.role == "admin")
    if "radio_default" in body and user.role == "admin":
        music.set_radio_default(pid if body["radio_default"] else "")
    return await asyncio.to_thread(_playlist_out, new, user, True)


@app.delete("/api/music/playlists/{pid}")
async def music_playlist_delete(pid: str, request: Request):
    user = request.state.user
    p = music.playlist(pid)
    if not p or not music.can_edit(p, user):
        raise HTTPException(404, "No such playlist, or it isn't yours")
    music.delete_playlist(pid)
    return {"ok": True}


@app.get("/api/music/queue")
async def music_queue(request: Request, type: str = "radio", id: str = ""):
    """The tracks for something to play: the radio, a playlist, an album, an artist, or everything."""
    user = request.state.user
    if type == "playlist":
        p = music.playlist(id)
        if not p or not music.can_see(p, user):
            raise HTTPException(404)
        return {"name": p["name"], "tracks": await asyncio.to_thread(music.by_id, p["tracks"])}
    if type == "album":
        r = await asyncio.to_thread(music.search, "", "", id, "", False, "", 0, 500)
        return {"name": r["tracks"][0]["album"] if r["tracks"] else "Album", "tracks": r["tracks"]}
    if type == "artist":
        r = await asyncio.to_thread(music.search, "", id, "", "", False, "", 0, 500)
        return {"name": id, "tracks": r["tracks"]}
    if type == "ids":
        return {"name": "Picked songs", "tracks": await asyncio.to_thread(music.by_id, [x for x in id.split(",") if x][:500])}
    if type == "main":
        return {"name": "Main library", "tracks": [t for t in await asyncio.to_thread(music.all_tracks) if t["source"] == "main"]}
    r = await asyncio.to_thread(music.radio)
    return {"name": r["name"], "tracks": r["tracks"]}


@app.get("/api/music/settings")
async def music_settings(request: Request):
    auth.require_admin(request)
    r = music.rules()
    return {"public": music.public(), "mode": r["mode"], "blocked": r["blocked"], "approved": r["approved"],
            "radio_default": music.radio_settings()["default"], "external": music.external_status(), "main": music.main_tracks()}


@app.put("/api/music/settings")
async def music_settings_put(request: Request):
    user = auth.require_admin(request)
    body = await _body(request)
    if isinstance(body.get("public"), bool):
        music.update(public_flag=body["public"])
    if body.get("mode") in ("all", "approved"):
        music.set_mode(body["mode"])
    if "radio_default" in body:
        music.set_radio_default(str(body["radio_default"] or ""))
    auth.audit(user, None, "music_settings", ", ".join(k for k in body))
    return await music_settings(request)


@app.post("/api/music/rule")
async def music_rule(request: Request):
    """Block (or approve) a song, an album or an artist. Blocked music can't be listed or played anywhere."""
    user = auth.require_admin(request)
    body = await _body(request)
    try:
        r = music.set_rule(str(body.get("action")), str(body.get("kind")), str(body.get("value") or ""), bool(body.get("on", True)))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    auth.audit(user, None, f"music_{body.get('action')}", f"{body.get('kind')}: {body.get('value')} {'on' if body.get('on', True) else 'off'}")
    return r


@app.put("/api/music/tracks/{tid}")
async def music_retag(tid: str, request: Request):
    """Fix the title, artist or album of a song uploaded through Solstone (and re-file it)."""
    user = auth.require_admin(request)
    body = await _body(request)
    t = await asyncio.to_thread(music.retag_uploaded, tid, str(body.get("title") or "").strip()[:120],
                                str(body.get("artist") or "").strip()[:120], str(body.get("album") or "").strip()[:120])
    if not t:
        raise HTTPException(404, "Only music uploaded through Solstone can be changed")
    auth.audit(user, None, "music_retag", t["title"])
    return t


@app.post("/api/music/move-uploads")
async def music_move_uploads(request: Request):
    user = auth.require_admin(request)
    try:
        r = await asyncio.to_thread(music.move_main_into_library)
    except ValueError as e:
        raise HTTPException(409, str(e)) from e
    auth.audit(user, None, "music_move_uploads", f"{r['moved']} songs")
    return r


@app.post("/api/music/rescan")
async def music_rescan(request: Request):
    auth.require_admin(request)
    if not music.external_root():
        raise HTTPException(409, "No music folder is set up (MUSIC_LIBRARY_DIR)")
    asyncio.get_running_loop().run_in_executor(None, music.scan)
    return music.external_status()


@app.post("/api/music")
async def music_upload(request: Request, title: str = "", filename: str = "", force: bool = False):
    user = auth.require_admin(request)
    ext = music.ext_for(request.headers.get("content-type", ""), filename)
    if not ext:
        raise HTTPException(415, "That doesn't look like an audio file (MP3, OGG, M4A, WAV, FLAC or Opus).")
    music.DIR.mkdir(parents=True, exist_ok=True)
    tmp = music.DIR / f".upload-{secrets.token_hex(6)}"
    size = 0
    try:
        with tmp.open("wb") as fh:
            async for chunk in request.stream():
                size += len(chunk)
                if size > music.MAX_BYTES:
                    raise HTTPException(413, f"Files can be up to {music.MAX_BYTES // 1024 // 1024} MB.")
                fh.write(chunk)
        if size == 0:
            raise HTTPException(400, "The file was empty")
        name = title or re.sub(r"\.[^.]+$", "", filename)
        if music.upload_root():           # into the library's Solstone folder, sorted by artist and album
            t = await asyncio.to_thread(music.file_upload, tmp, ext, name, force)
        else:
            t = await asyncio.to_thread(music.add, tmp, ext, name, size)
    except FileExistsError as e:
        raise HTTPException(409, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    finally:
        tmp.unlink(missing_ok=True)
    auth.audit(user, None, "music_upload", t["title"])
    return t


@app.put("/api/music")
async def music_update(request: Request):
    auth.require_admin(request)
    body = await _body(request)
    return music.update(body.get("order") if isinstance(body.get("order"), list) else None,
                        body.get("titles") if isinstance(body.get("titles"), dict) else None,
                        body.get("public") if isinstance(body.get("public"), bool) else None)


@app.delete("/api/music/{tid}")
async def music_delete(tid: str, request: Request):
    """Uploaded music only: Solstone never deletes anything else in the library (block it instead)."""
    user = auth.require_admin(request)
    if not music.delete(tid) and not await asyncio.to_thread(music.delete_uploaded, tid):
        raise HTTPException(404, "Only music uploaded through Solstone can be deleted; block anything else")
    auth.audit(user, None, "music_delete", tid)
    return {"ok": True}


# ---- the Firework editor: anyone signed in can make fireworks; people can change their
# own, and admins can change or remove anyone's.
def _can_edit(user, d: dict) -> bool:
    return user.role == "admin" or d.get("author") == user.username


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


@app.post("/api/fireworks")
async def create_firework(request: Request):
    user = request.state.user
    try:
        d = fireworks.create(await _body(request), user.username)
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
    resp = JSONResponse({"user": user.public()})
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
    return {"user": auth.require_user(request).public(), "version": VERSION}


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
    u = auth.create_user(str(body.get("username", "")).strip(), str(body.get("password", "")), str(body.get("role", "viewer")))
    auth.audit(admin, None, "add_user", f"{u.username} ({u.role})")
    return u.public()


@app.patch("/api/users/{uid}")
async def edit_user(uid: int, request: Request):
    admin = auth.require_admin(request)
    body = await _body(request)
    u = auth.update_user(uid, role=body.get("role") or None, password=body.get("password") or None)
    changes = ", ".join(k for k in ("role", "password") if body.get(k))
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
    for srv in S.registry.servers.values():
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
async def player_skin(uuid: str):
    return await _skin_response(uuid, "private, max-age=3600")


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


@app.get("/{full_path:path}", include_in_schema=False)
async def spa(full_path: str):
    if full_path.startswith("api/"):
        raise HTTPException(404)
    return HTMLResponse(_page("index.html"), headers={"Cache-Control": "no-cache"})


ASSET_NAMES = ("app.css", "sky.js", "showbar.js", "hud.js", "board.js", "recap.js", "login.js", "app.js", "history.js", "control.js", "editor.js", "fwsettings.js", "announce.js", "music.js", "status.js")


def _asset_stamp() -> str:
    files = [STATIC / n for n in ASSET_NAMES]
    return format(int(max(f.stat().st_mtime for f in files if f.exists())), "x")


def _page(name: str) -> str:
    """An HTML page with ?v= on the CSS/JS links so browsers pick up new versions after an update."""
    stamp = _asset_stamp()
    html = (STATIC / name).read_text(encoding="utf-8")
    for n in ASSET_NAMES:
        html = html.replace(f"/static/{n}\"", f"/static/{n}?v={stamp}\"")
    return html
