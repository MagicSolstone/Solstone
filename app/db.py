"""SQLite history store: play sessions, server metrics, activity events.

Minecraft itself only keeps lifetime totals, so anything over time (who played
today, TPS last night, the chat log) is recorded here by the background
recorder. One small file in DATA_DIR; WAL mode so reads never block writes.
"""
from __future__ import annotations

import os
import sqlite3
import threading
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .config import config

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY,
    server_id TEXT NOT NULL,
    player TEXT NOT NULL,
    uuid TEXT,
    start_ts REAL NOT NULL,
    last_seen_ts REAL NOT NULL,
    end_ts REAL
);
CREATE INDEX IF NOT EXISTS ix_sessions_server ON sessions(server_id, start_ts);
CREATE INDEX IF NOT EXISTS ix_sessions_open ON sessions(server_id, end_ts);

CREATE TABLE IF NOT EXISTS metrics (
    server_id TEXT NOT NULL,
    ts REAL NOT NULL,
    running INTEGER NOT NULL,
    players INTEGER,
    cpu REAL,
    mem_mb REAL,
    mem_pct REAL,
    tps REAL,
    mspt REAL
);
CREATE INDEX IF NOT EXISTS ix_metrics ON metrics(server_id, ts);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    server_id TEXT NOT NULL,
    ts REAL NOT NULL,
    type TEXT NOT NULL,          -- join, leave, chat, death, advancement, server
    player TEXT,
    uuid TEXT,
    message TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_events ON events(server_id, ts);
CREATE INDEX IF NOT EXISTS ix_events_player ON events(server_id, player, ts);

