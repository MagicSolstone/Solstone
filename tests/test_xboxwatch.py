"""Watching MCXboxBroadcast in the server log: a quick reconnect is fine, a long one is down (and said once)."""
from app import xboxwatch

LOST = "[21:57:50] [MCXboxBroadcast Thread-1/WARN]: [mcxboxbroadcast] [Primary Session] Connection to websocket lost, re-creating session..."
RELAY = "[22:11:30] [nioEventLoopGroup-18-1/WARN]: HttpRelaySignaling WebSocket to signal.franchise.minecraft-services.net closed, no more signals arrive through it"
NETHER = "[21:57:52] [MCXboxBroadcast Thread-1/INFO]: [mcxboxbroadcast] [Primary Session] NetherNet signaling started on ID: 4759176281548357496"
BACK = "[21:57:52] [MCXboxBroadcast Thread-1/INFO]: [mcxboxbroadcast] [Primary Session] WebSocket session reconnected"
RESET = "[22:20:23] [nioEventLoopGroup-19-1/ERROR]: Signaling Exception: Connection reset"
OTHER = "[21:51:17] [Server thread/INFO]: Player MagicSol standing on air - force-sending blocks below"


def test_which_lines_matter():
    assert all(xboxwatch.concerns(x) for x in (LOST, RELAY, NETHER, BACK, RESET)) and not xboxwatch.concerns(OTHER)
    assert not xboxwatch.concerns("\tat java.base/sun.nio.ch.SocketChannelImpl.read(SocketChannelImpl.java:489)")


def test_a_quick_reconnect_is_fine_and_a_long_one_is_down_once():
    sid = "xw-test"
    xboxwatch.forget(sid)
    try:
        assert xboxwatch.status(sid, True, True) == {"state": "unknown", "since": None}
        assert xboxwatch.status(sid, True, False) is None                       # not set up here: nothing to show
        import time
        t = time.time() - 3000
        for line, at in ((RELAY, t), (LOST, t + 1), (NETHER, t + 2), (BACK, t + 2)):   # the usual: back in 2 seconds
            xboxwatch.feed(sid, line, at)
        assert xboxwatch.status(sid, True, True)["state"] == "ok"
        assert xboxwatch.check(sid, "FBC", t + 500) == []                      # nothing to tell anyone
        assert xboxwatch.status(sid, True, True, admin=True)["drops_24h"] == 1
        xboxwatch.feed(sid, RESET, t + 600)                                      # lost, and nothing after it
        xboxwatch.feed(sid, LOST, t + 617)
        assert xboxwatch.status(sid, True, True)["state"] == "reconnecting" and xboxwatch.check(sid, "FBC", t + 650) == []
        said = xboxwatch.check(sid, "FBC", t + 600 + xboxwatch.GRACE + 5)
        assert len(said) == 1 and "isn't working" in said[0] and xboxwatch.status(sid, True, True)["state"] == "down"
        assert xboxwatch.check(sid, "FBC", t + 900) == []                       # said once
        assert "Connection reset" in xboxwatch.status(sid, True, True, admin=True)["problem"]
        xboxwatch.feed(sid, BACK, t + 1000)
        back = xboxwatch.check(sid, "FBC", t + 1001)
        assert back == ["Xbox friend joining is working again on FBC."] and xboxwatch.status(sid, True, True)["state"] == "ok"
        assert xboxwatch.status(sid, False, True)["state"] == "off"            # the server's off
    finally:
        xboxwatch.forget(sid)


def test_solstone_starting_reads_what_it_said_lately():
    sid = "xw-prime"
    xboxwatch.forget(sid)
    try:
        xboxwatch.prime(sid, "\n".join([OTHER, LOST, NETHER, BACK, OTHER]), 1_700_000_000.0)
        assert xboxwatch.status(sid, True, True)["state"] == "ok"
    finally:
        xboxwatch.forget(sid)
