"""Music: the main library (files an admin uploads) and an optional external library (a
folder such as Jellyfin's music, mounted read-only), playlists, and the "radio": the music
that plays by default, which can follow a schedule (a Christmas playlist in December).

Admins can block songs, albums or artists so they can't be listed or played anywhere, or
switch the external library to "only what I approve".
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import secrets
import threading
import time
from datetime import date, datetime
from pathlib import Path

from . import settings_store
from .config import config

log = logging.getLogger("solstone.music")

MAX_BYTES = 60 * 1024 * 1024
MAX_TRACKS = 300
MAX_PLAYLISTS = 200
MAX_PLAYLIST_TRACKS = 1000
TYPES = {"audio/mpeg": "mp3", "audio/mp3": "mp3", "audio/ogg": "ogg", "audio/opus": "opus", "audio/webm": "webm",
         "audio/wav": "wav", "audio/x-wav": "wav", "audio/wave": "wav", "audio/flac": "flac", "audio/x-flac": "flac",
         "audio/mp4": "m4a", "audio/x-m4a": "m4a", "audio/aac": "aac"}
MEDIA = {v: k for k, v in reversed(list(TYPES.items()))}
AUDIO_EXT = set(MEDIA)
COVER_NAMES = ("cover", "folder", "front", "album", "albumart")
_lock = threading.RLock()
DIR = config.data_dir / "music"
INDEX = config.data_dir / "music-index.json"


# ------------------------------------------------------------------ reading tags
def _tags(path: Path) -> dict:
    """Title, artist, album, track number and length, from the file's tags when it has them."""
    out: dict = {}
    try:
        import mutagen
        f = mutagen.File(path, easy=True)
        if f is not None:
            t = f.tags or {}
            first = lambda k: (t.get(k) or [""])[0] if hasattr(t, "get") else ""  # noqa: E731
            out = {"title": first("title"), "artist": first("artist"), "album": first("album"),
                   "albumartist": first("albumartist"), "year": str(first("date"))[:4]}
            for k, key in (("tracknumber", "track"), ("discnumber", "disc")):
                m = re.match(r"\d+", str(first(k)))
                out[key] = int(m.group()) if m else 0
            if getattr(f, "info", None) and getattr(f.info, "length", None):
                out["duration"] = round(float(f.info.length), 1)
    except Exception as e:                      # a broken file still plays, just without tags
        log.debug("no tags for %s: %s", path, e)
    return {k: (re.sub(r"\s+", " ", v).strip()[:120] if isinstance(v, str) else v) for k, v in out.items()}


def embedded_art(path: Path) -> tuple[bytes, str] | None:
    try:
        import mutagen
        f = mutagen.File(path)
        if f is None:
            return None
        pics = getattr(f, "pictures", None)          # FLAC
        if pics:
            return pics[0].data, pics[0].mime or "image/jpeg"
        tags = f.tags
        if tags is None:
            return None
        if hasattr(tags, "getall"):                  # ID3 (MP3)
            apic = tags.getall("APIC")
            if apic:
                return apic[0].data, apic[0].mime or "image/jpeg"
        covr = tags.get("covr") if hasattr(tags, "get") else None   # MP4
        if covr:
            return bytes(covr[0]), "image/png" if getattr(covr[0], "imageformat", 13) == 14 else "image/jpeg"
        for key in ("metadata_block_picture",):      # Ogg / Opus
            vals = tags.get(key) if hasattr(tags, "get") else None
            if vals:
                import base64

                from mutagen.flac import Picture
                p = Picture(base64.b64decode(vals[0]))
                return p.data, p.mime or "image/jpeg"
    except Exception:
        return None
    return None


def _folder_cover(folder: Path) -> Path | None:
    try:
        for f in folder.iterdir():
            if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp") and f.stem.lower() in COVER_NAMES:
                return f
    except OSError:
        return None
    return None


