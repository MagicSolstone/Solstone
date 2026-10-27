"""Accounts, permissions, server control commands, bedtime and the live console."""
import asyncio
import json
import struct
import threading
import time
from datetime import datetime

import pytest

import helpers
from app import auth, control, db, guard

RCON_PORT = 25998  # matches tests/helpers.py server.properties


# ---------------------------------------------------------------- fake RCON server
@pytest.fixture(scope="module")
def rcon(client, sid):
    """A Minecraft-like RCON server on the test server's port that records commands."""
    state = {"cmds": [], "replies": {"list": "There are 1 of a max of 10 players online: Tyler"}}
    loop = asyncio.new_event_loop()

    def pkt(rid, t, body: bytes):
        p = struct.pack("<ii", rid, t) + body + b"\0\0"
        return struct.pack("<i", len(p)) + p

    async def handle(r, w):
        try:
            while True:
                (ln,) = struct.unpack("<i", await r.readexactly(4))
                data = await r.readexactly(ln)
                rid, t = struct.unpack("<ii", data[:8])
                body = data[8:-2].decode()
                if t == 3:
                    w.write(pkt(rid if body == "hunter2" else -1, 2, b""))
                elif t == 2:
                    state["cmds"].append(body)
                    reply = state["replies"].get(body)
                    if reply is None:
                        reply = "Unknown or incomplete command, see below for error" if body.startswith("gamerule") else ""
                    w.write(pkt(rid, 0, reply.encode()))
                await w.drain()
        except (asyncio.IncompleteReadError, ConnectionResetError):
            pass

    async def start():
        return await asyncio.start_server(handle, "127.0.0.1", RCON_PORT)

    server = loop.run_until_complete(start())
    t = threading.Thread(target=loop.run_forever, daemon=True)
    t.start()

    from app import servers as S
    client.get("/api/servers")
    srv = S.registry.servers[sid]
    srv._rcon_backoff, srv.rcon_error, srv._rcon = 0.0, None, None
    S._live_cache.clear()
    control._rule_names.clear()
    yield state
    srv._rcon = None  # its connection belongs to this fixture's server; later tests expect RCON to be unreachable
    loop.call_soon_threadsafe(server.close)
    loop.call_soon_threadsafe(loop.stop)


# ---------------------------------------------------------------- auth
def test_login_required(anon):
    assert anon.get("/api/health").status_code == 200
    assert anon.get("/api/servers").status_code == 401
    assert anon.get("/api/auth/me").status_code == 401


def test_wrong_password_and_rate_limit(anon):
    for _ in range(auth.MAX_FAILS):
        assert anon.post("/api/auth/login", json={"username": "nobody", "password": "x"}).status_code == 401
    assert anon.post("/api/auth/login", json={"username": "nobody", "password": "x"}).status_code == 429
    auth._fails.clear()


def test_changes_need_csrf_header(client):
    from fastapi.testclient import TestClient

    from app.main import app
    bare = TestClient(app, cookies=client.cookies)
    assert bare.post("/api/auth/logout").status_code == 403


def test_viewer_is_read_only(viewer, sid):
    assert viewer.get("/api/servers").status_code == 200
    assert viewer.get(f"/api/servers/{sid}/players").status_code == 200
    assert viewer.get("/api/auth/me").json()["user"]["role"] == "trusted"
    for method, url in (("get", "/api/users"), ("get", f"/api/servers/{sid}/control"),
                        ("post", f"/api/servers/{sid}/control/command"), ("get", "/api/settings/notifications"),
                        ("get", f"/api/servers/{sid}/console/stream")):
        r = getattr(viewer, method)(url, **({"json": {"command": "list"}} if method == "post" else {}))
        assert r.status_code == 403, url


