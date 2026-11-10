"""Server stats over time: what everyone did on a server, day by day, kept for good (the Stats tab).

The detailed history (events) is kept 180 days and the performance readings 30, so each day is boiled down to one
small row of totals (monsters defeated, blocks mined, distance travelled, hours played...) that's kept forever. On
first use it's filled in from everything still on hand; after that the last couple of days are worked out again as
they change, and older days are left as they were (so pruning the detail later loses nothing).

Server-wide only: no player names anywhere in it.
"""
from __future__ import annotations

import json
import threading
import time
from datetime import date, datetime, timedelta

from . import adventures, db

KEYS = ("play_hours", "players", "new_players", "peak", "mobs", "deaths", "mined", "placed", "logs", "crops",
        "travelled", "fish", "advancements", "chat", "trades", "bred", "chests", "events")
_COUNTED = {"death": "deaths", "advancement": "advancements", "chat": "chat", "webchat": "chat", "fish": "fish",
            "bigfish": "fish", "challenge": "events", "race": "events", "game": "events"}
REFRESH = 600                                     # seconds between working the recent days out again
_lock = threading.Lock()
_done: dict[str, float] = {}                     # server id -> when its days were last brought up to date


def _ensure() -> None:
    db.x("CREATE TABLE IF NOT EXISTS daily_stats (server_id TEXT NOT NULL, day TEXT NOT NULL, data TEXT NOT NULL, "
         "PRIMARY KEY (server_id, day))")


def _bounds(d: date) -> tuple[float, float]:
    zone = db.tz()
    start = datetime.combine(d, datetime.min.time(), zone)
    return start.timestamp(), (start + timedelta(days=1)).timestamp()


def _day_of(ts: float) -> date:
    return datetime.fromtimestamp(ts, db.tz()).date()


def compute(sid: str, days: list[date]) -> dict[str, dict]:
    """Each day's totals, from the history on hand."""
    if not days:
        return {}
    lo, hi = _bounds(min(days))[0], _bounds(max(days))[1]
    out: dict[str, dict] = {d.isoformat(): {} for d in days}

    def add(day: str, key: str, n: float) -> None:
        if day in out and n:
            out[day][key] = out[day].get(key, 0) + n
    types = ["progress", *_COUNTED]
    marks = ",".join("?" * len(types))
    for e in db.q(f"SELECT ts, type, message FROM events WHERE server_id=? AND ts>=? AND ts<? AND type IN ({marks})",
                  (sid, lo, hi, *types)):
        day = _day_of(e["ts"]).isoformat()
        if e["type"] == "progress":
            for k, n in adventures.tally(e["message"]).items():
                if k in KEYS or k == "respawns":
                    add(day, k, n)
        else:
            add(day, _COUNTED[e["type"]], 1)
    # who played, and for how long (sessions are kept for good)
    seen: dict[str, set] = {}
    for s in db.q("SELECT lower(player) AS p, start_ts, COALESCE(end_ts, last_seen_ts) AS end_ts FROM sessions "
                  "WHERE server_id=? AND start_ts<? AND COALESCE(end_ts, last_seen_ts)>=?", (sid, hi, lo)):
        for d in days:
            a, b = _bounds(d)
            overlap = min(b, s["end_ts"]) - max(a, s["start_ts"])
            if overlap > 0:
                add(d.isoformat(), "play_hours", overlap / 3600)
                seen.setdefault(d.isoformat(), set()).add(s["p"])
    for day, who in seen.items():
        out[day]["players"] = len(who)
    for r in db.q("SELECT p, MIN(start_ts) AS first FROM (SELECT lower(player) AS p, start_ts FROM sessions WHERE server_id=?) "
                  "GROUP BY p HAVING first>=? AND first<?", (sid, lo, hi)):
        add(_day_of(r["first"]).isoformat(), "new_players", 1)
    for r in db.q("SELECT ts, players FROM metrics WHERE server_id=? AND ts>=? AND ts<? AND running=1 AND players IS NOT NULL",
                  (sid, lo, hi)):
        day = _day_of(r["ts"]).isoformat()
        if day in out:
            out[day]["peak"] = max(out[day].get("peak", 0), r["players"])
    # what each save added (adventures.record_save): every block travelled, every advancement and death, from the players'
    # own files. The feed's lines and the log can miss some, so each day takes whichever saw more.
    from .adventures import _tally_ensure
    _tally_ensure()
    seen_t: dict[str, dict[str, float]] = {}
    for r in db.q("SELECT ts, travelled, advancements, deaths FROM stat_tally WHERE server_id=? AND ts>=? AND ts<?", (sid, lo, hi)):
        t = seen_t.setdefault(_day_of(r["ts"]).isoformat(), {"travelled": 0.0, "advancements": 0, "deaths": 0})
        t["travelled"] += r["travelled"]
        t["advancements"] += r["advancements"]
        t["deaths"] += r["deaths"]
    for day, t in seen_t.items():
        if day in out:
            for k, n in t.items():
                if n > out[day].get(k, 0):
                    out[day][k] = n
    for v in out.values():
        # deaths: the log's death lines, or the players' own stats files (which never miss one), whichever saw more
        if v.get("respawns", 0) > v.get("deaths", 0):
            v["deaths"] = v["respawns"]
        v.pop("respawns", None)
        for k in ("play_hours", "travelled"):
            if k in v:
                v[k] = round(v[k], 2)
    return out


