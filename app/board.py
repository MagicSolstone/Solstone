"""Announcements: banners on the status page, the app and the sign-in page.

An admin writes notes (with an optional countdown that can set off a show and post
in the game when it reaches zero) and birthdays. Bedtime countdowns and the
holiday of the day are added automatically.
"""
from __future__ import annotations

import logging
import re
import secrets
from datetime import date, datetime

from . import db, fwshow, guard, settings_store
from . import servers as S
from .control import clean_text, component
from .rcon import RconError

log = logging.getLogger("solstone.board")

STYLES = ("info", "party", "heads")
WHERE = ("status", "app", "login")
DEFAULTS = {"items": [], "birthdays": [], "bedtime": {"show": True, "minutes": 30}, "birthday_soon": 7}
_DT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$")
_NAME = re.compile(r"^[A-Za-z0-9_]{1,16}$")


def _dt(v) -> str:
    v = str(v or "").strip()[:16]
    if not _DT.match(v):
        return ""
    try:
        datetime.fromisoformat(v)
    except ValueError:
        return ""
    return v


def _ts(v: str) -> float | None:
    return datetime.fromisoformat(v).replace(tzinfo=db.tz()).timestamp() if v else None


def _line(v, n: int) -> str:
    return " ".join(str(v or "").split())[:n]


def clean_item(it: dict) -> dict | None:
    if not isinstance(it, dict):
        return None
    text = _line(it.get("text"), 120)
    if not text:
        return None
    where = [w for w in WHERE if w in (it.get("where") or [])] or list(WHERE)
    return {"id": re.sub(r"[^a-z0-9]", "", str(it.get("id") or "").lower())[:16] or secrets.token_hex(4),
            "enabled": bool(it.get("enabled", True)), "text": text, "detail": _line(it.get("detail"), 240),
            "emoji": _line(it.get("emoji"), 8), "style": it.get("style") if it.get("style") in STYLES else "info",
            "start": _dt(it.get("start")), "end": _dt(it.get("end")), "countdown": _dt(it.get("countdown")),
            "done_text": _line(it.get("done_text"), 80), "show": re.sub(r"[^a-z0-9_-]", "", str(it.get("show") or ""))[:24],
            "say": bool(it.get("say")), "where": where, "server": str(it.get("server") or "")[:64]}


def clean_birthday(b: dict) -> dict | None:
    if not isinstance(b, dict) or not _NAME.match(str(b.get("player") or "")):
        return None
    try:
        m, d = int(b.get("month")), int(b.get("day"))
        date(2024, m, d)                      # a leap year, so 29 February is allowed
    except (TypeError, ValueError):
        return None
    return {"player": str(b["player"]), "month": m, "day": d,
            "show": re.sub(r"[^a-z0-9_-]", "", str(b.get("show") or ""))[:24], "say": bool(b.get("say", True))}


def config() -> dict:
    saved = settings_store.load().get("board") or {}
    bt = saved.get("bedtime") or {}
    return {"items": [i for i in (clean_item(x) for x in saved.get("items") or []) if i],
            "birthdays": [b for b in (clean_birthday(x) for x in saved.get("birthdays") or []) if b],
            "bedtime": {"show": bool(bt.get("show", True)), "minutes": max(5, min(180, int(bt.get("minutes", 30) or 30)))},
            "birthday_soon": max(0, min(31, int(saved.get("birthday_soon", 7) or 0)))}


def save(body: dict) -> dict:
    cur = config()
    if isinstance(body.get("items"), list):
        cur["items"] = [i for i in (clean_item(x) for x in body["items"][:60]) if i]
    if isinstance(body.get("birthdays"), list):
        cur["birthdays"] = [b for b in (clean_birthday(x) for x in body["birthdays"][:100]) if b]
    if isinstance(body.get("bedtime"), dict):
        cur["bedtime"] = {"show": bool(body["bedtime"].get("show", True)),
                          "minutes": max(5, min(180, int(body["bedtime"].get("minutes", 30) or 30)))}
    if "birthday_soon" in body:
        cur["birthday_soon"] = max(0, min(31, int(body.get("birthday_soon") or 0)))
    settings_store.save_section("board", cur)
    return cur


# ------------------------------------------------------------------ what's showing now
def _birthday_on(b: dict, year: int) -> date:
    try:
        return date(year, b["month"], b["day"])
    except ValueError:                        # 29 February outside a leap year
        return date(year, 2, 28)


def _show(sid: str) -> dict | None:
    return fwshow.resolved(fwshow.get_show(sid)) if sid else None


def item_window(it: dict) -> tuple[float | None, float | None, float | None]:
    start, end, cd = _ts(it["start"]), _ts(it["end"]), _ts(it["countdown"])
    if cd and not end:
        end = cd + 3600                       # the "it's here" line stays up for an hour
    return start, end, cd