def test_user_management(client):
    r = client.post("/api/users", json={"username": "grandma", "password": "short", "role": "viewer"})
    assert r.status_code == 400
    u = client.post("/api/users", json={"username": "grandma", "password": "long-enough-1", "role": "viewer"}).json()
    assert client.post("/api/users", json={"username": "Grandma", "password": "long-enough-1"}).status_code == 409
    assert client.patch(f"/api/users/{u['id']}", json={"role": "admin"}).json()["role"] == "admin"
    assert client.delete(f"/api/users/{u['id']}").status_code == 200
    me = client.get("/api/auth/me").json()["user"]
    assert client.delete(f"/api/users/{me['id']}").status_code == 400  # not yourself
    assert client.patch(f"/api/users/{me['id']}", json={"role": "viewer"}).status_code == 400  # last admin
    actions = [a["action"] for a in client.get("/api/audit").json()]
    assert {"add_user", "edit_user", "delete_user"} <= set(actions)


def test_passwords_and_tokens_not_stored_plain(client):
    rows = db.q("SELECT password_hash FROM users")
    assert all(r["password_hash"].startswith("scrypt$") for r in rows)
    token = client.cookies.get(auth.COOKIE)
    assert token and not db.q("SELECT 1 FROM sessions_auth WHERE token_hash=?", (token,))


def test_change_password(client):
    from fastapi.testclient import TestClient

    from app.main import app
    client.post("/api/users", json={"username": "pwtest", "password": "first-pass-1", "role": "viewer"})
    c = TestClient(app, headers={"X-Solstone": "1"})
    c.post("/api/auth/login", json={"username": "pwtest", "password": "first-pass-1"})
    assert c.post("/api/auth/password", json={"current": "wrong", "new": "second-pass-2"}).status_code == 400
    assert c.post("/api/auth/password", json={"current": "first-pass-1", "new": "second-pass-2"}).status_code == 200
    assert c.get("/api/auth/me").status_code == 200  # still signed in with the new session
    c2 = TestClient(app, headers={"X-Solstone": "1"})
    assert c2.post("/api/auth/login", json={"username": "pwtest", "password": "second-pass-2"}).status_code == 200


# ---------------------------------------------------------------- command safety
@pytest.mark.parametrize("bad", ["Tyler kick", "Tyler;op", "@a", "x" * 17, "", "Ty ler"])
def test_bad_player_names_rejected(client, sid, bad):
    r = client.post(f"/api/servers/{sid}/control/player/{bad or '_'}/kick" if bad else f"/api/servers/{sid}/control/player/%20/kick", json={})
    assert r.status_code in (400, 404)


def test_validation_helpers():
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        control.check_choice("time", "day; op Tyler")
    assert control.clean_text("hi\nop Tyler") == "hi op Tyler"
    comp = json.loads(control.component([("[Dad] ", "gold"), ('say "hi"', None)]))
    assert comp[1]["text"] == 'say "hi"'


