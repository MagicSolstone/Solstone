"""Push notifications to ntfy and/or Discord when things happen on a server."""
from __future__ import annotations

import asyncio
import logging
import os

import httpx

from . import settings_store

log = logging.getLogger("lodestone.notify")

EVENT_TYPES = ["join", "leave", "death", "advancement", "server", "backup"]
DEFAULT_EVENTS = ["join"]
TAGS = {"join": "green_circle", "leave": "wave", "death": "skull", "advancement": "trophy", "server": "gear",
        "backup": "floppy_disk", "screen_time": "hourglass", "digest": "bar_chart"}


def get_config() -> dict:
    stored = settings_store.load().get("notify", {})
    return {
        "ntfy_url": stored.get("ntfy_url") or os.getenv("NTFY_URL", ""),
        "ntfy_token": stored.get("ntfy_token") or os.getenv("NTFY_TOKEN", ""),
        "discord_webhook": stored.get("discord_webhook") or os.getenv("DISCORD_WEBHOOK_URL", ""),
        "events": stored.get("events", DEFAULT_EVENTS),
        "quiet_start": stored.get("quiet_start", ""),  # "22:00" -> no pushes until quiet_end
        "quiet_end": stored.get("quiet_end", ""),
        # player name (lowercase) -> daily limit in minutes
        "limits": {k.lower(): int(v) for k, v in (stored.get("limits") or {}).items() if str(v).isdigit() and int(v) > 0},
        "digest_enabled": bool(stored.get("digest_enabled", False)),
        "digest_day": int(stored.get("digest_day", 6)),     # 0 = Monday ... 6 = Sunday
        "digest_hour": int(stored.get("digest_hour", 18)),
    }


def public_config() -> dict:
    c = get_config()
    return {
        "ntfy_url": c["ntfy_url"],
        "ntfy_token_set": bool(c["ntfy_token"]),
        "discord_webhook_set": bool(c["discord_webhook"]),
        "events": c["events"],
        "quiet_start": c["quiet_start"],
        "quiet_end": c["quiet_end"],
        "event_types": EVENT_TYPES,
        "limits": c["limits"],
        "digest_enabled": c["digest_enabled"],
        "digest_day": c["digest_day"],
        "digest_hour": c["digest_hour"],
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
    if not (c["quiet_start"] and c["quiet_end"]):
        return False
    from datetime import datetime

    from .db import tz
    try:
        now = datetime.now(tz()).strftime("%H:%M")
    except Exception:
        return False
    s, e = c["quiet_start"], c["quiet_end"]
    return (s <= now < e) if s <= e else (now >= s or now < e)


async def send(title: str, message: str, tag: str = "video_game", force: bool = False) -> list[str]:
    """Send to every configured channel. Returns error strings (empty = all good)."""
    c = get_config()
    if not force and _in_quiet_hours(c):
        return []
    errors: list[str] = []
    async with httpx.AsyncClient(timeout=8) as client:
        jobs = []
        if c["ntfy_url"]:
            headers = {"Title": title.encode("utf-8"), "Tags": tag}
            if c["ntfy_token"]:
                headers["Authorization"] = f"Bearer {c['ntfy_token']}"
            jobs.append(("ntfy", client.post(c["ntfy_url"], content=message.encode("utf-8"), headers=headers)))
        if c["discord_webhook"]:
            jobs.append(("Discord", client.post(c["discord_webhook"], json={"username": "Lodestone",
                                                                             "content": f"**{title}**\n{message}"})))
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


def maybe_notify(etype: str, server_name: str, message: str) -> None:
    """Fire-and-forget notification if this event type is enabled."""
    c = get_config()
    if etype not in c["events"] or not (c["ntfy_url"] or c["discord_webhook"]):
        return
    try:
        asyncio.get_running_loop().create_task(send(server_name, message, TAGS.get(etype, "video_game")))
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
