"""Announcements: banners on the status page, the app and the sign-in page.

An admin writes notes (with an optional countdown that can set off a show and post
in the game when it reaches zero). Bedtime countdowns and the
holiday of the day are added automatically.
"""
from __future__ import annotations

import logging
import re
import secrets
from datetime import datetime, timedelta

from . import db, fwshow, mcname, playtime, settings_store
from .control import clean_text, component
from .rcon import RconError

log = logging.getLogger("solstone.board")

STYLES = ("info", "party", "heads", "ocean", "forest", "sunset", "candy", "night", "ruby", "custom")
_HEX = re.compile(r"^#[0-9a-f]{6}$")
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


_MARKS = [(re.compile(r"\[([^\]]+)\]\([^)\s]+\)"), r"\1"), (re.compile(r"\*\*([^*]+)\*\*"), r"\1"), (re.compile(r"__([^_]+?)__"), r"\1"),
          (re.compile(r"(^|[\s(])[*_]([^*_]+)[*_]"), r"\1\2"), (re.compile(r"\{/?[a-z]+\}"), "")]


def plain(text: str) -> str:
    """An announcement without its formatting (bold, italic, links, colours), for the game's chat and lists."""
    for rx, to in _MARKS:
        text = rx.sub(to, text or "")
    return text


def clean_item(it: dict) -> dict | None:
    if not isinstance(it, dict):
        return None
    text = _line(it.get("text"), 300)            # room for formatting: **bold**, {red}…{/red}, [links](…)
    if not plain(text).strip():
        return None
    where = [w for w in WHERE if w in (it.get("where") or [])] or list(WHERE)
    return {"id": re.sub(r"[^a-z0-9]", "", str(it.get("id") or "").lower())[:16] or secrets.token_hex(4),
            "enabled": bool(it.get("enabled", True)), "text": text, "detail": _line(it.get("detail"), 600),
            "emoji": _line(it.get("emoji"), 8), "style": it.get("style") if it.get("style") in STYLES else "info",
            # "custom": the admin's own two or three colours, as a gradient
            "colors": [c for c in (str(x or "").strip().lower() for x in (it.get("colors") or [])[:3]) if _HEX.match(c)],
            "start": _dt(it.get("start")), "end": _dt(it.get("end")), "countdown": _dt(it.get("countdown")),
            "done_text": _line(it.get("done_text"), 80),
            "say": bool(it.get("say")), "where": where, "server": str(it.get("server") or "")[:64]}


def config() -> dict:
    saved = settings_store.load().get("board") or {}
    if "birthdays" in saved or "birthday_soon" in saved:      # birthdays aren't kept any more: what was saved goes
        saved = {k: v for k, v in saved.items() if k not in ("birthdays", "birthday_soon")}
        settings_store.save_section("board", saved)
    bt = saved.get("bedtime") or {}
    return {"items": [i for i in (clean_item(x) for x in saved.get("items") or []) if i],
            "bedtime": {"show": bool(bt.get("show", True)), "minutes": max(5, min(180, int(bt.get("minutes", 30) or 30)))},
            # contests, races and games in the banners (starting soon, on now, results): only if an admin wants them
            "games": bool(saved.get("games", False))}


def save(body: dict) -> dict:
    cur = config()
    if isinstance(body.get("items"), list):
        cur["items"] = [i for i in (clean_item(x) for x in body["items"][:60]) if i]
    if "games" in body:
        cur["games"] = bool(body["games"])
    if isinstance(body.get("bedtime"), dict):
        cur["bedtime"] = {"show": bool(body["bedtime"].get("show", True)),
                          "minutes": max(5, min(180, int(body["bedtime"].get("minutes", 30) or 30)))}
    settings_store.save_section("board", cur)
    return cur


# ------------------------------------------------------------------ what's showing now
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
                    "style": it["style"], "colors": it.get("colors") or [], "countdown": cd, "done_text": it["done_text"] or "It's here!"})
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
    out += holiday_banners(now)                   # one banner per holiday: its countdown, the day, its reward days
    if names and cfg["games"]:
        from . import challenges, games, races
        for one in ([sid] if sid or allowed is None else sorted(allowed)):
            out += challenges.banners(one) + races.banners(one) + games.banners(one)
    order = {"bedtime": 0, "challenge": 0.5, "note": 1, "holiday": 3, "reward": 3.5, "holiday-soon": 4, "vote": 1.5}
    out.sort(key=lambda x: (order.get(x["kind"], 5), x.get("countdown") or 1e12))
    return out


# ------------------------------------------------------------------ holidays
def holiday_banners(now: datetime) -> list[dict]:
    """One banner for each holiday, all the way through (Manage → Announcements → Holidays):
      - before it: "Christmas is in 3 days", counting down (from as many days before as it asks);
      - on its day(s): its message;
      - after it, while its reward is still being given: its own words, or "Christmas is over, but there's still time for its reward".
    Whenever its reward is being given, the banner shows it (the items, its description, and the last day for it),
    and the banner stays up for the reward's days before and after if the reward asks for that. Its look is its own."""
    from . import holidaygifts
    today, out = now.date(), []
    for e in fwshow.calendar():
        if not e["enabled"] or not e["banner"]["show"]:
            continue
        weekly, rw = e["date"]["type"] == "weekly", e["reward"]
        for s in sorted(fwshow._starts(e, today)):
            end = s + timedelta(days=e["days"] - 1)
            r_first, r_last = holidaygifts.window(e, s) if rw["items"] else (s, end)
            stay = bool(rw["items"]) and rw["banner"]
            first = min(s - timedelta(days=0 if weekly else e["banner_days"]), r_first if stay else s)
            last = max(end, r_last if stay else end)
            if not first <= today <= last:
                continue
            giving = bool(rw["items"]) and r_first <= today <= r_last
            if today < s:
                days = (s - today).days
                phase = {"kind": "holiday-soon", "text": f"{e['name_fmt']} is {'tomorrow' if days == 1 else f'in {days} days'}",
                         "countdown": datetime.combine(s, datetime.min.time(), now.tzinfo).timestamp(), "done_text": e["message"] or "It's here!"}
            elif today <= end:
                if not (e["message_fmt"] or e["colors"] or e["kinds"] or giving):
                    break                                   # (a plain weekly show night: no banner of its own)
                phase = {"kind": "holiday", "text": e["message_fmt"] or e["name_fmt"], "countdown": None}
            else:
                phase = {"kind": "reward", "text": rw.get("after_text") or f"{e['name_fmt']} is over, but there's still time for its reward!", "countdown": None}
            b = {"id": f"hol-{e['id']}-{s.isoformat()}-{phase['kind']}", "emoji": e["emoji"] or "🎉", "detail": "",
                 "style": e["banner"]["style"], "colors": e["banner"]["colors"], **phase}
            if giving:
                t = holidaygifts.tag(e, s)
                b.update(items=t["items"], reward_note=t["note"],
                         reward_until="Today only" if r_last == today else f"Now until {r_last.strftime('%a %-d %b')}")
            out.append(b)
            break
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
            text = it["done_text"] if cd and it["done_text"] else plain(it["text"])
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