# ---------------------------------------------------------------- control via RCON
def test_control_actions(client, sid, rcon):
    base = f"/api/servers/{sid}/control"
    rcon["replies"]["gamerule keepInventory"] = "Gamerule keepInventory is currently set to: false"
    info = client.get(base).json()
    assert info["can_rcon"] and info["online"] == ["Tyler"]
    assert [r["key"] for r in info["game_rules"]] == ["keep_inventory"]

    rcon["cmds"].clear()
    client.post(f"{base}/quick", json={"action": "time", "value": "night"})
    client.post(f"{base}/quick", json={"action": "weather", "value": "clear"})
    client.post(f"{base}/gamerule", json={"key": "keep_inventory", "value": True})
    client.post(f"{base}/broadcast", json={"message": "Dinner\nin 10", "on_screen": True})
    client.post(f"{base}/player/Tyler/kick", json={"reason": "bed"})
    client.post(f"{base}/player/Tyler/give", json={"item": "diamond", "count": 3})
    client.post(f"{base}/player/Tyler/gamemode", json={"mode": "creative"})
    client.post(f"{base}/player/Tyler/bring", json={"target": "Gimli_Jr"})
    client.post(f"{base}/command", json={"command": "/say hello"})
    cmds = rcon["cmds"]
    assert "time set night" in cmds and "weather clear" in cmds and "gamerule keepInventory true" in cmds
    tell = next(c for c in cmds if c.startswith("tellraw @a "))
    assert json.loads(tell[len("tellraw @a "):])[1]["text"] == "Dinner in 10"
    assert any(c.startswith("title @a title ") for c in cmds)
    assert "kick Tyler bed" in cmds and "give Tyler minecraft:diamond 3" in cmds
    assert "gamemode creative Tyler" in cmds and "tp Gimli_Jr Tyler" in cmds and "say hello" in cmds

    # Bedrock players (through Geyser and Floodgate) have a dot in front of their name
    rcon["cmds"].clear()
    assert client.post(f"{base}/player/.Steve_K/give", json={"item": "diamond", "count": 2}).status_code == 200
    client.post(f"{base}/player/.Steve_K/whitelist_add", json={})
    client.post(f"{base}/player/Tyler/whitelist_add", json={})
    assert "give .Steve_K minecraft:diamond 2" in rcon["cmds"]
    assert "fwhitelist add Steve_K" in rcon["cmds"] and "whitelist add Tyler" in rcon["cmds"]     # Floodgate's list, by gamertag
    assert client.post(f"{base}/player/..Steve/give", json={"item": "diamond"}).status_code == 400
    assert client.post(f"{base}/player/Tyler/give", json={"item": "diamond 64 @a"}).status_code == 400
    assert client.post(f"{base}/quick", json={"action": "time", "value": "dawn"}).status_code == 400
    assert client.post(f"{base}/command", json={"command": "say a\nop Tyler"}).status_code == 400
    audit = client.get(base).json()["audit"]
    assert any(a["action"] == "broadcast" and a["username"] == "admin" for a in audit)


def test_power_needs_crafty(client, sid, rcon):
    r = client.post(f"/api/servers/{sid}/control/power/stop_server")
    assert r.status_code == 409 and "Crafty" in r.json()["detail"]


# ---------------------------------------------------------------- bedtime
def _fresh(srv):
    """asyncio.run makes a new event loop each time; drop the RCON connection from the old one."""
    srv._rcon = None
    return srv


def _dt(day, hh, mm):  # 2026-10-19 is a Monday
    return datetime(2026, 10, 19 + day, hh, mm)


def test_bedtime_windows():
    cfg = guard.validate_bedtime({"enabled": True, "start": "21:00", "end": "7:00", "days": [0, 1, 2, 3, 6]})
    assert guard.bedtime_state(cfg, _dt(0, 20, 50))[:2] == ("before", 600)
    assert guard.bedtime_state(cfg, _dt(0, 21, 30))[0] == "active"
    assert guard.bedtime_state(cfg, _dt(1, 6, 59))[0] == "active"           # Monday night into Tuesday
    assert guard.bedtime_state(cfg, _dt(1, 7, 0)) is None or guard.bedtime_state(cfg, _dt(1, 7, 0))[0] == "before"
    assert guard.bedtime_state(cfg, _dt(4, 22, 0)) is None                   # Friday not selected
    assert guard.bedtime_state(cfg, _dt(5, 3, 0)) is None                    # early Saturday (Friday off)
    day = guard.validate_bedtime({"start": "13:00", "end": "14:00", "days": [0]})
    assert guard.bedtime_state(day, _dt(0, 13, 30))[0] == "active"
    with pytest.raises(ValueError):
        guard.validate_bedtime({"start": "nine"})


