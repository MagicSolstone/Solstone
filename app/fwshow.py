"""The fireworks show beyond random launches: game events that set fireworks off,
each player's signature join firework, and a calendar of holiday themes and
scheduled shows (with a New Year countdown).

Triggers live in a small in-memory feed that every open Solstone page polls.
"""
from __future__ import annotations

import re
import secrets
import threading
import time
from collections import deque
from datetime import date, datetime, timedelta

from . import db, fireworks, mcname, settings_store

# ------------------------------------------------------------------ events
EVENT_TYPES = ("join", "advancement", "challenge", "goal", "death", "level", "night", "start")
EVENT_DEFAULTS: dict[str, dict] = {
    "join": {"on": True, "firework": "signature"},
    "advancement": {"on": True, "firework": "random"},
    "challenge": {"on": True, "firework": "showpiece"},
    "goal": {"on": True, "firework": "random"},
    "death": {"on": True, "firework": "dud"},
    "level": {"on": True, "firework": "random", "every": 10},
    "night": {"on": False, "firework": "show", "minutes": 2},
    "start": {"on": True, "firework": "random"},
}
# What an event can launch: these, a built-in kind, or "custom:<id>".
EVENT_CHOICES = ("signature", "random", "showpiece", "dud", "show", "none")
BUILTIN_KINDS = ("ball", "large", "star", "burst", "ring", "crossette", "spiral", "willow", "saturn", "pair", "cube", "pickaxe",
                 "axe", "creeper", "heart", "candle", "cake", "fountain", "wheel", "sparkler", "shootingstar", "dragon", "bow", "tree")
_feed: deque = deque(maxlen=60)
_feed_lock = threading.Lock()
_seq = int(time.time() * 1000) % 10**9  # survives restarts without clients seeing old ids as new


def events_cfg() -> dict:
    saved = settings_store.load().get("fw_events") or {}
    out = {}
    for k, default in EVENT_DEFAULTS.items():
        cur = {**default, **(saved.get(k) if isinstance(saved.get(k), dict) else {})}
        cur["on"] = bool(cur.get("on"))
        fw = str(cur.get("firework") or default["firework"])
        if fw not in EVENT_CHOICES and fw not in BUILTIN_KINDS and not fw.startswith(("custom:", "show:")):
            fw = default["firework"]
        cur["firework"] = fw
        if "every" in default:
            cur["every"] = max(1, min(100, int(cur.get("every") or default["every"])))
        if "minutes" in default:
            cur["minutes"] = max(1, min(30, int(cur.get("minutes") or default["minutes"])))
        out[k] = cur
    return out


def signatures() -> dict[str, str]:
    saved = settings_store.load().get("fw_signatures") or {}
    return {str(k).lower(): str(v) for k, v in saved.items() if isinstance(v, str)}


def save_events(body: dict) -> dict:
    cur = events_cfg()
    for k, v in (body or {}).items():
        if k in cur and isinstance(v, dict):
            cur[k] = {**cur[k], **v}
    settings_store.save_section("fw_events", cur)
    return events_cfg()


def save_signatures(body: dict) -> dict[str, str]:
    clean = {str(k).lower()[:16]: str(v) for k, v in (body or {}).items() if v and mcname.is_name(str(k))}
    settings_store.save_section("fw_signatures", clean)
    return signatures()


def _resolve(event: str, player: str | None) -> dict | None:
    """Turn an event into what the sky should launch."""
    cfg = events_cfg()[event]
    if not cfg["on"]:
        return None
    fw = cfg["firework"]
    if fw == "signature":
        sig = signatures().get((player or "").lower())
        d = fireworks.get(sig) if sig else None
        if d:
            return {"design": {**d, **fireworks.sanitize(d)}, "count": 1}
        fw = "random"
    if fw.startswith("custom:"):
        d = fireworks.get(fw.split(":", 1)[1])
        return {"design": {**d, **fireworks.sanitize(d)}, "count": 1} if d else {"kind": "random", "count": 1}
    if fw == "none":
        return None
    if fw.startswith("show:"):
        sh = resolved(get_show(fw.split(":", 1)[1]))
        return {"play": sh} if sh else {"kind": "random", "count": 1}
    count = {"challenge": 3, "start": 2}.get(event, 1)
    if fw == "show":
        return {"show": cfg.get("minutes", 2) * 60}
    return {"kind": fw, "count": count}


def push(server_id: str, server: str, event: str, player: str | None = None, text: str = "") -> None:
    global _seq
    if event not in EVENT_DEFAULTS:
        return
    show = _resolve(event, player)
    if not show:
        return
    with _feed_lock:
        _seq += 1
        _feed.append({"id": _seq, "ts": time.time(), "event": event, "server_id": server_id, "server": server,
                      "player": player, "text": text[:160], "show": show})


