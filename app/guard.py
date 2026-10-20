"""Bedtime mode and screen-time enforcement (runs every few seconds in the recorder).

Bedtime (per server): in-game warnings before bedtime, then save and disconnect
everyone not on the exempt list. Anyone who joins before wake-up time is
disconnected again within seconds.

Screen time (all servers): when a player's daily limit is set to "warn then
disconnect", they get an in-game warning when they pass it, then are
disconnected after a grace period, and again if they rejoin that day.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta

from . import auth, db, notify
from . import servers as S
from .control import component
from .rcon import RconError

log = logging.getLogger("solstone.guard")
DEFAULT_BEDTIME = {"enabled": False, "start": "21:00", "end": "07:00", "days": list(range(7)),
                   "warn_minutes": [15, 5, 1], "exempt": [], "message": ""}


def _hm(s: str) -> int:
    h, m = str(s).split(":")[:2]
    return (int(h) % 24) * 60 + int(m) % 60


def bedtime_config(srv: S.Server) -> dict:
    return {**DEFAULT_BEDTIME, **(srv.settings.get("bedtime") or {})}


def validate_bedtime(raw: dict) -> dict:
    cfg = {**DEFAULT_BEDTIME}
    cfg["enabled"] = bool(raw.get("enabled"))
    for k in ("start", "end"):
        v = str(raw.get(k) or DEFAULT_BEDTIME[k])
        _hm(v)  # raises on nonsense
        cfg[k] = f"{_hm(v) // 60:02d}:{_hm(v) % 60:02d}"
    cfg["days"] = sorted({int(d) for d in raw.get("days", DEFAULT_BEDTIME["days"]) if 0 <= int(d) <= 6})
    cfg["warn_minutes"] = sorted({int(m) for m in raw.get("warn_minutes", DEFAULT_BEDTIME["warn_minutes"]) if 0 < int(m) <= 120},
                                 reverse=True)
    cfg["exempt"] = sorted({str(n) for n in raw.get("exempt", []) if re.fullmatch(r"[A-Za-z0-9_]{1,16}", str(n))}, key=str.lower)
    cfg["message"] = " ".join(str(raw.get("message") or "").split())[:120]
    return cfg


def bedtime_state(cfg: dict, now: datetime) -> tuple[str, float, date] | None:
    """("active", 0, night) during bedtime; ("before", seconds_until, night) earlier the same day."""
    start, end = _hm(cfg["start"]), _hm(cfg["end"])
    if start == end or not cfg.get("days"):
        return None
    days = set(cfg["days"])
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


def _fmt_clock(hm: str) -> str:
    return datetime(2000, 1, 1, _hm(hm) // 60, _hm(hm) % 60).strftime("%I:%M %p").lstrip("0")


async def _say(srv: S.Server, who: str, parts: list[tuple[str, str | None]]) -> None:
    await srv.rcon(f"tellraw {who} {component(parts)}")


async def tick(servers: list[S.Server]) -> None:
    now = datetime.now(db.tz())
    ncfg = notify.get_config()
    enforce_limits = ncfg.get("limit_action") == "kick" and ncfg["limits"]
    totals: dict[str, int] = {}
    if enforce_limits:
        for srv in servers:
            for name, secs in db.daily_playtime(srv.id, 1)[0]["players"].items():
                totals[name.lower()] = totals.get(name.lower(), 0) + secs

    for srv in servers:
        if not srv.is_java or not srv.rcon_conf():
            continue
        cfg = bedtime_config(srv)
        st = bedtime_state(cfg, now) if cfg["enabled"] else None
        if not st and not enforce_limits:
            continue
        try:
            online, source = await S.online_players(srv)
            if source != "rcon":
                continue
            if st:
                await _bedtime(srv, cfg, st, online)
            if enforce_limits and online:
                await _limits(srv, ncfg, totals, online, now)
        except RconError as e:
            log.debug("guard skipped %s: %s", srv.id, e)


async def _bedtime(srv: S.Server, cfg: dict, st: tuple, online: list[str]) -> None:
    kind, secs_left, night = st
    exempt = {n.lower() for n in cfg["exempt"]}
    if kind == "before":
        due = [w for w in cfg["warn_minutes"] if secs_left <= w * 60]
        if due and online:
            w = min(due)
            # Mark this and any larger warnings as sent so a late start doesn't fire them all at once.
            fresh = [db.alert_once(f"bed:{srv.id}:{night}:{m}") for m in due]
            if fresh[due.index(w)]:
                await _say(srv, "@a", [("Bedtime ", "gold"), (f"in {w} minute{'s' if w != 1 else ''}. Find a safe spot!", None)])
        return
    targets = [n for n in online if n.lower() not in exempt]
    if db.alert_once(f"bedsave:{srv.id}:{night}"):
        if online:
            await _say(srv, "@a", [("Bedtime! ", "gold"), ("Saving the world. Good night!", None)])
        await srv.rcon("save-all")
    message = cfg["message"] or f"Bedtime! The server opens again at {_fmt_clock(cfg['end'])}."
    for name in targets:
        await srv.rcon(f"kick {name} {message}")
        auth.audit("Bedtime", srv.id, "kick", name, message)


async def _limits(srv: S.Server, ncfg: dict, totals: dict[str, int], online: list[str], now: datetime) -> None:
    grace = int(ncfg.get("limit_grace_minutes", 5))
    today = now.date().isoformat()
    for name in online:
        key = name.lower()
        limit = ncfg["limits"].get(key)
        if not limit or totals.get(key, 0) < limit * 60:
            continue
        warn_key = f"limitwarn:{key}:{today}"
        if db.alert_once(warn_key):
            await _say(srv, name, [("Screen time: ", "gold"),
                                   (f"you've reached today's limit. You'll be disconnected in {grace} minute{'s' if grace != 1 else ''}.", None)])
            continue
        warned = db.q("SELECT ts FROM alerts WHERE key=?", (warn_key,))
        if warned and now.timestamp() - warned[0]["ts"] >= grace * 60:
            msg = "You've reached today's screen-time limit. See you tomorrow!"
            await srv.rcon(f"kick {name} {msg}")
            auth.audit("Screen time", srv.id, "kick", name, msg)