# ------------------------------------------------------------------ main library (uploads)
def _main_cfg() -> dict:
    c = settings_store.load().get("music")
    c = c if isinstance(c, dict) else {}
    tracks = [t for t in c.get("tracks", []) if isinstance(t, dict) and (DIR / str(t.get("file", ""))).is_file()]
    return {**c, "tracks": tracks, "public": bool(c.get("public", False))}


def _main_track(t: dict) -> dict:
    return {"id": t["id"], "title": t["title"], "artist": t.get("artist", ""), "album": t.get("album", ""),
            "albumartist": t.get("albumartist", ""), "track": t.get("track", 0), "disc": t.get("disc", 0), "year": t.get("year", ""),
            "duration": t.get("duration", 0), "ext": t["ext"], "size": t.get("size", 0), "source": "main", "art": True}


def public() -> bool:
    return _main_cfg()["public"]


def ext_for(content_type: str, filename: str) -> str | None:
    ext = TYPES.get((content_type or "").split(";")[0].strip().lower())
    if not ext:
        m = re.search(r"\.([A-Za-z0-9]{2,5})$", filename or "")
        ext = m.group(1).lower() if m and m.group(1).lower() in MEDIA else None
    return ext


def add(tmp: Path, ext: str, title: str, size: int) -> dict:
    with _lock:
        c = _main_cfg()
        if len(c["tracks"]) >= MAX_TRACKS:
            tmp.unlink(missing_ok=True)
            raise ValueError(f"The main library is full ({MAX_TRACKS} tracks).")
        tid = secrets.token_hex(6)
        dest = DIR / f"{tid}.{ext}"
        tmp.replace(dest)
        tags = _tags(dest)
        t = {"id": tid, "title": re.sub(r"\s+", " ", tags.get("title") or title).strip()[:80] or "Untitled", "file": dest.name,
             "ext": ext, "size": size, **{k: tags.get(k) for k in ("artist", "album", "albumartist", "track", "disc", "year", "duration") if tags.get(k)}}
        c["tracks"].append(t)
        settings_store.save_section("music", c)
        return _main_track(t)


def update(order: list | None = None, titles: dict | None = None, public_flag: bool | None = None) -> dict:
    with _lock:
        c = _main_cfg()
        if order:
            pos = {tid: i for i, tid in enumerate(order)}
            c["tracks"].sort(key=lambda t: pos.get(t["id"], 10**6))
        for t in c["tracks"]:
            if titles and t["id"] in titles:
                t["title"] = str(titles[t["id"]]).strip()[:80] or t["title"]
        if public_flag is not None:
            c["public"] = bool(public_flag)
        settings_store.save_section("music", c)
        return {"tracks": main_tracks(), "public": c["public"]}


def delete(tid: str) -> bool:
    with _lock:
        c = _main_cfg()
        t = next((t for t in c["tracks"] if t["id"] == tid), None)
        if not t:
            return False
        (DIR / t["file"]).unlink(missing_ok=True)
        c["tracks"] = [x for x in c["tracks"] if x["id"] != tid]
        settings_store.save_section("music", c)
        return True


def main_tracks() -> list[dict]:
    return [_main_track(t) for t in _main_cfg()["tracks"]]


# ------------------------------------------------------------------ external library (read-only folder)
_index: dict = {"tracks": {}, "scanned": 0, "root": ""}
_scan = {"running": False, "done": 0, "error": ""}


def external_root() -> Path | None:
    root = config.music_library_dir.strip()
    return Path(root) if root and Path(root).is_dir() else None


def _load_index() -> None:
    global _index
    try:
        data = json.loads(INDEX.read_text())
        if isinstance(data, dict) and isinstance(data.get("tracks"), dict):
            _index = data
    except (OSError, ValueError):
        pass


def _xid(rel: str) -> str:
    return "x" + hashlib.sha1(rel.encode("utf-8", "surrogateescape")).hexdigest()[:14]


