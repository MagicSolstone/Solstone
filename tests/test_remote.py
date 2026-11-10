"""Servers somewhere else: the mirror kept over a real SFTP connection (a little SFTP server started here, serving a
pretend Minecraft folder), the host's key remembered, a wrong password explained, the log followed line by line, a
file written back; and the host's panel (Pterodactyl's client API) for running or not, CPU, memory, start and stop."""
import asyncio
import json

import asyncssh
import httpx
import pytest

from app import remote, settings_store


def _server_folder(root):
    (root / "world" / "stats").mkdir(parents=True)
    (root / "world" / "playerdata").mkdir(parents=True)
    (root / "logs").mkdir()
    (root / "mods").mkdir()
    (root / "server.properties").write_text("level-name=world\nenable-rcon=true\nrcon.port=25575\nrcon.password=pw\nmotd=Far away\n")
    (root / "usercache.json").write_text(json.dumps([{"name": "Ann", "uuid": "00000000-0000-0000-0000-00000000000a"}]))
    (root / "whitelist.json").write_text("[]")
    (root / "world" / "level.dat").write_bytes(b"\x1f\x8b fake")
    (root / "world" / "stats" / "00000000-0000-0000-0000-00000000000a.json").write_text('{"stats": {}}')
    (root / "world" / "playerdata" / "00000000-0000-0000-0000-00000000000a.dat").write_bytes(b"nbt")
    (root / "logs" / "latest.log").write_text("[10:00:00] [Server thread/INFO]: Done (3.2s)! For help, type \"help\"\n")
    (root / "mods" / "tide.jar").write_bytes(b"PK jar")
    (root / "secret.txt").write_text("not for Solstone")


class _Sftp(asyncssh.SSHServer):
    def begin_auth(self, username):
        return True

    def password_auth_supported(self):
        return True

    def validate_password(self, username, password):
        return username == "steve" and password == "hunter2"


async def _start(root, key):
    return await asyncssh.listen("127.0.0.1", 0, server_host_keys=[key], server_factory=_Sftp,
                                 sftp_factory=lambda chan: asyncssh.SFTPServer(chan, chroot=str(root).encode()))


@pytest.fixture()
def far(tmp_path, monkeypatch):
    """A pretend host: its SFTP server, on its own event loop for the test."""
    root = tmp_path / "host"
    root.mkdir()
    _server_folder(root)
    monkeypatch.setattr(settings_store, "_PATH", tmp_path / "settings.json")
    monkeypatch.setattr(remote.config, "data_dir", tmp_path / "data")
    loop = asyncio.new_event_loop()
    key = asyncssh.generate_private_key("ssh-ed25519")
    srv = loop.run_until_complete(_start(root, key))
    port = srv.sockets[0].getsockname()[1]
    remote._mirrors.clear()
    yield loop, root, {"name": "Far away", "host": "127.0.0.1", "port": port, "user": "steve", "password": "hunter2", "path": "/"}, key
    for m in list(remote._mirrors.values()):
        m.close()
    srv.close()
    loop.run_until_complete(srv.wait_closed())
    loop.close()


def _added(loop, cfg):
    """Added the way Manage → Servers does it: tested (the host's key learned), then saved."""
    t = loop.run_until_complete(remote.test(cfg))
    sid = remote.save(None, cfg)
    data = remote.all_cfg(); data[sid].update(host_key=t["host_key"], host_pub=t["host_pub"]); settings_store.save_section(remote.SECTION, data)
    return sid


def test_connecting_learns_the_hosts_key_and_finds_the_server(far):
    loop, root, cfg, key = far
    res = loop.run_until_complete(remote.test(cfg))
    assert res["ok"] and res["host_key"].startswith("SHA256:") and res["host_pub"].startswith("ssh-ed25519 ") and res["rcon"] and res["rcon_port"] == "25575"
    assert "server.properties" in res["files"] and res["motd"] == "Far away"
    bad = loop.run_until_complete(remote.test({**cfg, "password": "nope"}))
    assert not bad["ok"] and "wasn't accepted" in bad["error"]
    wrong_folder = loop.run_until_complete(remote.test({**cfg, "path": "/mods"}))
    assert not wrong_folder["ok"] and "no server.properties" in wrong_folder["error"]
    # never connected before, and not an admin's test: it won't connect (nothing learned to check it against)
    with pytest.raises(remote.HostKeyChanged):
        loop.run_until_complete(remote._connect(cfg))


