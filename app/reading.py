"""What people read on the website: each page's views, how many different people, how many read it to the end, and
how long they stayed (Manage → Solstone → What people read).

The page itself reports it (home.js): a view when it opens, "read" once someone has reached the end and been on it
15 seconds or more, and the time they had it open on screen when they leave. Admins' own visits aren't counted.

Nobody is named: visitors are told apart for the day by a scrambled address that changes daily (never stored), and
signed-in players by their account, only to count them once; what's kept is counts per page, per day.
"""
from __future__ import annotations

import hashlib
import re
import secrets
import threading
import time

from . import db

KEEP_DAYS = 730
READ_SECS = 15                         # (the page decides "read": reached the end, and open this long)
_PAGE = re.compile(r"^/(?:|help|events|post/[a-z0-9-]{1,80}|guides/[a-z0-9_-]{1,40})$")
_BOT = re.compile(r"bot|spider|crawl|slurp|preview|fetch", re.I)
_lock = threading.Lock()
_day = {"day": "", "salt": b"", "people": set(), "reads": set(), "secs": {}}


def _ensure() -> None:
    db.x("CREATE TABLE IF NOT EXISTS reading (day TEXT NOT NULL, page TEXT NOT NULL, who TEXT NOT NULL, views INTEGER NOT NULL DEFAULT 0, "
         "people INTEGER NOT NULL DEFAULT 0, reads INTEGER NOT NULL DEFAULT 0, secs REAL NOT NULL DEFAULT 0, timed INTEGER NOT NULL DEFAULT 0, "
         "PRIMARY KEY (day, page, who))")
    db.x("CREATE TABLE IF NOT EXISTS reading_titles (page TEXT PRIMARY KEY, title TEXT NOT NULL)")


def page_ok(page: str) -> bool:
    return bool(_PAGE.match(page or ""))


def is_bot(agent: str) -> bool:
    return bool(_BOT.search(agent or ""))


def _today(now: float) -> str:
    day = time.strftime("%Y-%m-%d", time.localtime(now))
    if _day["day"] != day:                             # a new scramble each day: yesterday's can't be matched up
        _day.update(day=day, salt=secrets.token_bytes(16), people=set(), reads=set(), secs={})
    return day


def note(page: str, title: str, event: str, view_id: str, user, ip: str, secs: float = 0, now: float | None = None) -> bool:
    """One report from a page. Not counted: admins, unknown pages. True if counted."""
    if not page_ok(page) or event not in ("view", "read", "time") or getattr(user, "role", "") == "admin":
        return False
    now = now or time.time()
    who = "player" if user is not None else "visitor"
    view_id = str(view_id or "")[:40]
    _ensure()
    with _lock:
        day = _today(now)
        person = f"u{user.id}" if user is not None else hashlib.sha256(_day["salt"] + ip.encode()).hexdigest()[:16]
        add = {"views": 0, "people": 0, "reads": 0, "secs": 0.0, "timed": 0}
        if event == "view":
            add["views"] = 1
            if (page, person) not in _day["people"]:
                _day["people"].add((page, person))
                add["people"] = 1
        elif event == "read":
            if not view_id or (page, view_id) in _day["reads"]:
                return False
            _day["reads"].add((page, view_id))
            add["reads"] = 1
        else:                                          # time: sent each time they leave (or switch away); only what's new counts
            secs = max(0.0, min(float(secs or 0), 4 * 3600))
            key = (page, view_id)
            before = _day["secs"].get(key)
            if not view_id or secs <= (before or 0):
                return False
            _day["secs"][key] = secs
            add["secs"] = secs - (before or 0)
            add["timed"] = 0 if before is not None else 1
    db.x("INSERT INTO reading (day, page, who, views, people, reads, secs, timed) VALUES (?,?,?,?,?,?,?,?) "
         "ON CONFLICT(day, page, who) DO UPDATE SET views=views+excluded.views, people=people+excluded.people, "
         "reads=reads+excluded.reads, secs=secs+excluded.secs, timed=timed+excluded.timed",
         (day, page, who, add["views"], add["people"], add["reads"], add["secs"], add["timed"]))
    if event == "view" and title:
        db.x("INSERT INTO reading_titles (page, title) VALUES (?, ?) ON CONFLICT(page) DO UPDATE SET title=excluded.title",
             (page, " ".join(str(title).split())[:120]))
    return True


def prune(now: float | None = None) -> None:
    _ensure()
    cut = time.strftime("%Y-%m-%d", time.localtime((now or time.time()) - KEEP_DAYS * 86400))
    db.x("DELETE FROM reading WHERE day < ?", (cut,))


def report(days: int = 30, now: float | None = None) -> dict:
    """Each page over the last so many days: views, people, read to the end, average time, by visitors and players."""
    _ensure()
    now = now or time.time()
    since = time.strftime("%Y-%m-%d", time.localtime(now - (days - 1) * 86400))
    rows = db.q("SELECT page, who, SUM(views) v, SUM(people) p, SUM(reads) r, SUM(secs) s, SUM(timed) t FROM reading "
                "WHERE day >= ? GROUP BY page, who", (since,))
    titles = {r["page"]: r["title"] for r in db.q("SELECT page, title FROM reading_titles")}
    pages: dict[str, dict] = {}
    for r in rows:
        p = pages.setdefault(r["page"], {"page": r["page"], "title": titles.get(r["page"]) or r["page"], "views": 0, "people": 0,
                                          "reads": 0, "secs": 0.0, "timed": 0, "visitors": 0, "players": 0})
        p["views"] += r["v"] or 0
        p["people"] += r["p"] or 0
        p["reads"] += r["r"] or 0
        p["secs"] += r["s"] or 0
        p["timed"] += r["t"] or 0
        p["visitors" if r["who"] == "visitor" else "players"] += r["p"] or 0
    out = []
    for p in pages.values():
        p["avg_secs"] = round(p["secs"] / p["timed"]) if p["timed"] else None
        p["article"] = p["page"].startswith(("/post/", "/guides/"))
        del p["secs"], p["timed"]
        out.append(p)
    out.sort(key=lambda x: (-x["views"], x["title"]))
    daily = db.q("SELECT day, SUM(views) v FROM reading WHERE day >= ? GROUP BY day ORDER BY day", (since,))
    return {"days": days, "pages": out, "daily": [{"day": r["day"], "views": r["v"]} for r in daily],
            "read_secs": READ_SECS}
