"""Solstone's own backups: its database (accounts, posts, history), its settings and the website's pictures,
as one zip a day in a folder of their own, for an off-site backup tool to pick up.

The database is copied with SQLite's own backup, so a copy taken while Solstone is busy is still whole (copying
the file itself can catch it halfway through a write). Map pictures, skins and game assets aren't included:
Solstone fetches or draws them again by itself.

To restore: stop Solstone, unzip a backup into its data folder (replacing solstone.db, settings.json and site/),
and start it again.
"""
from __future__ import annotations

import logging
import os
import sqlite3
import tempfile
import time
import zipfile
from datetime import datetime
from pathlib import Path

from . import db
from .config import config

log = logging.getLogger("solstone.selfbackup")

KEEP = max(1, int(os.getenv("SOLSTONE_BACKUP_KEEP", "14")))
EVERY_HOURS = float(os.getenv("SOLSTONE_BACKUP_HOURS", "24"))
PREFIX = "solstone-backup-"


def folder() -> Path:
    return Path(os.getenv("SOLSTONE_BACKUP_DIR") or config.data_dir / "backups")


def backups() -> list[dict]:
    """Newest first: name, size, when."""
    d = folder()
    if not d.is_dir():
        return []
    out = [{"name": p.name, "size": p.stat().st_size, "ts": p.stat().st_mtime} for p in d.glob(f"{PREFIX}*.zip")]
    return sorted(out, key=lambda b: -b["ts"])


def path_of(name: str) -> Path | None:
    p = folder() / name
    return p if name.startswith(PREFIX) and name.endswith(".zip") and "/" not in name and p.is_file() else None


def _copy_db(dest: Path) -> None:
    with db._lock:
        src = db.conn()
        out = sqlite3.connect(dest)
        try:
            src.backup(out)
        finally:
            out.close()


def make() -> dict:
    """One backup now. Old ones beyond KEEP are removed."""
    d = folder()
    d.mkdir(parents=True, exist_ok=True)
    name = f"{PREFIX}{datetime.now().strftime('%Y-%m-%d-%H%M%S')}.zip"
    tmp_zip = d / (name + ".part")
    with tempfile.TemporaryDirectory() as td:
        copy = Path(td) / "solstone.db"
        _copy_db(copy)
        with zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(copy, "solstone.db")
            settings = config.data_dir / "settings.json"
            if settings.is_file():
                z.write(settings, "settings.json")
            site = config.data_dir / "site"
            if site.is_dir():
                for f in sorted(site.rglob("*")):
                    if f.is_file():
                        z.write(f, f"site/{f.relative_to(site).as_posix()}")
    tmp_zip.replace(d / name)
    for old in backups()[KEEP:]:
        (d / old["name"]).unlink(missing_ok=True)
    log.info("Solstone backup made: %s", name)
    return next(b for b in backups() if b["name"] == name)


def due() -> bool:
    b = backups()
    return not b or time.time() - b[0]["ts"] > EVERY_HOURS * 3600 - 60
