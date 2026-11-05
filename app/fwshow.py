"""Fireworks beyond the random mix: each player's join firework (it goes off on every open Solstone page when they
join), and the calendar of holidays (their colours, favourite kinds, banners and rewards).

Joins live in a small in-memory feed that every open Solstone page polls.
"""
from __future__ import annotations

import re
import secrets
import threading
import time
from collections import deque
from datetime import date, datetime, timedelta

from . import db, fireworks, mcname, settings_store

# ------------------------------------------------------------------ joins
BUILTIN_KINDS = ("ball", "large", "star", "burst", "ring", "crossette", "spiral", "willow", "saturn", "pair", "cube", "pickaxe",
                 "axe", "creeper", "heart", "candle", "cake", "fountain", "wheel", "sparkler", "shootingstar", "dragon", "bow", "tree")
_feed: deque = deque(maxlen=60)
_feed_lock = threading.Lock()
_seq = int(time.time() * 1000) % 10**9  # survives restarts without clients seeing old ids as new


def join_cfg() -> dict:
    """Join fireworks on or off (on unless switched off; the old "Someone joins" game event's switch carries over)."""
    saved = settings_store.load()
    j = saved.get("fw_join")
    if not isinstance(j, dict):
        old = (saved.get("fw_events") or {}).get("join")
        j = {"on": old.get("on", True) is not False and old.get("firework") != "none"} if isinstance(old, dict) else {}
    return {"on": j.get("on", True) is not False}


def save_join(body: dict) -> dict:
    settings_store.save_section("fw_join", {"on": bool((body or {}).get("on"))})
    return join_cfg()


def signatures() -> dict[str, str]:
    saved = settings_store.load().get("fw_signatures") or {}
    return {str(k).lower(): str(v) for k, v in saved.items() if isinstance(v, str)}


def save_signatures(body: dict) -> dict[str, str]:
    clean = {str(k).lower()[:16]: str(v) for k, v in (body or {}).items() if v and mcname.is_name(str(k))}
    settings_store.save_section("fw_signatures", clean)
    return signatures()


def resolve_join(player: str | None, check_on: bool = True) -> dict | None:
    """What goes off when someone joins: their join firework, or a random one."""
    if check_on and not join_cfg()["on"]:
        return None
    sig = signatures().get((player or "").lower())
    d = fireworks.get_live(sig) if sig else None
    if d:
        return {"design": {**d, **fireworks.sanitize(d)}, "count": 1}
    return {"kind": "random", "count": 1}


