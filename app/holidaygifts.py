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
WHEN = "holiday_reward_times"          # {the same key: {name: when it was given (a timestamp)}}: for "Who's had it"
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
            times = settings_store.load().get(WHEN) or {}
            times.setdefault(key, {})[name.lower()] = round(datetime.now(db.tz()).timestamp())
            settings_store.save_section(WHEN, times)
            r = e["reward"]
            try:
                got = [item for item in r["items"]               # no room: it waits, and they're told (challenges.py)
                       if await challenges.award(srv, name, item, f"{e['name']} reward", note=f"Here's your {e['name']} reward!")]
                if got:
                    await say(srv, name, e, got)
                    n += 1
            except Exception as ex:                               # offline again: the prize waits for their next join
                log.info("holiday reward for %s on %s: %s", name, srv.id, ex)
    if changed:
        cutoff = (datetime.now(db.tz()).date() - timedelta(days=KEEP_DAYS)).isoformat()
        settings_store.save_section(SECTION, {k: v for k, v in given.items() if k.split(":")[1] >= cutoff})
        times = settings_store.load().get(WHEN) or {}
        settings_store.save_section(WHEN, {k: v for k, v in times.items() if k.split(":")[1] >= cutoff})
    return n


def given_to(event_id: str) -> list[dict]:
    """Who's had this event's reward (admins only see it): each time round, each server, newest first. `waiting`: it's
    theirs, but hasn't fitted in their inventory yet (it arrives when there's room)."""
    from . import servers as S
    d = settings_store.load()
    given, times = d.get(SECTION) or {}, d.get(WHEN) or {}
    e = next((x for x in fwshow.calendar() if x["id"] == event_id), None)
    why = f"{e['name']} reward" if e else ""
    held = {(g["server"], g["player"].lower()) for g in challenges._load()["gifts"] if g.get("why") == why}
    out = []
    for key, names in given.items():
        eid, start, sid = key.split(":", 2)
        if eid != event_id or not names:
            continue
        srv = S.registry.servers.get(sid)
        shown = {p["name"].lower(): p["name"] for p in S.known_players(srv).values() if p.get("name")} if srv else {}
        when = times.get(key) or {}
        people = [{"name": shown.get(n, n), "when": when.get(n), "waiting": (sid, n) in held} for n in names]
        people.sort(key=lambda p: (-(p["when"] or 0), p["name"].lower()))
        out.append({"start": start, "server": sid, "server_name": srv.display_name if srv else sid, "players": people})
    out.sort(key=lambda r: (r["start"], r["server_name"]), reverse=True)
    return out


async def say(srv, name: str, e: dict, items: list[dict]) -> None:
    """The reward's message in the game: the admin's own (with & colour codes), then what they got."""
    from . import welcome
    msg = e["reward"]["message"]
    if not msg:
        await srv.rcon(f"tellraw {name} " + component([("★ ", "gold"), (f"{e['name']}! A present for being here", "yellow"), (f": {_say(items)}", "white")]))
        return
    for cmd in welcome.commands(name, welcome.fill(msg, name, srv.display_name)):
        await srv.rcon(cmd)
    await srv.rcon(f"tellraw {name} " + component([("★ ", "gold"), (_say(items), "white")]))


def tag(e: dict, start: date) -> dict | None:
    """The reward for the Events page and its banner: the items, its description, and the days it's given."""
    r = e["reward"]
    if not r["items"]:
        return None
    first, last = window(e, start)
    return {"items": [{"item": x["item"], "count": x["count"], "name": x.get("name") or x["item"].split(":", 1)[-1].replace("_", " ").title()}
                      for x in r["items"]],
            "note": r["note"], "first": first.isoformat(), "last": last.isoformat(),
            "when": first.strftime("%a %-d %b") if first == last else f"{first.strftime('%a %-d %b')} to {last.strftime('%a %-d %b')}"}


def rewarded_items() -> set[str]:
    """Every item set as a holiday's reward (their pictures may be shown to anyone)."""
    return {x["item"] for e in fwshow.calendar() for x in e["reward"]["items"]}


def describe(e: dict) -> str:
    return _say(e["reward"]["items"]) if e["reward"]["items"] else ""

