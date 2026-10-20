"""Backup status from Crafty's backups folder (mounted read-only at BACKUPS_DIR).

Crafty writes each server's backups under backups/<server-uuid>/ (4.4+ adds a
sub-folder per backup schedule). We only look at file names, sizes and
modification times -- never the contents.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from . import servers as S

BACKUPS_DIR = Path(os.getenv("BACKUPS_DIR", "/backups"))
STALE_HOURS = float(os.getenv("BACKUP_STALE_HOURS", "48"))
SUFFIXES = (".zip", ".tar", ".tar.gz", ".tgz", ".tar.zst", ".7z")
_cache: dict[str, tuple[float, dict]] = {}


def _candidate_dirs(srv: S.Server) -> list[Path]:
    dirs = [BACKUPS_DIR / srv.id]
    crafty_path = (srv.crafty or {}).get("backup_path")
    if crafty_path:
        p = Path(crafty_path)
        dirs += [BACKUPS_DIR / p.name, p]
    seen, out = set(), []
    for d in dirs:
        if d not in seen:
            seen.add(d)
            out.append(d)
    return out


def status(srv: S.Server) -> dict:
    hit = _cache.get(srv.id)
    if hit and time.monotonic() - hit[0] < 60:
        return hit[1]
    files = []
    found_dir = None
    for d in _candidate_dirs(srv):
        try:
            if not d.is_dir():
                continue
        except OSError:
            continue
        found_dir = found_dir or d
        for f in d.rglob("*"):
            try:
                if f.is_file() and f.name.lower().endswith(SUFFIXES):
                    st = f.stat()
                    files.append((st.st_mtime, st.st_size, f.name))
            except OSError:
                continue
    files.sort(reverse=True)
    if not BACKUPS_DIR.is_dir():
        result = {"configured": False, "hint": f"Mount Crafty's backups folder at {BACKUPS_DIR} to see backup status."}
    elif not files:
        result = {"configured": True, "found": False, "folder": str(found_dir) if found_dir else None,
                  "stale_hours": STALE_HOURS}
    else:
        latest = files[0]
        age_h = (time.time() - latest[0]) / 3600
        result = {"configured": True, "found": True, "latest": {"ts": latest[0], "bytes": latest[1], "name": latest[2]},
                  "count": len(files), "total_bytes": sum(f[1] for f in files),
                  "age_hours": round(age_h, 1), "stale": age_h > STALE_HOURS, "stale_hours": STALE_HOURS}
    _cache[srv.id] = (time.monotonic(), result)
    return result
