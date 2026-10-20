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
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import auth, backups, control, db, fireworks, fwshow, guard, music, notify, skins
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
                                  "raining": w.get("raining"), "thundering": w.get("thundering")}
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
        evs = db.events(srv.id, ["join", "leave", "death", "advancement", "server"], None, 14)
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
        return {"enabled": False, "servers": []}
    if _list_cache and time.monotonic() - _list_cache[0] < 15:
        return {"enabled": True, "servers": _list_cache[1]}
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
    return {"enabled": True, "servers": out}


@app.get("/api/public/status/{sid}")
async def public_board(sid: str):
    cfg = _require_status()
    board = await _board(await _public_server(sid), cfg)
    return JSONResponse(board, headers={"Cache-Control": "no-store"})


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


def _fireworks_cfg() -> dict:
    saved = settings_store.load().get("fireworks", {})
    kinds = saved.get("kinds") if isinstance(saved.get("kinds"), dict) else {}
    colors = [c for c in saved.get("colors", []) if c in FIREWORK_COLORS] if isinstance(saved.get("colors"), list) else []
    return {
        "kinds": {k: bool(kinds.get(k, True)) for k in FIREWORK_KINDS},
        "colors": colors or list(FIREWORK_COLORS),
        "pace": saved.get("pace") if saved.get("pace") in FIREWORK_PACE else "normal",
        "showpieces": saved.get("showpieces") if saved.get("showpieces") in FIREWORK_SPECIALS else "sometimes",
    }


@app.get("/api/public/fireworks")
async def public_fireworks(request: Request):
    signed_in = request.state.user is not None
    return JSONResponse({**_fireworks_cfg(), "custom": fireworks.in_show(), **fwshow.today_state(),
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
            "music": {"tracks": music.tracks(), "public": music.public()}}


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
    auth.audit(user, None, "fireworks_show", ", ".join(sorted(k for k in body if k in ("events", "signatures", "calendar"))))
    return await get_firework_show(request)


@app.post("/api/fireworks/test-event")
async def test_firework_event(request: Request):
    """Pretend an event happened, to see what it sets off."""
    auth.require_admin(request)
    body = await _body(request)
    ev = body.get("event")
    if ev not in fwshow.EVENT_DEFAULTS:
        raise HTTPException(400, "Unknown event")
    player = str(body.get("player") or "") or None
    fwshow.push("test", "Test", ev, player, f"Test: {ev}" + (f" for {player}" if player else ""))
    return {"ok": True}


# ---- music for the show
def _music_allowed(request: Request) -> None:
    if request.state.user is None and not (music.public() and _status_cfg()["enabled"]):
        raise HTTPException(404)


@app.get("/api/public/music")
async def music_list(request: Request):
    _music_allowed(request)
    return music.tracks()


@app.get("/api/public/music/{tid}")
async def music_file(tid: str, request: Request):
    _music_allowed(request)
    found = music.path_of(tid)
    if not found:
        raise HTTPException(404)
    path, media = found
    return FileResponse(path, media_type=media, headers={"Cache-Control": "private, max-age=86400"})


@app.post("/api/music")
async def music_upload(request: Request, title: str = "", filename: str = ""):
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
        t = await asyncio.to_thread(music.add, tmp, ext, title or re.sub(r"\.[^.]+$", "", filename), size)
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
    user = auth.require_admin(request)
    if not music.delete(tid):
        raise HTTPException(404)
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
    return fireworks.update(fid, await _body(request))


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
    if isinstance(body.get("kinds"), dict):
        cur["kinds"].update({k: bool(v) for k, v in body["kinds"].items() if k in FIREWORK_KINDS})
    if isinstance(body.get("colors"), list):
        picked = [c for c in FIREWORK_COLORS if c in body["colors"]]
        if not picked:
            raise HTTPException(400, "Pick at least one colour")
        cur["colors"] = picked
    if body.get("pace") in FIREWORK_PACE:
        cur["pace"] = body["pace"]
    if body.get("showpieces") in FIREWORK_SPECIALS:
        cur["showpieces"] = body["showpieces"]
    if not any(cur["kinds"].values()):
        raise HTTPException(400, "Leave at least one kind of firework on")
    settings_store.save_section("fireworks", cur)
    auth.audit(user, None, "fireworks_settings", f"{sum(cur['kinds'].values())} kinds, {len(cur['colors'])} colours, {cur['pace']}")
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


ASSET_NAMES = ("app.css", "sky.js", "showbar.js", "hud.js", "login.js", "app.js", "history.js", "control.js", "editor.js", "fwsettings.js", "status.js")


def _page(name: str) -> str:
    """An HTML page with ?v= on the CSS/JS links so browsers pick up new versions after an update."""
    files = [STATIC / n for n in ASSET_NAMES]
    stamp = format(int(max(f.stat().st_mtime for f in files if f.exists())), "x")
    html = (STATIC / name).read_text(encoding="utf-8")
    for n in ASSET_NAMES:
        html = html.replace(f"/static/{n}\"", f"/static/{n}?v={stamp}\"")
    return html