def test_the_mirror_follows_the_log_and_fetches_only_what_changed(far):
    loop, root, cfg, key = far
    sid = _added(loop, cfg)
    m = remote.mirror(sid)
    loop.run_until_complete(m.tick(now=1000))
    d = remote.mirror_dir(sid)
    assert m.status["ok"], m.status
    assert (d / "server.properties").read_text().startswith("level-name=world")
    assert (d / "world/stats/00000000-0000-0000-0000-00000000000a.json").exists() and (d / "world/level.dat").exists()
    assert (d / "mods/tide.jar").exists() and (d / "logs/latest.log").read_text().count("\n") == 1
    assert not (d / "secret.txt").exists()                                        # only what Solstone reads
    # the log: just its new lines next time
    with (root / "logs/latest.log").open("a") as f:
        f.write("[10:00:05] [Server thread/INFO]: Ann joined the game\n")
    before = m.status["bytes"]
    loop.run_until_complete(m.tick(now=1004))
    assert (d / "logs/latest.log").read_text().endswith("Ann joined the game\n")
    assert m.status["bytes"] - before == len("[10:00:05] [Server thread/INFO]: Ann joined the game\n")   # nothing else fetched
    # a restart: a new, shorter log is fetched from the start
    (root / "logs/latest.log").write_text("[11:00:00] [Server thread/INFO]: Starting\n")
    loop.run_until_complete(m.tick(now=1008))
    assert (d / "logs/latest.log").read_text() == "[11:00:00] [Server thread/INFO]: Starting\n"
    # the whitelist, written back
    loop.run_until_complete(m.put("whitelist.json", b'[{"name": ".Kid", "uuid": "x"}]'))
    assert json.loads((root / "whitelist.json").read_text())[0]["name"] == ".Kid" and (d / "whitelist.json").exists()


def test_a_changed_host_key_is_refused(far):
    loop, root, cfg, key = far
    sid = _added(loop, cfg)
    other = asyncssh.generate_private_key("ssh-ed25519").export_public_key("openssh").decode()
    data = remote.all_cfg(); data[sid]["host_pub"] = other; settings_store.save_section(remote.SECTION, data)   # someone else's key
    m = remote.mirror(sid)
    loop.run_until_complete(m.tick(now=1000))
    assert m.status["ok"] is False and "identity" in m.status["error"]
    assert not (remote.mirror_dir(sid) / "server.properties").exists()


def test_settings_keep_their_secrets(far):
    loop, root, cfg, key = far
    from app import connections
    conn = connections.save(None, {"type": "panel", "url": "https://panel.example.com/", "key": "ptlc_x"})
    sid = remote.save(None, {**cfg, "conn": conn, "panel_id": "1a2b3c4d"})
    pub = remote.public(remote.get(sid))
    assert "password" not in pub and pub["password_set"] and pub["conn"] == conn and pub["panel_id"] == "1a2b3c4d"
    remote.save(sid, {**cfg, "password": ""})                                        # blank: the saved one stays
    assert remote.get(sid)["password"] == "hunter2"
    with pytest.raises(ValueError):
        remote.clean({**cfg, "conn": "no-such-connection"})
    with pytest.raises(ValueError):
        remote.clean({"name": "x", "host": "", "user": "u"})
    assert sid in (settings_store.load().get(settings_store.SEEN) or [])            # added by an admin: not "new"


