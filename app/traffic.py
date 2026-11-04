"""Website traffic: what Solstone itself answers, hour by hour (Manage → Solstone → Website traffic).

Every request is counted as it's answered: who asked (each admin by name, signed-in players together, or visitors who
aren't signed in), what kind of thing (pages, the map, everything else), how much was sent, and how long the answer
took (so it's plain whether the site stays quick). Visitors are told apart for a daily count by a scrambled address
that changes each day; no address is ever stored.

The machine's own network counters (/proc/net/dev) give everything else this container sends and receives too:
talking to the game (RCON), Crafty, Modrinth and the like.

Cloudflare sees what never reaches here (bots it blocks, countries, attacks): this is what got through.
"""
from __future__ import annotations

import hashlib
import secrets
import threading
import time
from pathlib import Path

from . import db

KEEP_DAYS = 30
SPEED = (0.1, 0.3, 1.0)                # answer time buckets: under 0.1 s, under 0.3 s, under 1 s, slower
_lock = threading.Lock()
_pending: dict[tuple, list] = {}       # (hour, who, kind) -> [requests, bytes out, bytes in, total secs, b0, b1, b2, b3]
_visitors: dict[str, set] = {}         # day -> scrambled visitor ids (not stored, just counted)
_salt = {"day": "", "salt": b""}
_net_last: dict = {}


def _ensure() -> None:
    db.x("CREATE TABLE IF NOT EXISTS traffic (hour REAL NOT NULL, who TEXT NOT NULL, kind TEXT NOT NULL, requests INTEGER NOT NULL, "
         "bytes_out INTEGER NOT NULL, bytes_in INTEGER NOT NULL, secs REAL NOT NULL, b0 INTEGER NOT NULL, b1 INTEGER NOT NULL, "
         "b2 INTEGER NOT NULL, b3 INTEGER NOT NULL, PRIMARY KEY (hour, who, kind))")
    db.x("CREATE TABLE IF NOT EXISTS traffic_daily (day TEXT PRIMARY KEY, visitors INTEGER NOT NULL)")
    db.x("CREATE TABLE IF NOT EXISTS traffic_net (hour REAL PRIMARY KEY, rx INTEGER NOT NULL, tx INTEGER NOT NULL)")


def kind_of(path: str) -> str:
    if path.startswith("/api/servers/") and ("/webmap" in path or "/map" in path or "/tiles" in path):
        return "map"
    if path.startswith("/static/") or path.startswith("/api/public/icon") or path.endswith((".png", ".js", ".css", ".svg", ".woff2")):
        return "files"
    if path.startswith("/api/"):
        return "api"
    return "pages"


def who_of(user) -> str:
    if user is None:
        return "visitor"
    if getattr(user, "role", "") == "admin":
        return f"admin:{user.username}"
    return "player"


def record(path: str, user, ip: str, out_bytes: int, in_bytes: int, secs: float, now: float | None = None) -> None:
    """One answered request (from the web middleware)."""
    now = now or time.time()
    hour = now - now % 3600
    key = (hour, who_of(user), kind_of(path))
    b = 0 if secs < SPEED[0] else 1 if secs < SPEED[1] else 2 if secs < SPEED[2] else 3
    day = time.strftime("%Y-%m-%d", time.localtime(now))
    with _lock:
        row = _pending.setdefault(key, [0, 0, 0, 0.0, 0, 0, 0, 0])
        row[0] += 1
        row[1] += max(0, out_bytes)
        row[2] += max(0, in_bytes)
        row[3] += secs
        row[4 + b] += 1
        if user is None:
            if _salt["day"] != day:                     # a new scramble each day: yesterday's can't be matched up
                _salt.update(day=day, salt=secrets.token_bytes(16))
            _visitors.setdefault(day, set()).add(hashlib.sha256(_salt["salt"] + ip.encode()).hexdigest()[:16])


def _net() -> tuple[int, int] | None:
    """This container's own network counters (bytes received, sent), all interfaces but loopback."""
    try:
        rx = tx = 0
        for line in Path("/proc/net/dev").read_text().splitlines()[2:]:
            name, _, rest = line.partition(":")
            if name.strip() == "lo":
                continue
            f = rest.split()
            rx, tx = rx + int(f[0]), tx + int(f[8])
        return rx, tx
    except (OSError, ValueError, IndexError):
        return None