def pushed_recently(server_id: str, event: str, player: str | None, within: float = 120) -> bool:
    """Was this already set off a moment ago (the log and the online check can both notice a join)?"""
    cutoff = time.time() - within
    with _feed_lock:
        return any(i["server_id"] == server_id and i["event"] == event and (i["player"] or "").lower() == (player or "").lower()
                   and i["ts"] >= cutoff for i in _feed)


def feed_since(since: int, names: bool) -> dict:
    with _feed_lock:
        items = list(_feed)
        last = _seq
    if since < 0:
        return {"last": last, "items": []}
    fresh = [i for i in items if i["id"] > since and time.time() - i["ts"] < 120]
    if not names:
        fresh = [{**i, "player": None, "text": ""} for i in fresh]
    return {"last": last, "items": fresh[-12:]}


def advancement_kind(message: str) -> str:
    if "completed the challenge" in message:
        return "challenge"
    if "reached the goal" in message:
        return "goal"
    return "advancement"


# ------------------------------------------------------------------ calendar
# date.type: fixed (month/day), easter, nth (month, weekday 0=Mon, n 1–4 or -1 for last),
# weekly (weekday), once (iso date). A finale is a big show at a set time, optionally
# with a 10-second countdown first.
DEFAULT_CALENDAR = [
    {"id": "newyear", "name": "New Year", "emoji": "🎆", "date": {"type": "fixed", "month": 12, "day": 31}, "days": 2,
     "colors": ["#ffe45c", "#ffffff", "#ffcf5a", "#c46cf0"], "kinds": ["large", "crossette", "willow", "cake", "saturn"],
     "message": "Happy New Year!", "finale": {"on": True, "day": 1, "time": "00:00", "minutes": 5, "countdown": True}},
    {"id": "valentine", "name": "Valentine's Day", "emoji": "💖", "date": {"type": "fixed", "month": 2, "day": 14}, "days": 1,
     "colors": ["#ff5a7a", "#ff8fc0", "#ffffff"], "kinds": ["heart", "heart", "ring"], "message": "Happy Valentine's Day!",
     "finale": {"on": False, "day": 0, "time": "20:00", "minutes": 5, "countdown": False}},
    {"id": "stpatrick", "name": "St. Patrick's Day", "emoji": "☘️", "date": {"type": "fixed", "month": 3, "day": 17}, "days": 1,
     "colors": ["#3fbf5a", "#9be34a", "#ffe45c"], "kinds": ["creeper", "palm", "willow"], "message": "Happy St. Patrick's Day!",
     "finale": {"on": False, "day": 0, "time": "20:00", "minutes": 5, "countdown": False}},
    {"id": "easter", "name": "Easter", "emoji": "🐣", "date": {"type": "easter"}, "days": 1,
     "colors": ["#ffb7d5", "#bfe9ff", "#fff3a8", "#c9f2c1"], "kinds": ["ring", "heart", "spiral"], "message": "Happy Easter!",
     "finale": {"on": False, "day": 0, "time": "19:30", "minutes": 5, "countdown": False}},
    {"id": "july4", "name": "Independence Day", "emoji": "🇺🇸", "date": {"type": "fixed", "month": 7, "day": 4}, "days": 1,
     "colors": ["#ff4f4f", "#ffffff", "#5d8bff"], "kinds": ["large", "star", "crossette", "willow", "cake", "candle"],
     "message": "Happy 4th of July!", "finale": {"on": True, "day": 0, "time": "21:30", "minutes": 10, "countdown": False}},
    {"id": "halloween", "name": "Halloween", "emoji": "🎃", "date": {"type": "fixed", "month": 10, "day": 31}, "days": 1,
     "colors": ["#ffa13d", "#c46cf0", "#7dff5c"], "kinds": ["creeper", "spiral", "crossette", "dragon"], "message": "Happy Halloween!",
     "finale": {"on": True, "day": 0, "time": "19:00", "minutes": 5, "countdown": False}},
    {"id": "thanksgiving", "name": "Thanksgiving", "emoji": "🦃", "date": {"type": "nth", "month": 11, "weekday": 3, "n": 4}, "days": 1,
     "colors": ["#ffa13d", "#ff5a4f", "#ffcf5a"], "kinds": ["tree", "willow", "fountain"], "message": "Happy Thanksgiving!",
     "finale": {"on": False, "day": 0, "time": "19:00", "minutes": 5, "countdown": False}},
    {"id": "christmas", "name": "Christmas", "emoji": "🎄", "date": {"type": "fixed", "month": 12, "day": 24}, "days": 2,
     "colors": ["#ff4f4f", "#3fbf5a", "#ffffff"], "kinds": ["tree", "tree", "star", "willow", "sparkler"], "message": "Merry Christmas!",
     "finale": {"on": True, "day": 0, "time": "19:00", "minutes": 5, "countdown": False}},
    {"id": "friday", "name": "Friday night show", "emoji": "🎇", "date": {"type": "weekly", "weekday": 4}, "days": 1,
     "colors": [], "kinds": [], "message": "", "enabled": False,
     "finale": {"on": True, "day": 0, "time": "20:00", "minutes": 10, "countdown": False}},
]
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_TIME = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


