"""Play time: bedtimes and daily screen-time limits, set in one place (Manage → Play time).

Bedtimes are schedules: each has its days, from and until, and the servers it covers (or all of them), so a
weekend can have a later one. Each person (an account with all its Minecraft names, or a player without an
account) has their own row: whether bedtime applies to them, a daily limit and a weekend one. Limits count every
server and every name the person plays as together.

guard.py enforces this in the game, board.py shows the bedtime banners, recorder.py sends the screen-time
notification. The first time it's opened, the older settings (each server's bedtime, the limits that were in
Notifications) move over by themselves.
"""
from __future__ import annotations

import re
import secrets
from datetime import date, datetime, timedelta

from . import auth, db, notify, settings_store

SECTION = "playtime"
_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
DEFAULTS = {"bedtimes": [], "warn_minutes": [15, 5, 1], "message": "", "people": {},
            "limit_action": "notify", "grace_minutes": 5, "limit_warn": [15, 5]}
WEEKEND = {5, 6}            # Saturday, Sunday (0 is Monday)


def _hm(s: str) -> int:
    h, m = str(s).split(":")[:2]
    return (int(h) % 24) * 60 + int(m) % 60


def _clean_rule(r: dict) -> dict:
    out = {"id": re.sub(r"[^a-z0-9-]", "", str(r.get("id") or ""))[:24] or secrets.token_hex(4),
           "name": " ".join(str(r.get("name") or "").split())[:40] or "Bedtime",
           "enabled": bool(r.get("enabled", True))}
    for k, d in (("start", "21:00"), ("end", "07:00")):
        v = str(r.get(k) or d)
        out[k] = v if _TIME.match(v) else d
    out["days"] = sorted({int(x) for x in r.get("days", range(7)) if str(x).lstrip("-").isdigit() and 0 <= int(x) <= 6})
    sv = r.get("servers", "all")
    out["servers"] = "all" if sv == "all" else sorted({str(s)[:64] for s in (sv or [])})
    return out


def _nums(v, lo: int, hi: int, default: list[int]) -> list[int]:
    try:
        return sorted({int(x) for x in v if lo < int(x) <= hi}, reverse=True)
    except (TypeError, ValueError):
        return default


def _minutes(v) -> int:
    try:
        return max(0, min(24 * 60, int(v or 0)))
    except (TypeError, ValueError):
        return 0


def clean(raw: dict) -> dict:
    cfg = {**DEFAULTS}
    cfg["bedtimes"] = [_clean_rule(r) for r in (raw.get("bedtimes") or [])[:20] if isinstance(r, dict)]
    cfg["warn_minutes"] = _nums(raw.get("warn_minutes", DEFAULTS["warn_minutes"]), 0, 120, DEFAULTS["warn_minutes"])
    cfg["limit_warn"] = _nums(raw.get("limit_warn", DEFAULTS["limit_warn"]), 0, 120, DEFAULTS["limit_warn"])
    cfg["message"] = " ".join(str(raw.get("message") or "").split())[:120]
    cfg["limit_action"] = raw.get("limit_action") if raw.get("limit_action") in ("notify", "kick") else "notify"
    try:
        cfg["grace_minutes"] = max(1, min(30, int(raw.get("grace_minutes", 5))))
    except (TypeError, ValueError):
        cfg["grace_minutes"] = 5
    people = {}
    for key, p in (raw.get("people") or {}).items():
        if not isinstance(p, dict) or not re.fullmatch(r"(u\d+|p:[.a-z0-9_]{1,17})", str(key)):
            continue
        row = {"bedtime": bool(p.get("bedtime", True)), "limit": _minutes(p.get("limit")), "weekend_limit": _minutes(p.get("weekend_limit"))}
        if row != {"bedtime": True, "limit": 0, "weekend_limit": 0}:          # only what differs from the default
            people[str(key)] = row
    cfg["people"] = people
    return cfg


