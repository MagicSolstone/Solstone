"""Admin server control: console, quick actions, player actions, broadcast, power.

Every value that ends up inside a command is validated here (player names,
item ids, numbers, fixed choices) so a quick action can never be turned into a
different command. The free-form console is the one place raw commands go in,
and it's admin-only and audited like everything else.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from pathlib import Path

from fastapi import HTTPException

from . import mcname
from . import servers as S
from .crafty import crafty
from .rcon import RconError

NAME_RE = mcname.NAME_RE
ITEM_RE = re.compile(r"^[a-z0-9_.-]+:[a-z0-9_./-]+$")
CHOICES = {
    "time": ("day", "noon", "night", "midnight"),
    "weather": ("clear", "rain", "thunder"),
    "difficulty": ("peaceful", "easy", "normal", "hard"),
    "gamemode": ("survival", "creative", "adventure", "spectator"),
    "power": ("start_server", "stop_server", "restart_server", "backup_server"),
}
# Game rules people toggle most. Names changed in 1.21.11 (camelCase -> namespaced
# snake_case) and some were renamed, so each has candidates; the server is asked
# which one it knows.
GAME_RULES = [
    ("keep_inventory", "Keep inventory when you die", "bool", ("keepInventory", "minecraft:keep_inventory", "keep_inventory")),
    ("daylight", "Day and night cycle", "bool", ("doDaylightCycle", "minecraft:advance_time", "advance_time")),
    ("weather_cycle", "Weather changes", "bool", ("doWeatherCycle", "minecraft:advance_weather", "advance_weather")),
    ("mob_griefing", "Mobs can break blocks (creepers, endermen)", "bool", ("mobGriefing", "minecraft:mob_griefing", "mob_griefing")),
    ("phantoms", "Phantoms spawn when you don't sleep", "bool", ("doInsomnia", "minecraft:spawn_phantoms", "spawn_phantoms")),
    ("fire_spread", "Fire spreads", "bool", ("doFireTick", "minecraft:fire_spread_radius_around_player", "fire_spread")),
    ("pvp", "Players can hurt each other", "bool", ("pvp", "minecraft:pvp")),
    ("immediate_respawn", "Respawn instantly", "bool", ("doImmediateRespawn", "minecraft:immediate_respawn", "immediate_respawn")),
    ("sleep_percent", "Players needed to sleep (%)", "int", ("playersSleepingPercentage", "minecraft:players_sleeping_percentage", "players_sleeping_percentage")),
]
_ERROR_HINTS = ("unknown", "incorrect", "expected", "<--[here]", "invalid", "error", "no such")
_rule_names: dict[str, dict[str, str]] = {}  # server id -> rule key -> name the server accepts


def check_name(name: str, what: str = "player") -> str:
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise HTTPException(400, f"That doesn't look like a Minecraft {what} name")
    return name


def check_choice(kind: str, value: str) -> str:
    if value not in CHOICES[kind]:
        raise HTTPException(400, f"Unknown {kind}: {value}")
    return value


def clean_text(text: str, limit: int = 256) -> str:
    text = " ".join(str(text or "").split())  # no newlines, collapse whitespace
    if not text:
        raise HTTPException(400, "Type a message first")
    return text[:limit]


def component(parts: list[tuple[str, str | None]]) -> str:
    """A chat component. JSON is valid SNBT, so this works before and after 1.21.5.
    A colour ending in "!" is bold too ("gold!")."""
    def one(t, c):
        bold = bool(c and c.endswith("!"))
        c = (c or "").rstrip("!")
        return {"text": t, **({"color": c} if c else {}), **({"bold": True} if bold else {})}
    comp = [one(t, c) for t, c in parts]
    return json.dumps(comp, ensure_ascii=False)


def _is_error(reply: str | None) -> bool:
    low = (reply or "").lower()
    return any(h in low for h in _ERROR_HINTS)


async def run(srv: S.Server, command: str) -> dict:
    """Run one command. RCON when available (returns output); otherwise Crafty's console input."""
    command = command.strip().lstrip("/")
    if not command or "\n" in command or "\r" in command:
        raise HTTPException(400, "Enter a single command")
    if len(command) > 1000:
        raise HTTPException(400, "That command is too long")
    if srv.rcon_conf():
        try:
            out = await srv.rcon(command)
            return {"command": command, "output": out or "", "via": "rcon", "ok": not _is_error(out)}
        except RconError as e:
            if not srv.crafty:
                raise HTTPException(502, str(e)) from e
    if srv.crafty and crafty.enabled:
        try:
            await crafty.stdin(srv.id, command)
        except Exception as e:
            raise HTTPException(502, f"Crafty couldn't send the command: {e}") from e
        return {"command": command, "output": "", "via": "crafty", "ok": True,
                "note": "Sent through Crafty. The reply appears in the console log."}
    raise HTTPException(409, "Turn on RCON for this server (or connect Crafty) to send commands")


