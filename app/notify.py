"""Push notifications to ntfy and/or Discord when things happen on a server."""
from __future__ import annotations

import asyncio
import logging
import os
import re

import httpx

from . import settings_store

log = logging.getLogger("solstone.notify")

EVENT_TYPES = ["join", "leave", "death", "advancement", "server", "backup", "blocked", "updates"]
DEFAULT_EVENTS = ["join"]
TAGS = {"join": "green_circle", "leave": "wave", "death": "skull", "advancement": "trophy", "server": "gear",
        "backup": "floppy_disk", "blocked": "no_entry", "screen_time": "hourglass", "digest": "bar_chart", "updates": "arrow_up"}


def get_config() -> dict:
    stored = settings_store.load().get("notify", {})
    return {
        "ntfy_url": stored.get("ntfy_url") or os.getenv("NTFY_URL", ""),
        "ntfy_token": stored.get("ntfy_token") or os.getenv("NTFY_TOKEN", ""),
        "discord_webhook": stored.get("discord_webhook") or os.getenv("DISCORD_WEBHOOK_URL", ""),
        "events": stored.get("events", DEFAULT_EVENTS),
        "quiet_start": stored.get("quiet_start", ""),  # "22:00" -> no pushes until quiet_end
        "quiet_end": stored.get("quiet_end", ""),
        # quiet hours can be switched off without losing the times (older settings: on if both set)
        "quiet_enabled": bool(stored.get("quiet_enabled", bool(stored.get("quiet_start") and stored.get("quiet_end")))),
        # player name (lowercase) -> daily limit in minutes
        "limits": {k.lower(): int(v) for k, v in (stored.get("limits") or {}).items() if str(v).isdigit() and int(v) > 0},
        "digest_enabled": bool(stored.get("digest_enabled", False)),
        "digest_day": int(stored.get("digest_day", 6)),     # 0 = Monday ... 6 = Sunday
        "digest_hour": int(stored.get("digest_hour", 18)),
        "limit_action": stored.get("limit_action", "notify"),   # "notify" or "kick" (warn, then disconnect)
        "limit_grace_minutes": int(stored.get("limit_grace_minutes", 5)),
        # each server: "same" (the choices above), "off" (nothing from it), or "own" (its own events and quiet hours)
        "servers": {sid: _server_cfg(v) for sid, v in (stored.get("servers") or {}).items() if isinstance(v, dict)},
    }


_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _server_cfg(v: dict) -> dict:
    mode = v.get("mode") if v.get("mode") in ("same", "off", "own") else "same"
    return {"mode": mode, "events": [e for e in v.get("events") or [] if e in EVENT_TYPES],
            "quiet_enabled": bool(v.get("quiet_enabled")),
            "quiet_start": v.get("quiet_start") if _TIME.match(str(v.get("quiet_start") or "")) else "",
            "quiet_end": v.get("quiet_end") if _TIME.match(str(v.get("quiet_end") or "")) else ""}


def for_server(c: dict, sid: str | None) -> dict | None:
    """The choices that apply to one server: None means nothing is sent for it."""
    o = c["servers"].get(sid or "")
    if not o or o["mode"] == "same":
        return c
    if o["mode"] == "off":
        return None
    return {**c, "events": o["events"], "quiet_enabled": o["quiet_enabled"], "quiet_start": o["quiet_start"], "quiet_end": o["quiet_end"]}


def public_config() -> dict:
    c = get_config()
    return {
        "ntfy_url": c["ntfy_url"],
        "ntfy_token_set": bool(c["ntfy_token"]),
        "discord_webhook_set": bool(c["discord_webhook"]),
        "events": c["events"],
        "quiet_start": c["quiet_start"],
        "quiet_end": c["quiet_end"],
        "quiet_enabled": c["quiet_enabled"],
        "quiet_now": _in_quiet_hours(c),
        "event_types": EVENT_TYPES,
        "limits": c["limits"],
        "digest_enabled": c["digest_enabled"],
        "digest_day": c["digest_day"],
        "digest_hour": c["digest_hour"],
        "limit_action": c["limit_action"],
        "limit_grace_minutes": c["limit_grace_minutes"],
        "servers": c["servers"],
    }


def save_config(values: dict) -> dict:
    data = settings_store.load()
    cur = data.get("notify", {})
    for k in ("ntfy_url", "ntfy_token", "discord_webhook", "quiet_start", "quiet_end"):
        if k in values:
            v = (values[k] or "").strip()
            if v:
                cur[k] = v
            else:
                cur.pop(k, None)
    if "events" in values and isinstance(values["events"], list):
        cur["events"] = [e for e in values["events"] if e in EVENT_TYPES]
    if "limits" in values and isinstance(values["limits"], dict):
        limits = {}
        for name, mins in values["limits"].items():
            try:
                mins = int(mins)
            except (TypeError, ValueError):
                continue
            if mins > 0:
                limits[str(name).lower()] = min(mins, 24 * 60)
        cur["limits"] = limits
    if values.get("limit_action") in ("notify", "kick"):
        cur["limit_action"] = values["limit_action"]
    if "limit_grace_minutes" in values:
        try:
            cur["limit_grace_minutes"] = max(1, min(30, int(values["limit_grace_minutes"])))
        except (TypeError, ValueError):
            pass
    if "quiet_enabled" in values:
        cur["quiet_enabled"] = bool(values["quiet_enabled"])
    if isinstance(values.get("servers"), dict):
        cur["servers"] = {str(sid)[:64]: _server_cfg(v) for sid, v in list(values["servers"].items())[:50]
                          if isinstance(v, dict) and _server_cfg(v)["mode"] != "same"}
    if "digest_enabled" in values:
        cur["digest_enabled"] = bool(values["digest_enabled"])
    for k, lo, hi in (("digest_day", 0, 6), ("digest_hour", 0, 23)):
        if k in values:
            try:
                cur[k] = max(lo, min(hi, int(values[k])))
            except (TypeError, ValueError):
                pass
    settings_store.save_section("notify", cur)
    return public_config()


