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

PATTERNS = ("ball", "ring", "star", "burst", "spiral", "palm", "saturn", "pop", "picture")
COLOR_MODES = ("mix", "alternate", "change", "rainbow")
LAUNCHES = ("rocket", "fountain", "wheel")           # from the sky, or set up on the hill
ROCKET_STYLES = ("normal", "sparkly", "corkscrew", "colored", "invisible")
STAGE_ACTIONS = ("burst", "pieces", "shatter", "implode")
LAUNCH_SOUNDS = ("whoosh", "whistle", "custom", "none")
BURST_SOUNDS = ("boom", "pop", "thud", "crack", "custom", "none")
GROUND_SOUNDS = ("hiss", "crackle", "custom", "none")      # fountains and wheels
# "Make your own" sounds, bfxr style: a wave, an envelope, pitch moves, filters and effects.
SFX_WAVES = ("square", "saw", "triangle", "sine", "noise")
SFX_NUMBERS = {
    "freq": (20, 5000, 440), "slide": (-1, 1, 0), "vib": (0, 1, 0), "vib_speed": (0, 30, 6), "jump": (-12, 12, 0), "jump_at": (0, 1, 0.5),
    "duty": (0.05, 0.5, 0.5), "attack": (0, 1, 0), "sustain": (0, 2, 0.1), "punch": (0, 1, 0), "decay": (0, 3, 0.5),
    "lp": (0, 1, 1), "lp_sweep": (-1, 1, 0), "res": (0, 1, 0), "hp": (0, 1, 0), "crunch": (0, 1, 0), "drive": (0, 1, 0),
    "repeat": (1, 8, 1), "repeat_gap": (0.02, 0.5, 0.08), "echo": (0, 1, 0), "echo_delay": (0.05, 0.6, 0.25), "volume": (0, 1, 0.6),
}
MAX_STAGES = 3

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
    "rockets": (1, 12, 1),           # how many go up (a volley, like a Roman candle or a cake)
    "interval": (0.05, 2, 0.25),     # seconds between them
    "fan": (0, 1, 0),                # spread their launch angles like a fan
    "spot": (0, 1, 0.3),             # 0 = all from one spot, 1 = spread across the sky
    "lean": (-1, 1, 0),              # launch at an angle
    "hang": (0, 3, 0),               # seconds the rocket hangs at the top before bursting
    "wind": (-1, 1, 0),              # pushes the pieces sideways
    "piece": (1, 3, 1),              # piece size in pixels
    "grow": (0, 1, 0),               # pieces get bigger as they fade
    "wobble": (0, 1, 0),             # pieces zigzag
    "fizzle": (0, 1, 0),             # pieces flicker out at the end
    "duration": (1, 10, 4),          # fountains and wheels: seconds they burn
    "rate": (0.1, 1, 0.5),           # fountains and wheels: how many sparks
    "power": (0.2, 1.5, 0.8),        # fountains: how high; wheels: how far the sparks fly
    "angle": (0, 1, 0.3),            # fountains: how wide the spray is
    "wheel_spin": (-1, 1, 0.6),      # wheels: speed and direction
    "move_x": (-1, 1, 0),            # pictures: drift sideways while holding
    "move_y": (-1, 1, 0),            # pictures: drift up or down
    "turn": (-1, 1, 0),              # pictures: spin while holding
    "swap": (0, 2, 0.4),             # pictures: seconds between frame 1 and frame 2
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
INTS = {"sparks", "points", "arms", "rockets", "piece"}
STAGE_NUMBERS = {"delay": (0.1, 4, 0.8), "size": (0.2, 3, 0.8), "sparks": (8, 120, 30)}
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
        out[k] = _num(d.get(k, default), lo, hi, default, k in INTS)
    out["launch"] = d.get("launch") if d.get("launch") in LAUNCHES else "rocket"
    out["rocket_style"] = d.get("rocket_style") if d.get("rocket_style") in ROCKET_STYLES else "normal"
    out["mirror"] = bool(d.get("mirror"))
    out["sound_launch"] = d.get("sound_launch") if d.get("sound_launch") in LAUNCH_SOUNDS else "whoosh"
    out["sound_burst"] = d.get("sound_burst") if d.get("sound_burst") in BURST_SOUNDS else "boom"
    if out["sound_launch"] == "custom":
        out["sfx_launch"] = _sfx(d.get("sfx_launch"))
    if out["sound_burst"] == "custom":
        out["sfx_burst"] = _sfx(d.get("sfx_burst"))
    out["sound_ground"] = d.get("sound_ground") if d.get("sound_ground") in GROUND_SOUNDS else "hiss"
    if out["sound_ground"] == "custom":
        out["sfx_ground"] = _sfx(d.get("sfx_ground"))
    out["sound_crackle"] = d.get("sound_crackle", True) is not False
    out["sound_fizzle"] = bool(d.get("sound_fizzle", False))
    out["picture"] = _picture(d.get("picture"))
    out["picture2"] = _picture(d.get("picture2"))
    out["stages"] = [_stage(st) for st in (d.get("stages") or [])[:MAX_STAGES] if isinstance(st, dict)]
    if out["pattern"] == "picture" and not any(c != "." for r in out["picture"] for c in r):
        out["pattern"] = "ball"            # an empty picture would launch nothing
    return out