def active(where: str, sid: str | None = None, names: bool = True, now: datetime | None = None,
           servers: list | None = None) -> list[dict]:
    """Banners for one place. names=False leaves out anything naming players (for anonymous
    visitors when the public status page is off)."""
    zone = db.tz()
    now = now or datetime.now(zone)
    t = now.timestamp()
    cfg = config()
    out: list[dict] = []
    for it in cfg["items"]:
        if not it["enabled"] or where not in it["where"] or (it["server"] and sid and it["server"] != sid):
            continue
        start, end, cd = item_window(it)
        if (start and t < start) or (end and t >= end):
            continue
        out.append({"id": f"n-{it['id']}", "kind": "note", "text": it["text"], "detail": it["detail"], "emoji": it["emoji"],
                    "style": it["style"], "countdown": cd, "done_text": it["done_text"] or "It's here!",
                    "show": _show(it["show"]) if cd and it["show"] else None})
    if names:
        for b in cfg["birthdays"]:
            bd = _birthday_on(b, now.year)
            if bd < now.date():
                bd = _birthday_on(b, now.year + 1)
            days = (bd - now.date()).days
            if days == 0:
                out.append({"id": f"b-{b['player'].lower()}-{bd.isoformat()}", "kind": "birthday", "emoji": "🎂", "style": "party",
                            "text": f"Happy birthday, {b['player']}!", "detail": "", "player": b["player"], "countdown": None,
                            "show": _show(b["show"])})
            elif 0 < days <= cfg["birthday_soon"]:
                out.append({"id": f"bs-{b['player'].lower()}", "kind": "birthday-soon", "emoji": "🎈", "style": "info",
                            "text": f"{b['player']}'s birthday is {'tomorrow' if days == 1 else f'in {days} days'}",
                            "detail": bd.strftime("%A %d %B").replace(" 0", " "), "player": b["player"], "countdown": None})
    if cfg["bedtime"]["show"] and where in ("status", "app") and servers:
        for srv in servers:
            if sid and srv.id != sid:
                continue
            bcfg = guard.bedtime_config(srv)
            st = guard.bedtime_state(bcfg, now) if bcfg["enabled"] else None
            if not st:
                continue
            kind, left, _night = st
            if kind == "before" and left <= cfg["bedtime"]["minutes"] * 60:
                out.append({"id": f"bt-{srv.id}-{now.date()}", "kind": "bedtime", "emoji": "🌙", "style": "heads",
                            "text": f"Bedtime on {srv.display_name}", "detail": f"The server closes at {guard._fmt_clock(bcfg['start'])}",
                            "countdown": t + left, "done_text": "Time for bed. Good night!"})
            elif kind == "active":
                out.append({"id": f"bta-{srv.id}", "kind": "bedtime", "emoji": "😴", "style": "info",
                            "text": f"{srv.display_name} is asleep", "detail": f"Back at {guard._fmt_clock(bcfg['end'])}", "countdown": None})
    th = fwshow.today_state(now)["theme"]
    if th and (th.get("message") or th.get("name")):
        out.append({"id": f"h-{th['id']}-{now.date()}", "kind": "holiday", "emoji": th.get("emoji") or "🎉", "style": "party",
                    "text": th.get("message") or th["name"], "detail": "", "countdown": None})
    if names:
        from . import challenges, games, races
        out += challenges.banners(sid) + races.banners(sid) + games.banners(sid)
    order = {"bedtime": 0, "challenge": 0.5, "note": 1, "birthday": 2, "holiday": 3, "birthday-soon": 4}
    out.sort(key=lambda x: (order.get(x["kind"], 5), x.get("countdown") or 1e12))
    return out


# ------------------------------------------------------------------ in the game
async def _say_all(servers: list, msg: str, title: str, only: str = "") -> None:
    for srv in servers:
        if only and srv.id != only:
            continue
        if not srv.is_java or not srv.rcon_conf():
            continue
        try:
            await srv.rcon(f"tellraw @a {component([('★ ', 'gold'), (clean_text(msg), 'yellow')])}")
            if title:
                await srv.rcon("title @a times 10 70 20")
                await srv.rcon(f"title @a title {component([(clean_text(title)[:40], 'gold')])}")
        except RconError as e:
            log.debug("announcement not sent to %s: %s", srv.id, e)


async def tick(servers: list) -> None:
    """Post announcements in the game when they start or their countdown reaches zero."""
    t = datetime.now(db.tz()).timestamp()
    for it in config()["items"]:
        if not it["enabled"] or not it["say"]:
            continue
        start, end, cd = item_window(it)
        when = cd or start
        if not when or not when <= t < when + 120:
            continue
        if db.alert_once(f"board:{it['id']}:{int(when)}"):
            text = it["done_text"] if cd and it["done_text"] else it["text"]
            await _say_all(servers, text, text if cd else "", it["server"])  # Minecraft's font has no emoji


async def greet(srv: S.Server, player: str) -> None:
    """Happy birthday in the game when someone joins on their birthday (once a day)."""
    today = datetime.now(db.tz()).date()
    for b in config()["birthdays"]:
        if b["player"].lower() != player.lower() or not b["say"] or _birthday_on(b, today.year) != today:
            continue
        if not srv.rcon_conf() or not db.alert_once(f"bday:{srv.id}:{player.lower()}:{today}"):
            return
        try:
            await srv.rcon(f"tellraw @a {component([('♥ Happy birthday, ', 'light_purple'), (b['player'], 'gold'), ('!', 'light_purple')])}")
            await srv.rcon("title " + b["player"] + " times 10 80 20")
            await srv.rcon(f"title {b['player']} title {component([('Happy birthday!', 'gold')])}")
        except RconError as e:
            log.debug("birthday greeting failed on %s: %s", srv.id, e)


def days_until(b: dict, today: date | None = None) -> int:
    today = today or datetime.now(db.tz()).date()
    d = _birthday_on(b, today.year)
    if d < today:
        d = _birthday_on(b, today.year + 1)
    return (d - today).days

