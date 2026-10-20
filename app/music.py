"""Background music for the fireworks: audio files an admin uploads, played in order
(or shuffled) by the music player on Solstone's pages."""
from __future__ import annotations

import re
import secrets
import threading
from pathlib import Path

from . import settings_store
from .config import config

MAX_BYTES = 60 * 1024 * 1024
MAX_TRACKS = 100
TYPES = {"audio/mpeg": "mp3", "audio/mp3": "mp3", "audio/ogg": "ogg", "audio/opus": "opus", "audio/webm": "webm",
         "audio/wav": "wav", "audio/x-wav": "wav", "audio/wave": "wav", "audio/flac": "flac", "audio/x-flac": "flac",
         "audio/mp4": "m4a", "audio/x-m4a": "m4a", "audio/aac": "aac"}
MEDIA = {v: k for k, v in reversed(list(TYPES.items()))}
_lock = threading.Lock()
DIR = config.data_dir / "music"


def _cfg() -> dict:
    c = settings_store.load().get("music")
    c = c if isinstance(c, dict) else {}
    tracks = [t for t in c.get("tracks", []) if isinstance(t, dict) and (DIR / str(t.get("file", ""))).is_file()]
    return {"tracks": tracks, "public": bool(c.get("public", False))}


def tracks() -> list[dict]:
    return [{k: t[k] for k in ("id", "title", "size", "ext")} for t in _cfg()["tracks"]]


def public() -> bool:
    return _cfg()["public"]


def path_of(tid: str) -> tuple[Path, str] | None:
    t = next((t for t in _cfg()["tracks"] if t["id"] == tid), None)
    if not t:
        return None
    return DIR / t["file"], MEDIA.get(t["ext"], "application/octet-stream")


def ext_for(content_type: str, filename: str) -> str | None:
    ext = TYPES.get((content_type or "").split(";")[0].strip().lower())
    if not ext:
        m = re.search(r"\.([A-Za-z0-9]{2,5})$", filename or "")
        ext = m.group(1).lower() if m and m.group(1).lower() in MEDIA else None
    return ext


def add(tmp: Path, ext: str, title: str, size: int) -> dict:
    with _lock:
        c = _cfg()
        if len(c["tracks"]) >= MAX_TRACKS:
            tmp.unlink(missing_ok=True)
            raise ValueError(f"The playlist is full ({MAX_TRACKS} tracks).")
        tid = secrets.token_hex(6)
        dest = DIR / f"{tid}.{ext}"
        tmp.replace(dest)
        t = {"id": tid, "title": re.sub(r"\s+", " ", title).strip()[:80] or "Untitled", "file": dest.name, "ext": ext, "size": size}
        c["tracks"].append(t)
        settings_store.save_section("music", c)
        return {k: t[k] for k in ("id", "title", "size", "ext")}


def update(order: list | None = None, titles: dict | None = None, public_flag: bool | None = None) -> dict:
    with _lock:
        c = _cfg()
        if order:
            pos = {tid: i for i, tid in enumerate(order)}
            c["tracks"].sort(key=lambda t: pos.get(t["id"], 10**6))
        for t in c["tracks"]:
            if titles and t["id"] in titles:
                t["title"] = str(titles[t["id"]]).strip()[:80] or t["title"]
        if public_flag is not None:
            c["public"] = bool(public_flag)
        settings_store.save_section("music", c)
        return {"tracks": tracks(), "public": c["public"]}


def delete(tid: str) -> bool:
    with _lock:
        c = _cfg()
        t = next((t for t in c["tracks"] if t["id"] == tid), None)
        if not t:
            return False
        (DIR / t["file"]).unlink(missing_ok=True)
        c["tracks"] = [x for x in c["tracks"] if x["id"] != tid]
        settings_store.save_section("music", c)
        return True