def _clean_entry(e: dict, fallback_id: str | None = None) -> dict | None:
    if not isinstance(e, dict):
        return None
    dt = e.get("date") if isinstance(e.get("date"), dict) else {}
    t = dt.get("type") if dt.get("type") in ("fixed", "easter", "nth", "weekly", "once") else "fixed"

    def num(v, lo, hi, default):
        try:
            return max(lo, min(hi, int(v)))
        except (TypeError, ValueError):
            return default
    d: dict = {"type": t}
    if t in ("fixed", "nth"):
        d["month"] = num(dt.get("month"), 1, 12, 1)
    if t == "fixed":
        d["day"] = num(dt.get("day"), 1, 31, 1)
    if t in ("nth", "weekly"):
        d["weekday"] = num(dt.get("weekday"), 0, 6, 4)
    if t == "nth":
        n = num(dt.get("n"), -1, 4, 1)
        d["n"] = n if n != 0 else 1
    if t == "once":
        try:
            d["iso"] = date.fromisoformat(str(dt.get("iso"))).isoformat()
        except ValueError:
            d["iso"] = date.today().isoformat()
    fin = e.get("finale") if isinstance(e.get("finale"), dict) else {}
    days = num(e.get("days"), 1, 14, 1)
    return {
        "id": re.sub(r"[^a-z0-9_-]", "", str(e.get("id") or fallback_id or secrets.token_hex(4)).lower())[:24] or secrets.token_hex(4),
        "name": str(e.get("name") or "Celebration").strip()[:40],
        "emoji": str(e.get("emoji") or "🎆")[:4],
        "date": d, "days": days,
        "colors": [c.lower() for c in (e.get("colors") or []) if isinstance(c, str) and _HEX.match(c)][:6],
        "kinds": [k for k in (e.get("kinds") or []) if k in BUILTIN_KINDS or (isinstance(k, str) and k.startswith("custom:"))][:10],
        "message": str(e.get("message") or "").strip()[:80],
        "enabled": e.get("enabled", True) is not False,
        "finale": {"on": bool(fin.get("on")), "day": num(fin.get("day"), 0, days - 1, 0),
                   "show": str(fin.get("show") or "")[:24],
                   "time": fin.get("time") if isinstance(fin.get("time"), str) and _TIME.match(fin["time"]) else "20:00",
                   "minutes": num(fin.get("minutes"), 1, 30, 5), "countdown": bool(fin.get("countdown"))},
    }


def calendar() -> list[dict]:
    saved = settings_store.load().get("fw_calendar")
    items = saved if isinstance(saved, list) else DEFAULT_CALENDAR
    return [c for c in (_clean_entry(e) for e in items) if c]


def save_calendar(items: list) -> list[dict]:
    clean = [c for c in (_clean_entry(e) for e in (items or [])[:40]) if c]
    seen: set[str] = set()
    for c in clean:                                  # ids must be unique
        while c["id"] in seen:
            c["id"] = f"{c['id'][:18]}-{secrets.token_hex(2)}"
        seen.add(c["id"])
    settings_store.save_section("fw_calendar", clean)
    return calendar()


def easter(year: int) -> date:
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    month = (h + m - 7 * n + 114) // 31
    day = (h + m - 7 * n + 114) % 31 + 1
    return date(year, month, day)


def _starts(entry: dict, around: date) -> list[date]:
    """Start dates of this entry near `around` (so spans across New Year work)."""
    d = entry["date"]
    out = []
    if d["type"] == "weekly":
        back = (around.weekday() - d["weekday"]) % 7
        first = around - timedelta(days=back)
        return [first - timedelta(days=7), first, first + timedelta(days=7)]
    if d["type"] == "once":
        return [date.fromisoformat(d["iso"])]
    for y in (around.year - 1, around.year, around.year + 1):
        try:
            if d["type"] == "fixed":
                out.append(date(y, d["month"], min(d["day"], 28 if d["month"] == 2 and not _leap(y) else 31)))
            elif d["type"] == "easter":
                out.append(easter(y))
            elif d["type"] == "nth":
                out.append(_nth(y, d["month"], d["weekday"], d["n"]))
        except ValueError:
            continue
    return out


