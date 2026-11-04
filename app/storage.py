"""How much room Solstone takes (Manage → Solstone → Servers & history): its data folder by part, the biggest
things in its database, how long each kind of history is kept, and the disk's free space.

What grows: the trail of where everyone walks (Adventures) is the biggest, a row every few seconds per player while
anyone plays, so it's cleared after POSITIONS_DAYS (saved adventures keep theirs). Server checks (CPU, TPS) and the
activity feed are cleared too. Play sessions, daily recaps and fish caught are small and kept for good.
"""
from __future__ import annotations

import os
import shutil
import threading
import time
from pathlib import Path

from . import adventures, db, selfbackup
from .config import config

# what's in each table, in words, and how long it's kept
TABLES = {
    "positions": ("Where everyone went (Adventures trails)", f"{adventures.POSITIONS_DAYS} days, saved adventures for good"),
    "events": ("The activity feed: joins, chat, deaths, what happened", "180 days"),
    "metrics": ("Server checks every 30 s: players, CPU, TPS", "30 days"),
    "sessions": ("Play sessions: who played when", "for good"),
    "recaps": ("Daily recaps", "for good"),
    "fish_catches": ("Fish caught", "for good"),
    "audit": ("The admin activity log", "for good"),
    "posts": ("Posts: news, guides and questions", "until deleted"),
    "users": ("Website accounts", "until deleted"),
    "signups": ("Who's coming to events", "for good"),
    "sessions_auth": ("Who's signed in to the website", "until they sign out"),
    "alerts": ("Notifications already sent (so none goes twice)", "for good"),
}


def _size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def report() -> dict:
    base = config.data_dir
    parts: dict[str, int] = {}
    for p in base.iterdir() if base.is_dir() else []:
        name = p.name
        if name.startswith("solstone.db"):
            name = "solstone.db"                      # the database and its journal files together
        parts[name] = parts.get(name, 0) + _size(p)
    backups = selfbackup.folder()
    if backups.is_dir() and base not in backups.parents and backups != base:
        parts["backups"] = parts.get("backups", 0) + _size(backups)
    tables = []
    try:
        sizes = {r["name"]: r["b"] for r in db.q("SELECT name, SUM(pgsize) AS b FROM dbstat GROUP BY name")}
    except Exception:                                 # a SQLite without dbstat: rows only
        sizes = {}
    names = [r["name"] for r in db.q("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    index_of = {r["name"]: r["tbl_name"] for r in db.q("SELECT name, tbl_name FROM sqlite_master WHERE type='index'")}
    for t in names:
        rows = db.q(f'SELECT COUNT(*) AS n FROM "{t}"')[0]["n"]
        idx = sum(v for k, v in sizes.items() if index_of.get(k) == t)
        what, kept = TABLES.get(t, ("", ""))
        tables.append({"name": t, "rows": rows, "bytes": (sizes.get(t) or 0) + idx, "what": what, "kept": kept})
    tables.sort(key=lambda x: (-x["bytes"], -x["rows"]))
    disk = shutil.disk_usage(base)
    return {"folder": str(base), "total": sum(parts.values()),
            "parts": sorted(({"name": k, "bytes": v} for k, v in parts.items()), key=lambda x: -x["bytes"]),
            "tables": tables[:12], "disk": {"free": disk.free, "total": disk.total}}


# Measuring counts every row and page of the database (seconds once it's big), and it hardly changes minute to minute:
# the last measurement is kept and shown straight away; past KEEP_SECS it's measured again in the background.
KEEP_SECS = 600
_kept: dict = {"at": 0.0, "report": None}
_measuring = threading.Lock()


def _measure() -> dict:
    with _measuring:
        r = {**report(), "measured": time.time()}
        _kept.update(at=time.monotonic(), report=r)
        return r


def cached_report() -> dict:
    """The storage report, measured at most every 10 minutes; only the first ever look waits for it."""
    r = _kept["report"]
    if r is None:
        return _measure()
    if time.monotonic() - _kept["at"] > KEEP_SECS and not _measuring.locked():
        threading.Thread(target=_measure, daemon=True).start()
    return r

