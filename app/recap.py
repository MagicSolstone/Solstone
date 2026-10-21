"""Daily recaps: who played, what they did, and "on this day" looking back.

Raw events are pruned after a while (EVENTS_RETENTION_DAYS), so each finished day
is boiled down to one small summary row that is kept forever. Days from before
Solstone was installed are filled in once from the server's own old logs
(logs/YYYY-MM-DD-N.log.gz), which Minecraft keeps until someone deletes them.
"""
from __future__ import annotations

import gzip
import json
import logging
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from . import db
from .logparse import parse_line

log = logging.getLogger("solstone.recap")

_ADV = re.compile(r"has (made the advancement|completed the challenge|reached the goal) \[(.+)\]$")
_LOG_NAME = re.compile(r"^(\d{4}-\d{2}-\d{2})-(\d+)\.log(\.gz)?$")
MAX_LIST = 40          # advancements/deaths kept per day
MAX_LOG_BYTES = 64 * 1024 * 1024   # skip absurdly large single logs


def _bounds(day: date) -> tuple[float, float]:
    zone = db.tz()
    s = datetime.combine(day, datetime.min.time(), zone)
    return s.timestamp(), datetime.combine(day + timedelta(days=1), datetime.min.time(), zone).timestamp()


def _adv_kind(message: str) -> tuple[str, str]:
    m = _ADV.search(message)
    if not m:
        return "advancement", message
    verb, title = m.groups()
    return {"made the advancement": "advancement", "completed the challenge": "challenge", "reached the goal": "goal"}[verb], title


def summarize(day: date, intervals: list[tuple[str, str | None, float, float]], events: list[tuple[float, str, str | None, str]],
              seen_before: set[str]) -> dict:
    """intervals: (player, uuid, start, end); events: (ts, type, player, message). Both may spill past the day."""
    d0, d1 = _bounds(day)
    secs: dict[str, float] = {}
    first: dict[str, float] = {}
    uuids: dict[str, str] = {}
    edges: list[tuple[float, int]] = []
    canon: dict[str, str] = {}
    for name, uuid, s, e in intervals:
        s, e = max(s, d0), min(e, d1)
        if e <= s:
            continue
        key = canon.setdefault(name.lower(), name)
        secs[key] = secs.get(key, 0) + (e - s)
        first[key] = min(first.get(key, s), s)
        if uuid:
            uuids[key] = uuid
        edges += [(s, 1), (e, -1)]
    peak = cur = 0
    for _t, step in sorted(edges, key=lambda x: (x[0], x[1])):
        cur += step
        peak = max(peak, cur)
    adv, deaths, levels, chats = [], [], [], 0
    for ts, etype, player, message in sorted(events, key=lambda x: x[0]):
        if not d0 <= ts < d1:
            continue
        if etype == "chat":
            chats += 1
        elif etype == "advancement" and len(adv) < MAX_LIST:
            kind, title = _adv_kind(message)
            adv.append({"player": player, "title": title, "kind": kind, "ts": round(ts)})
        elif etype == "death" and len(deaths) < MAX_LIST:
            deaths.append({"player": player, "message": message, "ts": round(ts)})
        elif etype == "level":
            levels.append({"player": player, "message": message})
        if player and player.lower() not in canon and etype in ("advancement", "death", "join"):
            canon[player.lower()] = player
    players = sorted(({"name": n, "uuid": uuids.get(n), "seconds": round(v), "first": round(first[n])} for n, v in secs.items() if v >= 30),
                     key=lambda p: -p["seconds"])
    newcomers = [p["name"] for p in players if p["name"].lower() not in seen_before]
    return {"day": day.isoformat(), "players": players, "total_seconds": sum(p["seconds"] for p in players),
            "peak": peak, "advancements": adv, "deaths": deaths, "levels": levels[:MAX_LIST], "chats": chats,
            "newcomers": newcomers}


def active(r: dict | None) -> bool:
    return bool(r and (r.get("players") or r.get("advancements") or r.get("deaths")))


# ------------------------------------------------------------------ from Solstone's own history
def _seen_before(server_id: str, day: date) -> set[str]:
    seen = {r["player"].lower() for r in db.q("SELECT DISTINCT player FROM sessions WHERE server_id=? AND start_ts < ?",
                                              (server_id, _bounds(day)[0]))}
    for r in db.q("SELECT data FROM recaps WHERE server_id=? AND day < ?", (server_id, day.isoformat())):
        try:
            seen.update(p["name"].lower() for p in json.loads(r["data"]).get("players", []))
        except (ValueError, KeyError, TypeError):
            continue
    return seen


