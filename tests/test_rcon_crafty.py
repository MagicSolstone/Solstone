"""RCON client against a fake server, and Crafty helpers against a mock transport."""
import asyncio
import struct

import httpx
import pytest

from app.crafty import CraftyClient, parse_player_list
from app.rcon import Rcon, RconError

BIG = "x" * 10_000  # forces a multi-packet reply


def _pkt(rid, t, body: bytes):
    p = struct.pack("<ii", rid, t) + body + b"\0\0"
    return struct.pack("<i", len(p)) + p


async def _fake_rcon(reader, writer):
    """Behaves like vanilla's RconClient: each socket read must contain exactly one
    packet (length == bytes read - 4) or the server closes the connection."""
    try:
        while True:
            data = await reader.read(1460)
            if len(data) < 10:
                break
            (ln,) = struct.unpack("<i", data[:4])
            if ln != len(data) - 4:
                break  # two packets in one read: vanilla gives up on the client
            rid, t = struct.unpack("<ii", data[4:12])
            body = data[12:-2].decode()
            if t == 3:
                writer.write(_pkt(rid if body == "pw" else -1, 2, b""))
            elif t == 2:
                out = (BIG if body == "big" else f"echo {body}").encode()
                for i in range(0, len(out), 4096):
                    writer.write(_pkt(rid, 0, out[i:i + 4096]))
            else:
                writer.write(_pkt(rid, 0, f"Unknown request {t:x}".encode()))
            await writer.drain()
    finally:
        writer.close()


def test_rcon_multipacket_and_auth():
    async def run():
        srv = await asyncio.start_server(_fake_rcon, "127.0.0.1", 0)
        port = srv.sockets[0].getsockname()[1]
        try:
            r = Rcon("127.0.0.1", port, "pw", timeout=2)
            assert await r.command("list") == "echo list"
            assert await r.command("big") == BIG
            assert await r.command("list") == "echo list"  # connection still usable afterwards
            await r.close()
            with pytest.raises(RconError, match="password"):
                await Rcon("127.0.0.1", port, "wrong", timeout=2).command("list")
        finally:
            srv.close()
    asyncio.run(run())


def test_rcon_unreachable():
    async def run():
        with pytest.raises(RconError):
            await Rcon("127.0.0.1", 1, "pw", timeout=1).command("list")
    asyncio.run(run())


@pytest.mark.parametrize("raw,expected", [
    ("['Tyler', 'Sam']", ["Tyler", "Sam"]),
    ('["Tyler"]', ["Tyler"]),
    ("[]", []),
    ("", []),
    (None, []),
    (["A"], ["A"]),
])
def test_parse_player_list(raw, expected):
    assert parse_player_list(raw) == expected


def test_crafty_client_with_mock_transport():
    def handler(request: httpx.Request):
        assert request.headers["Authorization"] == "Bearer tok"
        if request.url.path == "/api/v2/servers":
            return httpx.Response(200, json={"status": "ok", "data": [{"server_id": "abc", "path": "/crafty/servers/abc"}]})
        return httpx.Response(200, json={"status": "ok", "data": {"running": True, "players": "['Tyler']"}})

    async def run():
        c = CraftyClient()
        c.base, c._token = "https://crafty.test", "tok"
        c._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        assert (await c.servers())[0]["server_id"] == "abc"
        stats = await c.stats("abc")
        assert stats["running"] is True
        assert parse_player_list(stats["players"]) == ["Tyler"]
        await c.close()
    asyncio.run(run())


def test_one_dropped_connection_is_retried_not_backed_off():
    """A single 'connection closed' used to switch RCON off for 30 s (archery and races stalled)."""
    import asyncio

    from app import servers as S
    from app.rcon import RconError
    srv = next(iter(S.registry.servers.values()), None) or S.Server.__new__(S.Server)

    class Flaky:
        def __init__(self, conf):
            self.host, self.port, self.password = conf
            self.calls = 0

        async def command(self, cmd):
            self.calls += 1
            if self.calls == 1:
                raise RconError("RCON command failed: 0 bytes read on a total of 4 expected bytes")
            return "ok"

    conf = ("127.0.0.1", 25575, "pw")
    srv.rcon_conf = lambda: conf
    srv._rcon, srv._rcon_backoff, srv.rcon_error = Flaky(conf), 0.0, None
    assert asyncio.run(S.Server.rcon(srv, "list")) == "ok"
    assert srv.rcon_error is None and srv._rcon_backoff == 0.0
    del srv.rcon_conf
    srv._rcon = None


def test_registry_keeps_crafty_servers_while_crafty_is_down(monkeypatch, tmp_path):
    """Crafty restarting used to empty the server list (pages blank, links broken) until it came back."""
    from app import servers as S
    from app.config import config
    from app.crafty import crafty
    monkeypatch.setattr(config, "data_dir", tmp_path)
    monkeypatch.setattr(config, "servers_dir", tmp_path / "none")
    monkeypatch.setattr(type(crafty), "enabled", property(lambda _s: True))
    up = [{"server_id": "abc", "server_name": "Family", "path": "/crafty/servers/abc"}]
    state = {"list": up}

    async def servers():
        return state["list"]
    monkeypatch.setattr(crafty, "servers", servers)
    reg = S.Registry()
    asyncio.run(reg.refresh(force=True))
    assert list(reg.servers) == ["abc"]
    state["list"] = None                                    # Crafty goes away
    asyncio.run(reg.refresh(force=True))
    assert list(reg.servers) == ["abc"] and reg.servers["abc"].crafty.get("_unreachable")
    fresh = S.Registry()                                    # and Solstone restarts while it's away
    asyncio.run(fresh.refresh(force=True))
    assert list(fresh.servers) == ["abc"] and fresh.servers["abc"].name == "Family"
