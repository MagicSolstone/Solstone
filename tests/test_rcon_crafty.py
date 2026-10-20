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
    try:
        while True:
            (ln,) = struct.unpack("<i", await reader.readexactly(4))
            data = await reader.readexactly(ln)
            rid, t = struct.unpack("<ii", data[:8])
            body = data[8:-2].decode()
            if t == 3:
                writer.write(_pkt(rid if body == "pw" else -1, 2, b""))
            elif t == 2:
                out = (BIG if body == "big" else f"echo {body}").encode()
                for i in range(0, len(out), 4096):
                    writer.write(_pkt(rid, 0, out[i:i + 4096]))
            else:
                writer.write(_pkt(rid, 0, b"Unknown request"))
            await writer.drain()
    except asyncio.IncompleteReadError:
        pass


def test_rcon_multipacket_and_auth():
    async def run():
        srv = await asyncio.start_server(_fake_rcon, "127.0.0.1", 0)
        port = srv.sockets[0].getsockname()[1]
        try:
            r = Rcon("127.0.0.1", port, "pw", timeout=2)
            assert await r.command("list") == "echo list"
            assert await r.command("big") == BIG
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
