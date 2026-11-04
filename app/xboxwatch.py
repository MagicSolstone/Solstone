"""Is joining through the Xbox friend (MCXboxBroadcast) working?

MCXboxBroadcast keeps the friend account online so Bedrock players can join from their Friends tab. It writes to the
server's log, and Solstone reads that log anyway, so it watches what it says:

  - "WebSocket session reconnected", a session created or logged in: working.
  - "Connection to websocket lost, re-creating session" (and Microsoft's relay closing): it's reconnecting. That happens
    every so often and normally takes a second or two, so it only counts as a problem if it doesn't reconnect within
    GRACE seconds.
  - an error from it: noted (the last one is shown to admins), and the same grace before it counts as down.

Down for longer than the grace: a notification ("Xbox friend joining isn't working"), and another when it's back.
The home page shows the state under the gamertag; the server's Control page shows the details.
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta

GRACE = 120                     # seconds to reconnect before it counts as down
_OK = ("websocket session reconnected", "session was successful", "created session", "session created", "logged in as",
       "successfully logged in", "successfully created")
_LOST = ("connection to websocket lost", "re-creating session", "httprelaysignaling websocket")
_BAD = ("failed", "unable to", "could not", "exception", "error")
_CLOCK = re.compile(r"^\[(\d{2}):(\d{2}):(\d{2})\]")

_state: dict[str, dict] = {}    # server id -> {"state", "since", "lost_at", "drops": [ts...], "problem", "problem_at", "seen"}


def concerns(line: str) -> bool:
    low = line.lower()
    return "mcxboxbroadcast" in low or "httprelaysignaling" in low or "signaling exception" in low


def _st(sid: str) -> dict:
    return _state.setdefault(sid, {"state": "unknown", "since": time.time(), "lost_at": None, "drops": [], "problem": "",
                                   "problem_at": None, "seen": False, "told_down": False})


def feed(sid: str, line: str, ts: float) -> None:
    """One log line about MCXboxBroadcast (or Microsoft's relay it uses), written at ts."""
    st = _st(sid)
    low = line.lower()
    st["seen"] = True
    if any(k in low for k in _OK):
        if st["state"] != "ok":
            st["state"], st["since"] = "ok", ts
        st["lost_at"] = None
        return
    if any(k in low for k in _LOST):
        if st["state"] == "ok" or st["lost_at"] is None:
            st["drops"] = [t for t in st["drops"] if t > ts - 86400] + [ts]
            st["lost_at"] = ts
            if st["state"] == "ok":
                st["state"], st["since"] = "reconnecting", ts
        return
    level_bad = "/error]" in low or "/warn]" in low and any(k in low for k in _BAD)
    if level_bad or (any(k in low for k in _BAD) and "mcxboxbroadcast" in low):
        msg = line.split("]: ", 1)[-1].strip()
        st["problem"], st["problem_at"] = msg[:200], ts
        if st["lost_at"] is None:
            st["lost_at"] = ts
        if st["state"] == "ok":
            st["state"], st["since"] = "reconnecting", ts


def check(sid: str, name: str, now: float | None = None) -> list[str]:
    """Every few seconds: a reconnect that's taking too long is down (said once), and back is said once too.
    Returns messages to send as notifications."""
    now = now or time.time()
    st = _state.get(sid)
    if not st:
        return []
    out = []
    if st["state"] in ("reconnecting", "unknown") and st["lost_at"] and now - st["lost_at"] > GRACE:
        st["state"], st["since"] = "down", st["lost_at"]
    if st["state"] == "down" and not st["told_down"]:
        st["told_down"] = True
        out.append(f"Xbox friend joining isn't working on {name}: MCXboxBroadcast lost its connection "
                   f"{int((now - st['lost_at']) // 60) or 1} min ago and hasn't reconnected. Bedrock players can still join "
                   "with the server address.")
    if st["state"] == "ok" and st["told_down"]:
        st["told_down"] = False
        out.append(f"Xbox friend joining is working again on {name}.")
    return out


def prime(sid: str, text: str, mtime: float) -> None:
    """Solstone just started: read what the end of the log says (only the MCXboxBroadcast lines), so the state's known
    straight away rather than from its next message."""
    if sid in _state:
        return
    now = datetime.fromtimestamp(mtime)
    for line in text.splitlines():
        if not concerns(line):
            continue
        m = _CLOCK.match(line)
        ts = mtime
        if m:
            t = now.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=int(m.group(3)), microsecond=0)
            if t > now + timedelta(seconds=60):
                t -= timedelta(days=1)
            ts = t.timestamp()
        feed(sid, line, ts)
    _st(sid)


def forget(sid: str) -> None:
    """The server stopped (or its log started again): nothing known until MCXboxBroadcast says something."""
    _state.pop(sid, None)


def status(sid: str, running: bool, configured: bool, admin: bool = False) -> dict | None:
    """For the home page (and, with admin, the Control page). None: not set up on this server."""
    st = _state.get(sid)
    if not configured and not (st and st["seen"]):
        return None
    if not running:
        out = {"state": "off", "since": None}
    elif not st or not st["seen"]:
        out = {"state": "unknown", "since": None}
    elif st["state"] == "unknown" and st["lost_at"] is None:
        out = {"state": "ok", "since": st["since"]}      # it's been talking, and hasn't lost its connection
    else:
        out = {"state": st["state"], "since": st["since"]}
    if admin and st:
        now = time.time()
        out.update(drops_24h=len([t for t in st["drops"] if t > now - 86400]), problem=st["problem"], problem_at=st["problem_at"],
                   grace=GRACE)
    return out