async def run_all(srv: S.Server, commands: list[str]) -> list[dict]:
    return [await run(srv, c) for c in commands]


# ---------------------------------------------------------------- game rules
def _rule_value(reply: str | None) -> str | None:
    if not reply or _is_error(reply):
        return None
    m = re.search(r"(true|false|-?\d+)\s*\.?\s*$", reply.strip(), re.I)
    return m.group(1).lower() if m else None


async def game_rules(srv: S.Server) -> list[dict]:
    if not srv.rcon_conf():
        return []
    known = _rule_names.setdefault(srv.id, {})
    out = []
    for key, label, kind, candidates in GAME_RULES:
        names = [known[key]] if key in known else list(candidates)
        for name in names:
            try:
                value = _rule_value(await srv.rcon(f"gamerule {name}"))
            except RconError:
                return out
            if value is not None:
                known[key] = name
                out.append({"key": key, "label": label, "kind": kind, "name": name,
                            "value": value == "true" if kind == "bool" else int(value)})
                break
    return out


async def set_rule(srv: S.Server, key: str, value) -> list[dict]:
    rule = next((r for r in GAME_RULES if r[0] == key), None)
    if not rule:
        raise HTTPException(400, "Unknown game rule")
    if key not in _rule_names.get(srv.id, {}):
        await game_rules(srv)
    name = _rule_names.get(srv.id, {}).get(key)
    if not name:
        raise HTTPException(409, "This server doesn't have that game rule")
    if rule[2] == "bool":
        v = "true" if value in (True, "true", 1, "1") else "false"
    else:
        try:
            v = str(max(0, min(100, int(value))))
        except (TypeError, ValueError) as e:
            raise HTTPException(400, "Enter a number from 0 to 100") from e
    return await run_all(srv, [f"gamerule {name} {v}"])


# ---------------------------------------------------------------- quick + player actions
async def quick(srv: S.Server, action: str, value: str, sender: str) -> list[dict]:
    if action == "time":
        return await run_all(srv, [f"time set {check_choice('time', value)}"])
    if action == "weather":
        return await run_all(srv, [f"weather {check_choice('weather', value)}"])
    if action == "difficulty":
        return await run_all(srv, [f"difficulty {check_choice('difficulty', value)}"])
    if action == "save":
        return await run_all(srv, ["save-all"])
    raise HTTPException(400, "Unknown action")


async def broadcast(srv: S.Server, message: str, sender: str, on_screen: bool) -> list[dict]:
    msg = clean_text(message)
    cmds = [f"tellraw @a {component([(f'[{sender}] ', 'gold'), (msg, None)])}"]
    if on_screen:
        cmds += ["title @a times 10 70 20", f"title @a title {component([(msg[:60], 'gold')])}"]
    return await run_all(srv, cmds)


async def player_action(srv: S.Server, player: str, action: str, body: dict, sender: str) -> list[dict]:
    p = check_name(player)
    if action == "message":
        return await run_all(srv, [f"tellraw {p} {component([(f'[{sender} → you] ', 'light_purple'), (clean_text(body.get('message', '')), None)])}"])
    if action == "tp_to_player":
        return await run_all(srv, [f"tp {p} {check_name(body.get('target', ''))}"])
    if action == "bring":  # bring someone else to this player
        return await run_all(srv, [f"tp {check_name(body.get('target', ''))} {p}"])
    if action == "tp_spawn":
        w = await asyncio.to_thread(S.world_info, srv)
        sp = w.get("spawn")
        if not sp:
            raise HTTPException(409, "Couldn't find the world spawn")
        dim = sp.get("dimension") or "minecraft:overworld"
        return await run_all(srv, [f"execute in {dim} run tp {p} {int(sp['x'])} {int(sp['y'])} {int(sp['z'])}"])
    if action == "tp_bed":
        uuid = next((u for u, kp in S.known_players(srv).items() if kp["name"].lower() == p.lower()), None)
        data = (await S.live_player(srv, p)) or (S.player_file_data(srv, uuid)[0] if uuid else None)
        r = (data or {}).get("respawn")
        if not r:
            raise HTTPException(409, f"{p} hasn't set a bed or respawn point")
        dim = r.get("dimension") or "minecraft:overworld"
        return await run_all(srv, [f"execute in {dim} run tp {p} {int(r['x'])} {int(r['y']) + 1} {int(r['z'])}"])
    if action == "heal":
        return await run_all(srv, [f"effect give {p} minecraft:instant_health 1 10 true",
                                   f"effect give {p} minecraft:saturation 1 10 true"])
    if action == "gamemode":
        return await run_all(srv, [f"gamemode {check_choice('gamemode', body.get('mode', ''))} {p}"])
    if action == "give":
        item = str(body.get("item", "")).strip().lower()
        if ":" not in item:
            item = f"minecraft:{item}"
        if not ITEM_RE.match(item):
            raise HTTPException(400, "That isn't a valid item id")
        try:
            count = max(1, min(6400, int(body.get("count", 1))))
        except (TypeError, ValueError) as e:
            raise HTTPException(400, "Enter how many to give") from e
        return await run_all(srv, [f"give {p} {item} {count}"])
    if action == "kick":
        reason = clean_text(body.get("reason") or "Kicked by an admin", 120)
        return await run_all(srv, [f"kick {p} {reason}"])
    if action in ("whitelist_add", "whitelist_remove"):
        if mcname.is_bedrock(p):          # Bedrock players are let in by Floodgate's own list, by gamertag (no dot)
            return await run_all(srv, [f"fwhitelist {'add' if action == 'whitelist_add' else 'remove'} {p[1:]}"])
        return await run_all(srv, [f"whitelist {'add' if action == 'whitelist_add' else 'remove'} {p}"])
    if action in ("op", "deop"):
        return await run_all(srv, [f"{action} {p}"])
    raise HTTPException(400, "Unknown player action")