def rollup(sid: str, force: bool = False) -> None:
    """Bring this server's days up to date: any day with history that isn't stored yet, and the last two days again."""
    if not force and time.time() - _done.get(sid, 0) < REFRESH:
        return
    with _lock:
        _ensure()
        have = {r["day"] for r in db.q("SELECT day FROM daily_stats WHERE server_id=?", (sid,))}
        firsts = [r["t"] for r in db.q("SELECT MIN(ts) AS t FROM events WHERE server_id=? UNION ALL "
                                       "SELECT MIN(start_ts) FROM sessions WHERE server_id=?", (sid, sid)) if r["t"]]
        today = _day_of(time.time())
        todo = []
        if firsts:
            d = _day_of(min(firsts))
            while d <= today:
                if d.isoformat() not in have or (today - d).days <= 1:
                    todo.append(d)
                d += timedelta(days=1)
        for i in range(0, len(todo), 60):                 # a couple of months at a time
            for day, data in compute(sid, todo[i:i + 60]).items():
                db.x("INSERT OR REPLACE INTO daily_stats(server_id, day, data) VALUES (?,?,?)", (sid, day, json.dumps(data)))
        _done[sid] = time.time()


def days(sid: str) -> list[dict]:
    _ensure()
    return [{"day": r["day"], **json.loads(r["data"])}
            for r in db.q("SELECT day, data FROM daily_stats WHERE server_id=? ORDER BY day", (sid,))]


def heat(sid: str, since: float = 0) -> list[list[float]]:
    """Hours played by weekday (Monday first) and hour of the day, from the sessions."""
    grid = [[0.0] * 24 for _ in range(7)]
    zone = db.tz()
    for s in db.q("SELECT start_ts, COALESCE(end_ts, last_seen_ts) AS end_ts FROM sessions WHERE server_id=? "
                  "AND COALESCE(end_ts, last_seen_ts)>=?", (sid, since)):
        t, end = max(s["start_ts"], since), s["end_ts"]
        while t < end:
            dt = datetime.fromtimestamp(t, zone)
            nxt = min(end, (dt.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)).timestamp())
            grid[dt.weekday()][dt.hour] += (nxt - t) / 3600
            t = nxt
    return [[round(h, 2) for h in row] for row in grid]


def history(sid: str, since: float = 0) -> dict:
    rollup(sid)
    return {"days": days(sid), "heat": heat(sid, since), "keys": list(KEYS)}