def scan() -> int:
    """Walk the external folder and (re)read tags for new or changed files."""
    root = external_root()
    if not root:
        return 0
    with _lock:
        if _scan["running"]:
            return 0
        _scan.update(running=True, done=0, error="")
    try:
        old = {v["path"]: v for v in _index.get("tracks", {}).values()} if _index.get("root") == str(root) else {}
        tracks: dict = {}
        covers: dict[str, str | None] = {}
        for dirpath, dirnames, files in os.walk(root, followlinks=False):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for name in files:
                ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
                if ext not in AUDIO_EXT or name.startswith("."):
                    continue
                full = Path(dirpath) / name
                try:
                    st = full.stat()
                except OSError:
                    continue
                rel = full.relative_to(root).as_posix()
                prev = old.get(rel)
                if prev and prev.get("mtime") == int(st.st_mtime) and prev.get("size") == st.st_size:
                    t = prev
                else:
                    tags = _tags(full)
                    parts = rel.split("/")
                    t = {"path": rel, "mtime": int(st.st_mtime), "size": st.st_size, "ext": ext,
                         "title": tags.get("title") or re.sub(r"^\d+[\s._-]+", "", name.rsplit(".", 1)[0]),
                         "artist": tags.get("artist") or (parts[-3] if len(parts) >= 3 else ""),
                         "album": tags.get("album") or (parts[-2] if len(parts) >= 2 else ""),
                         "albumartist": tags.get("albumartist", ""), "disc": tags.get("disc", 0),
                         "track": tags.get("track") or int((re.match(r"^(\d{1,3})(?!\d)", name) or [0, 0])[1]),
                         "year": tags.get("year", ""), "duration": tags.get("duration", 0)}
                folder = str(Path(rel).parent)
                if folder not in covers:
                    c = _folder_cover(full.parent)
                    covers[folder] = c.relative_to(root).as_posix() if c else None
                t["cover"] = covers[folder]
                tracks[_xid(rel)] = t
                _scan["done"] += 1
        data = {"root": str(root), "scanned": time.time(), "tracks": tracks}
        tmp = INDEX.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, separators=(",", ":")))
        tmp.replace(INDEX)
        with _lock:
            _index.clear(); _index.update(data)
        log.info("Music library: %d tracks in %s", len(tracks), root)
        return len(tracks)
    except Exception as e:
        _scan["error"] = str(e)
        log.exception("music library scan failed")
        return 0
    finally:
        _scan["running"] = False


def _ext_track(tid: str, t: dict) -> dict:
    return {"id": tid, "title": t["title"], "artist": t.get("artist", ""), "album": t.get("album", ""), "albumartist": t.get("albumartist", ""),
            "track": t.get("track", 0), "disc": t.get("disc", 0), "year": t.get("year", ""), "duration": t.get("duration", 0),
            "ext": t["ext"], "size": t.get("size", 0), "source": "external", "art": True}


def external_status() -> dict:
    root = config.music_library_dir.strip()
    return {"configured": bool(root), "found": external_root() is not None, "root": root, "count": len(_index.get("tracks", {})),
            "scanned": _index.get("scanned") or None, "scanning": _scan["running"], "progress": _scan["done"], "error": _scan["error"]}


