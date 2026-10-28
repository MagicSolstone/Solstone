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

CREATE UNIQUE INDEX IF NOT EXISTS ux_events ON events(server_id, ts, type, COALESCE(player, ''), message);

-- One summary per server per day, kept forever (the raw events are pruned).
CREATE TABLE IF NOT EXISTS recaps (
    server_id TEXT NOT NULL,
    day TEXT NOT NULL,
    data TEXT NOT NULL,
    source TEXT NOT NULL,
    created_ts REAL NOT NULL,
    PRIMARY KEY (server_id, day)
);

-- Every fish from the Solstone data pack, kept for good: the fishing journal.
CREATE TABLE IF NOT EXISTS fish_catches (
    id INTEGER PRIMARY KEY,
    server_id TEXT NOT NULL,
    ts REAL NOT NULL,
    player TEXT NOT NULL,
    species TEXT NOT NULL,
    name TEXT NOT NULL,
    quality INTEGER NOT NULL,
    quality_name TEXT NOT NULL,
    weight REAL NOT NULL,
    points INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_fish ON fish_catches(server_id, player, species);

CREATE TABLE IF NOT EXISTS alerts (
    key TEXT PRIMARY KEY,
    ts REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS positions (
    server_id TEXT NOT NULL,
    ts REAL NOT NULL,
    player TEXT NOT NULL,
    dim TEXT NOT NULL,
    x REAL NOT NULL, y REAL NOT NULL, z REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS positions_by_time ON positions(server_id, ts);
CREATE TABLE IF NOT EXISTS adventures (
    id INTEGER PRIMARY KEY,
    server_id TEXT NOT NULL,
    start_ts REAL NOT NULL,
    end_ts REAL NOT NULL,
    title TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    created_by TEXT,
    created_ts REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS adventures_hidden (
    server_id TEXT NOT NULL,
    start_ts REAL NOT NULL,
    end_ts REAL NOT NULL,
    hidden_by TEXT,
    hidden_ts REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    category TEXT NOT NULL,
    published INTEGER NOT NULL DEFAULT 1,
    pinned INTEGER NOT NULL DEFAULT 0,
    author TEXT,
    created_ts REAL NOT NULL,
    updated_ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_posts_list ON posts(category, published, pinned, created_ts);

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
            path = config.data_dir / "solstone.db"
            _conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
            _conn.row_factory = sqlite3.Row
            # WAL needs shared-memory mmap, which FUSE filesystems such as Unraid's
            # /mnt/user can't provide. Fall back to a classic rollback journal there.
            try:
                mode = _conn.execute("PRAGMA journal_mode=WAL").fetchone()[0]
            except sqlite3.OperationalError:
                mode = None
            if mode != "wal":
                _conn.execute("PRAGMA journal_mode=DELETE")
            _conn.execute("PRAGMA synchronous=NORMAL")
            try:
                _conn.executescript(SCHEMA)
            except sqlite3.IntegrityError:
                # Older databases may already hold duplicate events; drop them, then index.
                _conn.execute("DELETE FROM events WHERE id NOT IN (SELECT MIN(id) FROM events "
                              "GROUP BY server_id, ts, type, COALESCE(player, ''), message)")
                _conn.executescript(SCHEMA)
            # Added later: a post can be the join guide, the account guide or the rules (site.ROLES)
            cols = {c[1] for c in _conn.execute("PRAGMA table_info(posts)")}
            if "role" not in cols:
                _conn.execute("ALTER TABLE posts ADD COLUMN role TEXT")
            if "summary" not in cols:                # and its own words for its card (empty: the start of the post)
                _conn.execute("ALTER TABLE posts ADD COLUMN summary TEXT")
            # Early builds stored Crafty's byte counts as megabytes; convert them.
            _conn.execute("UPDATE metrics SET mem_mb = ROUND(mem_mb / 1048576.0, 1) WHERE mem_mb > 100000")
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
        "first_ts": (q("SELECT MIN(ts) AS t FROM metrics WHERE server_id=?", (server_id,))[0]["t"]),
    }


# ---------------------------------------------------------------- events
def add_event(server_id: str, ts: float, etype: str, message: str, player: str | None = None, uuid: str | None = None) -> int:
    # OR IGNORE: the same log line read twice (e.g. after a rotation mix-up) is stored once.
    return x("INSERT OR IGNORE INTO events(server_id, ts, type, player, uuid, message) VALUES (?,?,?,?,?,?)",
             (server_id, ts, etype, player, uuid, message))


def events_after(server_id: str, types: list[str], after_id: int = 0, limit: int = 200) -> list[dict]:
    """Newest `limit` events of these types (after_id=0), or everything newer than after_id; oldest first."""
    marks = ",".join("?" * len(types))
    if after_id:
        rows = q(f"SELECT * FROM events WHERE server_id=? AND type IN ({marks}) AND id > ? ORDER BY id LIMIT ?",
                 (server_id, *types, after_id, min(limit, 500)))
        return [dict(r) for r in rows]
    rows = q(f"SELECT * FROM events WHERE server_id=? AND type IN ({marks}) ORDER BY ts DESC, id DESC LIMIT ?",
             (server_id, *types, min(limit, 500)))
    return [dict(r) for r in reversed(rows)]


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


# ---------------------------------------------------------------- timeline
MATCH_SLACK = 90  # seconds; sessions come from a 30 s poll, log lines are exact


def _session_until(r, now: float) -> float:
    return now + 60 if r["end_ts"] is None else (r["end_ts"] or r["last_seen_ts"])


def timeline(server_id: str, player: str | None = None, before: float | None = None,
             sessions_limit: int = 20, include_chat: bool = True) -> dict:
    """Activity grouped into play-session blocks, newest first.

    Sessions that overlap in time are merged into one "played together" block
    so a conversation between players reads in order. Each block holds the
    events (chat, deaths, advancements, and for groups joins/leaves) that
    happened while its players were online. Server start/stop and anything
    outside a session stay as standalone items.

    Paging is by the requested player's (or anyone's) sessions. A block is
    shown on the page that holds its newest session, so it never repeats.
    """
    now = time.time()
    before = before or now + 60
    sql = "SELECT * FROM sessions WHERE server_id=? AND start_ts < ?"
    args: list = [server_id, before]
    if player:
        sql += " AND lower(player)=lower(?)"
        args.append(player)
    sql += " ORDER BY start_ts DESC LIMIT ?"
    args.append(sessions_limit)
    page = q(sql, tuple(args))
    more = len(page) == sessions_limit
    cutoff = min(r["start_ts"] for r in page) if more else 0.0

    # Pull in every session that overlaps (transitively) with this page's sessions.
    members: dict[int, sqlite3.Row] = {r["id"]: r for r in page}
    frontier = list(page)
    for _ in range(10):
        if not frontier:
            break
        lo = min(r["start_ts"] for r in frontier) - MATCH_SLACK
        hi = max(_session_until(r, now) for r in frontier) + MATCH_SLACK
        rows = q("SELECT * FROM sessions WHERE server_id=? AND start_ts <= ? AND COALESCE(end_ts, ?) >= ?",
                 (server_id, hi, now + 60, lo))
        frontier = [r for r in rows if r["id"] not in members and any(
            r["start_ts"] <= _session_until(m, now) + MATCH_SLACK and _session_until(r, now) + MATCH_SLACK >= m["start_ts"]
            for m in members.values())]
        for r in frontier:
            members[r["id"]] = r

    # Cluster overlapping sessions.
    rows = sorted(members.values(), key=lambda r: r["start_ts"])
    clusters: list[list[sqlite3.Row]] = []
    cur_end = None
    for r in rows:
        if clusters and r["start_ts"] <= cur_end + MATCH_SLACK:
            clusters[-1].append(r)
            cur_end = max(cur_end, _session_until(r, now))
        else:
            clusters.append([r])
            cur_end = _session_until(r, now)
    # A cluster belongs to the page holding its newest session; drop ones owned by a newer page,
    # and with a player filter, ones that don't include that player.
    page_ids = {r["id"] for r in page}
    keep = [c for c in clusters if max(r["start_ts"] for r in c) < before and any(r["id"] in page_ids for r in c)]
    # Events of sessions in clusters shown on another page must not leak in here as loose lines.
    elsewhere = [(r["player"].lower(), r["start_ts"], _session_until(r, now)) for c in clusters if c not in keep for r in c]
    clusters = keep

    lo = min((r["start_ts"] for c in clusters for r in c), default=cutoff) - MATCH_SLACK
    hi = max([before] + [_session_until(r, now) for c in clusters for r in c]) + MATCH_SLACK
    esql = "SELECT * FROM events WHERE server_id=? AND ts >= ? AND ts < ?"
    eargs: list = [server_id, min(lo, cutoff - MATCH_SLACK) if cutoff else 0, hi]
    if not include_chat:
        esql += " AND type != 'chat'"
    esql += " ORDER BY ts ASC, id ASC LIMIT 10000"
    evs = [dict(r) for r in q(esql, tuple(eargs))]

    # Sessions straddling the cutoff belong to the next page; their events wait for it.
    straddle = []
    if more:
        ssql = "SELECT * FROM sessions WHERE server_id=? AND start_ts < ? AND COALESCE(end_ts, last_seen_ts) >= ?"
        straddle = [(r["player"].lower(), r["start_ts"], _session_until(r, now))
                    for r in q(ssql, (server_id, cutoff, cutoff - MATCH_SLACK)) if r["id"] not in members]
    straddle += elsewhere

    blocks = []
    owner: list[tuple[str, float, float, dict]] = []  # (player, start, until, block)
    for c in clusters:
        sessions_out = []
        for r in sorted(c, key=lambda r: r["start_ts"]):
            end = r["end_ts"] or r["last_seen_ts"]
            sessions_out.append({"player": r["player"], "uuid": r["uuid"], "start": r["start_ts"], "end": r["end_ts"],
                                 "last_seen": r["last_seen_ts"], "open": r["end_ts"] is None,
                                 "seconds": max(0, end - r["start_ts"])})
        start = min(x["start"] for x in sessions_out)
        until_c = max(_session_until(r, now) for r in c)
        is_open = any(x["open"] for x in sessions_out)
        names = list(dict.fromkeys(x["player"] for x in sessions_out))
        b = {"kind": "session" if len(names) == 1 else "group", "players": names, "sessions": sessions_out,
             "start": start, "end": None if is_open else until_c, "open": is_open,
             "seconds": max(0, (now if is_open else until_c) - start), "events": []}
        if len(names) == 1:  # keep the single-session fields the UI already uses
            first = sessions_out[0]
            b.update(player=first["player"], uuid=first["uuid"], last_seen=sessions_out[-1]["last_seen"],
                     seconds=sum(x["seconds"] for x in sessions_out))
        blocks.append(b)
        for r in c:
            owner.append((r["player"].lower(), r["start_ts"], _session_until(r, now), b))

    loose = []
    for e in evs:
        home = None
        if e["player"]:
            pl = e["player"].lower()
            for p, s0, u, b in owner:
                if p == pl and s0 - MATCH_SLACK <= e["ts"] <= u + MATCH_SLACK:
                    home = b
                    break
        if home is not None:
            # A solo block's edges are its join/leave; in a group they show who came and went.
            if e["type"] not in ("join", "leave") or home["kind"] == "group":
                home["events"].append(e)
            continue
        if e["ts"] >= before or (cutoff and e["ts"] < cutoff):
            continue
        if player and e["type"] != "server" and (e["player"] or "").lower() != player.lower():
            continue
        if e["player"] and any(p == e["player"].lower() and s0 - MATCH_SLACK <= e["ts"] <= u + MATCH_SLACK
                               for p, s0, u in straddle):
            continue
        loose.append({"kind": "event", **e})

    for b in blocks:
        counts: dict[str, int] = {}
        for e in b["events"]:
            counts[e["type"]] = counts.get(e["type"], 0) + 1
        b["counts"] = counts

    items = blocks + loose
    items.sort(key=lambda it: it["start"] if it["kind"] != "event" else it["ts"], reverse=True)
    return {"items": items, "next_before": cutoff if more else None}


# ---------------------------------------------------------------- log state
def get_log_state(server_id: str) -> sqlite3.Row | None:
    rows = q("SELECT * FROM log_state WHERE server_id=?", (server_id,))
    return rows[0] if rows else None


def set_log_state(server_id: str, inode: int, offset: int, head: str) -> None:
    x("INSERT INTO log_state VALUES (?,?,?,?) ON CONFLICT(server_id) DO UPDATE SET inode=excluded.inode, "
      "offset=excluded.offset, head=excluded.head", (server_id, inode, offset, head))


def alert_once(key: str) -> bool:
    """True the first time a key is seen (used so an alert fires once per day/week)."""
    with _lock:
        cur = conn().execute("INSERT OR IGNORE INTO alerts(key, ts) VALUES (?, ?)", (key, time.time()))
        return cur.rowcount == 1


def week_stats(server_id: str, days: int = 7) -> dict:
    """Numbers for the weekly digest."""
    daily = daily_playtime(server_id, days)
    since = datetime.combine(datetime.fromisoformat(daily[0]["date"]).date(), datetime.min.time(), tz()).timestamp()
    per_player: dict[str, dict] = {}
    for d in daily:
        for name, secs in d["players"].items():
            per_player.setdefault(name, {"seconds": 0, "deaths": 0, "advancements": 0})["seconds"] += secs
    for r in q("SELECT player, type, COUNT(*) AS n FROM events WHERE server_id=? AND ts>=? AND type IN ('death','advancement') "
               "AND player IS NOT NULL GROUP BY player, type", (server_id, since)):
        entry = next((v for k, v in per_player.items() if k.lower() == r["player"].lower()), None)
        if entry is None:
            entry = per_player.setdefault(r["player"], {"seconds": 0, "deaths": 0, "advancements": 0})
        entry["deaths" if r["type"] == "death" else "advancements"] += r["n"]
    busiest = max(daily, key=lambda d: sum(d["players"].values())) if daily else None
    # Time spent online together, per pair of players
    rows = q("SELECT player, start_ts, COALESCE(end_ts, last_seen_ts) AS e FROM sessions WHERE server_id=? AND "
             "COALESCE(end_ts, last_seen_ts) >= ?", (server_id, since))
    pairs: dict[tuple[str, str], float] = {}
    for i, a in enumerate(rows):
        for b in rows[i + 1:]:
            if a["player"].lower() == b["player"].lower():
                continue
            overlap = min(a["e"], b["e"]) - max(a["start_ts"], b["start_ts"], since)
            if overlap > 0:
                key = tuple(sorted((a["player"], b["player"]), key=str.lower))
                pairs[key] = pairs.get(key, 0) + overlap
    top_pair = max(pairs.items(), key=lambda kv: kv[1]) if pairs else None
    return {
        "players": per_player,
        "busiest_day": {"date": busiest["date"], "seconds": sum(busiest["players"].values())} if busiest and sum(busiest["players"].values()) else None,
        "together": {"players": list(top_pair[0]), "seconds": round(top_pair[1])} if top_pair else None,
    }


def prune(metrics_days: int, events_days: int) -> None:
    now = time.time()
    x("DELETE FROM metrics WHERE ts < ?", (now - metrics_days * 86400,))
    x("DELETE FROM events WHERE ts < ?", (now - events_days * 86400,))


def add_catch(server_id: str, ts: float, player: str, c: dict) -> dict:
    """Record a fish; says whether it's new to this player's journal and a personal best."""
    prev = q("SELECT COUNT(*) AS n, MAX(weight) AS best FROM fish_catches WHERE server_id=? AND player=? AND species=?",
             (server_id, player, c["species"]))[0]
    x("INSERT INTO fish_catches(server_id, ts, player, species, name, quality, quality_name, weight, points) VALUES (?,?,?,?,?,?,?,?,?)",
      (server_id, ts, player, c["species"], c["name"], c["quality"], c["quality_name"], c["weight"], c["points"]))
    kinds = q("SELECT COUNT(DISTINCT species) AS n FROM fish_catches WHERE server_id=? AND player=?", (server_id, player))[0]["n"]
    return {"new_species": prev["n"] == 0, "personal_best": prev["n"] > 0 and c["weight"] > (prev["best"] or 0), "species_caught": kinds}


def clear_fishing(server_id: str, player: str) -> int:
    """Forget a player's catches and fishing feed lines (for a fresh start). Returns how many catches went."""
    with _lock:
        c = conn()
        n = c.execute("DELETE FROM fish_catches WHERE server_id=? AND lower(player)=lower(?)", (server_id, player)).rowcount
        c.execute("DELETE FROM events WHERE server_id=? AND type IN ('fish','bigfish') AND lower(player)=lower(?)", (server_id, player))
    return n


def fish_catches(server_id: str, player: str | None = None) -> list[dict]:
    if player:
        rows = q("SELECT * FROM fish_catches WHERE server_id=? AND player=? ORDER BY ts", (server_id, player))
    else:
        rows = q("SELECT * FROM fish_catches WHERE server_id=? ORDER BY ts", (server_id,))
    return [dict(r) for r in rows]


# ---------------------------------------------------------------- clearing what Solstone kept about a server
# (Manage → Servers: for a new world, or a fresh start.) The game server itself is never touched.
CHAT_TYPES = ("chat", "webchat", "webdm")
CLEAR_KINDS = ("chat", "activity", "recaps", "play", "performance", "fishing")


def clear_server(server_id: str, kinds: set[str]) -> dict[str, int]:
    """Delete the chosen kinds of saved history for one server. Returns rows removed per kind.
    Sessions still open (someone playing right now) are kept, so they don't count as joining again."""
    marks = ",".join("?" * len(CHAT_TYPES))
    plan = {
        "chat": [(f"DELETE FROM events WHERE server_id=? AND type IN ({marks})", (server_id, *CHAT_TYPES))],
        "activity": [(f"DELETE FROM events WHERE server_id=? AND type NOT IN ({marks})", (server_id, *CHAT_TYPES))],
        "recaps": [("DELETE FROM recaps WHERE server_id=?", (server_id,))],
        "play": [("DELETE FROM sessions WHERE server_id=? AND end_ts IS NOT NULL", (server_id,)),
                 ("DELETE FROM positions WHERE server_id=?", (server_id,)),
                 ("DELETE FROM adventures WHERE server_id=?", (server_id,)),
                 ("DELETE FROM adventures_hidden WHERE server_id=?", (server_id,))],
        "performance": [("DELETE FROM metrics WHERE server_id=?", (server_id,))],
        "fishing": [("DELETE FROM fish_catches WHERE server_id=?", (server_id,))],
    }
    out: dict[str, int] = {}
    with _lock:
        c = conn()
        for kind in CLEAR_KINDS:
            if kind in kinds:
                out[kind] = sum(c.execute(sql, args).rowcount for sql, args in plan[kind])
        c.commit()
    return out