CREATE TABLE IF NOT EXISTS log_state (
    server_id TEXT PRIMARY KEY,
    inode INTEGER,
    offset INTEGER,
    head TEXT
);
"""


def tz() -> ZoneInfo:
    try:
        return ZoneInfo(os.getenv("TZ") or "UTC")
    except Exception:
        return ZoneInfo("UTC")


def conn() -> sqlite3.Connection:
    global _conn
    with _lock:
        if _conn is None:
            path = config.data_dir / "lodestone.db"
            _conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
            _conn.row_factory = sqlite3.Row
            _conn.execute("PRAGMA journal_mode=WAL")
            _conn.execute("PRAGMA synchronous=NORMAL")
            _conn.executescript(SCHEMA)
        return _conn


def q(sql: str, args: tuple = ()) -> list[sqlite3.Row]:
    with _lock:
        return conn().execute(sql, args).fetchall()


def x(sql: str, args: tuple = ()) -> int:
    with _lock:
        cur = conn().execute(sql, args)
        return cur.lastrowid or cur.rowcount


# ---------------------------------------------------------------- sessions
def open_sessions(server_id: str) -> dict[str, sqlite3.Row]:
    rows = q("SELECT * FROM sessions WHERE server_id=? AND end_ts IS NULL", (server_id,))
    return {r["player"].lower(): r for r in rows}


def update_sessions(server_id: str, online: dict[str, str | None], now: float) -> tuple[list[str], list[str]]:
    """online: name -> uuid. Returns (joined, left) names since the last call."""
    current = open_sessions(server_id)
    joined, left = [], []
    with _lock:
        for name, uuid in online.items():
            row = current.get(name.lower())
            if row:
                x("UPDATE sessions SET last_seen_ts=?, uuid=COALESCE(uuid, ?) WHERE id=?", (now, uuid, row["id"]))
            else:
                x("INSERT INTO sessions(server_id, player, uuid, start_ts, last_seen_ts) VALUES (?,?,?,?,?)",
                  (server_id, name, uuid, now, now))
                joined.append(name)
        online_l = {n.lower() for n in online}
        for key, row in current.items():
            if key not in online_l:
                x("UPDATE sessions SET end_ts=last_seen_ts WHERE id=?", (row["id"],))
                left.append(row["player"])
    return joined, left


def close_stale_sessions(max_gap: float) -> None:
    """On startup: sessions not seen recently ended when they were last seen."""
    x("UPDATE sessions SET end_ts=last_seen_ts WHERE end_ts IS NULL AND last_seen_ts < ?", (time.time() - max_gap,))


def sessions(server_id: str, player: str | None = None, limit: int = 50, since: float | None = None) -> list[dict]:
    sql = "SELECT * FROM sessions WHERE server_id=?"
    args: list = [server_id]
    if player:
        sql += " AND lower(player)=lower(?)"
        args.append(player)
    if since:
        sql += " AND COALESCE(end_ts, last_seen_ts) >= ?"
        args.append(since)
    sql += " ORDER BY start_ts DESC LIMIT ?"
    args.append(limit)
    out = []
    for r in q(sql, tuple(args)):
        end = r["end_ts"] or r["last_seen_ts"]
        out.append({"player": r["player"], "uuid": r["uuid"], "start": r["start_ts"], "end": r["end_ts"],
                    "last_seen": r["last_seen_ts"], "seconds": max(0, end - r["start_ts"]), "open": r["end_ts"] is None})
    return out


def daily_playtime(server_id: str, days: int = 14, player: str | None = None) -> list[dict]:
    """Seconds played per player per local day, splitting sessions across midnight."""
    zone = tz()
    today = datetime.now(zone).date()
    first = today - timedelta(days=days - 1)
    start_ts = datetime.combine(first, datetime.min.time(), zone).timestamp()
    sql = "SELECT player, start_ts, COALESCE(end_ts, last_seen_ts) AS e FROM sessions WHERE server_id=? AND COALESCE(end_ts, last_seen_ts) >= ?"
    args: list = [server_id, start_ts]
    if player:
        sql += " AND lower(player)=lower(?)"
        args.append(player)
    buckets: dict[date, dict[str, float]] = {first + timedelta(days=i): {} for i in range(days)}
    for r in q(sql, tuple(args)):
        s, e = max(r["start_ts"], start_ts), r["e"]
        while s < e:
            d = datetime.fromtimestamp(s, zone).date()
            next_midnight = datetime.combine(d + timedelta(days=1), datetime.min.time(), zone).timestamp()
            chunk_end = min(e, next_midnight)
            if d in buckets:
                buckets[d][r["player"]] = buckets[d].get(r["player"], 0) + (chunk_end - s)
            s = chunk_end
    return [{"date": d.isoformat(), "players": {k: round(v) for k, v in p.items()}} for d, p in sorted(buckets.items())]


def today_seconds(server_id: str) -> dict[str, int]:
    day = daily_playtime(server_id, days=1)[0]["players"]
    return {k.lower(): v for k, v in day.items()}


# ---------------------------------------------------------------- metrics
def add_metric(server_id: str, ts: float, running: bool, players: int | None, cpu: float | None,
               mem_mb: float | None, mem_pct: float | None, tps: float | None, mspt: float | None) -> None:
    x("INSERT INTO metrics VALUES (?,?,?,?,?,?,?,?,?)",
      (server_id, ts, int(running), players, cpu, mem_mb, mem_pct, tps, mspt))


RANGES = {"6h": (6 * 3600, 120), "24h": (86400, 300), "7d": (7 * 86400, 1800), "30d": (30 * 86400, 7200)}


def metrics(server_id: str, rng: str = "24h") -> dict:
    span, bucket = RANGES.get(rng, RANGES["24h"])
    since = time.time() - span
    rows = q(f"""SELECT CAST(ts/{bucket} AS INTEGER)*{bucket} AS t, MAX(running) AS running, MAX(players) AS players,
                 AVG(cpu) AS cpu, AVG(mem_mb) AS mem_mb, AVG(mem_pct) AS mem_pct, AVG(tps) AS tps, AVG(mspt) AS mspt,
                 MIN(tps) AS tps_min
                 FROM metrics WHERE server_id=? AND ts>=? GROUP BY t ORDER BY t""", (server_id, since))
    up = q("SELECT COUNT(*) AS n, SUM(running) AS r FROM metrics WHERE server_id=? AND ts>=?", (server_id, since))[0]
    latest = q("SELECT * FROM metrics WHERE server_id=? ORDER BY ts DESC LIMIT 1", (server_id,))
    return {
        "range": rng, "bucket": bucket, "since": since,
        "points": [{k: (round(r[k], 2) if isinstance(r[k], float) else r[k]) for k in r.keys()} for r in rows],
        "uptime": (up["r"] or 0) / up["n"] if up["n"] else None,
        "samples": up["n"],
        "latest": dict(latest[0]) if latest else None,
    }


# ---------------------------------------------------------------- events
def add_event(server_id: str, ts: float, etype: str, message: str, player: str | None = None, uuid: str | None = None) -> int:
    return x("INSERT INTO events(server_id, ts, type, player, uuid, message) VALUES (?,?,?,?,?,?)",
             (server_id, ts, etype, player, uuid, message))


def events(server_id: str, types: list[str] | None = None, player: str | None = None,
           limit: int = 100, before: float | None = None) -> list[dict]:
    sql = "SELECT * FROM events WHERE server_id=?"
    args: list = [server_id]
    if types:
        sql += f" AND type IN ({','.join('?' * len(types))})"
        args += types
    if player:
        sql += " AND lower(player)=lower(?)"
        args.append(player)
    if before:
        sql += " AND ts < ?"
        args.append(before)
    sql += " ORDER BY ts DESC, id DESC LIMIT ?"
    args.append(min(limit, 500))
    return [dict(r) for r in q(sql, tuple(args))]


# ---------------------------------------------------------------- log state
def get_log_state(server_id: str) -> sqlite3.Row | None:
    rows = q("SELECT * FROM log_state WHERE server_id=?", (server_id,))
    return rows[0] if rows else None


def set_log_state(server_id: str, inode: int, offset: int, head: str) -> None:
    x("INSERT INTO log_state VALUES (?,?,?,?) ON CONFLICT(server_id) DO UPDATE SET inode=excluded.inode, "
      "offset=excluded.offset, head=excluded.head", (server_id, inode, offset, head))


def prune(metrics_days: int, events_days: int) -> None:
    now = time.time()
    x("DELETE FROM metrics WHERE ts < ?", (now - metrics_days * 86400,))
    x("DELETE FROM events WHERE ts < ?", (now - events_days * 86400,))
