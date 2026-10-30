"""Announcements: banners on the status page, the app and the sign-in page.

An admin writes notes (with an optional countdown that can set off a show and post
in the game when it reaches zero). Bedtime countdowns and the
holiday of the day are added automatically.
"""
from __future__ import annotations

import logging
import re
import secrets
from datetime import datetime

from . import db, fwshow, mcname, playtime, settings_store
from .control import clean_text, component
from .rcon import RconError

log = logging.getLogger("solstone.board")

STYLES = ("info", "party", "heads")
WHERE = ("home", "status", "app", "login")
DEFAULTS = {"items": [], "bedtime": {"show": True, "minutes": 30}}
_DT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$")
_NAME = mcname.NAME_RE


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


def config() -> dict:
    saved = settings_store.load().get("board") or {}
    if "birthdays" in saved or "birthday_soon" in saved:      # birthdays aren't kept any more: what was saved goes
        saved = {k: v for k, v in saved.items() if k not in ("birthdays", "birthday_soon")}
        settings_store.save_section("board", saved)
    bt = saved.get("bedtime") or {}
    return {"items": [i for i in (clean_item(x) for x in saved.get("items") or []) if i],
            "bedtime": {"show": bool(bt.get("show", True)), "minutes": max(5, min(180, int(bt.get("minutes", 30) or 30)))}}


def save(body: dict) -> dict:
    cur = config()
    if isinstance(body.get("items"), list):
        cur["items"] = [i for i in (clean_item(x) for x in body["items"][:60]) if i]
    if isinstance(body.get("bedtime"), dict):
        cur["bedtime"] = {"show": bool(body["bedtime"].get("show", True)),
                          "minutes": max(5, min(180, int(body["bedtime"].get("minutes", 30) or 30)))}
    settings_store.save_section("board", cur)
    return cur


# ------------------------------------------------------------------ what's showing now
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
    allowed = None if servers is None else {x.id for x in servers}     # given: only these servers' items (none of a private one's)
    for it in cfg["items"]:
        if allowed is not None and it["server"] and it["server"] not in allowed:
            continue
        shown_here = where in it["where"] or (where == "home" and "status" in it["where"])      # status-page notes show at home too
        if not it["enabled"] or not shown_here or (it["server"] and sid and it["server"] != sid):
            continue
        start, end, cd = item_window(it)
        if (start and t < start) or (end and t >= end):
            continue
        out.append({"id": f"n-{it['id']}", "kind": "note", "text": it["text"], "detail": it["detail"], "emoji": it["emoji"],
                    "style": it["style"], "countdown": cd, "done_text": it["done_text"] or "It's here!",
                    "show": _show(it["show"]) if cd and it["show"] else None})
    if cfg["bedtime"]["show"] and where in ("home", "status", "app") and servers:
        pt = playtime.config()
        for srv in servers:
            if sid and srv.id != sid:
                continue
            st = playtime.server_state(pt, srv.id, now)
            if not st:
                continue
            kind, left, _night, bcfg = st
            if kind == "before" and left <= cfg["bedtime"]["minutes"] * 60:
                out.append({"id": f"bt-{srv.id}-{now.date()}", "kind": "bedtime", "emoji": "🌙", "style": "heads",
                            "text": f"Bedtime on {srv.display_name}", "detail": f"The server closes at {playtime.fmt_clock(bcfg['start'])}",
                            "countdown": t + left, "done_text": "Time for bed. Good night!"})
            elif kind == "active":
                out.append({"id": f"bta-{srv.id}", "kind": "bedtime", "emoji": "😴", "style": "info",
                            "text": f"{srv.display_name} is asleep", "detail": f"Back at {playtime.fmt_clock(bcfg['end'])}", "countdown": None})
    # a holiday coming up: a countdown banner from as many days before as it asks (Manage → Holidays)
    today = now.date()
    for e in fwshow.calendar():
        if not e["enabled"] or not e.get("banner_days") or e["date"]["type"] == "weekly":
            continue
        nxt = min((s for s in fwshow._starts(e, today) if s > today), default=None)
        if nxt and (nxt - today).days <= e["banner_days"]:
            days = (nxt - today).days
            out.append({"id": f"hs-{e['id']}-{nxt.isoformat()}", "kind": "holiday-soon", "emoji": e["emoji"] or "🎉", "style": "info",
                        "text": f"{e['name']} is {'tomorrow' if days == 1 else f'in {days} days'}", "detail": "",
                        "countdown": datetime.combine(nxt, datetime.min.time(), zone).timestamp(), "done_text": e["message"] or "It's here!"})
    th = fwshow.today_state(now)["theme"]
    if th and (th.get("message") or th.get("name")):
        out.append({"id": f"h-{th['id']}-{now.date()}", "kind": "holiday", "emoji": th.get("emoji") or "🎉", "style": "party",
                    "text": th.get("message") or th["name"], "detail": "", "countdown": None})
    if names:
        from . import challenges, games, races
        for one in ([sid] if sid or allowed is None else sorted(allowed)):
            out += challenges.banners(one) + races.banners(one) + games.banners(one)
    order = {"bedtime": 0, "challenge": 0.5, "note": 1, "holiday": 3, "holiday-soon": 4, "vote": 1.5}
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


def vote_banners(voter: str) -> list[dict]:
    """For someone signed in, on every page: a banner for each open vote they haven't voted in yet."""
    from . import community
    out = []
    for p in community.unvoted(voter)[:2]:
        out.append({"id": f"vote-{p['id']}", "kind": "vote", "emoji": "🏆" if p["kind"] == "build" else "🗳️", "style": "info",
                    "text": p["question"], "detail": "Vote now: Votes, or !vote in the game", "link": "/app#/votes",
                    "countdown": p["closes"], "done_text": "Voting has closed!"})
    return out