def push_join(server_id: str, server: str, player: str, text: str = "") -> None:
    global _seq
    show = resolve_join(player)
    if not show:
        return
    with _feed_lock:
        _seq += 1
        _feed.append({"id": _seq, "ts": time.time(), "event": "join", "server_id": server_id, "server": server,
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


# ------------------------------------------------------------------ calendar
# date.type: fixed (month/day), easter, nth (month, weekday 0=Mon, n 1–4 or -1 for last),
# weekly (weekday), once (iso date).
DEFAULT_CALENDAR = [
    {"id": "newyear", "name": "New Year", "emoji": "🎆", "date": {"type": "fixed", "month": 12, "day": 31}, "days": 2,
     "colors": ["#ffe45c", "#ffffff", "#ffcf5a", "#c46cf0"], "kinds": ["large", "crossette", "willow", "cake", "saturn"],
     "message": "Happy New Year!"},
    {"id": "valentine", "name": "Valentine's Day", "emoji": "💖", "date": {"type": "fixed", "month": 2, "day": 14}, "days": 1,
     "colors": ["#ff5a7a", "#ff8fc0", "#ffffff"], "kinds": ["heart", "heart", "ring"], "message": "Happy Valentine's Day!"},
    {"id": "stpatrick", "name": "St. Patrick's Day", "emoji": "☘️", "date": {"type": "fixed", "month": 3, "day": 17}, "days": 1,
     "colors": ["#3fbf5a", "#9be34a", "#ffe45c"], "kinds": ["creeper", "palm", "willow"], "message": "Happy St. Patrick's Day!"},
    {"id": "easter", "name": "Easter", "emoji": "🐣", "date": {"type": "easter"}, "days": 1,
     "colors": ["#ffb7d5", "#bfe9ff", "#fff3a8", "#c9f2c1"], "kinds": ["ring", "heart", "spiral"], "message": "Happy Easter!"},
    {"id": "july4", "name": "Independence Day", "emoji": "🇺🇸", "date": {"type": "fixed", "month": 7, "day": 4}, "days": 1,
     "colors": ["#ff4f4f", "#ffffff", "#5d8bff"], "kinds": ["large", "star", "crossette", "willow", "cake", "candle"],
     "message": "Happy 4th of July!"},
    {"id": "halloween", "name": "Halloween", "emoji": "🎃", "date": {"type": "fixed", "month": 10, "day": 31}, "days": 1,
     "colors": ["#ffa13d", "#c46cf0", "#7dff5c"], "kinds": ["creeper", "spiral", "crossette", "dragon"], "message": "Happy Halloween!"},
    {"id": "thanksgiving", "name": "Thanksgiving", "emoji": "🦃", "date": {"type": "nth", "month": 11, "weekday": 3, "n": 4}, "days": 1,
     "colors": ["#ffa13d", "#ff5a4f", "#ffcf5a"], "kinds": ["tree", "willow", "fountain"], "message": "Happy Thanksgiving!"},
    {"id": "christmas", "name": "Christmas", "emoji": "🎄", "date": {"type": "fixed", "month": 12, "day": 24}, "days": 2,
     "colors": ["#ff4f4f", "#3fbf5a", "#ffffff"], "kinds": ["tree", "tree", "star", "willow", "sparkler"], "message": "Merry Christmas!"},
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
    days = num(e.get("days"), 1, 14, 1)
    from .board import STYLES, plain
    # the name and message can be formatted like posts (**bold**, {red}…{/red}); "name" and "message" are the same
    # without it, for the game, titles and lists
    name_fmt = " ".join(str(e.get("name_fmt") or e.get("name") or "Celebration").split())[:120]
    name = " ".join(plain(name_fmt).split())[:40] or "Celebration"
    message_fmt = " ".join(str(e.get("message_fmt") if e.get("message_fmt") is not None else e.get("message") or "").split())[:240]
    bn = e.get("banner") if isinstance(e.get("banner"), dict) else {}
    return {
        "id": re.sub(r"[^a-z0-9_-]", "", str(e.get("id") or fallback_id or secrets.token_hex(4)).lower())[:24] or secrets.token_hex(4),
        "name": name, "name_fmt": name_fmt if plain(name_fmt).strip() else name,
        "emoji": str(e.get("emoji") or "🎆")[:4],
        "date": d, "days": days,
        # its one banner on every page (the countdown, the day itself, and any reward days after): on or off, and its look
        "banner": {"show": bn.get("show", True) is not False, "style": bn.get("style") if bn.get("style") in STYLES else "party",
                   "colors": [c.lower() for c in (bn.get("colors") or [])[:3] if isinstance(c, str) and _HEX.match(c)]},
        "colors": [c.lower() for c in (e.get("colors") or []) if isinstance(c, str) and _HEX.match(c)][:6],
        "kinds": [k for k in (e.get("kinds") or []) if k in BUILTIN_KINDS or (isinstance(k, str) and k.startswith("custom:"))][:10],
        "message": " ".join(plain(message_fmt).split())[:80], "message_fmt": message_fmt,
        "banner_days": num(e.get("banner_days"), 0, 30, 0),     # a countdown banner this many days before (0: just on the day)
        # the fireworks' colours and favourite kinds: from this many days before the holiday to this many after
        # (a red, green and white week for Christmas), and whether players' own fireworks take the colours too
        "colors_before": num(e.get("colors_before"), 0, 30, 0), "colors_after": num(e.get("colors_after"), 0, 30, 0),
        "recolor": e.get("recolor", True) is not False,
        # a longer description for the Events page, formatted like posts (bold, colours, links)
        "detail": str(e.get("detail") or "").replace("\r", "").strip()[:600],
        # everyone who plays during it gets this once (holidaygifts.py)
        "reward": _clean_reward(e.get("reward")),
        "enabled": e.get("enabled", True) is not False,
    }


REWARD_ITEMS = 9                                 # a holiday's reward: up to a hotbar's worth of different things


def _clean_reward(r) -> dict:
    from . import challenges
    r = r if isinstance(r, dict) else {}
    items = []
    for x in (r.get("items") or [])[:REWARD_ITEMS]:
        try:
            p = challenges.clean_prize(x)
        except ValueError:
            p = None
        if p:
            items.append(p)
    def days(v):
        try:
            return max(0, min(30, int(v)))
        except (TypeError, ValueError):
            return 0
    # given from this many days before the holiday to this many after it (Thanksgiving through the weekend: 0 and 3)
    # the message in the game when they get it: the game's own & colour codes, like the welcome message
    lines = [" ".join(x.split())[:200] for x in str(r.get("message") or "").replace("\r", "").split("\n")]
    return {"items": items, "message": "\n".join([x for x in lines if x][:5])[:600] if any(lines) else "",           # up to 5 lines in the chat
            "after_text": " ".join(str(r.get("after_text") or "").split())[:160],      # the banner after the holiday, if not the usual words
            "before": days(r.get("before")), "after": days(r.get("after")),
            # its own line on the Events page and its banner ("Reward for playing Thanksgiving weekend"), formatted like posts
            "note": " ".join(str(r.get("note") or "").split())[:300],
            "banner": bool(r.get("banner"))}            # the holiday's banner stays up for the reward's days before and after


def calendar() -> list[dict]:
    saved = settings_store.load().get("fw_calendar")
    items = saved if isinstance(saved, list) else DEFAULT_CALENDAR
    return [c for c in (_clean_entry(e) for e in items) if c]


def with_next(cal: list[dict], today: date | None = None) -> list[dict]:
    """Each holiday with the day it next starts (or the one on now, reward days included), for the editor's preview."""
    today = today or datetime.now(db.tz()).date()
    out = []
    for e in cal:
        tail = e["days"] + (e["reward"]["after"] if e["reward"]["items"] else 0)
        nxt = [s for s in _starts(e, today) if s + timedelta(days=tail) > today]
        out.append({**e, "next": min(nxt).isoformat() if nxt else None})
    return out


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
    """The theme for today: the colours and favourite kinds of a holiday on now (or within its colour days)."""
    zone = db.tz()
    now = now or datetime.now(zone)
    today = now.date()
    theme = None
    for e in calendar():
        if not e["enabled"]:
            continue
        for start in _starts(e, today):
            on_day = start <= today < start + timedelta(days=e["days"])
            near = start - timedelta(days=e["colors_before"]) <= today < start + timedelta(days=e["days"] + e["colors_after"])
            if near and theme is None and (e["colors"] or (on_day and e["message"]) or e["kinds"]):
                # the colours for its whole window; its message (the banner on every page) on the day itself
                theme = {"id": e["id"], "name": e["name"], "emoji": e["emoji"], "message": e["message"] if on_day else "",
                         "colors": e["colors"], "kinds": e["kinds"], "on_day": on_day, "recolor": e["recolor"]}
    return {"theme": theme, "now": now.timestamp()}


def overlaps(now: datetime | None = None) -> dict[str, list[dict]]:
    """For the year ahead: days two calendar entries share (the higher one in the list sets the colours and
    message). Small notes, not errors."""
    zone = db.tz()
    today = (now or datetime.now(zone)).date()
    cal = [e for e in calendar() if e["enabled"]]
    order = {e["id"]: i for i, e in enumerate(cal)}
    days: dict[tuple[str, str], list[date]] = {}
    for i in range(366):
        d = today + timedelta(days=i)
        active = []
        for e in cal:
            for s0 in _starts(e, d):
                if s0 <= d < s0 + timedelta(days=e["days"]) and (e["colors"] or e["message"] or e["kinds"]) and e not in active:
                    active.append(e)
        for a_i, a in enumerate(active):
            for b in active[a_i + 1:]:
                days.setdefault((a["id"], b["id"]), []).append(d)
    names = {e["id"]: e["name"] for e in cal}
    out: dict[str, list[dict]] = {e["id"]: [] for e in cal}
    for (a, b), ds in days.items():
        first, second = (a, b) if order[a] < order[b] else (b, a)
        note = {"kind": "day", "dates": [x.isoformat() for x in ds[:3]], "count": len(ds)}
        out[first].append({**note, "with": names[second], "wins": True})
        out[second].append({**note, "with": names[first], "wins": False})
    return out