def _in_quiet_hours(c: dict) -> bool:
    if not (c.get("quiet_enabled") and c["quiet_start"] and c["quiet_end"]):
        return False
    from datetime import datetime

    from .db import tz
    try:
        now = datetime.now(tz()).strftime("%H:%M")
    except Exception:
        return False
    s, e = c["quiet_start"], c["quiet_end"]
    return (s <= now < e) if s <= e else (now >= s or now < e)


async def send(title: str, message: str, tag: str = "video_game", force: bool = False, sid: str | None = None,
               click: str | None = None) -> list[str]:
    """Send to every configured channel. Returns error strings (empty = all good). sid: the server it's about,
    for that server's own quiet hours (or none at all, if it's switched off)."""
    c = get_config()
    rules = for_server(c, sid) if sid else c
    if not force and (rules is None or _in_quiet_hours(rules)):
        return []
    errors: list[str] = []
    async with httpx.AsyncClient(timeout=8) as client:
        jobs = []
        if c["ntfy_url"]:
            headers = {"Title": title.encode("utf-8"), "Tags": tag}
            if click:                                      # tapping the notification opens this page
                headers["Click"] = click
            if c["ntfy_token"]:
                headers["Authorization"] = f"Bearer {c['ntfy_token']}"
            jobs.append(("ntfy", client.post(c["ntfy_url"], content=message.encode("utf-8"), headers=headers)))
        if c["discord_webhook"]:
            jobs.append(("Discord", client.post(c["discord_webhook"], json={"username": "Solstone",
                                                                             "content": f"**{title}**\n{message}" + (f"\n{click}" if click else "")})))
        if not jobs:
            return ["No notification channel is set up"]
        results = await asyncio.gather(*(j for _, j in jobs), return_exceptions=True)
        for (name, _), r in zip(jobs, results, strict=True):
            if isinstance(r, Exception):
                errors.append(f"{name}: {type(r).__name__}: {r}")
            elif r.status_code >= 300:
                errors.append(f"{name}: HTTP {r.status_code} {r.text[:120]}")
    for e in errors:
        log.warning("Notification failed: %s", e)
    return errors


def maybe_notify(etype: str, server_name: str, message: str, sid: str | None = None) -> None:
    """Fire-and-forget notification if this event type is enabled (for this server)."""
    c = get_config()
    rules = for_server(c, sid)
    if rules is None or etype not in rules["events"] or not (c["ntfy_url"] or c["discord_webhook"]):
        return
    from .config import config
    click = f"{config.public_url}/app#/manage/whitelist" if etype == "blocked" and config.public_url else None
    try:
        asyncio.get_running_loop().create_task(send(server_name, message, TAGS.get(etype, "video_game"), sid=sid, click=click))
    except RuntimeError:
        pass


# ---------------------------------------------------------------- screen time + digest
def _fmt(seconds: float) -> str:
    m = int(seconds // 60)
    h, m = divmod(m, 60)
    return f"{h}h {m}m" if h else f"{m}m"


def screen_time_due(today: dict[str, int], limits: dict[str, int]) -> list[tuple[str, int, int]]:
    """(player, seconds today, limit minutes) for everyone over their limit."""
    return [(name, secs, limits[name.lower()]) for name, secs in today.items()
            if name.lower() in limits and secs >= limits[name.lower()] * 60]


def digest_text(sections: list[tuple[str, dict]]) -> str:
    """sections: (server name, db.week_stats(...)) for each server."""
    from datetime import date
    lines: list[str] = []
    for server_name, st in sections:
        players = sorted(st["players"].items(), key=lambda kv: -kv[1]["seconds"])
        players = [(n, p) for n, p in players if p["seconds"] or p["deaths"] or p["advancements"]]
        if not players:
            continue
        if len(sections) > 1:
            lines.append(f"{server_name}:")
        for name, p in players:
            bits = [_fmt(p["seconds"])]
            if p["deaths"]:
                bits.append(f"{p['deaths']} death{'s' if p['deaths'] != 1 else ''}")
            if p["advancements"]:
                bits.append(f"{p['advancements']} advancement{'s' if p['advancements'] != 1 else ''}")
            lines.append(f"• {name}: " + " · ".join(bits))
        if st.get("together"):
            a, b = st["together"]["players"]
            lines.append(f"Played together most: {a} & {b} ({_fmt(st['together']['seconds'])})")
        if st.get("busiest_day"):
            day = date.fromisoformat(st["busiest_day"]["date"]).strftime("%A")
            lines.append(f"Busiest day: {day} ({_fmt(st['busiest_day']['seconds'])})")
        lines.append("")
    return "\n".join(lines).strip() or "Nobody played this week."