def test_bedtime_kicks_everyone_but_exempt(client, sid, rcon):
    from app import servers as S
    srv = S.registry.servers[sid]
    rcon["replies"]["list"] = "There are 2 of a max of 10 players online: Tyler, Gimli_Jr"
    rcon["cmds"].clear()
    cfg = guard.validate_bedtime({"enabled": True, "start": "21:00", "end": "07:00", "exempt": ["Tyler"]})
    night = datetime.now().date()
    asyncio.run(guard._bedtime(_fresh(srv), cfg, ("active", 0, night), ["Tyler", "Gimli_Jr"]))
    assert "save-all" in rcon["cmds"]
    assert any(c.startswith("kick Gimli_Jr ") for c in rcon["cmds"])
    assert not any(c.startswith("kick Tyler") for c in rcon["cmds"])
    # Warnings only fire once each
    rcon["cmds"].clear()
    asyncio.run(guard._bedtime(_fresh(srv), cfg, ("before", 290, night), ["Gimli_Jr"]))
    asyncio.run(guard._bedtime(_fresh(srv), cfg, ("before", 280, night), ["Gimli_Jr"]))
    assert sum(c.startswith("tellraw @a") for c in rcon["cmds"]) == 1


def test_screen_time_warn_then_kick(client, sid, rcon):
    from app import servers as S
    srv = S.registry.servers[sid]
    rcon["cmds"].clear()
    ncfg = {"limits": {"gimli_jr": 60}, "limit_action": "kick", "limit_grace_minutes": 5}
    now = datetime.now(db.tz())
    asyncio.run(guard._limits(_fresh(srv), ncfg, {"gimli_jr": 3700}, ["Gimli_Jr"], now))
    assert any(c.startswith("tellraw Gimli_Jr") for c in rcon["cmds"]) and not any(c.startswith("kick") for c in rcon["cmds"])
    db.x("UPDATE alerts SET ts=? WHERE key LIKE 'limitwarn:gimli_jr:%'", (time.time() - 400,))
    asyncio.run(guard._limits(_fresh(srv), ncfg, {"gimli_jr": 3700}, ["Gimli_Jr"], now))
    assert any(c.startswith("kick Gimli_Jr") for c in rcon["cmds"])


def test_bedtime_settings_saved(client, sid):
    r = client.put(f"/api/servers/{sid}/settings", json={"bedtime": {"enabled": True, "start": "20:30", "end": "06:45",
                                                                       "warn_minutes": [10, 1], "exempt": ["Tyler", "bad name"]}})
    bt = r.json()["bedtime"]
    assert bt["start"] == "20:30" and bt["warn_minutes"] == [10, 1] and bt["exempt"] == ["Tyler"]
    assert client.put(f"/api/servers/{sid}/settings", json={"bedtime": {"start": "late"}}).status_code == 400
    client.put(f"/api/servers/{sid}/settings", json={"bedtime": {"enabled": False}})


# ---------------------------------------------------------------- console
def test_console_stream(client, sid):
    from app import servers as S
    srv = S.registry.servers[sid]
    log = srv.dir / "logs" / "latest.log"
    log.parent.mkdir(exist_ok=True)
    log.write_text("[10:00:00] [Server thread/INFO]: line one\n[10:00:01] [Server thread/INFO]: line two\n")

    async def run():
        calls = {"n": 0}

        async def disconnected():
            calls["n"] += 1
            if calls["n"] == 1:
                with log.open("a") as fh:
                    fh.write("[10:00:02] [Server thread/INFO]: line three\n")
            return calls["n"] > 2

        return [e async for e in control.console_stream(srv, disconnected)]

    events = [json.loads(e[6:]) for e in asyncio.run(run()) if e.startswith("data: ")]
    assert events[0]["reset"] and events[0]["lines"][-1].endswith("line two")
    assert any("line three" in ln for e in events[1:] for ln in e.get("lines", []))


def test_helpers_players_constant():
    assert helpers.PLAYERS[0][0] == "Tyler"