def test_the_hosts_panel(monkeypatch, tmp_path):
    """Pterodactyl's client API: what it says becomes what Crafty would say (running, CPU, memory), and power and
    commands go to it."""
    monkeypatch.setattr(settings_store, "_PATH", tmp_path / "settings.json")
    sent = []

    def answer(req: httpx.Request):
        assert req.headers["authorization"] == "Bearer ptlc_key"
        sent.append((req.method, req.url.path, req.content.decode()))
        if req.url.path.endswith("/resources"):
            return httpx.Response(200, json={"attributes": {"current_state": "running", "resources": {
                "memory_bytes": 3 * 1024 ** 3, "cpu_absolute": 42.5, "disk_bytes": 5 * 1024 ** 3, "uptime": 3600_000}}})
        if req.url.path.endswith("/1a2b3c4d"):
            return httpx.Response(200, json={"attributes": {"name": "Family", "node": "Dallas 1", "limits": {"memory": 6144}}})
        return httpx.Response(204)
    from app import connections
    conn = connections.save(None, {"type": "panel", "url": "https://panel.example.com", "key": "ptlc_key"})
    sid = remote.save(None, {"name": "Far", "host": "sftp.example.com", "user": "u", "password": "p", "conn": conn, "panel_id": "1a2b3c4d"})
    remote._panels.clear()
    p = remote.panel(sid)
    p._client = httpx.AsyncClient(transport=httpx.MockTransport(answer))
    t = asyncio.run(p.test())
    assert t["ok"] and t["name"] == "Family" and t["memory_mb"] == 6144
    p._stats = None
    st = asyncio.run(p.stats())
    assert st["running"] and st["cpu"] == 42.5 and st["mem"] == "3.0GB" and st["mem_percent"] == 50.0
    asyncio.run(p.power("restart_server"))
    asyncio.run(p.command("say hi"))
    asyncio.run(p.power("backup_server"))
    assert ("POST", "/api/client/servers/1a2b3c4d/backups", '{"name":"Solstone"}') in sent
    assert ("POST", "/api/client/servers/1a2b3c4d/power", '{"signal":"restart"}') in sent
    assert ("POST", "/api/client/servers/1a2b3c4d/command", '{"command":"say hi"}') in sent

    def refuse(req):
        return httpx.Response(401)
    p._client = httpx.AsyncClient(transport=httpx.MockTransport(refuse))
    p._stats = None
    assert asyncio.run(p.stats()) is None and "API key" in p.error


def test_a_server_elsewhere_is_one_of_the_servers(far):
    """In the registry like any other: its files are the mirror, RCON goes to the host's address, and it isn't "new"."""
    from app import servers as S
    loop, root, cfg, key = far
    sid = _added(loop, cfg)
    loop.run_until_complete(remote.mirror(sid).tick(now=1000))
    reg = S.Registry()
    loop.run_until_complete(reg.refresh(force=True))
    srv = reg.servers[sid]
    assert srv.remote and srv.is_java and srv.display_name == "Far away" and srv.panel is None and not srv.managed
    assert srv.rcon_conf() == ("127.0.0.1", 25575, "pw")                          # RCON at the host's own address
    assert not settings_store.server(sid).get("hidden")
    assert [p["name"] for p in S.known_players(srv).values()] == ["Ann"]


def test_adding_one_from_manage_servers(client, viewer):
    """Through the API, as the page does: added (nothing answering yet), listed with the others, its secrets kept back,
    and removed again."""
    body = {"name": "Rented", "host": "127.0.0.1", "port": 1, "user": "u", "password": "secret-pw", "path": "/"}
    assert viewer.put("/api/manage/remote", json=body).status_code == 403
    t = client.post("/api/manage/remote/test", json=body).json()
    assert not t["files"]["ok"] and "Couldn't reach" in t["files"]["error"]
    r = client.put("/api/manage/remote", json=body)
    assert r.status_code == 200, r.text
    sid = r.json()["id"]
    try:
        got = client.get(f"/api/manage/remote/{sid}").json()
        assert got["name"] == "Rented" and got["password_set"] and "password" not in got
        row = next(x for x in client.get("/api/manage/servers").json() if x["id"] == sid)
        assert row["remote"] and row["where"] == "127.0.0.1" and not row["hidden"] and not row["new"]
        assert client.put(f"/api/manage/remote/{sid}", json={**body, "password": ""}).status_code == 200
        assert remote.get(sid)["password"] == "secret-pw"                                # blank kept the saved one
        assert client.put("/api/manage/remote", json={**body, "host": ""}).status_code == 400
    finally:
        assert client.delete(f"/api/manage/remote/{sid}").status_code == 200
    assert not any(x["id"] == sid for x in client.get("/api/manage/servers").json())


