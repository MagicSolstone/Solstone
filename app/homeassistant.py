"""Home Assistant: everything about the servers at one address, for a dashboard (Manage → Solstone → Home Assistant).

An admin makes a key (shown once; only its hash is kept). Home Assistant asks GET /api/ha/status with it
(Authorization: Bearer <key>) and gets every server Solstone shows: up or not, who's on, TPS, CPU, memory, uptime,
today's play, backups, the full copy, the Xbox friend, and anyone asking to join. The key can only read this: it
can't sign in, change anything, or see anything else. With "names" off, player names are left out (counts only).
The page also writes the Home Assistant settings to paste (configuration.yaml's rest: sensors), one set per server.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from . import auth, settings_store
from . import servers as S

SECTION = "ha_keys"              # {id: {"name", "hash", "names", "created", "last_used"}}
PREFIX = "sol_ha_"
CACHE_SECS = 10                  # Home Assistant asks every 30 s or so; several keys share one answer
router = APIRouter()
_cache: dict[bool, tuple[float, dict]] = {}


# ------------------------------------------------------------------ keys
def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def keys() -> dict[str, dict]:
    return dict(settings_store.load().get(SECTION) or {})


def public_keys() -> list[dict]:
    return [{"id": k, "name": v.get("name", ""), "names": bool(v.get("names")), "created": v.get("created"),
             "last_used": v.get("last_used"), "hint": v.get("hint", "")} for k, v in keys().items()]


def make_key(name: str, names: bool) -> tuple[str, str]:
    """A new key: (its id, the key itself, which is shown once and never kept)."""
    key = PREFIX + secrets.token_urlsafe(32)
    kid = secrets.token_hex(6)
    data = keys()
    data[kid] = {"name": (name or "Home Assistant").strip()[:60], "hash": _hash(key), "names": bool(names),
                 "created": time.time(), "last_used": None, "hint": key[-4:]}
    settings_store.save_section(SECTION, data)
    return kid, key


def remove_key(kid: str) -> bool:
    data = keys()
    if data.pop(kid, None) is None:
        return False
    settings_store.save_section(SECTION, data)
    return True


def set_names(kid: str, names: bool) -> bool:
    data = keys()
    if kid not in data:
        return False
    data[kid]["names"] = bool(names)
    settings_store.save_section(SECTION, data)
    return True


def check(key: str) -> dict | None:
    """The key's settings if it's one of ours (compared in constant time), noting when it was last used."""
    if not key or not key.startswith(PREFIX):
        return None
    h = _hash(key)
    data = keys()
    for kid, v in data.items():
        if hmac.compare_digest(v.get("hash", ""), h):
            if not v.get("last_used") or time.time() - v["last_used"] > 300:       # (not every 30 s)
                v["last_used"] = time.time()
                settings_store.save_section(SECTION, data)
            return {"id": kid, **v}
    return None


def _key_from(request: Request) -> str:
    a = request.headers.get("authorization") or ""
    if a.lower().startswith("bearer "):
        return a[7:].strip()
    return request.headers.get("x-solstone-key") or request.query_params.get("key") or ""


# ------------------------------------------------------------------ what Home Assistant gets
def slug(name: str, taken: set[str]) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "server"
    if s[0].isdigit():
        s = "s_" + s
    out, n = s, 2
    while out in taken:
        out, n = f"{s}_{n}", n + 1
    taken.add(out)
    return out


def _iso(ts: float | None) -> str | None:
    if not ts:
        return None
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")


async def build(names: bool) -> dict:
    """Every server Solstone shows (hidden ones aren't), keyed by a short name for Home Assistant's templates."""
    import asyncio

    from . import db, remote, site, xboxwatch
    from . import main as M
    from .recorder import parse_mem_mb, recorder
    hit = _cache.get(names)
    if hit and time.time() - hit[0] < CACHE_SECS:
        return hit[1]
    await S.registry.refresh()
    shown = [s for s in S.registry.servers.values() if not s.settings.get("hidden")]
    summaries = await asyncio.gather(*(S.server_summary(s) for s in shown), return_exceptions=True)
    taken: set[str] = set()
    out: dict[str, dict] = {}
    for srv, summ in zip(shown, summaries, strict=True):
        key = slug(srv.display_name, taken)
        if isinstance(summ, Exception):
            out[key] = {"id": srv.id, "name": srv.display_name, "online": False, "error": str(summ)}
            continue
        running = bool(summ["running"])
        perf = summ.get("perf") or {}
        today = db.daily_playtime(srv.id, 1)[0]["players"] if names else {}
        b = summ.get("backup") or {}
        latest = (b.get("latest") or {}) if b.get("found") else {}
        row = {
            "id": srv.id, "name": srv.display_name, "online": running,
            "players_online": len(summ["online"]) if running else 0, "players_max": summ.get("max_players"),
            "tps": perf.get("tps") if running else None, "mspt": perf.get("mspt") if running else None,
            "cpu": round(float(summ["cpu"]), 1) if running and summ.get("cpu") is not None else None,
            "cpu_cores": summ.get("cpu_cores"),
            "mem_mb": parse_mem_mb(summ.get("mem")) if running else None,
            "mem_percent": summ.get("mem_percent") if running else None,
            "uptime_7d": round(u * 100, 1) if (u := M._uptime(srv.id, 7)) is not None else None,
            "up_since": _iso(M._up_since(srv.id, summ.get("started"))) if running else None,
            "version": summ.get("version"), "loader": summ.get("loader"),
            "players_today": M._today(srv.id).get("players", 0),
            "today": M._today(srv.id),
            "backup_last": _iso(latest.get("ts")), "backup_overdue": bool(b.get("found") and b.get("stale")),
            "recorder_error": recorder.status(srv.id).get("error"),
        }
        if names:
            row["players"] = sorted(summ["online"]) if running else []
            row["played_today_minutes"] = {n: round(s / 60) for n, s in sorted(today.items()) if s >= 30}
        if srv.settings.get("join_xbox"):
            x = xboxwatch.status(srv.id, running, True) or {}
            row["xbox"] = x.get("state")
            row["xbox_ok"] = x.get("state") == "ok"
        if srv.remote and (m := remote.mirror(srv.id)):
            fc = m.backup_status()
            last = fc.get("last") or {}
            row["full_copy"] = {"on": bool(fc.get("on")), "running": bool(fc.get("running")), "ok": last.get("ok"),
                                "finished": _iso(last.get("finished")), "next": _iso(fc.get("next"))}
            row["full_copy_ok"] = bool(last.get("ok")) if last.get("finished") else None
            row["full_copy_last"] = _iso(last.get("finished"))
        out[key] = row
    data = {"solstone": {"version": M.VERSION, "time": _iso(time.time())},
            "join_requests": len(site.join_requests()),
            "players_online": sum(r.get("players_online") or 0 for r in out.values()),
            "servers": out}
    _cache[names] = (time.time(), data)
    return data


# ------------------------------------------------------------------ Home Assistant's settings, to paste
def yaml(status: dict, base: str) -> str:
    """configuration.yaml's rest: sensors for every server, reading the status address once for all of them."""
    def q(s: str) -> str:
        return '"' + s.replace('"', "'") + '"'
    lines = ["# Solstone for Home Assistant: add this to configuration.yaml (if you already have a rest: section,",
             "# put the - resource: part under it), put the key in secrets.yaml as shown, and restart Home Assistant.",
             "rest:",
             f"  - resource: {base.rstrip('/')}/api/ha/status",
             "    headers:",
             "      Authorization: !secret solstone_auth",
             "    scan_interval: 30",
             "    timeout: 20",
             "    sensor:",
             "      - name: Solstone players online",
             "        unique_id: solstone_players_online",
             '        value_template: "{{ value_json.players_online }}"',
             "        unit_of_measurement: players",
             "        state_class: measurement",
             "      - name: Solstone asking to join",
             "        unique_id: solstone_join_requests",
             '        value_template: "{{ value_json.join_requests }}"',
             "        icon: mdi:account-question"]
    binary: list[str] = []
    for key, s in status["servers"].items():
        n = s["name"]
        v = f"value_json.servers.{key}"

        def sensor(label, field, unit=None, cls=None, icon=None, nullable=True, attrs=None, measure=True, n=n, key=key, v=v):
            lines.extend([f"      - name: {q(n + ' ' + label)}", f"        unique_id: solstone_{key}_{field}",
                          f'        value_template: "{{{{ {v}.{field} }}}}"'])
            if nullable:
                lines.append(f'        availability: "{{{{ {v}.{field} is not none }}}}"')
            if unit:
                lines.append(f"        unit_of_measurement: {q(unit)}")
            if cls:
                lines.append(f"        device_class: {cls}")
            if measure and unit:
                lines.append("        state_class: measurement")
            if icon:
                lines.append(f"        icon: {icon}")
            if attrs:
                lines.extend([f'        json_attributes_path: "$.servers.{key}"', f"        json_attributes: [{', '.join(attrs)}]"])

        attrs = ["players", "players_max", "played_today_minutes"] if "players" in s else ["players_max"]
        sensor("players online", "players_online", "players", icon="mdi:account-group", nullable=False, attrs=attrs)
        sensor("TPS", "tps", "TPS", icon="mdi:speedometer")
        sensor("tick time", "mspt", "ms", icon="mdi:timer-outline")
        sensor("CPU", "cpu", "%", icon="mdi:cpu-64-bit")
        sensor("memory", "mem_mb", "MB", cls="data_size")
        sensor("uptime 7 days", "uptime_7d", "%", icon="mdi:percent")
        sensor("up since", "up_since", cls="timestamp")
        sensor("players today", "players_today", "players", icon="mdi:calendar-account", nullable=False, attrs=["today"])
        sensor("version", "version", icon="mdi:minecraft", measure=False)
        if s.get("backup_last") is not None or "backup_overdue" in s:
            sensor("last backup", "backup_last", cls="timestamp")
        if "full_copy" in s:
            sensor("last full copy", "full_copy_last", cls="timestamp", attrs=["full_copy"])
        binary.extend([f"      - name: {q(n + ' online')}", f"        unique_id: solstone_{key}_online",
                       f'        value_template: "{{{{ {v}.online }}}}"', "        device_class: connectivity"])
        binary.extend([f"      - name: {q(n + ' backup overdue')}", f"        unique_id: solstone_{key}_backup_overdue",
                       f'        value_template: "{{{{ {v}.backup_overdue }}}}"', "        device_class: problem"])
        if "xbox_ok" in s:
            binary.extend([f"      - name: {q(n + ' Xbox friend')}", f"        unique_id: solstone_{key}_xbox",
                           f'        value_template: "{{{{ {v}.xbox_ok }}}}"', "        device_class: connectivity"])
        if "full_copy" in s:
            binary.extend([f"      - name: {q(n + ' full copy problem')}", f"        unique_id: solstone_{key}_full_copy_problem",
                           f'        value_template: "{{{{ {v}.full_copy_ok == false }}}}"', "        device_class: problem"])
    lines.append("    binary_sensor:")
    lines.extend(binary)
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------ routes
@router.get("/api/ha/status")
async def ha_status(request: Request):
    """For Home Assistant (with a key from Manage → Solstone → Home Assistant): every server, in one answer."""
    k = check(_key_from(request))
    if not k:
        return JSONResponse({"detail": "A Home Assistant key from Solstone is needed (Authorization: Bearer ...)"}, status_code=401)
    return JSONResponse(await build(bool(k.get("names"))), headers={"Cache-Control": "no-store"})


@router.get("/api/manage/ha")
async def ha_keys(request: Request):
    from . import main as M
    auth.require_admin(request)
    return {"keys": public_keys(), "base": M._public_base(request)}


@router.post("/api/manage/ha/keys")
async def ha_new_key(request: Request):
    from . import main as M
    user = auth.require_admin(request)
    body = await M._body(request)
    kid, key = make_key(str(body.get("name") or ""), bool(body.get("names", True)))
    auth.audit(user, None, "ha_key_made", f"{body.get('name') or 'Home Assistant'} (…{key[-4:]})")
    return {"id": kid, "key": key, "keys": public_keys()}


@router.put("/api/manage/ha/keys/{kid}")
async def ha_key_names(kid: str, request: Request):
    from . import main as M
    auth.require_admin(request)
    body = await M._body(request)
    if not set_names(kid, bool(body.get("names"))):
        raise HTTPException(404, "No such key")
    _cache.clear()
    return {"keys": public_keys()}


@router.delete("/api/manage/ha/keys/{kid}")
async def ha_remove_key(kid: str, request: Request):
    user = auth.require_admin(request)
    if not remove_key(kid):
        raise HTTPException(404, "No such key")
    auth.audit(user, None, "ha_key_removed", kid)
    return {"keys": public_keys()}


@router.get("/api/manage/ha/yaml")
async def ha_yaml(request: Request, base: str = "", names: bool = True):
    from . import main as M
    auth.require_admin(request)
    base = base.strip() or M._public_base(request)
    if not re.fullmatch(r"https?://[^\s\"'#]+", base):
        raise HTTPException(400, "The address Home Assistant uses starts with http:// or https://")
    status = await build(names)
    return {"yaml": yaml(status, base), "servers": [{"key": k, "name": v["name"]} for k, v in status["servers"].items()],
            "base": base}
