"""Server registry (Crafty + folder discovery), world info, mods and players."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import struct
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import settings_store
from .config import config
from .crafty import crafty, parse_player_list
from .nbtutil import load_dat, norm_player, parse_entity_snbt
from .rcon import Rcon, RconError

log = logging.getLogger("solstone.servers")


# ---------------------------------------------------------------- small helpers
class MtimeCache:
    """Cache keyed by (key, mtime) so file reads only happen when files change."""

    def __init__(self) -> None:
        self._d: dict[Any, tuple[float, Any]] = {}

    def get(self, key: Any, path: Path, loader):
        try:
            m = path.stat().st_mtime
        except OSError:
            return None
        hit = self._d.get(key)
        if hit and hit[0] == m:
            return hit[1]
        try:
            val = loader(path)
        except Exception as e:
            log.debug("load failed %s: %s", path, e)
            return hit[1] if hit else None
        self._d[key] = (m, val)
        return val


_cache = MtimeCache()


def read_properties(path: Path) -> dict[str, str]:
    props: dict[str, str] = {}
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            props[k.strip()] = v.strip().replace("\\:", ":").replace("\\=", "=")
    except OSError:
        pass
    return props


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _first_dir(base: Path, *candidates: str) -> Path:
    for c in candidates:
        p = base / c
        if p.is_dir():
            return p
    return base / candidates[0]


def norm_uuid(u: str) -> str:
    u = u.replace("-", "").lower()
    if len(u) == 32:
        return f"{u[:8]}-{u[8:12]}-{u[12:16]}-{u[16:20]}-{u[20:]}"
    return u


# ---------------------------------------------------------------- server model
@dataclass
class Server:
    id: str
    name: str
    dir: Path
    crafty: dict | None = None
    type: str = "minecraft-java"
    _rcon: Rcon | None = field(default=None, repr=False)
    _rcon_backoff: float = 0.0
    rcon_error: str | None = None

    @property
    def props(self) -> dict[str, str]:
        return _cache.get(("props", self.id), self.dir / "server.properties", read_properties) or {}

    @property
    def game(self) -> str:
        """minecraft-java, minecraft-bedrock, hytale, or whatever Crafty calls it.
        Only Java servers get the world/player/RCON features."""
        t = (self.type or "").lower()
        has_props = (self.dir / "server.properties").is_file()
        if "bedrock" in t:
            return "minecraft-bedrock"
        if "hytale" in t or (not has_props and any(self.dir.glob("Hytale*"))):
            return "hytale"
        if has_props or "java" in t or not t:
            return "minecraft-java"
        return t

    @property
    def is_java(self) -> bool:
        return self.game == "minecraft-java"

    @property
    def world_dir(self) -> Path:
        return self.dir / self.props.get("level-name", "world")

    @property
    def settings(self) -> dict:
        return settings_store.server(self.id)

    @property
    def display_name(self) -> str:
        return self.settings.get("display_name") or self.name

    def level(self) -> dict:
        nbt = _cache.get(("level", self.id), self.world_dir / "level.dat", load_dat) or {}
        return nbt.get("Data", nbt)

    @property
    def mc_version(self) -> str | None:
        v = self.level().get("Version")
        if isinstance(v, dict) and v.get("Name"):
            return str(v["Name"])
        if self.crafty and self.crafty.get("_stats", {}).get("version"):
            return str(self.crafty["_stats"]["version"])
        return None

    # ---- RCON
    def rcon_conf(self) -> tuple[str, int, str] | None:
        if not self.is_java:
            return None
        s = self.settings
        p = self.props
        password = s.get("rcon_password") or p.get("rcon.password", "")
        enabled = p.get("enable-rcon", "false").lower() == "true" or s.get("rcon_password")
        if not enabled or not password:
            return None
        port = int(s.get("rcon_port") or p.get("rcon.port", 25575) or 25575)
        host = s.get("rcon_host") or config.default_rcon_host
        return host, port, password

    async def rcon(self, cmd: str, wait: float | None = None) -> str | None:
        """wait: a longer time for the game to answer (whitelist and op look the name up with Mojang or Xbox first).
        Such a command isn't sent twice if it times out, so it can't happen twice."""
        conf = self.rcon_conf()
        if not conf:
            return None
        if time.monotonic() < self._rcon_backoff:
            raise RconError(self.rcon_error or "RCON unavailable (retrying shortly)")
        if self._rcon is None or (self._rcon.host, self._rcon.port, self._rcon.password) != conf:
            if self._rcon:
                await self._rcon.close()
            self._rcon = Rcon(*conf, timeout=config.rcon_timeout)
        try:
            out = await (self._rcon.command(cmd, wait) if wait else self._rcon.command(cmd))
        except RconError as first:
            if wait:
                self.rcon_error = str(first)
                raise
            # A dropped connection is common (the server closes it now and then): reconnect and
            # try once more straight away. Only if that fails too, leave RCON alone for a bit, and
            # not for long, since races and games read positions every second.
            if "password" in str(first) or "Nothing is listening" in str(first):
                self.rcon_error, self._rcon_backoff = str(first), time.monotonic() + 30
                raise
            try:
                out = await self._rcon.command(cmd)
            except RconError as e:
                self.rcon_error = str(e)
                self._rcon_backoff = time.monotonic() + 5
                raise
        self.rcon_error = None
        return out


def _crafty_list_file() -> Path:
    return config.data_dir / "crafty-servers.json"


def _save_crafty_list(listed: list[dict]) -> None:
    keep = [{k: v for k, v in s.items() if not k.startswith("_")} for s in listed if isinstance(s, dict)]
    try:
        f = _crafty_list_file()
        if f.is_file() and json.loads(f.read_text(encoding="utf-8")) == keep:
            return
        f.write_text(json.dumps(keep), encoding="utf-8")
    except (OSError, ValueError):
        pass


def _load_crafty_list() -> list[dict]:
    try:
        data = json.loads(_crafty_list_file().read_text(encoding="utf-8"))
        return [s for s in data if isinstance(s, dict)]
    except (OSError, ValueError):
        return []


class Registry:
    def __init__(self) -> None:
        self.servers: dict[str, Server] = {}
        self._refreshed = 0.0
        self._lock = asyncio.Lock()

    async def refresh(self, force: bool = False) -> None:
        async with self._lock:
            if not force and time.monotonic() - self._refreshed < 20 and self.servers:
                return
            found: dict[str, Server] = {}
            if crafty.enabled:
                listed = await crafty.servers()
                if listed is None:
                    # Crafty is down (or restarting): keep the servers we knew, so pages, links and ids stay put
                    # and show what's on disk; the saved list covers a Solstone restart while Crafty is down.
                    listed = [s.crafty for s in self.servers.values() if s.crafty] or _load_crafty_list()
                    for s in listed:
                        s["_unreachable"] = True
                else:
                    _save_crafty_list(listed)
                for s in listed:
                    sid = str(s.get("server_id"))
                    crafty_path = str(s.get("path", ""))
                    local = config.servers_dir / Path(crafty_path).name
                    if not local.is_dir():
                        # Path may already be valid in this container (same mount layout)
                        local = Path(crafty_path) if Path(crafty_path).is_dir() else local
                    old = self.servers.get(sid)
                    srv = Server(id=sid, name=s.get("server_name") or sid, dir=local,
                                 crafty=s, type=str(s.get("type") or "minecraft-java"))
                    if old:
                        srv._rcon, srv._rcon_backoff, srv.rcon_error = old._rcon, old._rcon_backoff, old.rcon_error
                    found[sid] = srv
            # Folder discovery: any folder with a server.properties not already known
            known_dirs = {s.dir.resolve() for s in found.values() if s.dir.exists()}
            if config.servers_dir.is_dir():
                for d in sorted(config.servers_dir.iterdir()):
                    if d.is_dir() and (d / "server.properties").exists() and d.resolve() not in known_dirs:
                        sid = d.name
                        old = self.servers.get(sid)
                        motd = read_properties(d / "server.properties").get("motd") or d.name
                        srv = Server(id=sid, name=motd if len(motd) < 40 else d.name, dir=d)
                        if old:
                            srv._rcon, srv._rcon_backoff, srv.rcon_error = old._rcon, old._rcon_backoff, old.rcon_error
                        found[sid] = srv
            if config.only_servers:     # this Solstone looks after just these (another one may have the rest)
                found = {k: v for k, v in found.items() if {k.lower(), v.name.lower(), v.dir.name.lower()} & set(config.only_servers)}
            self.servers = found
            self._refreshed = time.monotonic()

    async def get(self, sid: str) -> Server | None:
        await self.refresh()
        srv = self.servers.get(sid)
        if srv is None:
            await self.refresh(force=True)
            srv = self.servers.get(sid)
        return srv


registry = Registry()


# ---------------------------------------------------------------- status
_online_cache: dict[str, tuple[float, tuple[list[str], str]]] = {}


async def online_players(srv: Server) -> tuple[list[str], str]:
    """Return (names, source). Prefers RCON `list`, falls back to Crafty. Kept for a couple of seconds, so a
    page open on many screens at once asks the game once, not once per screen."""
    hit = _online_cache.get(srv.id)
    if hit and time.monotonic() - hit[0] < 2.0:
        return list(hit[1][0]), hit[1][1]
    out = await _online_players(srv)
    _online_cache[srv.id] = (time.monotonic(), out)
    return list(out[0]), out[1]


async def _online_players(srv: Server) -> tuple[list[str], str]:
    stats = await _crafty_stats(srv)
    if srv.crafty and stats is not None and not stats.get("running"):
        return [], "stopped"
    try:
        out = await srv.rcon("list")
        if out is not None:
            # "There are 1 of a max of 20 players online: Tyler"
            names = out.split(":", 1)[1] if ":" in out else ""
            return [n.strip() for n in names.split(",") if n.strip()], "rcon"
    except RconError as e:
        log.debug("rcon list failed for %s: %s", srv.id, e)
    if stats:
        return parse_player_list(stats.get("players")), "crafty"
    return [], "none"


_last_seen_stats: dict[str, dict] = {}       # server id -> the last MOTD, icon and version Crafty could read


async def _crafty_stats(srv: Server) -> dict | None:
    if not srv.crafty:
        return None
    stats = await crafty.stats(srv.id)
    if stats is not None:
        # Crafty's ping of the game fails now and then (it then has no MOTD or icon): keep showing the last ones
        keep = _last_seen_stats.setdefault(srv.id, {})
        for k in ("desc", "icon", "version"):
            if stats.get(k):
                keep[k] = stats[k]
            elif keep.get(k):
                stats[k] = keep[k]
        srv.crafty["_stats"] = stats
    return stats


def _server_icon(srv: Server) -> bool:
    return (srv.dir / "server-icon.png").is_file()


async def server_summary(srv: Server) -> dict:
    stats = await _crafty_stats(srv) or {}
    props = srv.props
    lvl = srv.level()
    online, source = await online_players(srv)
    # None = unknown (no Crafty, or Crafty can't be reached right now)
    running = bool(stats.get("running")) if srv.crafty and stats else None
    rcon = srv.rcon_conf()
    return {
        "id": srv.id,
        "name": srv.display_name,
        "type": srv.type,
        "managed_by_crafty": srv.crafty is not None,
        "crafty_unreachable": bool(srv.crafty and srv.crafty.get("_unreachable")),
        "folder_found": srv.dir.is_dir(),
        "folder": str(srv.dir),
        "running": running,
        "crashed": bool(stats.get("crashed")),
        "started": stats.get("started"),
        "cpu": stats.get("cpu"),
        "mem": _fmt_mem(stats.get("mem")),
        "mem_percent": stats.get("mem_percent"),
        "world_size": stats.get("world_size"),
        "version": srv.mc_version or stats.get("version"),
        "motd": stats.get("desc") or props.get("motd"),
        "port": stats.get("server_port") or props.get("server-port"),
        "max_players": stats.get("max") or _int(props.get("max-players")),
        "online": online,
        "online_source": source,
        "level_name": lvl.get("LevelName") or props.get("level-name"),
        "has_icon": _server_icon(srv) or bool(stats.get("icon")),
        "rcon": {"configured": rcon is not None, "host": rcon[0] if rcon else None,
                 "port": rcon[1] if rcon else None, "error": srv.rcon_error},
        "map_url": srv.settings.get("map_url"),
        "loader": detect_loader(srv) if srv.is_java else None,
        "game": srv.game,
        "game_label": GAME_LABELS.get(srv.game, srv.game.replace("-", " ").replace("_", " ").title()),
        "perf": _latest_perf(srv),
        "backup": _backup(srv),
        "fishing": _fishing_with(srv),
    }


def _backup(srv: Server) -> dict:
    from . import backups
    try:
        return backups.status(srv)
    except Exception as e:
        return {"configured": False, "error": str(e)}


def _latest_perf(srv: Server) -> dict | None:
    from . import db
    rows = db.q("SELECT tps, mspt, ts FROM metrics WHERE server_id=? AND tps IS NOT NULL ORDER BY ts DESC LIMIT 1", (srv.id,))
    if not rows or time.time() - rows[0]["ts"] > 180:
        return None
    return {"tps": rows[0]["tps"], "mspt": rows[0]["mspt"]}


def _fmt_mem(v: Any) -> str | None:
    """Human memory text whether Crafty sent "1.6GB" or a raw byte count."""
    from .recorder import parse_mem_mb
    mb = parse_mem_mb(v)
    if mb is None:
        return v if isinstance(v, str) and v else None
    return f"{mb / 1024:.2f} GB" if mb >= 1024 else f"{mb:.0f} MB"


GAME_LABELS = {"minecraft-java": "Minecraft Java", "minecraft-bedrock": "Minecraft Bedrock", "hytale": "Hytale"}


def _int(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def detect_loader(srv: Server) -> str:
    d = srv.dir
    if (d / ".fabric").is_dir() or any(d.glob("fabric-server-*.jar")):
        return "Fabric"
    if (d / ".quilt").is_dir() or any(d.glob("quilt-server-*.jar")):
        return "Quilt"
    if (d / "libraries" / "net" / "neoforged").is_dir():
        return "NeoForge"
    if (d / "libraries" / "net" / "minecraftforge").is_dir():
        return "Forge"
    if any(d.glob("paper*.jar")) or (d / "plugins").is_dir():
        return "Paper"
    return "Vanilla"


def server_icon_bytes(srv: Server) -> bytes | None:
    p = srv.dir / "server-icon.png"
    if p.is_file():
        return p.read_bytes()
    icon = (srv.crafty or {}).get("_stats", {}).get("icon")
    if icon:
        import base64
        try:
            return base64.b64decode(icon.split(",", 1)[-1])
        except Exception:
            return None
    return None


# ---------------------------------------------------------------- world
_DIM_NAMES = {"region": "minecraft:overworld", "DIM-1": "minecraft:the_nether", "DIM1": "minecraft:the_end"}
_chunk_cache: dict[str, tuple[float, list]] = {}


def _count_chunks(region_dir: Path) -> tuple[int, int]:
    chunks = size = 0
    for f in region_dir.glob("*.mca"):
        try:
            st = f.stat()
            size += st.st_size
            if st.st_size < 8192:
                continue
            with f.open("rb") as fh:
                header = fh.read(4096)
            chunks += sum(1 for i in range(1024) if struct.unpack_from(">I", header, i * 4)[0] != 0)
        except OSError:
            continue
    return chunks, size


def dimensions(srv: Server) -> list[dict]:
    hit = _chunk_cache.get(srv.id)
    if hit and time.monotonic() - hit[0] < 600:
        return hit[1]
    out = []
    w = srv.world_dir
    if w.is_dir():
        for region in sorted(w.glob("**/region")):
            rel = region.relative_to(w)
            if len(rel.parts) > 5:
                continue
            parent = rel.parts[-2] if len(rel.parts) > 1 else "region"
            if len(rel.parts) >= 3 and rel.parts[0] == "dimensions":
                dim_id = f"{rel.parts[1]}:{'/'.join(rel.parts[2:-1])}"
            else:
                dim_id = _DIM_NAMES.get(parent, parent)
            chunks, size = _count_chunks(region)
            if chunks or size:
                out.append({"id": dim_id, "chunks": chunks, "bytes": size})
    _chunk_cache[srv.id] = (time.monotonic(), out)
    return out


def _world_extras(srv: Server) -> dict[str, dict]:
    """Small saved-data files next to level.dat. Newer versions (26.1+) moved things like
    world clocks, weather and game rules out of level.dat into data/minecraft/*.dat."""
    out: dict[str, dict] = {}
    for folder in (srv.world_dir / "data" / "minecraft", srv.world_dir / "data"):
        if not folder.is_dir():
            continue
        for f in sorted(folder.glob("*.dat")):
            try:
                if f.stat().st_size > 2_000_000 or f.name.startswith(("map_", "raids", "chunks", "idcounts")):
                    continue
            except OSError:
                continue
            nbt = _cache.get(("extra", srv.id, str(f)), f, load_dat)
            if isinstance(nbt, dict):
                out[f.stem] = nbt
    return out


def _walk(obj: Any, path: tuple = ()):
    """Yield (path, value) for every leaf. Lists are walked too; a list entry with an
    "id" (e.g. {id: "minecraft:overworld", ticks: ...}) contributes that id to the path."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk(v, path + (str(k),))
    elif isinstance(obj, list) and obj and all(isinstance(x, dict) for x in obj):
        for i, item in enumerate(obj):
            tag = str(item.get("id") or item.get("clock") or item.get("name") or i)
            yield from _walk(item, path + (tag,))
    else:
        yield path, obj


def _num(v: Any) -> int | None:
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        return int(v)
    return None


def _find_key(sources: list[dict], *names: str) -> Any:
    wanted = {n.lower() for n in names}
    for src in sources:
        for path, v in _walk(src):
            if path and path[-1].lower() in wanted:
                return v
    return None


def _clock_ticks(sources: list[dict]) -> int | None:
    """26.1 world clocks: the overworld clock's elapsed ticks, wherever it's stored."""
    best = None
    for src in sources:
        for path, v in _walk(src):
            low = [p.lower() for p in path]
            n = _num(v)
            if n is None or not any("clock" in p for p in low) or not any("overworld" in p for p in low):
                continue
            if low[-1] in ("total_ticks", "ticks", "time", "elapsed", "total_time"):
                return n
            best = best if best is not None else n
    return best


def _game_rules(lvl: dict, extras: dict[str, dict]) -> dict:
    rules = lvl.get("GameRules") or lvl.get("game_rules")
    if rules:
        return rules
    for name, nbt in extras.items():
        if "rule" not in name:
            continue
        node = nbt.get("data", nbt) if isinstance(nbt, dict) else {}
        for _ in range(3):  # descend through single-key wrappers
            if isinstance(node, dict) and len(node) == 1 and isinstance(next(iter(node.values())), dict):
                node = next(iter(node.values()))
        if isinstance(node, dict) and node:
            return node
    return {}


def world_info(srv: Server, with_dimensions: bool = True) -> dict:
    lvl = srv.level()
    props = srv.props
    extras = _world_extras(srv)
    sources = [lvl] + list(extras.values())
    wgs = lvl.get("WorldGenSettings") or {}
    seed = wgs.get("seed", lvl.get("RandomSeed"))
    if seed is None:
        seed = _find_key(list(extras.values()), "seed")
    spawn = None
    if isinstance(lvl.get("spawn"), dict):  # 1.21.5+
        p = lvl["spawn"].get("pos")
        if isinstance(p, list):
            spawn = {"x": p[0], "y": p[1], "z": p[2], "dimension": lvl["spawn"].get("dimension")}
    elif "SpawnX" in lvl:
        spawn = {"x": lvl["SpawnX"], "y": lvl["SpawnY"], "z": lvl["SpawnZ"], "dimension": "minecraft:overworld"}
    rules = _game_rules(lvl, extras)
    datapacks = lvl.get("DataPacks") or {}
    diff = lvl.get("Difficulty")
    diff_name = {0: "peaceful", 1: "easy", 2: "normal", 3: "hard"}.get(diff, props.get("difficulty")) \
        if not isinstance(diff, str) else diff
    if isinstance(lvl.get("difficulty_settings"), dict):
        diff_name = lvl["difficulty_settings"].get("difficulty", diff_name)

    day_time = _num(lvl.get("DayTime"))
    time_source = "file" if day_time is not None else None
    if day_time is None:
        day_time = _clock_ticks(sources)
        time_source = "file" if day_time is not None else "unknown"
    raining = _find_key(sources, "raining")
    thundering = _find_key(sources, "thundering")
    game_time = _num(lvl.get("Time"))
    if game_time is None:
        game_time = _num(_find_key(list(extras.values()), "game_time", "gametime"))
    return {
        "level_name": lvl.get("LevelName") or props.get("level-name", "world"),
        "version": srv.mc_version,
        "data_version": lvl.get("DataVersion"),
        "seed": str(seed) if seed is not None else None,
        "hardcore": bool(lvl.get("hardcore", props.get("hardcore") == "true")),
        "difficulty": diff_name,
        "default_gamemode": props.get("gamemode", "survival"),
        "spawn": spawn,
        "game_time": game_time or 0,
        "day_time": day_time,
        "day": day_time // 24000 + 1 if day_time is not None else None,
        "time_of_day": day_time % 24000 if day_time is not None else None,
        "time_source": time_source,
        "raining": bool(_num(raining)) if raining is not None else None,
        "thundering": bool(_num(thundering)) if thundering is not None else None,
        "last_played": (lvl.get("LastPlayed") or 0) / 1000 or None,
        "allow_commands": bool(lvl.get("allowCommands", 0)),
        "game_rules": {str(k): (str(v) if not isinstance(v, (int, float, bool)) else v) for k, v in rules.items()
                       if not isinstance(v, (dict, list))},
        "datapacks": {"enabled": datapacks.get("Enabled", []), "disabled": datapacks.get("Disabled", [])},
        "dimensions": dimensions(srv) if with_dimensions else [],
        "properties": {k: props[k] for k in ("view-distance", "simulation-distance", "pvp", "spawn-protection",
                                               "white-list", "online-mode", "max-players", "allow-flight",
                                               "level-type") if k in props},
    }


_ERROR_HINTS = ("unknown or incomplete", "incorrect argument", "expected", "<--[here]", "unknown command",
                "invalid", "error", "no such", "can't", "cannot")
_INT = re.compile(r"-?\d+")
_SEED = re.compile(r"Seed:\s*\[?(-?\d+)\]?")
_live_world_cache: dict[str, tuple[float, dict]] = {}
_live_world_raw: dict[str, dict[str, str]] = {}


def _reply_int(out: str | None) -> int | None:
    """The number in a command reply such as "The time is 6000", or None for errors.
    Lenient on wording, because messages change between Minecraft versions."""
    if not out:
        return None
    low = out.lower()
    if any(h in low for h in _ERROR_HINTS):
        return None
    nums = _INT.findall(out.replace(",", ""))
    return int(nums[-1]) if nums else None


async def live_world(srv: Server) -> dict:
    """Ask the running server for the time and seed (works across format changes).

    Pre-26.1: `time query daytime` (ticks since world creation, wraps per day) and
    `time query day`. 26.1+ keeps time in world clocks: `time query time` is the
    overworld clock's elapsed ticks; `time query day` / `... repetitions` report
    the position in, and count of, the day timeline.
    """
    hit = _live_world_cache.get(srv.id)
    if hit and time.monotonic() - hit[0] < 20:
        return hit[1]
    raw: dict[str, str] = {}

    async def ask(cmd: str) -> int | None:
        reply = await srv.rcon(cmd)
        raw[cmd] = (reply or "")[:300]
        return _reply_int(reply)

    out: dict = {}
    try:
        day_time = await ask("time query daytime")
        if day_time is not None:
            days = await ask("time query day")
            out.update(day_time=day_time, day=(days if days is not None else day_time // 24000) + 1,
                       time_of_day=day_time % 24000, time_source="live")
        else:
            ticks = await ask("time query time")
            if ticks is not None:
                out.update(day_time=ticks, day=ticks // 24000 + 1, time_of_day=ticks % 24000, time_source="live")
            else:
                pos = await ask("time query day")
                reps = await ask("time query day repetitions")
                if pos is not None:
                    out.update(day_time=None, day=(reps or 0) + 1, time_of_day=pos % 24000, time_source="live")
        game_time = await ask("time query gametime")
        if game_time is not None:
            out["game_time"] = game_time
        seed_reply = await srv.rcon("seed")
        raw["seed"] = (seed_reply or "")[:120]
        m = _SEED.search(seed_reply or "")
        if m:
            out["seed"] = m.group(1)
    except RconError as e:
        raw["error"] = str(e)
        _live_world_raw[srv.id] = raw
        return {}
    _live_world_raw[srv.id] = raw
    if out.get("time_of_day") is not None:
        out["as_of"] = time.time()          # when the server said it, so pages can count on from there
    _live_world_cache[srv.id] = (time.monotonic(), out)
    return out


def world_debug(srv: Server) -> dict:
    """What Solstone saw while looking for the world time, to paste into a bug report."""
    sources = {"level.dat": srv.level(), **{f"data/{k}.dat": v for k, v in _world_extras(srv).items()}}
    keys = []
    for name, src in sources.items():
        for path, v in _walk(src):
            joined = "/".join(path)
            if any(w in joined.lower() for w in ("time", "clock", "day", "rain", "thunder", "weather", "seed")):
                keys.append(f"{name}: {joined} = {str(v)[:40]}")
    return {"rcon_replies": _live_world_raw.get(srv.id, {}), "time_related_keys": keys[:60],
            "data_files": sorted(sources)}


# ---------------------------------------------------------------- mods
# What some well-known mods do, for the ones whose files don't say (Floodgate's doesn't).
KNOWN_MODS = {
    "floodgate": "Lets Bedrock players (phones, tablets, consoles, Windows) join through Geyser without a Java account.",
    "geyser-fabric": "Lets Bedrock players join this Java server, translating between the two editions.",
    "geyser": "Lets Bedrock players join this Java server, translating between the two editions.",
    "fabric-api": "The shared toolkit most Fabric mods need.",
    "lithium": "Makes the server run faster without changing how the game plays.",
    "ferritecore": "Cuts down how much memory the game uses.",
    "c2me": "Generates new land faster by using more of the processor.",
    "krypton": "Makes the server's networking faster.",
    "spark": "A performance profiler for finding lag.",
    "bluemap": "Draws a 3D map of the world you can open in a web browser.",
    "squaremap": "Draws a map of the world you can open in a web browser.",
    "tide": "Tide+: fishing with rods, tackle, rigs, a journal and hundreds of fish.",
}


def _read_mod(jar: Path) -> dict:
    info: dict = {"file": jar.name}
    try:
        with zipfile.ZipFile(jar) as z:
            names = set(z.namelist())
            if "fabric.mod.json" in names:
                meta = json.loads(z.read("fabric.mod.json").decode("utf-8", "replace"), strict=False)
                authors = meta.get("authors") or []
                info.update(id=meta.get("id"), name=meta.get("name") or meta.get("id"),
                            version=meta.get("version"), description=meta.get("description"),
                            environment=meta.get("environment", "*"),
                            authors=[a if isinstance(a, str) else a.get("name") for a in authors][:3])
            elif "quilt.mod.json" in names:
                meta = json.loads(z.read("quilt.mod.json"))["quilt_loader"]
                md = meta.get("metadata", {})
                info.update(id=meta.get("id"), name=md.get("name") or meta.get("id"),
                            version=meta.get("version"), description=md.get("description"))
            elif "META-INF/mods.toml" in names or "META-INF/neoforge.mods.toml" in names:
                info.update(name=jar.stem)
    except Exception as e:
        info["error"] = str(e)
    info.setdefault("name", jar.stem)
    if not info.get("description"):
        key = str(info.get("id") or "").lower()
        info["description"] = KNOWN_MODS.get(key) or next((d for k, d in KNOWN_MODS.items() if jar.stem.lower().startswith(k + "-")), None)
    return info


def mods(srv: Server) -> list[dict]:
    d = srv.dir / "mods"
    if not d.is_dir():
        return []
    out = []
    for jar in sorted(d.glob("*.jar")):
        m = _cache.get(("mod", str(jar)), jar, _read_mod)
        if m:
            out.append(m)
    out.sort(key=lambda m: (m.get("name") or "").lower())
    return out


def mod_jars(srv: Server) -> list[Path]:
    d = srv.dir / "mods"
    return sorted(d.glob("*.jar")) if d.is_dir() else []


# ---------------------------------------------------------------- players
def _dirs(srv: Server) -> dict[str, Path]:
    w = srv.world_dir
    return {
        "playerdata": _first_dir(w, "playerdata", "players/data"),
        "stats": _first_dir(w, "stats", "players/stats"),
        "advancements": _first_dir(w, "advancements", "players/advancements"),
    }


def known_players(srv: Server) -> dict[str, dict]:
    """uuid -> {uuid, name}. Union of usercache, stats, playerdata."""
    players: dict[str, dict] = {}
    names: dict[str, str] = {}
    cache = _cache.get(("usercache", srv.id), srv.dir / "usercache.json", _json) or []
    for e in cache:
        if isinstance(e, dict) and e.get("uuid"):
            names[norm_uuid(e["uuid"])] = e.get("name")
    ops = _cache.get(("ops", srv.id), srv.dir / "ops.json", _json) or []
    op_ids = {norm_uuid(o["uuid"]) for o in ops if isinstance(o, dict) and o.get("uuid")}
    d = _dirs(srv)
    for folder, pattern in ((d["playerdata"], "*.dat"), (d["stats"], "*.json")):
        if folder.is_dir():
            for f in folder.glob(pattern):
                u = norm_uuid(f.stem)
                if len(u) != 36:
                    continue
                players.setdefault(u, {"uuid": u})
    for u, p in players.items():
        p["name"] = names.get(u) or u[:8]
        p["op"] = u in op_ids
    return players


def _player_files(srv: Server, uuid: str) -> dict[str, Path]:
    d = _dirs(srv)
    return {
        "playerdata": d["playerdata"] / f"{uuid}.dat",
        "stats": d["stats"] / f"{uuid}.json",
        "advancements": d["advancements"] / f"{uuid}.json",
    }


def player_file_data(srv: Server, uuid: str) -> tuple[dict | None, float | None]:
    p = _player_files(srv, uuid)["playerdata"]
    raw = _cache.get(("pd", srv.id, uuid), p, load_dat)
    if raw is None:
        return None, None
    return norm_player(raw), p.stat().st_mtime


def player_stats(srv: Server, uuid: str) -> dict:
    raw = _cache.get(("stats", srv.id, uuid), _player_files(srv, uuid)["stats"], _json) or {}
    return raw.get("stats", {})


def player_advancements(srv: Server, uuid: str) -> dict:
    raw = _cache.get(("adv", srv.id, uuid), _player_files(srv, uuid)["advancements"], _json) or {}
    out = {}
    for key, val in raw.items():
        if key == "DataVersion" or not isinstance(val, dict):
            continue
        crit = val.get("criteria") or {}
        out[key] = {"done": bool(val.get("done")), "criteria": len(crit),
                    "completed_at": max(crit.values()) if crit and val.get("done") else None}
    return out


def last_seen(srv: Server, uuid: str) -> float | None:
    ts = []
    for p in _player_files(srv, uuid).values():
        try:
            ts.append(p.stat().st_mtime)
        except OSError:
            pass
    return max(ts) if ts else None


def stat(stats: dict, cat: str, key: str) -> int:
    return int((stats.get(f"minecraft:{cat}") or {}).get(f"minecraft:{key}", 0))


def headline_stats(stats: dict) -> dict:
    custom = stats.get("minecraft:custom") or {}
    play = custom.get("minecraft:play_time", custom.get("minecraft:play_one_minute", 0))
    dist = sum(v for k, v in custom.items() if k.endswith("_one_cm"))
    return {
        "play_time": int(play),  # ticks
        "deaths": int(custom.get("minecraft:deaths", 0)),
        "mob_kills": int(custom.get("minecraft:mob_kills", 0)),
        "player_kills": int(custom.get("minecraft:player_kills", 0)),
        "distance_cm": int(dist),
        "jumps": int(custom.get("minecraft:jump", 0)),
        "blocks_mined": int(sum((stats.get("minecraft:mined") or {}).values())),
        "items_crafted": int(sum((stats.get("minecraft:crafted") or {}).values())),
        "damage_dealt": int(custom.get("minecraft:damage_dealt", 0)),
        "damage_taken": int(custom.get("minecraft:damage_taken", 0)),
        "fish_caught": int(custom.get("minecraft:fish_caught", 0)),
        "animals_bred": int(custom.get("minecraft:animals_bred", 0)),
        "time_since_death": int(custom.get("minecraft:time_since_death", 0)),
        "sleep": int(custom.get("minecraft:sleep_in_bed", 0)),
        "traded": int(custom.get("minecraft:traded_with_villager", 0)),
    }


# ---------------------------------------------------------------- live data
_live_cache: dict[tuple[str, str], tuple[float, dict]] = {}


async def live_player(srv: Server, name: str) -> dict | None:
    key = (srv.id, name.lower())
    hit = _live_cache.get(key)
    now = time.monotonic()
    if hit and now - hit[0] < config.live_ttl:
        return hit[1]
    try:
        out = await srv.rcon(f"data get entity {name}")
    except RconError as e:
        log.debug("live fetch failed: %s", e)
        return None
    if not out:
        return None
    try:
        nbt = parse_entity_snbt(out)
    except Exception as e:
        log.warning("Could not parse entity data for %s: %s", name, e)
        return None
    if not nbt:
        return None
    data = norm_player(nbt)
    _live_cache[key] = (now, data)
    return data


async def players_overview(srv: Server) -> dict:
    online, source = await online_players(srv)
    online_l = {n.lower() for n in online}
    rows = []
    known = known_players(srv)
    names_known = {p["name"].lower() for p in known.values()}
    for uuid, p in known.items():
        data, _m = player_file_data(srv, uuid)
        stats = player_stats(srv, uuid)
        adv = player_advancements(srv, uuid)
        rows.append({
            **p,
            "online": p["name"].lower() in online_l,
            "last_seen": last_seen(srv, uuid),
            "xp_level": data["xp_level"] if data else None,
            "health": data["health"] if data else None,
            "max_health": data["max_health"] if data else None,
            "food": data["food"] if data else None,
            "gamemode": data["gamemode"] if data else None,
            "dimension": data["position"]["dimension"] if data else None,
            "position": data["position"] if data else None,
            "advancements": sum(1 for k, a in adv.items() if a["done"] and "/recipes/" not in k and ":recipes/" not in k),
            "headline": headline_stats(stats),
        })
    # Players online who have never been saved yet (first join)
    for n in online:
        if n.lower() not in names_known:
            rows.append({"uuid": None, "name": n, "online": True, "op": False, "headline": headline_stats({})})
    # Refresh online players from RCON so the list shows live vitals/positions
    live_rows = [r for r in rows if r["online"] and r.get("uuid")]
    if live_rows and srv.rcon_conf():
        lives = await asyncio.gather(*(live_player(srv, r["name"]) for r in live_rows))
        for r, live in zip(live_rows, lives, strict=True):
            if live:
                r.update(xp_level=live["xp_level"], health=live["health"], max_health=live["max_health"],
                         food=live["food"], gamemode=live["gamemode"], dimension=live["position"]["dimension"],
                         position=live["position"], live=True)
    from . import db  # local import: db imports config only, avoids a cycle at startup
    today = db.today_seconds(srv.id)
    for r in rows:
        r["today_seconds"] = today.get(r["name"].lower(), 0)
    rows.sort(key=lambda r: (not r["online"], -(r.get("last_seen") or 0)))
    return {"players": rows, "online_source": source}


def _fishing_with(srv: Server) -> str | None:
    from . import fishing
    try:
        return fishing.available(srv)
    except Exception:
        return None


def _tide():
    from . import tide           # tide reads player files through this module
    return tide


async def player_detail(srv: Server, uuid: str) -> dict | None:
    known = known_players(srv)
    p = known.get(norm_uuid(uuid))
    if not p:
        return None
    online, _src = await online_players(srv)
    is_online = p["name"].lower() in {n.lower() for n in online}
    file_data, mtime = player_file_data(srv, p["uuid"])
    data, source, as_of = file_data, "file", mtime
    if is_online:
        live = await live_player(srv, p["name"])
        if live:
            data, source, as_of = live, "live", time.time()
    stats = player_stats(srv, p["uuid"])
    return {
        **p,
        "online": is_online,
        "last_seen": last_seen(srv, p["uuid"]),
        "source": source,  # "live" (RCON) or "file" (last save)
        "as_of": as_of,
        "live_available": srv.rcon_conf() is not None,
        "data": data,
        "headline": headline_stats(stats),
        "stats": stats,
        "advancements": player_advancements(srv, p["uuid"]),
        "fishing": _tide().player_summary(srv, p["uuid"]),
    }


# The one list of leaderboards, in display order. The app's Leaderboards tab and the status
# page's TV view both draw exactly these, so they can't drift apart.
# (key, title, kind) -- kind tells the pages how to show the number:
#   ticks -> a duration, cm -> a distance, hearts -> damage in hearts, count -> a plain number
LEADERBOARDS = [
    # no "time played" board: nobody should be racing to play longest
    ("xp_level", "Experience level", "count"),           # the level now (it drops on death)
    ("advancements", "Advancements", "count"),
    ("mob_kills", "Mobs defeated", "count"),
    ("blocks_mined", "Blocks mined", "count"),
    ("diamonds_mined", "Diamonds mined", "count"),
    ("distance_cm", "Distance travelled", "cm"),
    ("items_crafted", "Items crafted", "count"),
    ("deaths", "Most deaths", "count"),
    ("time_since_death", "Longest alive right now", "ticks"),
    ("jumps", "Jumps", "count"),
    ("fish_caught", "Fish caught", "count"),               # with Tide: fish in the journal (tide.leaderboard_values)
    ("fishing_level", "Fishing level", "count"),             # Tide (fishing mod) only
    ("heaviest_fish", "Heaviest fish", "grams"),              # Tide only
    ("animals_bred", "Animals bred", "count"),
    ("traded", "Villager trades", "count"),
    ("creepers_defeated", "Creepers defeated", "count"),
    ("damage_dealt", "Damage dealt", "hearts"),
    ("sleep", "Nights slept", "count"),
    ("flown_cm", "Distance flown", "cm"),
    ("swum_cm", "Distance swum", "cm"),
    ("chests_opened", "Chests opened", "count"),
    ("cake_eaten", "Cake slices eaten", "count"),
    ("raids_won", "Raids won", "count"),
]


def leaderboard_stats(stats: dict) -> dict:
    """headline_stats plus the extra numbers only the leaderboards use."""
    custom = stats.get("minecraft:custom") or {}
    mined = stats.get("minecraft:mined") or {}
    killed = stats.get("minecraft:killed") or {}
    return {
        **headline_stats(stats),
        "diamonds_mined": int(mined.get("minecraft:diamond_ore", 0) + mined.get("minecraft:deepslate_diamond_ore", 0)),
        "creepers_defeated": int(killed.get("minecraft:creeper", 0)),
        "flown_cm": int(custom.get("minecraft:aviate_one_cm", 0)),
        "swum_cm": int(custom.get("minecraft:swim_one_cm", 0)),
        "chests_opened": int(custom.get("minecraft:open_chest", 0)),
        "cake_eaten": int(custom.get("minecraft:eat_cake_slice", 0)),
        "raids_won": int(custom.get("minecraft:raid_win", 0)),
    }


async def leaderboard(srv: Server) -> dict:
    rows = []
    for uuid, p in known_players(srv).items():
        data, _ = player_file_data(srv, uuid)
        h = leaderboard_stats(player_stats(srv, uuid))
        h["xp_level"] = data["xp_level"] if data else 0
        adv = player_advancements(srv, uuid)
        h["advancements"] = sum(1 for k, a in adv.items() if a["done"] and "/recipes/" not in k and ":recipes/" not in k)
        h.update(_tide().leaderboard_values(srv, uuid))
        rows.append({"uuid": uuid, "name": p["name"], **{k: h.get(k, 0) for k, _t, _f in LEADERBOARDS}})
    return {"boards": [{"key": k, "title": t, "kind": f} for k, t, f in LEADERBOARDS], "players": rows}
