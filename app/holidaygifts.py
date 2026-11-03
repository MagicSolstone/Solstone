"""Holiday rewards: an item or a few for everyone who plays during a holiday (Manage → Announcements → Holidays).

Anyone who is on a server at any time while the holiday is on gets its reward once: one each per holiday, per
server, each year it comes round (Christmas 2026 and Christmas 2027 are two). If the game can't take it right then
(a full inventory, say), it waits for their next join like a contest prize does.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from . import challenges, db, fwshow, settings_store
from .control import component

log = logging.getLogger("solstone.holidaygifts")

SECTION = "holiday_rewards"            # {"<holiday id>:<start date>:<server id>": [player names, lowercased]}
KEEP_DAYS = 60


def active(today: date | None = None) -> list[tuple[dict, date]]:
    """Holidays on today that have a reward, with the day this time round started."""
    today = today or datetime.now(db.tz()).date()
    out = []
    for e in fwshow.calendar():
        if not e["enabled"] or not e["reward"]["items"]:
            continue
        for start in fwshow._starts(e, today):
            first, last = window(e, start)
            if first <= today <= last:
                out.append((e, start))
                break
    return out


def window(e: dict, start: date) -> tuple[date, date]:
    """The first and last day the reward is given, for the holiday starting on `start`."""
    r = e["reward"]
    return start - timedelta(days=r.get("before", 0)), start + timedelta(days=e["days"] - 1 + r.get("after", 0))


def _say(items: list[dict]) -> str:
    return ", ".join(f"{x['count']} {x.get('name') or x['item'].split(':', 1)[-1].replace('_', ' ')}" for x in items)


async def tick(srv, online: list[str]) -> int:
    """Give this holiday's reward to everyone on who hasn't had it yet. Returns how many got it."""
    if not online or not srv.is_java or not srv.rcon_conf():
        return 0
    todo = active()
    if not todo:
        return 0
    given = settings_store.load().get(SECTION) or {}
    n, changed = 0, False
    for e, start in todo:
        key = f"{e['id']}:{start.isoformat()}:{srv.id}"
        had = set(given.get(key) or [])
        for name in online:
            if name.lower() in had:
                continue
            had.add(name.lower())
            given[key] = sorted(had)
            changed = True
            settings_store.save_section(SECTION, given)          # first, so a hiccup can't give it twice
            r = e["reward"]
            try:
                for item in r["items"]:
                    await challenges.award(srv, name, item, f"{e['name']} reward")
                msg = r["message"] or f"{e['name']}! A present for being here"
                await srv.rcon(f"tellraw {name} " + component([("🎁 ", "gold"), (msg, "yellow"), (f": {_say(r['items'])}", "white")]))
                n += 1
            except Exception as ex:                               # offline again: the prize waits for their next join
                log.info("holiday reward for %s on %s: %s", name, srv.id, ex)
    if changed:
        cutoff = (datetime.now(db.tz()).date() - timedelta(days=KEEP_DAYS)).isoformat()
        settings_store.save_section(SECTION, {k: v for k, v in given.items() if k.split(":")[1] >= cutoff})
    return n


def describe(e: dict) -> str:
    return _say(e["reward"]["items"]) if e["reward"]["items"] else ""