# ------------------------------------------------------------------ saved sounds
# Sounds made in the editor can be saved with a name and used again in any firework.
MAX_SOUNDS = 200
MAX_SOUNDS_PER_USER = 40


def sounds() -> list[dict]:
    items = settings_store.load().get("sounds")
    return [{**x, "sfx": _sfx(x.get("sfx"))} for x in (items if isinstance(items, list) else []) if isinstance(x, dict) and x.get("id")]


def add_sound(name: str, sfx: dict, author: str) -> dict:
    name = re.sub(r"\s+", " ", str(name or "")).strip()[:32] or "My sound"
    with _lock:
        items = sounds()
        if len(items) >= MAX_SOUNDS:
            raise ValueError("There are already too many saved sounds; delete some first")
        if sum(1 for x in items if x.get("author") == author) >= MAX_SOUNDS_PER_USER:
            raise ValueError(f"You can save up to {MAX_SOUNDS_PER_USER} sounds")
        item = {"id": secrets.token_hex(5), "name": name, "author": author, "sfx": _sfx(sfx), "created": time.time()}
        settings_store.save_section("sounds", [*items, item])
    return item


def delete_sound(sid: str, user: str, admin: bool) -> bool:
    with _lock:
        items = sounds()
        keep = [x for x in items if not (x["id"] == sid and (admin or x.get("author") == user))]
        if len(keep) == len(items):
            return False
        settings_store.save_section("sounds", keep)
    return True


def _sfx(p) -> dict:
    p = p if isinstance(p, dict) else {}
    out: dict = {"wave": p.get("wave") if p.get("wave") in SFX_WAVES else "noise"}
    for k, (lo, hi, default) in SFX_NUMBERS.items():
        out[k] = _num(p.get(k, default), lo, hi, default, k == "repeat")
    total = out["attack"] + out["sustain"] + out["decay"]
    if total > 5:                          # keep any one sound short
        f = 5 / total
        for k in ("attack", "sustain", "decay"):
            out[k] = round(out[k] * f, 3)
    return out


def _num(v, lo: float, hi: float, default: float, as_int: bool = False):
    try:
        v = float(v)
    except (TypeError, ValueError):
        v = default
    if v != v:  # NaN
        v = default
    v = min(hi, max(lo, v))
    return int(round(v)) if as_int else round(v, 3)


def _picture(pic) -> list[str]:
    pic = pic if isinstance(pic, list) else []
    rows = [str(r)[:PIC_MAX] for r in pic[:PIC_MAX] if isinstance(r, str) and _PIC_ROW.match(str(r)[:PIC_MAX])]
    if rows:
        width = max(len(r) for r in rows)
        rows = [r.ljust(width, ".") for r in rows]
    return rows


def _stage(st: dict) -> dict:
    """One "then…" step: burst again from the centre, every piece bursts, the pieces
    shatter outwards, or they pull back in and pop."""
    out = {"action": st.get("action") if st.get("action") in STAGE_ACTIONS else "burst",
           "pattern": st.get("pattern") if st.get("pattern") in PATTERNS and st.get("pattern") != "picture" else "ball"}
    for k, (lo, hi, default) in STAGE_NUMBERS.items():
        out[k] = _num(st.get(k, default), lo, hi, default, k == "sparks")
    out["colors"] = [c.lower() for c in (st.get("colors") or []) if isinstance(c, str) and _HEX.match(c)][:4]
    return out


def _load() -> list[dict]:
    items = settings_store.load().get("custom_fireworks")
    return items if isinstance(items, list) else []


def _save(items: list[dict]) -> None:
    settings_store.save_section("custom_fireworks", items)


def all_designs() -> list[dict]:
    # Re-clean on the way out so designs saved by older versions get the newer fields.
    return [{**d, **sanitize(d), "weight": d.get("weight", 1)} for d in _load()]


def in_show() -> list[dict]:
    return [{"id": d["id"], "author": d.get("author", ""), "weight": d.get("weight", 1), **sanitize(d)} for d in _load() if d.get("in_show")]


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
                if "weight" in design:
                    merged["weight"] = design["weight"]
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