# ---------------------------------------------------------------- public status page
def test_public_status_page(anon, client, viewer, monkeypatch):
    from app import main
    from app import servers as S
    main._list_cache = None
    main._board_cache.clear()
    # Each anonymous test request runs in its own event loop, so a pooled RCON connection
    # can't be shared between them; read from files instead.
    monkeypatch.setattr(S.Server, "rcon_conf", lambda self: None)
    S.registry.servers[helpers.SID]._rcon = None

    # Off by default: nothing public except "it's off".
    off = anon.get("/api/public/status").json()
    assert off["enabled"] is False and off["servers"] == [] and off["build"]          # the build lets open pages notice an update
    assert anon.get(f"/api/public/status/{helpers.SID}").status_code == 404
    assert anon.get(f"/api/public/icon/{helpers.SID}.png").status_code == 404
    r = anon.get("/status", follow_redirects=False)          # the live status lives on the home page now
    assert r.status_code == 301 and r.headers["location"] == "/#live"
    assert anon.get(f"/status/{helpers.SID}?tv=1", follow_redirects=False).headers["location"] == "/#live"
    assert anon.get("/api/public/site").json()["live"] is False

    assert viewer.put("/api/settings/status", json={"enabled": True}).status_code == 403
    cfg = client.put("/api/settings/status", json={"enabled": True}).json()
    assert cfg == {"enabled": True, "show_positions": False, "show_items": True, "show_activity": True, "show_web_map": False}
    try:
        lst = anon.get("/api/public/status").json()
        assert lst["enabled"] is True
        assert any(s["id"] == helpers.SID for s in lst["servers"])
        assert anon.get("/api/public/site").json()["live"] is True
        assert "/static/live.js?v=" in anon.get("/").text
        board = anon.get(f"/api/public/status/{helpers.SID}").json()
        assert {"name", "running", "players", "recent", "recently", "world"} <= set(board)
        assert all(e["type"] != "chat" for e in board["recent"])   # chat is never public
        assert anon.get(f"/api/public/icon/{helpers.SID}.png").status_code == 200
        assert anon.get(f"/api/public/item/{helpers.SID}/minecraft/..%2f..%2fx.png").status_code == 404
        assert anon.get("/api/servers").status_code == 401         # everything else still needs a login
        assert anon.get(f"/api/servers/{helpers.SID}/players").status_code == 401

        client.put("/api/settings/status", json={"enabled": True, "show_positions": False, "show_items": False})
        main._board_cache.clear()
        board = anon.get(f"/api/public/status/{helpers.SID}").json()
        assert board["spawn"] is None
        assert all("position" not in p and "held" not in p for p in board["players"])
        assert anon.get(f"/api/public/item/{helpers.SID}/minecraft/stone.png").status_code == 404
    finally:
        client.put("/api/settings/status", json={"enabled": False})
        main._board_cache.clear()


def test_security_and_cache_headers(client, anon):
    page = anon.get("/app")
    csp = page.headers["content-security-policy"]
    assert "script-src 'self'" in csp and "object-src 'none'" in csp and "frame-ancestors 'self'" in csp
    assert page.headers["cache-control"] == "no-cache"
    import re
    js = re.search(r'/static/app\.js\?v=([0-9a-f]+)"', page.text)
    assert js, "pages link their scripts with a version stamp"
    assert "immutable" in anon.get(f"/static/app.js?v={js.group(1)}").headers["cache-control"]
    assert anon.get("/static/app.js").headers["cache-control"] == "no-cache"           # unversioned: always check
    assert "onerror=" not in anon.get("/static/app.js").text                           # no inline handlers (CSP)


def test_give_items(client):
    from helpers import SID
    r = client.get(f"/api/servers/{SID}/assets/items")
    assert r.status_code == 200 and isinstance(r.json(), list)
    bad = client.post(f"/api/servers/{SID}/control/player/Tyler/give", json={"item": "minecraft:dia mond", "count": 1})
    assert bad.status_code == 400


def test_hidden_servers_can_be_shown_again(client, viewer):
    from helpers import SID
    assert viewer.get("/api/servers-hidden").status_code == 403
    client.put(f"/api/servers/{SID}/settings", json={"hidden": True})
    try:
        assert SID not in [s["id"] for s in client.get("/api/servers").json()]
        assert [s["id"] for s in client.get("/api/servers-hidden").json()] == [SID]
    finally:
        client.put(f"/api/servers/{SID}/settings", json={"hidden": False})
    assert client.get("/api/servers-hidden").json() == []
    assert SID in [s["id"] for s in client.get("/api/servers").json()]