async def power(srv: S.Server, action: str) -> dict:
    check_choice("power", action)
    if not (srv.crafty and crafty.enabled):
        raise HTTPException(409, "Starting and stopping servers needs Crafty connected (CRAFTY_URL and CRAFTY_TOKEN)")
    try:
        await crafty.action(srv.id, action)
    except Exception as e:
        raise HTTPException(502, str(e)) from e
    return {"ok": True}


def _names(path: Path) -> list[str]:
    try:
        return sorted((e.get("name") for e in json.loads(path.read_text()) if e.get("name")), key=str.lower)
    except Exception:
        return []


def whitelist_names(srv: S.Server) -> list[str]:
    return _names(srv.dir / "whitelist.json")


async def whitelist(srv: S.Server) -> dict:
    """Read-only view of whitelist/ops files plus whether the whitelist is on."""
    return {"enabled": srv.props.get("white-list", "false") == "true",
            "whitelist": _names(srv.dir / "whitelist.json"), "ops": _names(srv.dir / "ops.json")}


# ---------------------------------------------------------------- live console
def log_path(srv: S.Server) -> Path:
    p = srv.dir / "logs" / "latest.log"
    if p.is_file() or not srv.crafty:
        return p
    crafty_log = srv.crafty.get("log_path")
    if crafty_log:
        rel = Path(crafty_log)
        parts = rel.parts
        if srv.id in parts:  # /crafty/servers/<id>/logs/latest.log -> <servers dir>/<id>/logs/latest.log
            return srv.dir.joinpath(*parts[parts.index(srv.id) + 1:])
    return p


async def console_stream(srv: S.Server, is_disconnected, backlog: int = 300):
    """Server-sent events: the tail of the server log, then new lines as they're written."""
    path = log_path(srv)

    def head_of() -> bytes:
        try:
            with path.open("rb") as fh:
                return fh.read(128)
        except OSError:
            return b""

    def read_from(offset: int) -> tuple[list[str], int]:
        with path.open("rb") as fh:
            fh.seek(offset)
            chunk = fh.read(1 << 20)
        end = chunk.rfind(b"\n")
        if end < 0:
            return [], offset
        return chunk[: end + 1].decode("utf-8", "replace").splitlines(), offset + end + 1

    def event(payload: dict) -> str:
        return f"data: {json.dumps(payload)}\n\n"

    if not path.is_file():
        yield event({"error": f"Can't read the server log at {path}. Check that Crafty's servers folder is mounted."})
        return
    size = path.stat().st_size
    start = max(0, size - 64 * 1024)
    lines, offset = await asyncio.to_thread(read_from, start)
    if start:
        lines = lines[1:]  # first line is probably partial
    yield event({"lines": lines[-backlog:], "reset": True})
    head = head_of()
    last_ping = time.monotonic()
    while not await is_disconnected():
        await asyncio.sleep(1)
        try:
            size = path.stat().st_size
        except OSError:
            continue
        new_head = head_of()
        if size < offset or (new_head[:64] != head[:64] and len(head) >= 64):
            offset, head = 0, new_head  # log rotated (server restarted)
            yield event({"lines": ["── log restarted ──"], "rotated": True})
        if size > offset:
            lines, offset = await asyncio.to_thread(read_from, offset)
            if lines:
                yield event({"lines": lines})
                last_ping = time.monotonic()
        if time.monotonic() - last_ping > 15:
            yield ": ping\n\n"
            last_ping = time.monotonic()