# ------------------------------------------------------------------ everything, with the rules applied
def _key(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def album_key(t: dict) -> str:
    return f"{_key(t.get('albumartist') or t.get('artist'))}|{_key(t.get('album'))}"


def rules() -> dict:
    r = settings_store.load().get("music_rules")
    r = r if isinstance(r, dict) else {}
    lists = lambda d: {k: sorted({str(x) for x in (d or {}).get(k, []) if x})[:5000] for k in ("tracks", "albums", "artists")}  # noqa: E731
    return {"mode": r.get("mode") if r.get("mode") in ("all", "approved") else "all",
            "blocked": lists(r.get("blocked")), "approved": lists(r.get("approved"))}


def set_rule(action: str, kind: str, value: str, on: bool) -> dict:
    if action not in ("blocked", "approved") or kind not in ("tracks", "albums", "artists"):
        raise ValueError("Unknown rule")
    value = value if kind == "tracks" else (value if kind == "albums" else _key(value))
    with _lock:
        r = rules()
        cur = set(r[action][kind])
        (cur.add if on else cur.discard)(value)
        r[action][kind] = sorted(cur)
        settings_store.save_section("music_rules", r)
        return r


def set_mode(mode: str) -> dict:
    with _lock:
        r = rules()
        r["mode"] = mode if mode in ("all", "approved") else "all"
        settings_store.save_section("music_rules", r)
        return r


def _status_of(t: dict, r: dict) -> str:
    """'ok', 'blocked' or 'unapproved' (external music in approve-only mode)."""
    b = r["blocked"]
    if t["id"] in b["tracks"] or album_key(t) in b["albums"] or _key(t.get("artist")) in b["artists"] or _key(t.get("albumartist")) in b["artists"]:
        return "blocked"
    if t["source"] == "external" and r["mode"] == "approved":
        a = r["approved"]
        if not (t["id"] in a["tracks"] or album_key(t) in a["albums"] or _key(t.get("artist")) in a["artists"] or _key(t.get("albumartist")) in a["artists"]):
            return "unapproved"
    return "ok"


def all_tracks(include_hidden: bool = False) -> list[dict]:
    r = rules()
    out = []
    for t in main_tracks() + [_ext_track(k, v) for k, v in list(_index.get("tracks", {}).items())]:
        st = _status_of(t, r)
        if st == "ok" or include_hidden:
            out.append({**t, "status": st} if include_hidden else t)
    return out


def by_id(ids: list[str], include_hidden: bool = False) -> list[dict]:
    want = set(ids)
    found = {t["id"]: t for t in all_tracks(include_hidden) if t["id"] in want}
    return [found[i] for i in ids if i in found]


def get(tid: str, include_hidden: bool = False) -> dict | None:
    r = by_id([tid], include_hidden)
    return r[0] if r else None


def _sort_key(t: dict):
    return (_key(t.get("albumartist") or t.get("artist")), _key(t.get("album")), t.get("disc") or 0, t.get("track") or 0, _key(t["title"]))


def search(q: str = "", artist: str = "", album: str = "", source: str = "", include_hidden: bool = False,
           status: str = "", offset: int = 0, limit: int = 100) -> dict:
    words = [w for w in _key(q).split(" ") if w]
    rows = []
    for t in all_tracks(include_hidden):
        if source and t["source"] != source:
            continue
        if artist and _key(artist) not in (_key(t.get("artist")), _key(t.get("albumartist"))):
            continue
        if album and album_key(t) != album:
            continue
        if status and t.get("status", "ok") != status:
            continue
        if words:
            hay = _key(" ".join(str(t.get(k) or "") for k in ("title", "artist", "album", "albumartist")))
            if not all(w in hay for w in words):
                continue
        rows.append(t)
    rows.sort(key=_sort_key)
    return {"total": len(rows), "tracks": rows[offset: offset + max(1, min(500, limit))]}


def albums(q: str = "", include_hidden: bool = False) -> list[dict]:
    words = [w for w in _key(q).split(" ") if w]
    groups: dict[str, dict] = {}
    for t in all_tracks(include_hidden):
        k = album_key(t)
        g = groups.setdefault(k, {"key": k, "album": t.get("album") or "Singles", "artist": t.get("albumartist") or t.get("artist") or "",
                                  "year": t.get("year", ""), "count": 0, "duration": 0, "art": t["id"], "source": t["source"], "statuses": set()})
        g["count"] += 1
        g["duration"] += t.get("duration") or 0
        if include_hidden:
            g["statuses"].add(t.get("status", "ok"))
    out = []
    for g in groups.values():
        if words and not all(w in _key(f"{g['album']} {g['artist']}") for w in words):
            continue
        st = g.pop("statuses")
        if include_hidden:
            g["status"] = "ok" if "ok" in st else ("blocked" if "blocked" in st else "unapproved")
        out.append(g)
    out.sort(key=lambda g: (_key(g["artist"]), g.get("year") or "", _key(g["album"])))
    return out


def artists(q: str = "", include_hidden: bool = False) -> list[dict]:
    words = [w for w in _key(q).split(" ") if w]
    groups: dict[str, dict] = {}
    for t in all_tracks(include_hidden):
        name = t.get("albumartist") or t.get("artist") or "Unknown artist"
        g = groups.setdefault(_key(name), {"name": name, "count": 0, "albums": set(), "art": t["id"], "statuses": set()})
        g["count"] += 1
        g["albums"].add(album_key(t))
        g["statuses"].add(t.get("status", "ok"))
    out = []
    for g in groups.values():
        if words and not all(w in _key(g["name"]) for w in words):
            continue
        st = g.pop("statuses")
        row = {**g, "albums": len(g["albums"])}
        if include_hidden:
            row["status"] = "ok" if "ok" in st else ("blocked" if "blocked" in st else "unapproved")
        out.append(row)
    out.sort(key=lambda g: _key(g["name"]))
    return out


def file_of(t: dict) -> tuple[Path, str] | None:
    if t["source"] == "main":
        raw = next((x for x in _main_cfg()["tracks"] if x["id"] == t["id"]), None)
        return (DIR / raw["file"], MEDIA.get(raw["ext"], "application/octet-stream")) if raw else None
    root = external_root()
    raw = _index.get("tracks", {}).get(t["id"])
    if not root or not raw:
        return None
    p = (root / raw["path"]).resolve()
    if root.resolve() not in p.parents or not p.is_file():
        return None
    return p, MEDIA.get(raw["ext"], "application/octet-stream")


def art_of(t: dict) -> tuple[bytes, str] | Path | None:
    f = file_of(t)
    if not f:
        return None
    if t["source"] == "external":
        raw = _index.get("tracks", {}).get(t["id"]) or {}
        root = external_root()
        if raw.get("cover") and root:
            p = (root / raw["cover"]).resolve()
            if root.resolve() in p.parents and p.is_file():
                return p
    return embedded_art(f[0])


# ------------------------------------------------------------------ playlists and the radio
def _clean_mmdd(v) -> str:
    m = re.match(r"^(\d{1,2})-(\d{1,2})$", str(v or ""))
    if not m:
        return ""
    mo, d = int(m.group(1)), int(m.group(2))
    try:
        date(2024, mo, d)
    except ValueError:
        return ""
    return f"{mo:02d}-{d:02d}"


def _clean_playlist(p: dict) -> dict | None:
    if not isinstance(p, dict):
        return None
    sched = p.get("schedule") if isinstance(p.get("schedule"), dict) else {}
    frm, to = _clean_mmdd(sched.get("from")), _clean_mmdd(sched.get("to"))
    return {"id": re.sub(r"[^a-z0-9]", "", str(p.get("id") or "").lower())[:16] or secrets.token_hex(5),
            "name": re.sub(r"\s+", " ", str(p.get("name") or "")).strip()[:60] or "My playlist",
            "owner": str(p.get("owner") or "")[:32], "shared": bool(p.get("shared")),
            "tracks": [str(x)[:20] for x in (p.get("tracks") or []) if isinstance(x, str)][:MAX_PLAYLIST_TRACKS],
            "schedule": {"on": bool(sched.get("on")) and bool(frm and to), "from": frm, "to": to},
            "created": p.get("created") or time.time()}


def playlists() -> list[dict]:
    raw = settings_store.load().get("playlists")
    return [p for p in (_clean_playlist(x) for x in (raw if isinstance(raw, list) else [])) if p]


def _save_playlists(items: list[dict]) -> None:
    settings_store.save_section("playlists", items)


def playlist(pid: str) -> dict | None:
    return next((p for p in playlists() if p["id"] == pid), None)


def can_see(p: dict, user) -> bool:
    return user is not None and (p["shared"] or p["owner"] == user.username or user.role == "admin" or p["schedule"]["on"])


def can_edit(p: dict, user) -> bool:
    return user is not None and (p["owner"] == user.username or user.role == "admin")


def create_playlist(body: dict, owner: str) -> dict:
    with _lock:
        items = playlists()
        if len(items) >= MAX_PLAYLISTS:
            raise ValueError("There are too many playlists; delete some first")
        if sum(1 for p in items if p["owner"] == owner) >= 50:
            raise ValueError("You can have up to 50 playlists")
        p = _clean_playlist({**body, "id": "", "owner": owner, "created": time.time()})
        if not body.get("_admin"):
            p["schedule"] = {"on": False, "from": "", "to": ""}
        items.append(p)
        _save_playlists(items)
        return p


def update_playlist(pid: str, body: dict, admin: bool) -> dict | None:
    with _lock:
        items = playlists()
        p = next((x for x in items if x["id"] == pid), None)
        if not p:
            return None
        tracks = list(p["tracks"])
        if isinstance(body.get("tracks"), list):
            tracks = [str(x) for x in body["tracks"]]
        for tid in body.get("add") or []:
            if str(tid) not in tracks:
                tracks.append(str(tid))
        drop = {str(x) for x in body.get("remove") or []}
        tracks = [t for t in tracks if t not in drop]
        merged = {**p, **{k: body[k] for k in ("name", "shared") if k in body}, "tracks": tracks}
        if admin and isinstance(body.get("schedule"), dict):
            merged["schedule"] = body["schedule"]
        new = _clean_playlist(merged)
        items[items.index(p)] = new
        _save_playlists(items)
        return new


def delete_playlist(pid: str) -> bool:
    with _lock:
        items = playlists()
        keep = [p for p in items if p["id"] != pid]
        if len(keep) == len(items):
            return False
        _save_playlists(keep)
        if radio_settings()["default"] == pid:
            set_radio_default("")
        return True


def radio_settings() -> dict:
    c = _main_cfg()
    return {"default": str(c.get("radio_default") or "")}


def set_radio_default(pid: str) -> None:
    with _lock:
        c = _main_cfg()
        c["radio_default"] = pid
        settings_store.save_section("music", c)


def _in_range(today: date, frm: str, to: str) -> tuple[bool, int]:
    """Is today between two MM-DD dates (wrapping over New Year)? Also how long the range is."""
    md = today.strftime("%m-%d")
    f, t = frm, to
    length = (date(2024, int(t[:2]), int(t[3:])) - date(2024, int(f[:2]), int(f[3:]))).days % 366
    return (f <= md <= t) if f <= t else (md >= f or md <= t), length


def radio(now: datetime | None = None) -> dict:
    """What plays when nobody has picked anything: a scheduled playlist whose dates include
    today (the shortest range wins), else the chosen default playlist, else the main library."""
    from . import db
    today = (now or datetime.now(db.tz())).date()
    best = None
    for p in playlists():
        s = p["schedule"]
        if s["on"]:
            hit, length = _in_range(today, s["from"], s["to"])
            if hit and (best is None or length < best[1]):
                best = (p, length)
    if best:
        p = best[0]
        tracks = by_id(p["tracks"])
        if tracks:
            return {"id": p["id"], "name": p["name"], "why": f"{_fmt_md(p['schedule']['from'])} to {_fmt_md(p['schedule']['to'])}", "tracks": tracks}
    d = radio_settings()["default"]
    p = playlist(d) if d else None
    if p:
        tracks = by_id(p["tracks"])
        if tracks:
            return {"id": p["id"], "name": p["name"], "why": "Default", "tracks": tracks}
    return {"id": "", "name": "Solstone radio", "why": "The main library", "tracks": [t for t in all_tracks() if t["source"] == "main"]}


def _fmt_md(md: str) -> str:
    return date(2024, int(md[:2]), int(md[3:])).strftime("%d %b").lstrip("0")


_load_index()
