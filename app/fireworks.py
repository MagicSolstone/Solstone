"""Custom fireworks made in the Firework editor.

Designs are plain numbers, colours and an optional pixel picture. Everything is
clamped here so a design can never make the sky engine do something silly (huge
spark counts, endless lifetimes), whoever sent it.
"""
from __future__ import annotations

import re
import secrets
import threading
import time

from . import settings_store

PATTERNS = ("ball", "ring", "star", "burst", "spiral", "palm", "picture")
COLOR_MODES = ("mix", "alternate", "change", "rainbow")

# name: (min, max, default)
NUMBERS: dict[str, tuple[float, float, float]] = {
    "sparks": (8, 160, 48),          # how many pieces (not used by pictures)
    "size": (0.3, 3.0, 1.2),         # how far it spreads
    "spread": (0, 1, 0.15),          # randomness in how far each piece flies
    "squash": (0.3, 1.5, 1.0),       # flatten or stretch vertically
    "tilt": (0, 1, 0.3),             # random rotation for stars and pictures
    "points": (3, 10, 5),            # star points
    "arms": (2, 6, 3),               # spiral arms
    "spin": (-1, 1, 0.5),            # spiral spin direction and speed
    "gravity": (0, 2, 1.0),
    "drag": (0, 1, 0.4),             # air resistance
    "life": (0.4, 6, 1.4),           # seconds before pieces fade out
    "height": (0.1, 1, 0.6),         # how high the rocket goes
    "rockets": (1, 5, 1),            # launched together
    "hold": (0, 3, 0.8),             # pictures: seconds they hang in shape
    "sparkle": (0, 1, 0),            # crackle
    "trail": (0, 1, 0),              # sparks leave short trails
    "glitter": (0, 1, 0),            # hanging glitter, like a willow
    "flash": (0, 1, 0.4),            # white flash at the burst
    "blink": (0, 1, 0),              # all pieces blink together
    "strobe": (0, 1, 0),             # white strobe flicker
    "breathe": (0, 1, 0),            # slow pulse
    "second": (0, 1, 0),             # share of pieces that burst again
    "second_delay": (0.2, 1.5, 0.5),
    "second_size": (0.2, 1.5, 0.6),
}
INTS = {"sparks", "points", "arms", "rockets"}
PIC_MAX = 25
MAX_DESIGNS = 200
MAX_PER_USER = 40
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_PIC_ROW = re.compile(r"^[.0-3]*$")
_lock = threading.Lock()  # read-modify-write of the design list


def sanitize(d: dict) -> dict:
    out: dict = {}
    name = re.sub(r"\s+", " ", str(d.get("name") or "")).strip()[:40]
    out["name"] = name or "My firework"
    out["pattern"] = d.get("pattern") if d.get("pattern") in PATTERNS else "ball"
    out["color_mode"] = d.get("color_mode") if d.get("color_mode") in COLOR_MODES else "mix"
    colors = [c.lower() for c in (d.get("colors") or []) if isinstance(c, str) and _HEX.match(c)][:4]
    out["colors"] = colors or ["#ffe45c"]
    for k, (lo, hi, default) in NUMBERS.items():
        try:
            v = float(d.get(k, default))
        except (TypeError, ValueError):
            v = default
        if v != v:  # NaN
            v = default
        v = min(hi, max(lo, v))
        out[k] = int(round(v)) if k in INTS else round(v, 3)
    pic = d.get("picture") if isinstance(d.get("picture"), list) else []
    rows = [str(r)[:PIC_MAX] for r in pic[:PIC_MAX] if isinstance(r, str) and _PIC_ROW.match(str(r)[:PIC_MAX])]
    if rows:
        width = max(len(r) for r in rows)
        rows = [r.ljust(width, ".") for r in rows]
    out["picture"] = rows
    if out["pattern"] == "picture" and not any(c != "." for r in rows for c in r):
        out["pattern"] = "ball"            # an empty picture would launch nothing
    return out


def _load() -> list[dict]:
    items = settings_store.load().get("custom_fireworks")
    return items if isinstance(items, list) else []


def _save(items: list[dict]) -> None:
    settings_store.save_section("custom_fireworks", items)


def all_designs() -> list[dict]:
    return _load()


def in_show() -> list[dict]:
    return [{"id": d["id"], **sanitize(d)} for d in _load() if d.get("in_show")]


def create(design: dict, author: str) -> dict:
    with _lock:
        items = _load()
        if len(items) >= MAX_DESIGNS:
            raise ValueError(f"There are already {MAX_DESIGNS} custom fireworks. Delete some first.")
        if sum(1 for d in items if d.get("author") == author) >= MAX_PER_USER:
            raise ValueError(f"You can keep up to {MAX_PER_USER} fireworks. Delete one to make room.")
        d = {"id": secrets.token_hex(6), **sanitize(design), "author": author,
             "in_show": bool(design.get("in_show", True)), "created": time.time(), "updated": time.time()}
        items.append(d)
        _save(items)
        return d


def get(fid: str) -> dict | None:
    return next((d for d in _load() if d.get("id") == fid), None)


def update(fid: str, design: dict) -> dict | None:
    with _lock:
        items = _load()
        for i, d in enumerate(items):
            if d.get("id") == fid:
                merged = {**d, **sanitize({**d, **design}), "updated": time.time()}
                if "in_show" in design:
                    merged["in_show"] = bool(design["in_show"])
                items[i] = merged
                _save(items)
                return merged
        return None


def delete(fid: str) -> bool:
    with _lock:
        items = _load()
        left = [d for d in items if d.get("id") != fid]
        if len(left) == len(items):
            return False
        _save(left)
        return True