def _leap(y: int) -> bool:
    return y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)


def _nth(y: int, month: int, weekday: int, n: int) -> date:
    if n == -1:
        nxt = date(y + (month == 12), month % 12 + 1, 1)
        last = nxt - timedelta(days=1)
        return last - timedelta(days=(last.weekday() - weekday) % 7)
    first = date(y, month, 1)
    return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))


def today_state(now: datetime | None = None) -> dict:
    """The theme for today and any finales from a little while ago to a day ahead."""
    zone = db.tz()
    now = now or datetime.now(zone)
    today = now.date()
    theme, finales = None, []
    for e in calendar():
        if not e["enabled"]:
            continue
        for start in _starts(e, today):
            if start <= today < start + timedelta(days=e["days"]) and theme is None and (e["colors"] or e["message"] or e["kinds"]):
                theme = {"id": e["id"], "name": e["name"], "emoji": e["emoji"], "message": e["message"],
                         "colors": e["colors"], "kinds": e["kinds"]}
            f = e["finale"]
            if f["on"]:
                hh, mm = (int(x) for x in f["time"].split(":"))
                st = datetime.combine(start + timedelta(days=f["day"]), datetime.min.time(), zone).replace(hour=hh, minute=mm)
                end = st + timedelta(minutes=f["minutes"])
                if now - timedelta(minutes=f["minutes"]) <= st <= now + timedelta(hours=26) or st <= now < end:
                    finales.append({"id": e["id"], "name": e["name"], "emoji": e["emoji"], "message": e["message"],
                                    "start": st.timestamp(), "end": end.timestamp(), "countdown": f["countdown"],
                                    "colors": e["colors"], "kinds": e["kinds"], "show": resolved(get_show(f["show"])) if f["show"] else None})
    finales.sort(key=lambda x: x["start"])
    return {"theme": theme, "finales": finales, "now": now.timestamp()}


def overlaps(now: datetime | None = None) -> dict[str, list[dict]]:
    """For the year ahead: days two calendar entries share (the higher one in the list sets the
    colours and message) and scheduled shows that start together. Small notes, not errors."""
    zone = db.tz()
    today = (now or datetime.now(zone)).date()
    cal = [e for e in calendar() if e["enabled"]]
    order = {e["id"]: i for i, e in enumerate(cal)}
    days: dict[tuple[str, str], list[date]] = {}
    shows: dict[tuple[str, str], list[date]] = {}
    for i in range(366):
        d = today + timedelta(days=i)
        active, finales = [], []
        for e in cal:
            for s0 in _starts(e, d):
                if s0 <= d < s0 + timedelta(days=e["days"]) and (e["colors"] or e["message"] or e["kinds"]) and e not in active:
                    active.append(e)
                f = e["finale"]
                if f["on"] and s0 + timedelta(days=f["day"]) == d:
                    hh, mm = (int(x) for x in f["time"].split(":"))
                    finales.append((hh * 60 + mm, f["minutes"], e))
        for a_i, a in enumerate(active):
            for b in active[a_i + 1:]:
                days.setdefault((a["id"], b["id"]), []).append(d)
        finales.sort(key=lambda x: x[0])
        for a_i, (sa, ma, a) in enumerate(finales):
            for sb, _mb, b in finales[a_i + 1:]:
                if sb < sa + ma and a["id"] != b["id"]:
                    shows.setdefault((a["id"], b["id"]), []).append(d)
    names = {e["id"]: e["name"] for e in cal}
    out: dict[str, list[dict]] = {e["id"]: [] for e in cal}
    for kind, pairs in (("day", days), ("show", shows)):
        for (a, b), ds in pairs.items():
            first, second = (a, b) if order[a] < order[b] else (b, a)
            note = {"kind": kind, "dates": [x.isoformat() for x in ds[:3]], "count": len(ds)}
            out[first].append({**note, "with": names[second], "wins": True})
            out[second].append({**note, "with": names[first], "wins": False})
    return out


# ------------------------------------------------------------------ shows
# A show is a timeline: at N seconds, launch something (a kind, a design, something
# random or a show-piece), so many times, from somewhere. Base shows (day and night)
# replace the random mix while the Show switch is on; special shows play at calendar
# times or for game events.
SHOW_WHERE = ("random", "left", "center", "right", "spread", "sides")
MAX_STEPS = 120


