"""Coming up: everything with a date ahead, in one list. Contests, races and games that are
scheduled (or on right now), birthdays, the fireworks calendar's holidays and their shows,
and announcements counting down to something."""
from __future__ import annotations

from datetime import datetime, timedelta

from . import community, board, challenges, db, fwshow, games, races

DAYS = 90


def _clock(ts: float) -> str:
    return datetime.fromtimestamp(ts, db.tz()).strftime("%I:%M %p").lstrip("0")


def items(server_names: dict[str, str], days: int = DAYS, now: datetime | None = None) -> list[dict]:
    zone = db.tz()
    now = now or datetime.now(zone)
    t, today = now.timestamp(), now.date()
    until = t + days * 86400
    out: list[dict] = []

    def add(at: float, kind: str, emoji: str, title: str, detail: str = "", *, all_day: bool = False, server: str | None = None,
            link: str | None = None, live: bool = False, length: int = 1) -> None:
        out.append({"at": at, "date": datetime.fromtimestamp(at, zone).date().isoformat(), "time": None if all_day else _clock(at),
                    "kind": kind, "emoji": emoji, "title": title, "detail": detail, "server": server_names.get(server or "", None) if server else None,
                    "link": link, "live": live, "days": length, "key": community.event_key(kind, title, at)})

    # contests, races, games: on now, or scheduled ahead
    for c in challenges._load()["items"]:
        if c["server"] not in server_names:
            continue
        label, emoji, unit, _crit, _div = challenges.KINDS.get(c["kind"], ("Contest", "🏆", ("", ""), [], 1))
        link = f"#/s/{c['server']}/challenges"
        if c["state"] == "running":
            add(c.get("started_at") or c["start"], "contest", emoji, c["name"], f"On now · ends at {_clock(c['ends_at'])}", server=c["server"], link=link, live=True)
        elif c["state"] == "scheduled" and c["start"] <= until:
            add(c["start"], "contest", emoji, c["name"], f"{label} · {c['minutes']} minutes", server=c["server"], link=link)
    for r in races._load()["runs"]:
        if r["server"] not in server_names:
            continue
        link = f"#/s/{r['server']}/challenges/races"
        if r["state"] in ("countdown", "running"):
            add(r["start"], "race", "🏁", f"{r['name']} race", "On now", server=r["server"], link=link, live=True)
        elif r["state"] == "scheduled" and r["start"] <= until:
            add(r["start"], "race", "🏁", f"{r['name']} race", f"{len(r['points']) - 2} checkpoints · {r['minutes']} minutes", server=r["server"], link=link)
    for r in games._load()["runs"]:
        if r["server"] not in server_names:
            continue
        name, emoji = games.KINDS.get(r["game"], ("Game", "🎲"))
        link = f"#/s/{r['server']}/challenges/games"
        if r["state"] in games.ACTIVE:
            add(r.get("started") or r["start"], "game", emoji, r["name"] or name, "On now", server=r["server"], link=link, live=True)
        elif r["state"] == "scheduled" and r["start"] <= until:
            add(r["start"], "game", emoji, r["name"] or name, name if (r["name"] or name) != name else "", server=r["server"], link=link)

    cfg = board.config()
    # birthdays
    for b in cfg["birthdays"]:
        bd = board._birthday_on(b, today.year)
        if bd < today:
            bd = board._birthday_on(b, today.year + 1)
        if (bd - today).days <= days:
            at = datetime.combine(bd, datetime.min.time(), zone).timestamp()
            add(at, "birthday", "🎂", f"{b['player']}'s birthday", "Today!" if bd == today else "", all_day=True, live=bd == today)

    # the fireworks calendar: holidays (and the show on the night, if it has one)
    for e in fwshow.calendar():
        if not e["enabled"]:
            continue
        starts = sorted(s for s in fwshow._starts(e, today) if s + timedelta(days=e["days"]) > today and (s - today).days <= days)
        if e["date"]["type"] == "weekly":
            starts = starts[:1]                       # just the next one, not every week
        for s in starts:
            at = datetime.combine(s, datetime.min.time(), zone).timestamp()
            on_now = s <= today < s + timedelta(days=e["days"])
            add(at, "holiday", e["emoji"], e["name"], e["message"], all_day=True, live=on_now, length=e["days"])
            f = e["finale"]
            if f["on"]:
                hh, mm = (int(x) for x in f["time"].split(":"))
                st = datetime.combine(s + timedelta(days=f["day"]), datetime.min.time(), zone).replace(hour=hh, minute=mm).timestamp()
                if st + f["minutes"] * 60 > t:
                    add(st, "show", "🎆", f"{e['name']} fireworks show", f"{f['minutes']} minutes" + (" · with a countdown" if f["countdown"] else ""),
                        live=st <= t < st + f["minutes"] * 60)

    # announcements counting down to something, or starting later
    for it in cfg["items"]:
        if not it["enabled"] or (it["server"] and it["server"] not in server_names):
            continue
        start, end, cd = board.item_window(it)
        when = cd or start
        if when and t - 3600 < when <= until:
            add(when, "note", it["emoji"] or "📣", it["text"], it["detail"], server=it["server"] or None,
                live=bool(cd and cd <= t), link="#/announcements")

    out.sort(key=lambda x: (not x["live"], x["at"]))
    return out

