"""Moving a server's history to another server (Manage → Solstone → History & data → Move history).

A server moved to a game host is a new server to Solstone (its own id), so what Solstone recorded of it at home (playtime,
the activity feed, the stats page, adventures, uptime, recaps, fish) stayed with the old one. This moves all of it to the
new one, in one go: the rows of every table kept by server are given the new server's id. Where both have a day (the new
one was tried out while the old one was still played on), they're put together: an event both have is kept once, and
that day's stats-page totals and recap are worked out again from the two together. The old server keeps its settings,
and is left with no history. A full backup of Solstone is made first (Manage → Solstone → Backups), so it can be undone.
Nothing on either Minecraft server is touched: only Solstone's own records.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime

from . import db

log = logging.getLogger("solstone.movehistory")

# (table, what it is): every table kept by server, but log_state (how far Solstone has read that server's own log)
TABLES = (
    ("sessions", "Play sessions (time played, leaderboards)"),
    ("events", "Activity (joins, chat, deaths, advancements, progress)"),
    ("stat_tally", "Stats from each save (distance, advancements, deaths)"),
    ("daily_stats", "Server stats page days"),
    ("positions", "Where players were (map trails, adventures)"),
    ("travel_cells", "Where each player has ever been (Travels, all time)"),
    ("travel_records", "Each player's deepest, highest and farthest"),
    ("adventures", "Adventures named or noted"),
    ("adventures_hidden", "Adventures hidden"),
    ("metrics", "Uptime, players on, CPU and memory"),
    ("recaps", "Daily recaps (and \"on this day\")"),
    ("fish_catches", "Fish caught"),
    ("audit", "Activity log entries"),
)
_lock = threading.Lock()


def _ensure() -> None:
    from . import adventures, serverstats
    adventures._tally_ensure()
    adventures.travel_ensure()
    serverstats._ensure()


def counts(sid: str) -> list[dict]:
    """How much of each kind a server has, and the days it covers."""
    _ensure()
    out = []
    for table, label in TABLES:
        n = db.q(f"SELECT COUNT(*) AS n FROM {table} WHERE server_id=?", (sid,))[0]["n"]
        out.append({"table": table, "label": label, "rows": n})
    return out


def _span(sid: str) -> dict:
    r = db.q("SELECT MIN(t) AS lo, MAX(t) AS hi FROM (SELECT MIN(start_ts) AS t FROM sessions WHERE server_id=? UNION ALL "
             "SELECT MAX(COALESCE(end_ts, last_seen_ts)) FROM sessions WHERE server_id=? UNION ALL "
             "SELECT MIN(ts) FROM events WHERE server_id=? UNION ALL SELECT MAX(ts) FROM events WHERE server_id=?)",
             (sid, sid, sid, sid))[0]
    return {"first": r["lo"], "last": r["hi"]}


def _days(sid: str, table: str) -> set[str]:
    return {r["day"] for r in db.q(f"SELECT day FROM {table} WHERE server_id=?", (sid,))}


def preview(src: str, dst: str) -> dict:
    """What moving would do: what the old one has, what the new one has, and the days both have."""
    _ensure()
    both = sorted(_days(src, "daily_stats") & _days(dst, "daily_stats"))
    return {"from": {"counts": counts(src), **_span(src)}, "to": {"counts": counts(dst), **_span(dst)}, "both_days": both}


def move(src: str, dst: str) -> dict:
    """Every row of src's history becomes dst's. Returns how many rows of each kind moved, and the days both had."""
    if not src or not dst or src == dst:
        raise ValueError("Pick two different servers")
    from . import selfbackup, serverstats
    _ensure()
    with _lock:
        backup = selfbackup.make()                       # (undo: put this backup back)
        both = sorted((_days(src, "daily_stats") | _days(src, "recaps")) & (_days(dst, "daily_stats") | _days(dst, "recaps")))
        moved: dict[str, int] = {}
        with db._lock:
            c = db.conn()
            c.execute("BEGIN IMMEDIATE")
            try:
                for table, _label in TABLES:
                    if table in ("daily_stats", "recaps"):
                        # the days both have: worked out again below from the two together
                        if both:
                            marks = ",".join("?" * len(both))
                            c.execute(f"DELETE FROM {table} WHERE server_id IN (?,?) AND day IN ({marks})", (src, dst, *both))
                    before = c.execute(f"SELECT COUNT(*) FROM {table} WHERE server_id=?", (src,)).fetchone()[0]
                    # OR IGNORE: an event the new server has too (the same moment, kind, player and words) is kept once
                    c.execute(f"UPDATE OR IGNORE {table} SET server_id=? WHERE server_id=?", (dst, src))
                    dup = c.execute(f"DELETE FROM {table} WHERE server_id=?", (src,)).rowcount
                    moved[table] = before - dup
                    if dup:
                        moved[f"{table}_same"] = dup
                c.execute("COMMIT")
            except Exception:
                c.execute("ROLLBACK")
                raise
        # the days both had: the stats page's totals from the two together (the recap: on its next round, as for any day)
        if both:
            days = [datetime.strptime(d, "%Y-%m-%d").date() for d in both]
            for day, data in serverstats.compute(dst, days).items():
                import json
                db.x("INSERT OR REPLACE INTO daily_stats(server_id, day, data) VALUES (?,?,?)", (dst, day, json.dumps(data)))
        for sid in (src, dst):
            serverstats._done.pop(sid, None)
        _forget_memory(src, dst)
    log.info("history moved from %s to %s: %s (backup %s)", src, dst, moved, backup.get("name"))
    return {"moved": moved, "both_days": both, "backup": backup.get("name")}


def _forget_memory(src: str, dst: str) -> None:
    """What's kept in memory about either server (last positions, last stats seen) is read afresh."""
    from . import adventures
    for cache in (adventures._last, adventures._stats):
        for k in [k for k in cache if k[0] in (src, dst)]:
            cache.pop(k, None)
