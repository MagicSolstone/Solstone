"""Tiny JSON settings store for per-server overrides (map URL, RCON host...)."""
from __future__ import annotations

import json
import threading

from .config import config

_PATH = config.data_dir / "settings.json"
_lock = threading.Lock()
ALLOWED = {"display_name", "map_url", "rcon_host", "rcon_port", "rcon_password", "hidden", "private", "bedtime",
           "join_address", "join_bedrock_address", "join_check", "join_bedrock_port", "join_note", "join_mods", "join_color", "join_xbox",
           "welcome", "welcome_when", "map_proxy",   # how to join this server, on the home page
           "new"}                                    # found by itself and hidden until an admin shows it (Manage → Server setup)


def load() -> dict:
    try:
        return json.loads(_PATH.read_text())
    except Exception:
        return {"servers": {}}


def server(sid: str) -> dict:
    return load().get("servers", {}).get(sid, {})


def _write(data: dict) -> None:
    tmp = _PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(_PATH)


def save_section(name: str, value: dict) -> None:
    with _lock:
        data = load()
        data[name] = value
        _write(data)


SEEN = "servers_seen"                            # every server id Solstone has found (a new one starts hidden)


def mark_seen(sid: str) -> None:
    """A server an admin added themselves: it's known (never "new", never hidden for being new)."""
    with _lock:
        data = load()
        data[SEEN] = sorted(set(data.get(SEEN) or []) | {sid})
        _write(data)


def note_found(ids: list[str]) -> list[str]:
    """Servers found on this look: any never seen before is hidden (and marked new) until an admin chooses to show it.
    The first time this runs (an older Solstone's settings), everything already there counts as seen. Returns the new ones."""
    with _lock:
        data = load()
        seen = data.get(SEEN)
        if seen is None:
            data[SEEN] = sorted(set(ids))
            _write(data)
            return []
        new = [i for i in ids if i not in seen]
        if not new:
            return []
        for i in new:
            cur = data.setdefault("servers", {}).setdefault(i, {})
            cur["hidden"], cur["new"] = True, True
        data[SEEN] = sorted(set(seen) | set(new))
        _write(data)
        return new


def update_server(sid: str, values: dict) -> dict:
    with _lock:
        data = load()
        cur = data.setdefault("servers", {}).setdefault(sid, {})
        for k, v in values.items():
            if k not in ALLOWED:
                continue
            if v in (None, ""):
                cur.pop(k, None)
            else:
                cur[k] = v
        _write(data)
        return cur
