"""Tiny JSON settings store for per-server overrides (map URL, RCON host...)."""
from __future__ import annotations

import json
import threading

from .config import config

_PATH = config.data_dir / "settings.json"
_lock = threading.Lock()
ALLOWED = {"display_name", "map_url", "rcon_host", "rcon_port", "rcon_password", "hidden", "bedtime"}


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
