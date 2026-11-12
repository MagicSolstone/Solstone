"""Removing a server from Solstone (Manage → Solstone → Server setup → a server's 🗑 Remove).

For a server Solstone doesn't look after any more: the old one at home after moving to a game host, say. Its settings,
map pictures, and (for a server elsewhere) the copy of its files go, and, if asked, its history too (after a full backup
of Solstone, so it can be undone). The game server itself is never touched. A server found in the servers folder or
listed by Crafty would be found again: it's remembered as removed, so it isn't, until it's brought back.
"""
from __future__ import annotations

import logging
import shutil
import time

from . import db, settings_store
from .config import config

log = logging.getLogger("solstone.serverremove")

REMOVED = "servers_removed"                  # {sid: {"name", "at"}}: not looked after, even if it's still found


def removed() -> dict[str, dict]:
    return dict(settings_store.load().get(REMOVED) or {})


def _bytes(path) -> int:
    try:
        return sum(p.stat().st_size for p in path.rglob("*") if p.is_file()) if path.is_dir() else 0
    except OSError:
        return 0


def plan(srv) -> dict:
    """What removing it would clear: its history (rows of each kind), its map pictures and its copied files."""
    from . import movehistory, remote, worldmap
    counts = movehistory.counts(srv.id)
    tiles = config.data_dir / "maptiles" / f"v{worldmap.RENDER_VERSION}" / srv.id
    return {"id": srv.id, "name": srv.display_name, "remote": bool(srv.remote), "history": counts,
            "history_rows": sum(c["rows"] for c in counts), "map_bytes": _bytes(tiles),
            "copy_bytes": _bytes(remote.mirror_dir(srv.id)) if srv.remote else 0,
            "folder": "" if srv.remote else str(srv.dir)}


def _forget_settings(sid: str) -> list[str]:
    """Every setting kept for this server (its own settings, notifications, mod updates, the boards' adjustments…)."""
    gone = []
    with settings_store._lock:
        data = settings_store.load()
        for name, section in list(data.items()):
            if name in (REMOVED, settings_store.SEEN) or not isinstance(section, dict):
                continue
            if sid in section and isinstance(section[sid], (dict, list)):
                section.pop(sid)
                gone.append(name)
        if isinstance((data.get("notify") or {}).get("servers"), dict) and sid in data["notify"]["servers"]:
            data["notify"]["servers"].pop(sid)
            gone.append("notify.servers")
        settings_store._write(data)
    return gone


def remove(srv, history: bool) -> dict:
    """Remove it from Solstone. history: its recorded history goes too (a backup of Solstone is made first)."""
    from . import movehistory, remote, selfbackup, worldmap
    sid, name = srv.id, srv.display_name
    backup = None
    if history:
        backup = selfbackup.make().get("name")
        movehistory._ensure()
        with db._lock:
            c = db.conn()
            for table, _label in movehistory.TABLES:
                c.execute(f"DELETE FROM {table} WHERE server_id=?", (sid,))
            c.execute("DELETE FROM log_state WHERE server_id=?", (sid,))
            c.commit()
    if srv.remote:                              # (its mirror was stopped by the caller, on the event loop)
        remote.forget(sid)
        shutil.rmtree(remote.mirror_dir(sid), ignore_errors=True)
    tiles = worldmap.clear_tiles(sid)
    gone = _forget_settings(sid)
    if not srv.remote:                          # (still in the folder, or Crafty: not found again)
        data = removed()
        data[sid] = {"name": name, "at": time.time()}
        settings_store.save_section(REMOVED, data)
    log.info("server %s (%s) removed from Solstone: settings %s, %s map pictures, history %s", sid, name, gone, tiles,
             "removed" if history else "kept")
    return {"ok": True, "settings": gone, "map_pictures": tiles, "history": bool(history), "backup": backup}


def bring_back(sid: str) -> bool:
    data = removed()
    if sid not in data:
        return False
    data.pop(sid)
    settings_store.save_section(REMOVED, data)
    return True