def test_the_activity_feed_reads_a_server_elsewhere(far):
    """Its log, mirrored line by line, is read by the recorder like any server's: Ann joining shows up."""
    from app import db
    from app import servers as S
    from app.recorder import Recorder
    loop, root, cfg, key = far
    sid = _added(loop, cfg)
    m = remote.mirror(sid)
    loop.run_until_complete(m.tick(now=1000))
    reg = S.Registry()
    loop.run_until_complete(reg.refresh(force=True))
    srv = reg.servers[sid]
    rec = Recorder()
    rec.tail_server(srv)                                                  # (first look: the log so far)
    with (root / "logs/latest.log").open("a") as f:
        f.write("[10:00:05] [Server thread/INFO]: Ann joined the game\n[10:00:09] [Server thread/INFO]: <Ann> hello from far away\n")
    loop.run_until_complete(m.tick(now=1004))
    rec.tail_server(srv)
    said = [e["message"] for e in db.events(sid, ["chat", "join"], None, 10)]
    assert "hello from far away" in said


def test_a_home_folder_it_cant_open_doesnt_stop_it(far, monkeypatch):
    """Solstone's container user isn't allowed into its home folder. On Python 3.12 looking for ~/.ssh files there
    raises "Permission denied" (3.13 just says no), and every connection failed that way (a real host: GodLike)."""
    from pathlib import Path
    loop, root, cfg, key = far
    real = Path.is_dir

    def is_dir(self):
        if ".ssh" in self.parts:
            raise PermissionError(13, "Permission denied", str(self))
        return real(self)
    monkeypatch.setattr(Path, "is_dir", is_dir)
    real_access = __import__("os").access
    monkeypatch.setattr("os.access", lambda p, m, **kw: False if ".ssh" in str(p) else real_access(p, m, **kw))
    res = loop.run_until_complete(remote.test(cfg))
    assert res["ok"], res


def test_a_panel_saved_with_a_server_becomes_a_connection(monkeypatch, tmp_path):
    """1.17 kept the panel's address and key with each server: moved, once, into one connection they share."""
    from app import connections
    monkeypatch.setattr(settings_store, "_PATH", tmp_path / "settings.json")
    old = {"name": "A", "host": "h", "user": "u", "password": "p", "panel_url": "https://panel.example.com/", "panel_key": "ptlc_k", "panel_id": "aaaa1111"}
    settings_store.save_section(remote.SECTION, {"r-1": old, "r-2": {**old, "name": "B", "panel_id": "bbbb2222"}})
    cfg = remote.all_cfg()
    assert cfg["r-1"]["conn"] and cfg["r-1"]["conn"] == cfg["r-2"]["conn"] and "panel_key" not in cfg["r-1"]
    c = connections.get(cfg["r-1"]["conn"])
    assert c["type"] == "panel" and c["url"] == "https://panel.example.com" and c["key"] == "ptlc_k"
    assert len(connections.of_type("panel")) == 1 and remote.panel("r-2")._url("/x").endswith("/servers/bbbb2222/x")