# ---------------------------------------------------------------- people: accounts with their names, or a name alone
def people(known: list[str]) -> list[dict]:
    """Everyone to show a row for: accounts with Minecraft names linked (all their names), then each name that
    has played but isn't anyone's. known: every name seen on the servers."""
    out, taken = [], set()
    for u in auth.list_users():
        names = [p["name"] for p in u["players"]]
        if not names:
            continue
        out.append({"key": f"u{u['id']}", "label": u["shown"], "names": names, "account": True})
        taken |= {n.lower() for n in names}
    for n in sorted(known, key=str.lower):
        if n.lower() not in taken:
            out.append({"key": f"p:{n.lower()}", "label": n, "names": [n], "account": False})
            taken.add(n.lower())
    return out


def row_for(cfg: dict, key: str, names: list[str]) -> dict | None:
    """A person's settings: their own row, or (an account made after a name was given settings) that name's."""
    people = cfg["people"]
    return people.get(key) or next((people[f"p:{n.lower()}"] for n in names if f"p:{n.lower()}" in people), None)


def _who(cfg: dict) -> dict[str, tuple[str, dict]]:
    """Each Minecraft name (lowercase) → (the person's key, their settings)."""
    out = {}
    for u in auth.list_users():
        names = [p["name"] for p in u["players"]]
        row = row_for(cfg, f"u{u['id']}", names)
        for n in names:
            out[n.lower()] = (f"u{u['id']}", row)
    for key, row in cfg["people"].items():
        if key.startswith("p:") and key[2:] not in out:
            out[key[2:]] = (key, row)
    return out


def stays_up(cfg: dict, name: str) -> bool:
    _key, row = _who(cfg).get(name.lower(), (None, None))
    return bool(row) and not row["bedtime"]


def limit_for(row: dict | None, day: date) -> int:
    """Today's limit in minutes for a person (0: none)."""
    if not row:
        return 0
    if day.weekday() in WEEKEND and row.get("weekend_limit"):
        return row["weekend_limit"]
    return row.get("limit") or 0


def totals_by_person(cfg: dict, totals: dict[str, int]) -> dict[str, int]:
    """Seconds played today per person, from seconds per name (lowercase), all names counted together."""
    who = _who(cfg)
    out: dict[str, int] = {}
    for name, secs in totals.items():
        key = who.get(name.lower(), (f"p:{name.lower()}", None))[0]
        out[key] = out.get(key, 0) + secs
    return out


def person_of(cfg: dict, name: str) -> tuple[str, dict | None]:
    return _who(cfg).get(name.lower(), (f"p:{name.lower()}", None))


# ---------------------------------------------------------------- bedtimes
def rules_for(cfg: dict, sid: str) -> list[dict]:
    return [r for r in cfg["bedtimes"] if r["enabled"] and (r["servers"] == "all" or sid in r["servers"])]


def rule_state(rule: dict, now: datetime) -> tuple[str, float, date] | None:
    """("active", 0, night) during this bedtime; ("before", seconds until, night) earlier on one of its days."""
    start, end = _hm(rule["start"]), _hm(rule["end"])
    if start == end or not rule.get("days"):
        return None
    days = set(rule["days"])
    secs = now.hour * 3600 + now.minute * 60 + now.second
    today, yday = now.weekday(), (now.weekday() - 1) % 7
    if start < end:
        if today in days and start * 60 <= secs < end * 60:
            return ("active", 0, now.date())
    else:
        if today in days and secs >= start * 60:
            return ("active", 0, now.date())
        if yday in days and secs < end * 60:
            return ("active", 0, now.date() - timedelta(days=1))
    if today in days and secs < start * 60:
        return ("before", start * 60 - secs, now.date())
    return None


def server_state(cfg: dict, sid: str, now: datetime) -> tuple[str, float, date, dict] | None:
    """The bedtime that matters for a server now: one going on, or else the next one today."""
    best = None
    for r in rules_for(cfg, sid):
        st = rule_state(r, now)
        if not st:
            continue
        if st[0] == "active":
            return (*st, r)
        if best is None or st[1] < best[1]:
            best = (*st, r)
    return best