def flush(now: float | None = None) -> None:
    """Every minute or so: what's been counted, into the database (added to what's there)."""
    now = now or time.time()
    with _lock:
        rows, _pending_copy = list(_pending.items()), None
        _pending.clear()
        seen = {d: len(v) for d, v in _visitors.items()}
        for d in [d for d in _visitors if d != time.strftime("%Y-%m-%d", time.localtime(now))]:
            _visitors.pop(d, None)                       # a finished day: only its count is kept
    _ensure()
    for (hour, who, kind), r in rows:
        db.x("INSERT INTO traffic VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(hour, who, kind) DO UPDATE SET "
             "requests=requests+excluded.requests, bytes_out=bytes_out+excluded.bytes_out, bytes_in=bytes_in+excluded.bytes_in, "
             "secs=secs+excluded.secs, b0=b0+excluded.b0, b1=b1+excluded.b1, b2=b2+excluded.b2, b3=b3+excluded.b3",
             (hour, who, kind, *r))
    for d, n in seen.items():
        db.x("INSERT INTO traffic_daily VALUES (?,?) ON CONFLICT(day) DO UPDATE SET visitors=MAX(visitors, excluded.visitors)", (d, n))
    got = _net()
    if got:
        last = _net_last.get("v")
        _net_last["v"] = got
        if last and got[0] >= last[0] and got[1] >= last[1]:          # (counters reset when the container restarts)
            hour = now - now % 3600
            db.x("INSERT INTO traffic_net VALUES (?,?,?) ON CONFLICT(hour) DO UPDATE SET rx=rx+excluded.rx, tx=tx+excluded.tx",
                 (hour, got[0] - last[0], got[1] - last[1]))
    cutoff = now - KEEP_DAYS * 86400
    db.x("DELETE FROM traffic WHERE hour < ?", (cutoff,))
    db.x("DELETE FROM traffic_net WHERE hour < ?", (cutoff,))


def report(viewer: str, days: int = 1, now: float | None = None) -> dict:
    """For the admin page: by who (you, other admins, players, visitors), by hour, speed, and the machine's network."""
    flush(now)
    now = now or time.time()
    since = now - now % 3600 - (days * 24 - 1) * 3600
    groups: dict[str, dict] = {}
    hours: dict[float, dict] = {}
    kinds: dict[str, int] = {}
    speed = [0, 0, 0, 0]
    secs = 0.0
    for r in db.q("SELECT * FROM traffic WHERE hour >= ? ORDER BY hour", (since,)):
        g = "you" if r["who"] == f"admin:{viewer}" else "admins" if r["who"].startswith("admin:") else r["who"] + "s"
        t = groups.setdefault(g, {"requests": 0, "bytes": 0})
        t["requests"] += r["requests"]
        t["bytes"] += r["bytes_out"]
        h = hours.setdefault(r["hour"], {"you": 0, "admins": 0, "players": 0, "visitors": 0, "bytes": 0})
        h[g] += r["requests"]
        h["bytes"] += r["bytes_out"]
        kinds[r["kind"]] = kinds.get(r["kind"], 0) + r["requests"]
        speed = [a + b for a, b in zip(speed, (r["b0"], r["b1"], r["b2"], r["b3"]), strict=True)]
        secs += r["secs"]
    total = sum(speed)
    day_from = time.strftime("%Y-%m-%d", time.localtime(since))
    visitors = sum(r["visitors"] for r in db.q("SELECT visitors FROM traffic_daily WHERE day >= ?", (day_from,)))
    net = db.q("SELECT COALESCE(SUM(rx),0) AS rx, COALESCE(SUM(tx),0) AS tx FROM traffic_net WHERE hour >= ?", (since,))[0]
    series = []
    for i in range(days * 24):
        hr = since + i * 3600
        series.append({"hour": hr, **(hours.get(hr) or {"you": 0, "admins": 0, "players": 0, "visitors": 0, "bytes": 0})})
    return {"days": days, "groups": groups, "kinds": kinds, "hours": series, "visitors": visitors,
            "speed": {"requests": total, "avg_ms": round(secs / total * 1000) if total else None, "buckets": speed},
            "net": {"rx": net["rx"], "tx": net["tx"], "available": _net() is not None}}
