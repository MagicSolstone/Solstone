"""Server registry (Crafty + folder discovery), world info, mods and players."""
from __future__ import annotations

import asyncio
import json
import logging
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

log = logging.getLogger("lodestone.servers")


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
        s = self.settings
        p = self.props
        password = s.get("rcon_password") or p.get("rcon.password", "")
        enabled = p.get("enable-rcon", "false").lower() == "true" or s.get("rcon_password")
        if not enabled or not password:
            return None
        port = int(s.get("rcon_port") or p.get("rcon.port", 25575) or 25575)
        host = s.get("rcon_host") or config.default_rcon_host
        return host, port, password

    async def rcon(self, cmd: str) -> str | None:
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
            out = await self._rcon.command(cmd)
        except RconError as e:
            self.rcon_error = str(e)
            self._rcon_backoff = time.monotonic() + 30
            raise
        self.rcon_error = None
        return out


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
                for s in await crafty.servers():
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
async def online_players(srv: Server) -> tuple[list[str], str]:
    """Return (names, source). Prefers RCON `list`, falls back to Crafty."""
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


async def _crafty_stats(srv: Server) -> dict | None:
    if not srv.crafty:
        return None
    stats = await crafty.stats(srv.id)
    if stats is not None:
        srv.crafty["_stats"] = stats
    return stats


def _server_icon(srv: Server) -> bool:
    return (srv.dir / "server-icon.png").is_file()


async def server_summary(srv: Server) -> dict:
    stats = await _crafty_stats(srv) or {}
    props = srv.props
    lvl = srv.level()
    online, source = await online_players(srv)
    running = bool(stats.get("running")) if srv.crafty else None
    rcon = srv.rcon_conf()
    return {
        "id": srv.id,
        "name": srv.display_name,
        "type": srv.type,
        "managed_by_crafty": srv.crafty is not None,
        "folder_found": srv.dir.is_dir(),
        "folder": str(srv.dir),
        "running": running,
        "crashed": bool(stats.get("crashed")),
        "started": stats.get("started"),
        "cpu": stats.get("cpu"),
        "mem": stats.get("mem"),
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
        "loader": detect_loader(srv),
        "perf": _latest_perf(srv),
        "backup": _backup(srv),
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


def world_info(srv: Server) -> dict:
    lvl = srv.level()
    props = srv.props
    wgs = lvl.get("WorldGenSettings") or {}
    seed = wgs.get("seed", lvl.get("RandomSeed"))
    spawn = None
    if isinstance(lvl.get("spawn"), dict):  # 1.21.5+
        p = lvl["spawn"].get("pos")
        if isinstance(p, list):
            spawn = {"x": p[0], "y": p[1], "z": p[2], "dimension": lvl["spawn"].get("dimension")}
    elif "SpawnX" in lvl:
        spawn = {"x": lvl["SpawnX"], "y": lvl["SpawnY"], "z": lvl["SpawnZ"], "dimension": "minecraft:overworld"}
    rules = lvl.get("GameRules") or lvl.get("game_rules") or {}
    datapacks = lvl.get("DataPacks") or {}
    diff = lvl.get("Difficulty")
    diff_name = {0: "peaceful", 1: "easy", 2: "normal", 3: "hard"}.get(diff, props.get("difficulty")) \
        if not isinstance(diff, str) else diff
    if isinstance(lvl.get("difficulty_settings"), dict):
        diff_name = lvl["difficulty_settings"].get("difficulty", diff_name)
    day_time = int(lvl.get("DayTime", 0))
    return {
        "level_name": lvl.get("LevelName") or props.get("level-name", "world"),
        "version": srv.mc_version,
        "data_version": lvl.get("DataVersion"),
        "seed": str(seed) if seed is not None else None,
        "hardcore": bool(lvl.get("hardcore", props.get("hardcore") == "true")),
        "difficulty": diff_name,
        "default_gamemode": props.get("gamemode", "survival"),
        "spawn": spawn,
        "game_time": int(lvl.get("Time", 0)),
        "day_time": day_time,
        "day": day_time // 24000 + 1,
        "time_of_day": day_time % 24000,
        "raining": bool(lvl.get("raining", 0)),
        "thundering": bool(lvl.get("thundering", 0)),
        "last_played": (lvl.get("LastPlayed") or 0) / 1000 or None,
        "allow_commands": bool(lvl.get("allowCommands", 0)),
        "game_rules": {str(k): (str(v) if not isinstance(v, (int, float, bool)) else v) for k, v in rules.items()},
        "datapacks": {"enabled": datapacks.get("Enabled", []), "disabled": datapacks.get("Disabled", [])},
        "dimensions": dimensions(srv),
        "properties": {k: props[k] for k in ("view-distance", "simulation-distance", "pvp", "spawn-protection",
                                               "white-list", "online-mode", "max-players", "allow-flight",
                                               "level-type") if k in props},
    }


# ---------------------------------------------------------------- mods
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
    }


async def leaderboard(srv: Server) -> dict:
    rows = []
    for uuid, p in known_players(srv).items():
        data, _ = player_file_data(srv, uuid)
        h = headline_stats(player_stats(srv, uuid))
        h["xp_level"] = data["xp_level"] if data else 0
        rows.append({"uuid": uuid, "name": p["name"], **h})
    return {"players": rows}