# ---------------------------------------------------------------- the settings, moved over from where they were
def _migrate() -> dict:
    from . import servers as S
    data = settings_store.load()
    raw: dict = {"bedtimes": [], "people": {}}
    groups: dict[tuple, list[str]] = {}
    exempt: set[str] = set()
    first = None
    for sid, s in (data.get("servers") or {}).items():
        b = s.get("bedtime") if isinstance(s, dict) else None
        if not isinstance(b, dict) or not b.get("enabled"):
            continue
        first = first or b
        groups.setdefault((b.get("start", "21:00"), b.get("end", "07:00"), tuple(b.get("days", range(7)))), []).append(sid)
        exempt |= {str(n).lower() for n in b.get("exempt") or []}
    known = set(S.registry.servers) if S.registry.servers else set()
    for i, ((start, end, days), sids) in enumerate(groups.items()):
        everywhere = known and set(sids) >= known
        raw["bedtimes"].append({"id": f"b{i + 1}", "name": "Bedtime" if len(groups) == 1 else f"Bedtime {i + 1}",
                                "start": start, "end": end, "days": list(days), "servers": "all" if everywhere else sids})
    if first:
        raw["warn_minutes"] = first.get("warn_minutes", DEFAULTS["warn_minutes"])
        raw["message"] = first.get("message", "")
    n = data.get("notify") or {}
    raw["limit_action"] = n.get("limit_action", "notify")
    raw["grace_minutes"] = n.get("limit_grace_minutes", 5)
    name_to_user = {p["name"].lower(): u["id"] for u in auth.list_users() for p in u["players"]}
    rows: dict[str, dict] = {}
    for name, mins in (n.get("limits") or {}).items():
        key = f"u{name_to_user[name.lower()]}" if name.lower() in name_to_user else f"p:{name.lower()}"
        row = rows.setdefault(key, {"bedtime": True, "limit": 0, "weekend_limit": 0})
        row["limit"] = max(row["limit"], _minutes(mins))
    for name in exempt:
        key = f"u{name_to_user[name]}" if name in name_to_user else f"p:{name}"
        rows.setdefault(key, {"bedtime": True, "limit": 0, "weekend_limit": 0})["bedtime"] = False
    raw["people"] = rows
    return clean(raw)


def config() -> dict:
    stored = settings_store.load().get(SECTION)
    if not isinstance(stored, dict):
        cfg = _migrate()
        settings_store.save_section(SECTION, cfg)
        return cfg
    return clean(stored)


def save(raw: dict) -> dict:
    cfg = clean(raw)
    settings_store.save_section(SECTION, cfg)
    return cfg


def over_limit(cfg: dict, totals: dict[str, int], day: date) -> list[tuple[str, int, int]]:
    """(person key, seconds today, limit minutes) for everyone past today's limit."""
    rows = {k: r for _n, (k, r) in _who(cfg).items()}
    return [(key, secs, limit_for(rows.get(key), day)) for key, secs in totals_by_person(cfg, totals).items()
            if limit_for(rows.get(key), day) and secs >= limit_for(rows.get(key), day) * 60]


def label(key: str) -> str:
    if key.startswith("u") and key[1:].isdigit():
        u = auth.get_user(int(key[1:]))
        if u:
            return u.shown
    return key[2:] if key.startswith("p:") else key


def notify_channels() -> bool:
    c = notify.get_config()
    return bool(c["ntfy_url"] or c["discord_webhook"])


def fmt_clock(hm: str) -> str:
    return datetime(2000, 1, 1, _hm(hm) // 60, _hm(hm) % 60).strftime("%I:%M %p").lstrip("0")


def today_totals(server_ids: list[str]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for sid in server_ids:
        for name, secs in db.daily_playtime(sid, 1)[0]["players"].items():
            totals[name.lower()] = totals.get(name.lower(), 0) + secs
    return totals