def test_serverprism(monkeypatch, tmp_path):
    """ServerPrism's own API (as its docs at serverprism.com/api describe it): its servers listed by service id; how
    one's doing in the shape Crafty's stats have; power and backups sent; its limits and refusals explained."""
    from app import connections
    monkeypatch.setattr(settings_store, "_PATH", tmp_path / "settings.json")
    sent = []

    def answer(req: httpx.Request):
        assert req.headers["authorization"] == "Bearer sp_token" and req.url.host == "serverprism.com"
        sent.append((req.method, req.url.path, req.content.decode()))
        if req.url.path == "/api/v1/client/servers":
            return httpx.Response(200, json={"data": [{"id": 1234, "name": "Family", "game": {"runtime": "paper", "version": "1.21.4"}}],
                                             "meta": {"total": 1, "last_page": 1}})
        if req.url.path == "/api/v1/client/servers/1234":
            return httpx.Response(200, json={"data": {"id": 1234, "name": "Family", "address": "fam.example.com", "game": {"version": "1.21.4"},
                                             "limits": {"memory_mb": 4096}, "resources": {"current_state": "running", "memory_bytes": 2147483648,
                                             "cpu_absolute": 18.5, "disk_bytes": 7300000000, "uptime_ms": 3600000}}})
        if req.url.path.endswith("/backups"):
            return httpx.Response(202, json={"data": {"status": "in_progress"}})
        return httpx.Response(200, json={"data": {"sent": True}})
    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(answer), **{k: v for k, v in kw.items() if k != "verify"}))
    cfg = connections.clean({"type": "serverprism", "key": "sp_token", "url": "https://elsewhere.example.com"})
    assert cfg["url"] == "https://serverprism.com" and cfg["verify_ssl"]                 # (its API is always there)
    assert asyncio.run(connections.test(cfg)) == {"ok": True, "servers": [{"id": "1234", "name": "Family", "node": "paper 1.21.4"}]}
    conn = connections.save(None, {"type": "serverprism", "key": "sp_token"})
    sid = remote.save(None, {"name": "Family", "host": "sftp.example.com", "user": "u", "password": "p", "conn": conn, "panel_id": "1234"})
    remote._panels.clear()
    p = remote.panel(sid)
    assert isinstance(p, remote.PrismPanel)
    st = asyncio.run(p.stats())
    assert st["running"] and st["cpu"] == 18.5 and st["mem"] == "2.0GB" and st["mem_percent"] == 50.0 and st["version"] == "1.21.4"
    asyncio.run(p.power("restart_server"))
    asyncio.run(p.power("backup_server"))
    asyncio.run(p.command("say hi"))
    assert ("POST", "/api/v1/client/servers/1234/power", '{"signal":"restart"}') in sent
    assert ("POST", "/api/v1/client/servers/1234/backups", '{"name":"Solstone"}') in sent
    assert ("POST", "/api/v1/client/servers/1234/command", '{"command":"say hi"}') in sent
    asyncio.run(p.stats())                                                               # (a restart: asked afresh)
    n = len(sent)
    asyncio.run(p.stats())
    assert len(sent) == n                                                                 # then at most every 10 s (its limits)

    def refuse(req):
        return httpx.Response(403, json={"message": "Token does not include the required scope."})
    p._client = real(transport=httpx.MockTransport(refuse))
    p._stats = None
    assert asyncio.run(p.stats()) is None and "scope" in p.error