def _clean_show(sh: dict) -> dict | None:
    if not isinstance(sh, dict):
        return None
    steps = []
    for st in (sh.get("steps") or [])[:MAX_STEPS]:
        if not isinstance(st, dict):
            continue
        what = str(st.get("what") or "random")
        if what not in ("random", "showpiece") and what not in BUILTIN_KINDS and not what.startswith("custom:"):
            what = "random"
        try:
            at = max(0.0, min(600.0, round(float(st.get("at", 0)), 2)))
            count = max(1, min(12, int(st.get("count", 1))))
        except (TypeError, ValueError):
            continue
        steps.append({"at": at, "what": what[:32], "count": count,
                      "where": st.get("where") if st.get("where") in SHOW_WHERE else "random"})
    steps.sort(key=lambda x: x["at"])
    return {"id": re.sub(r"[^a-z0-9_-]", "", str(sh.get("id") or secrets.token_hex(4)).lower())[:24] or secrets.token_hex(4),
            "name": str(sh.get("name") or "My show").strip()[:40] or "My show",
            "steps": steps, "loop_gap": max(0.0, min(30.0, float(sh.get("loop_gap", 2) or 0)))}


DEFAULT_SHOWS = [
    {"id": "gentle-night", "name": "Gentle night", "loop_gap": 3, "steps": [
        {"at": 0, "what": "willow", "count": 1, "where": "random"}, {"at": 3, "what": "random", "count": 1, "where": "random"},
        {"at": 6, "what": "spiral", "count": 1, "where": "random"}, {"at": 9, "what": "random", "count": 2, "where": "spread"},
        {"at": 13, "what": "fountain", "count": 1, "where": "random"}, {"at": 16, "what": "random", "count": 1, "where": "random"}]},
    {"id": "grand-finale", "name": "Grand finale", "loop_gap": 2, "steps": [
        {"at": 0, "what": "candle", "count": 2, "where": "sides"}, {"at": 2, "what": "large", "count": 3, "where": "spread"},
        {"at": 4, "what": "crossette", "count": 2, "where": "sides"}, {"at": 6, "what": "willow", "count": 3, "where": "spread"},
        {"at": 8, "what": "showpiece", "count": 1, "where": "center"}, {"at": 11, "what": "cake", "count": 2, "where": "sides"},
        {"at": 13, "what": "random", "count": 5, "where": "spread"}, {"at": 15, "what": "saturn", "count": 1, "where": "center"},
        {"at": 16, "what": "large", "count": 6, "where": "spread"}]},
    {"id": "daytime-smoke", "name": "Daytime smoke", "loop_gap": 6, "steps": [
        {"at": 0, "what": "ball", "count": 1, "where": "random"}, {"at": 5, "what": "ring", "count": 1, "where": "random"},
        {"at": 10, "what": "fountain", "count": 1, "where": "random"}]},
]


def shows() -> list[dict]:
    saved = settings_store.load().get("fw_shows")
    items = saved if isinstance(saved, list) else DEFAULT_SHOWS
    return [c for c in (_clean_show(x) for x in items) if c]


def get_show(sid: str) -> dict | None:
    return next((x for x in shows() if x["id"] == sid), None)


def save_shows(items: list) -> list[dict]:
    clean = [c for c in (_clean_show(x) for x in (items or [])[:40]) if c]
    seen: set[str] = set()
    for c in clean:
        while c["id"] in seen:
            c["id"] = f"{c['id'][:18]}-{secrets.token_hex(2)}"
        seen.add(c["id"])
    settings_store.save_section("fw_shows", clean)
    return shows()


def base_shows() -> dict:
    saved = settings_store.load().get("fw_base_shows") or {}
    return {k: str(saved.get(k) or "") for k in ("day", "night")}


def save_base_shows(body: dict) -> dict:
    cur = base_shows()
    for k in ("day", "night"):
        if k in (body or {}):
            cur[k] = str(body[k] or "")[:24]
    settings_store.save_section("fw_base_shows", cur)
    return base_shows()


def resolved(sh: dict | None) -> dict | None:
    """A show ready for the sky: editor fireworks it uses are sent along with it."""
    if not sh:
        return None
    steps = []
    for st in sh["steps"]:
        st = dict(st)
        if st["what"].startswith("custom:"):
            d = fireworks.get(st["what"].split(":", 1)[1])
            if d:
                st["design"] = {**d, **fireworks.sanitize(d)}
            else:
                st["what"] = "random"
        steps.append(st)
    return {**sh, "steps": steps}


def base_shows_resolved() -> dict:
    return {k: resolved(get_show(v)) if v else None for k, v in base_shows().items()}
