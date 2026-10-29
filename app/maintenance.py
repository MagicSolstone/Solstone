"""Planned maintenance: a time when the servers and website will be down on purpose (new hardware, say).

While it's coming up, a banner on every page counts down to it (an announcement Solstone looks after itself). And
because the website itself is off during it, the details are handed ahead of time to the Cloudflare Worker that
shows the "website is down" page (offline_worker.js): it keeps them in Cloudflare's own storage (KV), so visitors
see "Down for maintenance until …" instead of a plain "down" page.
"""
from __future__ import annotations

import secrets
from datetime import datetime

import httpx

from . import board, db, settings_store

BOARD_ID = "maintenance"


def worker_key() -> str:
    """A secret only Solstone and its Worker know, so nobody else can post maintenance notices to the Worker."""
    k = settings_store.load().get("worker_key")
    if not k:
        k = secrets.token_hex(24)
        settings_store.save_section("worker_key", k)
    return k


def current() -> dict | None:
    m = settings_store.load().get("maintenance")
    return m if isinstance(m, dict) and m.get("start") and m.get("end") else None


def _when(v: str) -> str:
    return datetime.fromisoformat(v).strftime("%A %-I:%M %p").replace(":00 ", " ")


def plan(start: str, end: str, message: str) -> dict:
    """Times like 2026-11-01T14:00 (the server's time zone), as the date pickers give them."""
    start, end = board._dt(start), board._dt(end)
    if not start or not end:
        raise ValueError("Pick when it starts and when it ends")
    if end <= start:
        raise ValueError("It has to end after it starts")
    m = {"start": start, "end": end, "message": " ".join(str(message or "").split())[:240]}
    settings_store.save_section("maintenance", m)
    cfg = board.config()
    items = [i for i in cfg["items"] if i["id"] != BOARD_ID]
    items.append({"id": BOARD_ID, "enabled": True, "emoji": "🛠️", "style": "info",
                  "text": "Planned maintenance", "detail": m["message"] or f"The servers and website will be down until {_when(end)}.",
                  "countdown": start, "end": end, "done_text": "Down for maintenance now"})
    board.save({"items": items})
    return m


def clear() -> None:
    settings_store.save_section("maintenance", None)
    cfg = board.config()
    board.save({"items": [i for i in cfg["items"] if i["id"] != BOARD_ID]})


def for_worker(m: dict | None) -> dict:
    if not m:
        return {}
    return {"start": board._ts(m["start"]), "end": board._ts(m["end"]), "message": m["message"],
            "until": _when(m["end"]), "tz": str(db.tz())}


async def push(base: str, m: dict | None) -> str | None:
    """Hand the notice to the Worker in front of the website. None when it took it, else why not."""
    if not base.startswith("https://"):
        return "The website's public address isn't known (set PUBLIC_URL), so the Cloudflare page wasn't told"
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(f"{base}/__solstone/maintenance", json=for_worker(m), headers={"X-Solstone-Key": worker_key()})
    except httpx.HTTPError as e:
        return f"Couldn't reach the Cloudflare page: {e}"
    if r.status_code == 200:
        return None
    if r.status_code == 501:
        return "The Cloudflare Worker has no storage yet: add a KV namespace to it, bound as SOLSTONE (see the steps)"
    return "The Cloudflare Worker didn't take it: download the Worker again and paste it in (it's an older one)"
