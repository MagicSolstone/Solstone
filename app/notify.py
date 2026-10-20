"""Push notifications to ntfy and/or Discord when things happen on a server."""
from __future__ import annotations

import asyncio
import logging
import os

import httpx

from . import settings_store

log = logging.getLogger("lodestone.notify")

EVENT_TYPES = ["join", "leave", "death", "advancement", "server"]
DEFAULT_EVENTS = ["join"]
TAGS = {"join": "green_circle", "leave": "wave", "death": "skull", "advancement": "trophy", "server": "gear"}


def get_config() -> dict:
    stored = settings_store.load().get("notify", {})
    return {
        "ntfy_url": stored.get("ntfy_url") or os.getenv("NTFY_URL", ""),
        "ntfy_token": stored.get("ntfy_token") or os.getenv("NTFY_TOKEN", ""),
        "discord_webhook": stored.get("discord_webhook") or os.getenv("DISCORD_WEBHOOK_URL", ""),
        "events": stored.get("events", DEFAULT_EVENTS),
        "quiet_start": stored.get("quiet_start", ""),  # "22:00" -> no pushes until quiet_end
        "quiet_end": stored.get("quiet_end", ""),
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