def from_db(server_id: str, day: date) -> dict:
    d0, d1 = _bounds(day)
    now = time.time()
    # A session that is still going counts up to now, not to the last 30 s poll.
    intervals = [(r["player"], r["uuid"], r["start_ts"], now if r["end_ts"] is None and r["e"] >= now - 120 else r["e"])
                 for r in db.q("SELECT player, uuid, start_ts, end_ts, COALESCE(end_ts, last_seen_ts) AS e FROM sessions "
                               "WHERE server_id=? AND start_ts < ? AND COALESCE(end_ts, last_seen_ts) > ?", (server_id, d1, d0))]
    events = [(r["ts"], r["type"], r["player"], r["message"]) for r in
              db.q("SELECT ts, type, player, message FROM events WHERE server_id=? AND ts>=? AND ts<?", (server_id, d0, d1))]
    out = summarize(day, intervals, events, _seen_before(server_id, day))
    out["source"] = "live"
    return out


def stored(server_id: str, day: date) -> dict | None:
    rows = db.q("SELECT data FROM recaps WHERE server_id=? AND day=?", (server_id, day.isoformat()))
    return json.loads(rows[0]["data"]) if rows else None


def _store(server_id: str, r: dict, source: str) -> None:
    r = {**r, "source": source}
    db.x("INSERT OR REPLACE INTO recaps(server_id, day, data, source, created_ts) VALUES (?,?,?,?,?)",
         (server_id, r["day"], json.dumps(r, separators=(",", ":")), source, time.time()))


def _first_day(server_id: str) -> date | None:
    r = db.q("SELECT MIN(t) AS t FROM (SELECT MIN(start_ts) AS t FROM sessions WHERE server_id=? "
             "UNION ALL SELECT MIN(ts) FROM events WHERE server_id=?)", (server_id, server_id))
    t = r[0]["t"] if r else None
    return datetime.fromtimestamp(t, db.tz()).date() if t else None


def finalize(server_id: str, max_days: int = 400) -> int:
    """Store a recap for every finished day since Solstone started recording that hasn't got one yet."""
    first = _first_day(server_id)
    if not first:
        return 0
    today = datetime.now(db.tz()).date()
    have = {r["day"] for r in db.q("SELECT day FROM recaps WHERE server_id=? AND day>=?", (server_id, first.isoformat()))}
    n = 0
    d = max(first, today - timedelta(days=max_days))
    while d < today:
        if d.isoformat() not in have:
            _store(server_id, from_db(server_id, d), "live")
            n += 1
        d += timedelta(days=1)
    return n


# ------------------------------------------------------------------ from old server logs
def _log_files(server_dir: Path) -> list[tuple[date, int, Path]]:
    folder = server_dir / "logs"
    out = []
    if not folder.is_dir():
        return out
    for f in folder.iterdir():
        m = _LOG_NAME.match(f.name)
        if m:
            try:
                out.append((date.fromisoformat(m.group(1)), int(m.group(2)), f))
            except ValueError:
                continue
    return sorted(out)


def _read(path: Path) -> str:
    try:
        if path.stat().st_size > MAX_LOG_BYTES:
            return ""
        raw = gzip.open(path, "rb").read(MAX_LOG_BYTES * 8) if path.suffix == ".gz" else path.read_bytes()
        return raw.decode("utf-8", errors="replace")
    except (OSError, EOFError, gzip.BadGzipFile):
        return ""


def from_logs(server_dir: Path, known: dict[str, str | None]) -> dict[date, tuple[list, list]]:
    """Old log files -> {day: (intervals, events)}. Each file's name gives the day its first line was written;
    a clock that goes backwards means midnight passed."""
    zone = db.tz()
    names = set(known)
    days: dict[date, tuple[list, list]] = {}
    for fday, _n, path in _log_files(server_dir):
        text = _read(path)
        if not text:
            continue
        day, prev = fday, -1
        open_: dict[str, float] = {}
        last_ts = None
        for line in text.splitlines():
            ev = parse_line(line, names)
            if not ev:
                continue
            secs = ev.hour * 3600 + ev.minute * 60 + ev.second
            if prev >= 0 and secs < prev - 600:
                day += timedelta(days=1)
            prev = secs
            ts = datetime.combine(day, datetime.min.time(), zone).replace(hour=ev.hour, minute=ev.minute, second=ev.second).timestamp()
            last_ts = ts
            if ev.player:
                names.add(ev.player.lower())
            bucket = days.setdefault(datetime.fromtimestamp(ts, zone).date(), ([], []))
            if ev.type == "join" and ev.player:
                open_.setdefault(ev.player, ts)
            elif ev.type == "leave" and ev.player and ev.player in open_:
                s = open_.pop(ev.player)
                _add_interval(days, zone, ev.player, known.get(ev.player.lower()), s, ts)
            elif ev.type == "server":
                for p, s in open_.items():
                    _add_interval(days, zone, p, known.get(p.lower()), s, ts)
                open_.clear()
            if ev.type in ("advancement", "death", "chat"):
                bucket[1].append((ts, ev.type, ev.player, ev.message))
        for p, s in open_.items():       # the log ended (crash or rotation) with people still on
            if last_ts:
                _add_interval(days, zone, p, known.get(p.lower()), s, last_ts)
    return days