def test_the_map_copies_only_where_players_have_been(far):
    """The world's region files: just those players have been in (and the eight around where they are now), the
    Nether from Paper's own folder too, and never the rest of a pregenerated world."""
    import time

    from app import db
    loop, root, cfg, key = far
    reg = root / "world" / "region"
    reg.mkdir(parents=True)
    for x, z in ((0, 0), (-1, 0), (1, 1), (9, 9), (40, 40)):
        (reg / f"r.{x}.{z}.mca").write_bytes(b"R" * 64)
    neth = root / "world_nether" / "DIM-1" / "region"                                 # (Paper keeps the Nether apart)
    neth.mkdir(parents=True)
    (neth / "r.0.0.mca").write_bytes(b"N" * 64)
    sid = _added(loop, cfg)
    now = time.time()
    db.x("DELETE FROM positions WHERE server_id=?", (sid,))
    db.x("INSERT INTO positions(server_id, ts, player, dim, x, y, z) VALUES (?,?,?,?,?,?,?)", (sid, now - 30, "Ann", "minecraft:overworld", 100, 64, 100))
    db.x("INSERT INTO positions(server_id, ts, player, dim, x, y, z) VALUES (?,?,?,?,?,?,?)", (sid, now - 86400, "Ann", "minecraft:overworld", 5000, 64, 5000))
    db.x("INSERT INTO positions(server_id, ts, player, dim, x, y, z) VALUES (?,?,?,?,?,?,?)", (sid, now - 86400, "Ann", "minecraft:the_nether", -3, 64, 10))
    m = remote.mirror(sid)
    for i in range(8):
        loop.run_until_complete(m.tick(now=now + i * 3))
    d = remote.mirror_dir(sid) / "world"
    have = sorted(p.name for p in (d / "region").glob("*.mca"))
    assert have == ["r.-1.0.mca", "r.0.0.mca", "r.1.1.mca", "r.9.9.mca"], have            # around Ann now, and where she was
    assert (d / "DIM-1" / "region" / "r.-1.0.mca").exists() is False                     # (never generated there)
    assert not (d / "region" / "r.40.40.mca").exists()                                   # pregenerated, never visited
    db.x("INSERT INTO positions(server_id, ts, player, dim, x, y, z) VALUES (?,?,?,?,?,?,?)", (sid, now, "Ann", "minecraft:the_nether", 5, 64, 5))
    m.last["regions"] = 0
    for i in range(8):                                                                   # (a few each time round)
        loop.run_until_complete(m.tick(now=now + 30 + i * 3))
    assert (d / "DIM-1" / "region" / "r.0.0.mca").read_bytes() == b"N" * 64              # Paper's Nether, where the map looks
    (reg / "r.0.0.mca").write_bytes(b"S" * 80)                                          # built on while she's there
    import os
    os.utime(reg / "r.0.0.mca", (now + 100, now + 100))
    m.last["regions"] = 0
    for i in range(8):
        loop.run_until_complete(m.tick(now=now + 60 + i * 3))
    assert (d / "region" / "r.0.0.mca").read_bytes() == b"S" * 80
    db.x("DELETE FROM positions WHERE server_id=?", (sid,))


def _region(chunks: dict[int, tuple[bytes, int]]) -> bytes:
    """A region file: its table (where each chunk is, when each was saved), then each chunk in its own 4 KB sectors."""
    loc, ts, body, sector = bytearray(4096), bytearray(4096), bytearray(), 2
    for i, (data, stamp) in sorted(chunks.items()):
        n = -(-len(data) // 4096)
        loc[i * 4: i * 4 + 4] = sector.to_bytes(3, "big") + bytes([n])
        ts[i * 4: i * 4 + 4] = stamp.to_bytes(4, "big")
        body += data.ljust(n * 4096, b"\0")
        sector += n
    return bytes(loc + ts + body)


def test_a_region_already_copied_fetches_only_its_changed_chunks(far):
    """Someone building where they are: only the 8 KB table and the chunks saved since are fetched, not the region."""
    import os
    import time

    from app import db
    loop, root, cfg, key = far
    reg = root / "world" / "region"
    reg.mkdir(parents=True)
    f = reg / "r.0.0.mca"
    f.write_bytes(_region({0: (b"A" * 5000, 100), 1: (b"B" * 3000, 100), 2: (b"C" * 4000, 100)}))
    sid = _added(loop, cfg)
    now = time.time()
    db.x("DELETE FROM positions WHERE server_id=?", (sid,))
    db.x("INSERT INTO positions(server_id, ts, player, dim, x, y, z) VALUES (?,?,?,?,?,?,?)", (sid, now, "Ann", "minecraft:overworld", 5, 64, 5))
    m = remote.mirror(sid)
    for i in range(5):
        loop.run_until_complete(m.tick(now=now + i * 3))
    copy = remote.mirror_dir(sid) / "world" / "region" / "r.0.0.mca"
    assert copy.read_bytes() == f.read_bytes()
    f.write_bytes(_region({0: (b"A" * 5000, 100), 1: (b"b" * 3000, 200), 2: (b"C" * 4000, 100)}))   # chunk 1 built on
    os.utime(f, (now + 50, now + 50))
    before = m.status["bytes"]
    m.last["regions"] = 0
    for i in range(5):
        loop.run_until_complete(m.tick(now=now + 100 + i * 3))
    assert copy.read_bytes() == f.read_bytes()
    assert m.status["bytes"] - before == 8192 + 4096                                       # the table and one sector
    db.x("DELETE FROM positions WHERE server_id=?", (sid,))