def _add_interval(days: dict, zone, player: str, uuid: str | None, s: float, e: float) -> None:
    if e <= s:
        return
    d = datetime.fromtimestamp(s, zone).date()
    days.setdefault(d, ([], []))[0].append((player, uuid, s, e))
    end_day = datetime.fromtimestamp(e, zone).date()
    while d < end_day:                   # a session past midnight counts on both days
        d += timedelta(days=1)
        days.setdefault(d, ([], []))[0].append((player, uuid, s, e))


def backfill(server_id: str, server_dir: Path, known: dict[str, str | None]) -> int:
    """Fill in recaps from old logs. A day Solstone already summarised is only replaced when
    the logs saw more play (the install day, say, when recording started part-way through)."""
    today = datetime.now(db.tz()).date()
    days = from_logs(server_dir, known)
    seen: set[str] = set()
    n = 0
    for d in sorted(days):
        if d >= today:
            break
        intervals, events = days[d]
        r = summarize(d, intervals, events, seen)
        seen.update(p["name"].lower() for p in r["players"])
        if not active(r):
            continue
        cur = stored(server_id, d)
        if cur is None or (cur.get("source") != "logs" and r["total_seconds"] > cur.get("total_seconds", 0) + 300):
            _store(server_id, r, "logs")
            n += 1
    return n


# ------------------------------------------------------------------ reading
def day_recap(server_id: str, day: date) -> dict:
    today = datetime.now(db.tz()).date()
    if day >= today:
        return from_db(server_id, today)
    return stored(server_id, day) or from_db(server_id, day)


def _same_day(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year - years)
    except ValueError:                  # 29 February
        return d.replace(year=d.year - years, day=28)


def _month_ago(d: date) -> date:
    y, m = (d.year, d.month - 1) if d.month > 1 else (d.year - 1, 12)
    for day in (d.day, 30, 29, 28):
        try:
            return date(y, m, day)
        except ValueError:
            continue
    return d - timedelta(days=30)


def on_this_day(server_id: str, day: date) -> list[dict]:
    """The same date in earlier years (and a month ago), when anything happened."""
    out = []
    first = db.q("SELECT MIN(day) AS d FROM recaps WHERE server_id=?", (server_id,))[0]["d"]
    if not first:
        return out
    m = _month_ago(day)
    r = stored(server_id, m)
    if active(r):
        out.append({"label": "A month ago", "years": 0, **r})
    for years in range(1, 30):
        d = _same_day(day, years)
        if d.isoformat() < first:
            break
        r = stored(server_id, d)
        if active(r):
            out.append({"label": "A year ago" if years == 1 else f"{years} years ago", "years": years, **r})
    return out


def neighbours(server_id: str, day: date) -> dict:
    """The nearest days before and after with something in them, for paging."""
    k = day.isoformat()
    prev = db.q("SELECT day, data FROM recaps WHERE server_id=? AND day<? ORDER BY day DESC LIMIT 60", (server_id, k))
    nxt = db.q("SELECT day, data FROM recaps WHERE server_id=? AND day>? ORDER BY day LIMIT 60", (server_id, k))
    pick = lambda rows: next((r["day"] for r in rows if active(json.loads(r["data"]))), None)  # noqa: E731
    today = datetime.now(db.tz()).date()
    after = pick(nxt)
    if not after and day < today:
        after = today.isoformat()
    first = db.q("SELECT MIN(day) AS d, COUNT(*) AS n FROM recaps WHERE server_id=?", (server_id,))[0]
    return {"prev": pick(prev), "next": after, "first": first["d"], "stored_days": first["n"]}
