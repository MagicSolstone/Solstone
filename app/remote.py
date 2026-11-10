"""Servers somewhere else: a game host, a rented server, another computer (Manage → Server setup → Add a server elsewhere).

Solstone reads a server's files all the time: the log (who joined, chat, deaths, catches), each player's stats and
saved data, the world's level.dat, server.properties, the whitelist, the mods. For a server on the same machine it
reads them where they are. For one somewhere else it keeps a **mirror**: a copy of just those files in its own data
folder, kept up to date over SFTP (which nearly every host offers), and every page and feature reads the mirror as if
the server were here. Nothing else in Solstone needs to know.

- The log is followed: every few seconds only its new lines are fetched (a host's SFTP can read from a point in a
  file), so the activity feed and the games react as quickly as for a server at home.
- The rest (stats, player data, level.dat, the small files at the top) is looked at every half a minute or so, and a
  file is fetched only when its size or time has changed.
- Mods and old logs: every ten minutes, each one once.
- The few things Solstone writes (a Bedrock player on the whitelist) go back the same way.

The host's own panel, when it's Pterodactyl or Pelican (what most game hosts run), does what Crafty does at home: start,
stop and restart, whether it's running, CPU and memory, and a console line when RCON isn't answering.

SFTP's host key is remembered the first time (and shown in Manage → Server setup): if it ever changes, Solstone stops and
says so instead of sending the password to something else.
"""
from __future__ import annotations

import asyncio
import logging
import posixpath
import secrets
import stat as stat_mod
import time
from pathlib import Path

import httpx

from . import settings_store
from .config import config

log = logging.getLogger("solstone.remote")

SECTION = "remote_servers"          # {sid: {...}}: how each one is reached (its secrets never leave Solstone)
SECRETS = ("password",)
LEARNED = ("host_key", "host_pub")      # the SFTP server's identity: only ever set from what a test saw
LOG_SECS = 3                        # the log: new lines this often
FILES_SECS = 30                     # stats, player data, level.dat, the files at the top: looked at this often (default)
SLOW_SECS = 600                     # mods and old logs
TOP_FILES = ("server.properties", "usercache.json", "ops.json", "whitelist.json", "banned-players.json", "server-icon.png")
WORLD_FILES = ("level.dat",)
WORLD_DIRS = ("stats", "playerdata", "advancements", "players/stats", "players/data", "players/advancements")
MAX_FILE = 64 * 1024 * 1024         # (a jar bigger than this isn't fetched: its name is enough)
# The map: only the parts of the world players have been to (a region file is 512 x 512 blocks, about 1-10 MB).
REGION_SECS = 60                    # where players are now: looked at this often (just its chunk table: 8 KB)
RECENT_SECS = 15 * 60               # "now": a position seen this recently (that region and the eight around it)
REGIONS_PER_TICK = 3                # fetched a few at a time, so the log never waits behind a big batch
SECTOR = 4096                       # a region file: a table of where each of its 1024 chunks is (4 KB) and when each was
HEADER = 2 * SECTOR                 # last saved (4 KB), then the chunks, each a whole number of 4 KB sectors
_DIM_DIRS = {"minecraft:overworld": ("region",), "minecraft:the_nether": ("DIM-1/region", "_nether/DIM-1/region"),
             "minecraft:the_end": ("DIM1/region", "_the_end/DIM1/region")}     # (Paper keeps the Nether and End apart)
CONNECT_SECS = 15


# ------------------------------------------------------------------ the saved settings
def all_cfg() -> dict[str, dict]:
    data = dict(settings_store.load().get(SECTION) or {})
    if any(c.get("panel_url") for c in data.values()):
        data = _panel_to_connection(data)
    return data


def _panel_to_connection(data: dict) -> dict:
    """1.17 kept a panel's address and key with each server: they're a connection of their own now (Manage → Server
    setup → Connections), shared by every server on that panel. Moved over once."""
    from . import connections
    for c in data.values():
        url, key = c.pop("panel_url", ""), c.pop("panel_key", "")
        if not url or not key or c.get("conn"):
            continue
        same = next((cid for cid, x in connections.of_type("panel").items() if x["url"] == url.rstrip("/") and x.get("key") == key), None)
        try:
            c["conn"] = same or connections.save(None, {"type": "panel", "name": "Host's panel", "url": url, "key": key})
        except ValueError:
            pass
    settings_store.save_section(SECTION, data)
    return data


def get(sid: str) -> dict | None:
    return all_cfg().get(sid)


def public(cfg: dict) -> dict:
    """What the page may see: everything but the secrets (and whether each is set)."""
    out = {k: v for k, v in cfg.items() if k not in SECRETS}
    for k in SECRETS:
        out[f"{k}_set"] = bool(cfg.get(k))
    return out


def clean(body: dict, old: dict | None = None) -> dict:
    """An admin's settings for a server elsewhere, checked. A secret left blank keeps the one saved."""
    old = old or {}

    def text(k, n=200):
        return " ".join(str(body.get(k) if body.get(k) is not None else old.get(k) or "").split())[:n]

    def num(k, lo, hi, default):
        try:
            return max(lo, min(hi, int(body.get(k) if body.get(k) not in (None, "") else old.get(k, default))))
        except (TypeError, ValueError):
            return default
    cfg = {"name": text("name", 60), "host": text("host", 253).lower(), "port": num("port", 1, 65535, 22), "user": text("user", 120),
           "path": (str(body.get("path") if body.get("path") is not None else old.get("path") or "") or "/").strip()[:300] or "/",
           "conn": text("conn", 40), "panel_id": text("panel_id", 64),
           "files_secs": num("files_secs", 10, 600, FILES_SECS), "host_key": old.get("host_key", ""), "host_pub": old.get("host_pub", ""),
           "map": bool(body["map"]) if "map" in body else old.get("map", True)}      # the map where players have been
    if not cfg["name"] or not cfg["host"] or not cfg["user"]:
        raise ValueError("A name, the SFTP address and the username are needed")
    if cfg["conn"]:
        from . import connections
        if (connections.get(cfg["conn"]) or {}).get("type") not in connections.HOSTS:
            raise ValueError("Pick one of your panel connections (or none)")
    for k in SECRETS:
        v = body.get(k)
        cfg[k] = str(v) if v else old.get(k, "")
    if (cfg["host"], cfg["port"]) != (old.get("host"), old.get("port")):
        cfg["host_key"] = cfg["host_pub"] = ""    # a different machine: its key is learned afresh
    return cfg


def save(sid: str | None, body: dict) -> str:
    """Add (sid None) or change one. Returns its id. Added by an admin: shown straight away (not "new")."""
    data = all_cfg()
    sid = sid or f"r-{secrets.token_hex(4)}"
    data[sid] = clean(body, data.get(sid))
    settings_store.save_section(SECTION, data)
    settings_store.mark_seen(sid)
    return sid


def forget(sid: str) -> None:
    data = all_cfg()
    data.pop(sid, None)
    settings_store.save_section(SECTION, data)
    _mirrors.pop(sid, None)
    _panels.pop(sid, None)


def mirror_dir(sid: str) -> Path:
    return config.data_dir / "remote" / sid


# ------------------------------------------------------------------ SFTP
class HostKeyChanged(Exception):
    pass


async def _connect(cfg: dict, learn: bool = False):
    """An SFTP session. The host must prove it's the machine Solstone met the first time (its saved public key),
    checked by SSH before the password is ever sent. With no key saved yet, only an admin's test (`learn`) may
    connect, and it learns the key. Returns (connection, sftp, (fingerprint, public key))."""
    import asyncssh
    pub = cfg.get("host_pub") or ""
    if pub:
        trusted = asyncssh.import_public_key(pub)
        known = ([trusted], [], [])                       # (trusted host keys, CA keys, revoked)
    elif learn:
        known = None                                      # (the admin is looking: what it learns is shown to them)
    else:
        raise HostKeyChanged("not learned yet: test the connection in Manage → Server setup first")
    conn = await asyncio.wait_for(asyncssh.connect(
        cfg["host"], port=int(cfg.get("port") or 22), username=cfg["user"], password=cfg.get("password") or None,
        known_hosts=known, client_keys=None, agent_path=None, connect_timeout=CONNECT_SECS,
        # Nothing from a home folder: no ~/.ssh config, certificates or keys. (Solstone's container user may not be allowed
        # into its home folder at all, and looking there then stopped every connection with "Permission denied".)
        config=[], x509_trusted_certs=None, x509_trusted_cert_paths=[], ignore_encrypted=True), CONNECT_SECS + 5)
    key = conn.get_server_host_key()
    ident = (key.get_fingerprint("sha256"), key.export_public_key("openssh").decode().strip()) if key else ("", "")
    return conn, await conn.start_sftp_client(), ident


def _why(e: Exception) -> str:
    import asyncssh
    if isinstance(e, asyncssh.PermissionDenied):
        return "The username or password wasn't accepted"
    if isinstance(e, HostKeyChanged) and "not learned" in str(e):
        return "Not connected yet: open its settings in Manage → Server setup and press Test the connection"
    if isinstance(e, asyncssh.HostKeyNotVerifiable) or isinstance(e, HostKeyChanged):
        return ("The server's identity (its SSH host key) has changed since Solstone first connected. If the host moved "
                "your server, press Forget its identity in its settings; otherwise someone may be in between, so don't")
    if isinstance(e, (asyncio.TimeoutError, TimeoutError)):
        return "Nothing answered at that address and port in time"
    if isinstance(e, OSError):
        return f"Couldn't reach it: {e.strerror or e}"
    return f"{type(e).__name__}: {e}"


async def test(cfg: dict) -> dict:
    """Connect, look in the folder, and learn the host's key (an admin is watching: Manage → Server setup)."""
    try:
        conn, sftp, (fp, pub) = await _connect(cfg, learn=True)
    except Exception as e:
        return {"ok": False, "error": _why(e)}
    try:
        path = cfg.get("path") or "/"
        try:
            names = sorted(await sftp.listdir(path))
        except Exception as e:
            return {"ok": False, "error": f"Connected, but couldn't open the folder {path}: {e}", "host_key": fp, "host_pub": pub}
        names = [n for n in names if n not in (".", "..")]
        props = {}
        if "server.properties" in names:
            from .servers import parse_properties
            async with sftp.open(posixpath.join(path, "server.properties"), "rb") as f:
                props = parse_properties((await f.read(256 * 1024)).decode("utf-8", "replace"))
        found = "server.properties" in names
        return {"ok": found, "host_key": fp, "host_pub": pub, "files": names[:40],
                "error": "" if found else "Connected, but there's no server.properties in that folder: is it the server's own folder?",
                "level": props.get("level-name", "world"), "rcon": props.get("enable-rcon") == "true",
                "rcon_port": props.get("rcon.port", ""), "port": props.get("server-port", ""), "motd": props.get("motd", "")}
    finally:
        conn.close()


class Mirror:
    """Keeps one server's mirror up to date (the copy Solstone reads)."""

    def __init__(self, sid: str):
        self.sid = sid
        self.dir = mirror_dir(sid)
        self.conn = self.sftp = None
        self.known: dict[str, tuple[int, int]] = {}      # remote path -> (size, mtime) of the copy we have
        self.log_at = 0                                  # how much of latest.log we have
        self.log_head = b""
        self.last = {"log": 0.0, "files": 0.0, "slow": 0.0, "regions": 0.0}
        self.regions: list[tuple[str, str, bool]] = []    # (local path, remote path, only if missing) still to look at
        self._dim_base: dict[str, str] = {}              # each dimension's region folder on the server, once found
        self.status = {"ok": None, "error": "", "synced": None, "files": 0, "bytes": 0}
        self._lock = asyncio.Lock()

    @property
    def cfg(self) -> dict:
        return get(self.sid) or {}

    def _local(self, rel: str) -> Path:
        p = (self.dir / rel).resolve()
        if self.dir.resolve() not in p.parents and p != self.dir.resolve():
            raise ValueError(f"outside the mirror: {rel}")
        return p

    def _remote(self, rel: str) -> str:
        return posixpath.join(self.cfg.get("path") or "/", rel)

    async def _session(self):
        if self.sftp is None:
            self.conn, self.sftp, _ident = await _connect(self.cfg)
        return self.sftp

    def close(self) -> None:
        if self.conn:
            self.conn.close()
        self.conn = self.sftp = None

    async def _fetch(self, rel: str, size: int, mtime: int, remote_rel: str | None = None) -> bool:
        """Copy one file if it changed. True if it was fetched. remote_rel: where it is on the server, when that's
        not where the copy goes (Paper's Nether: world_nether/DIM-1/region, copied to world/DIM-1/region)."""
        if self.known.get(rel) == (size, mtime) and self._local(rel).exists():
            return False
        if size > MAX_FILE:
            return False
        sftp = await self._session()
        local = self._local(rel)
        local.parent.mkdir(parents=True, exist_ok=True)
        tmp = local.with_name(local.name + ".part")
        async with sftp.open(self._remote(remote_rel or rel), "rb") as f:
            data = await f.read()
        tmp.write_bytes(data)
        tmp.replace(local)
        import os
        os.utime(local, (mtime, mtime))                  # (the copy keeps the server's time: "last played" and the like)
        self.known[rel] = (size, mtime)
        self.status["bytes"] += len(data)
        return True

    async def _list(self, rel: str) -> list[tuple[str, int, int, bool]]:
        """(name, size, mtime, is_dir) for a remote folder; [] if it isn't there."""
        sftp = await self._session()
        try:
            entries = await sftp.readdir(self._remote(rel))
        except Exception:
            return []
        out = []
        for e in entries:
            if e.filename in (".", ".."):
                continue
            a = e.attrs
            out.append((e.filename, int(a.size or 0), int(a.mtime or 0), stat_mod.S_ISDIR(a.permissions or 0)))
        return out

    async def _one(self, rel: str) -> None:
        sftp = await self._session()
        try:
            a = await sftp.stat(self._remote(rel))
        except Exception:
            return
        await self._fetch(rel, int(a.size or 0), int(a.mtime or 0))

    async def _folder(self, rel: str, suffixes: tuple[str, ...]) -> None:
        for name, size, mtime, is_dir in await self._list(rel):
            if not is_dir and name.endswith(suffixes):
                await self._fetch(f"{rel}/{name}", size, mtime)

    def _level(self) -> str:
        from .servers import read_properties
        return read_properties(self.dir / "server.properties").get("level-name", "world") or "world"

    async def follow_log(self) -> None:
        """latest.log: just what's new since last time. A new log (the server restarted: it's shorter, or starts
        differently) is fetched from the start."""
        sftp = await self._session()
        rel = "logs/latest.log"
        try:
            a = await sftp.stat(self._remote(rel))
        except Exception:
            return
        size = int(a.size or 0)
        local = self._local(rel)
        async with sftp.open(self._remote(rel), "rb") as f:
            head = await f.read(256)
            if size < self.log_at or (self.log_head and head[:len(self.log_head)] != self.log_head) or not local.exists():
                self.log_at = 0                                  # a new log
            if size == self.log_at:
                return
            await f.seek(self.log_at)
            new = await f.read(size - self.log_at)
        local.parent.mkdir(parents=True, exist_ok=True)
        with local.open("wb" if self.log_at == 0 else "ab") as out:
            out.write(new)
        self.log_at += len(new)
        self.log_head = head[:64]
        self.status["bytes"] += len(new)

    async def sync_files(self) -> None:
        for f in TOP_FILES:
            await self._one(f)
        level = self._level()
        for f in WORLD_FILES:
            await self._one(f"{level}/{f}")
        for d in WORLD_DIRS:
            await self._folder(f"{level}/{d}", (".json", ".dat"))

    async def sync_slow(self) -> None:
        await self._folder("mods", (".jar",))
        await self._folder("logs", (".log.gz",))          # old logs: what happened before (recaps)
        await self._folder("config", (".json", ".toml", ".yml", ".yaml", ".properties"))
        await self._folder(f"{self._level()}/datapacks", (".zip",))

    def _visited(self, now: float) -> list[tuple[str, int, int, bool]]:
        """The regions players have been in, from Solstone's own record of where they were (positions): (dimension,
        region x, region z, recent). Recent ones come with the eight around them (what they can see from there)."""
        from . import db
        rows = db.q("SELECT dim, CASE WHEN x < 0 THEN CAST((x - 511) / 512 AS INT) ELSE CAST(x / 512 AS INT) END AS rx, "
                    "CASE WHEN z < 0 THEN CAST((z - 511) / 512 AS INT) ELSE CAST(z / 512 AS INT) END AS rz, MAX(ts) AS t "
                    "FROM positions WHERE server_id=? GROUP BY dim, rx, rz", (self.sid,))
        out: dict[tuple[str, int, int], bool] = {}
        for r in rows:
            recent = r["t"] >= now - RECENT_SECS
            for dx in (-1, 0, 1) if recent else (0,):
                for dz in (-1, 0, 1) if recent else (0,):
                    k = (r["dim"], r["rx"] + dx, r["rz"] + dz)
                    out[k] = out.get(k, False) or recent
        return sorted(((d, x, z, rec) for (d, x, z), rec in out.items()), key=lambda v: not v[3])   # recent first

    async def _region_base(self, dim: str) -> str | None:
        """Where a dimension's region files are on the server (and so in the copy: the usual place)."""
        if dim in self._dim_base:
            return self._dim_base[dim]
        level = self._level()
        if dim in _DIM_DIRS:
            options = [f"{level}{'/' if not d.startswith('_') else ''}{d}" for d in _DIM_DIRS[dim]]
        else:
            ns, _, rest = dim.partition(":")
            if not ns or not rest or ".." in dim:
                return None
            options = [f"{level}/dimensions/{ns}/{rest}/region"]
        sftp = await self._session()
        for o in options:
            try:
                await sftp.stat(self._remote(o))
            except Exception:
                continue
            self._dim_base[dim] = o
            return o
        return None

    async def plan_regions(self, now: float) -> None:
        """What to look at next for the map: where players are now (fetched again if it changed), and anywhere they've
        been that the copy doesn't have yet."""
        self.regions = []
        level = self._level()
        for dim, rx, rz, recent in self._visited(now):
            base = await self._region_base(dim)
            if not base:
                continue
            local = f"{level}/{_DIM_DIRS[dim][0]}" if dim in _DIM_DIRS else base
            name = f"r.{rx}.{rz}.mca"
            if not recent and self._local(f"{local}/{name}").exists():
                continue
            self.regions.append((f"{local}/{name}", f"{base}/{name}", not recent))

    async def sync_regions(self) -> None:
        """A few of the planned regions: a new one copied whole; one the copy has, just the chunks saved since."""
        sftp = await self._session()
        for _ in range(min(REGIONS_PER_TICK, len(self.regions))):
            local, remote_rel, only_missing = self.regions.pop(0)
            have = self._local(local).exists()
            if only_missing and have:
                continue
            try:
                a = await sftp.stat(self._remote(remote_rel))
            except Exception:
                continue                                         # (never generated: nothing to draw there)
            size, mtime = int(a.size or 0), int(a.mtime or 0)
            if self.known.get(local) == (size, mtime) and have:
                continue
            if not have or not await self._patch_region(local, remote_rel, size, mtime):
                await self._fetch(local, size, mtime, remote_rel)

    async def _patch_region(self, local: str, remote_rel: str, size: int, mtime: int) -> bool:
        """Bring a region the copy already has up to date by fetching only its chunks saved since: their table says
        when each was saved, and where it is. A few KB instead of the whole file. False: fetch it whole instead."""
        path = self._local(local)
        try:
            mine = path.read_bytes()[:HEADER]
        except OSError:
            return False
        if len(mine) < HEADER or size < HEADER:
            return False
        sftp = await self._session()
        async with sftp.open(self._remote(remote_rel), "rb") as f:
            theirs = await f.read(HEADER)
            if len(theirs) < HEADER:
                return False
            changed = []
            for i in range(1024):
                if theirs[SECTOR + i * 4: SECTOR + i * 4 + 4] != mine[SECTOR + i * 4: SECTOR + i * 4 + 4] or \
                        theirs[i * 4: i * 4 + 4] != mine[i * 4: i * 4 + 4]:
                    loc = int.from_bytes(theirs[i * 4: i * 4 + 3], "big")
                    n = theirs[i * 4 + 3]
                    if loc and n:
                        changed.append((loc * SECTOR, n * SECTOR))
            chunks = []
            for off, length in changed:
                await f.seek(off)
                chunks.append((off, await f.read(length)))
        with path.open("r+b") as out:                    # the chunks first, then the table that points at them
            for off, data in chunks:
                out.seek(off)
                out.write(data)
            out.seek(0)
            out.write(theirs)
        import os
        os.utime(path, (mtime, mtime))
        self.known[local] = (size, mtime)
        self.status["bytes"] += HEADER + sum(len(d) for _o, d in chunks)
        return True

    async def tick(self, now: float | None = None) -> None:
        """Called every couple of seconds: does whatever is due."""
        now = now or time.time()
        if self._lock.locked():
            return
        async with self._lock:
            try:
                if now - self.last["files"] >= int(self.cfg.get("files_secs") or FILES_SECS) or not (self.dir / "server.properties").exists():
                    await self.sync_files()
                    self.last["files"] = now
                if now - self.last["slow"] >= SLOW_SECS:
                    await self.sync_slow()
                    self.last["slow"] = now
                if now - self.last["log"] >= LOG_SECS:
                    await self.follow_log()
                    self.last["log"] = now
                if self.cfg.get("map", True):
                    if now - self.last["regions"] >= REGION_SECS:
                        await self.plan_regions(now)
                        self.last["regions"] = now
                    if self.regions:
                        await self.sync_regions()
                self.status.update(ok=True, error="", synced=now, files=len(self.known) + (1 if self.log_at else 0))
            except Exception as e:
                self.close()                                     # a fresh connection next time
                why = _why(e)
                if self.status.get("error") != why:
                    log.warning("server %s: couldn't update its files: %s", self.sid, why)
                self.status.update(ok=False, error=why)

    async def put(self, rel: str, data: bytes) -> None:
        """A file Solstone changed (the whitelist): into the mirror and onto the server."""
        async with self._lock:
            sftp = await self._session()
            tmp = self._remote(rel) + ".solstone-tmp"
            async with sftp.open(tmp, "wb") as f:
                await f.write(data)
            try:
                await sftp.posix_rename(tmp, self._remote(rel))
            except Exception:
                await sftp.rename(tmp, self._remote(rel))       # (no posix rename: the target can't exist)
            local = self._local(rel)
            local.parent.mkdir(parents=True, exist_ok=True)
            local.write_bytes(data)
            a = await sftp.stat(self._remote(rel))
            self.known[rel] = (int(a.size or 0), int(a.mtime or 0))

    async def remove(self, rel: str) -> bool:
        async with self._lock:
            sftp = await self._session()
            try:
                await sftp.remove(self._remote(rel))
            except Exception:
                return False
            self._local(rel).unlink(missing_ok=True)
            self.known.pop(rel, None)
            return True


_mirrors: dict[str, Mirror] = {}


def mirror(sid: str) -> Mirror | None:
    if sid not in all_cfg():
        return None
    if sid not in _mirrors:
        _mirrors[sid] = Mirror(sid)
    return _mirrors[sid]


async def tick_all() -> None:
    """Every server elsewhere, at once (each keeps its own pace)."""
    ms = [m for m in (mirror(sid) for sid in all_cfg()) if m]
    if ms:
        await asyncio.gather(*(m.tick() for m in ms))


def rel_of(srv, path: Path) -> str | None:
    """A path in a server's mirror, as the server sees it ("whitelist.json"); None if it's not in one."""
    try:
        return str(Path(path).resolve().relative_to(mirror_dir(srv.id).resolve())).replace("\\", "/")
    except ValueError:
        return None


# ------------------------------------------------------------------ the host's panel (Pterodactyl, Pelican)
class Panel:
    """The client API every Pterodactyl (and Pelican) panel has: /api/client/servers/<id>/... with an API key the
    admin makes in the panel (Account → API Credentials)."""

    def __init__(self, sid: str, cfg: dict | None = None):
        self.sid = sid
        self._cfg = cfg                          # (a test of settings not saved yet)
        conn = self._conn()
        self._client = httpx.AsyncClient(timeout=10, verify=bool(conn.get("verify_ssl", True)))
        self._stats: tuple[float, dict] | None = None
        self.error = ""

    @property
    def cfg(self) -> dict:
        return self._cfg if self._cfg is not None else (get(self.sid) or {})

    def _conn(self) -> dict:
        """The panel connection this server is on (its address and API key)."""
        from . import connections
        return connections.get(self.cfg.get("conn")) or {}

    def _url(self, tail: str) -> str:
        return f"{self._conn().get('url', '')}/api/client/servers/{self.cfg['panel_id']}{tail}"

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._conn().get('key', '')}", "Accept": "application/json", "Content-Type": "application/json"}

    async def stats(self) -> dict | None:
        """Running or not, CPU and memory: in the shape Crafty's stats have, so the rest of Solstone needn't care."""
        if self._stats and time.monotonic() - self._stats[0] < 5:
            return self._stats[1]
        try:
            r = await self._client.get(self._url("/resources"), headers=self._headers())
            r.raise_for_status()
            a = r.json().get("attributes") or {}
        except Exception as e:
            self.error = _panel_why(e)
            return None
        self.error = ""
        res = a.get("resources") or {}
        state = a.get("current_state") or ""
        mem = int(res.get("memory_bytes") or 0)
        limit = int((self.cfg.get("_limits") or {}).get("memory") or 0) * 1024 * 1024
        up = int(res.get("uptime") or 0)                      # milliseconds
        out = {"running": state == "running", "state": state, "cpu": round(float(res.get("cpu_absolute") or 0), 1),
               "mem": f"{mem / 1024 ** 3:.1f}GB" if mem >= 1024 ** 3 else f"{mem / 1024 ** 2:.0f}MB",
               "mem_percent": round(mem * 100 / limit, 1) if limit else None,
               "world_size": f"{int(res.get('disk_bytes') or 0) / 1024 ** 3:.1f}GB",
               "started": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - up / 1000)) if up and state == "running" else None,
               "crashed": False}
        self._stats = (time.monotonic(), out)
        return out

    async def power(self, action: str) -> None:
        if action == "backup_server":                         # the host's own backup (it keeps it, in the panel)
            r = await self._client.post(self._url("/backups"), headers=self._headers(), json={"name": "Solstone"})
            r.raise_for_status()
            return
        signal = {"start_server": "start", "stop_server": "stop", "restart_server": "restart", "kill_server": "kill"}.get(action, action)
        r = await self._client.post(self._url("/power"), headers=self._headers(), json={"signal": signal})
        r.raise_for_status()
        self._stats = None

    async def command(self, command: str) -> None:
        r = await self._client.post(self._url("/command"), headers=self._headers(), json={"command": command})
        r.raise_for_status()

    async def test(self) -> dict:
        try:
            r = await self._client.get(self._url(""), headers=self._headers())
            r.raise_for_status()
            a = r.json().get("attributes") or {}
        except Exception as e:
            return {"ok": False, "error": _panel_why(e)}
        limits = a.get("limits") or {}
        data = all_cfg()
        if self._cfg is None and self.sid in data:            # its memory limit: for "how full"
            data[self.sid]["_limits"] = {"memory": limits.get("memory") or 0}
            settings_store.save_section(SECTION, data)
        st = await self.stats()
        if self._cfg is not None:
            await self._client.aclose()
        return {"ok": True, "name": a.get("name", ""), "node": a.get("node", ""), "state": (st or {}).get("state", ""),
                "memory_mb": limits.get("memory") or 0}


def _panel_why(e: Exception) -> str:
    if isinstance(e, httpx.HTTPStatusError):
        c = e.response.status_code
        try:
            said = (e.response.json() or {}).get("message") or ""
        except ValueError:
            said = ""
        if c == 403 and "serverprism.com" in str(e.request.url):
            return "That ServerPrism token is missing a scope it needs (servers:read; servers:control to start and stop)"
        if c == 409 and said:
            return f"The host said: {said}"
        if c == 429:
            return "Too many requests to the host for a moment (its limit): it'll be asked again shortly"
        return {401: "The panel didn't accept the API key", 403: "That API key can't see this server",
                404: "The panel has no server with that ID (it's the short one in the server's address, like 1a2b3c4d)"}.get(c, f"The panel said {c}")
    if isinstance(e, httpx.RequestError):
        return f"Couldn't reach the panel: {type(e).__name__}"
    return f"{type(e).__name__}: {e}"


_panels: dict[str, Panel] = {}


def panel(sid: str) -> Panel | None:
    from . import connections
    c = get(sid)
    kind = (connections.get(c.get("conn")) or {}).get("type") if c else None
    if not c or not c.get("panel_id") or kind not in connections.HOSTS:
        return None
    cls = PrismPanel if kind == "serverprism" else Panel
    if not isinstance(_panels.get(sid), cls):
        _panels[sid] = cls(sid)
    return _panels[sid]


class PrismPanel(Panel):
    """ServerPrism's own API (https://serverprism.com/api/v1/client): the same as a Pterodactyl panel to the rest of
    Solstone. Its limits: 60 reads and 20 commands a minute per token, so it's asked about the server at most every
    10 seconds, and the game itself (anything that needs the game's reply) stays with RCON."""
    STATS_SECS = 10

    def _url(self, tail: str) -> str:
        from .connections import SERVERPRISM
        return f"{SERVERPRISM}/api/v1/client/servers/{self.cfg['panel_id']}{tail}"

    async def stats(self) -> dict | None:
        if self._stats and time.monotonic() - self._stats[0] < self.STATS_SECS:
            return self._stats[1]
        try:
            r = await self._client.get(self._url(""), headers=self._headers())
            r.raise_for_status()
            a = r.json().get("data") or {}
        except Exception as e:
            self.error = _panel_why(e)
            return self._stats[1] if self._stats else None
        self.error = ""
        res = a.get("resources")
        if not res:                                   # (the node was briefly unreachable: what it said last)
            return self._stats[1] if self._stats else None
        state = res.get("current_state") or ""
        mem = int(res.get("memory_bytes") or 0)
        limit = int((a.get("limits") or {}).get("memory_mb") or 0) * 1024 * 1024
        up = int(res.get("uptime_ms") or 0)
        game = a.get("game") or {}
        out = {"running": state == "running", "state": state, "cpu": round(float(res.get("cpu_absolute") or 0), 1),
               "mem": f"{mem / 1024 ** 3:.1f}GB" if mem >= 1024 ** 3 else f"{mem / 1024 ** 2:.0f}MB",
               "mem_percent": round(mem * 100 / limit, 1) if limit else None,
               "world_size": f"{int(res.get('disk_bytes') or 0) / 1024 ** 3:.1f}GB",
               "started": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - up / 1000)) if up and state == "running" else None,
               "crashed": False, "version": game.get("version") or None, "address": a.get("address") or ""}
        self._stats = (time.monotonic(), out)
        return out

    async def power(self, action: str) -> None:
        if action == "backup_server":
            r = await self._client.post(self._url("/backups"), headers=self._headers(), json={"name": "Solstone"})
            r.raise_for_status()
            return
        signal = {"start_server": "start", "stop_server": "stop", "restart_server": "restart", "kill_server": "kill"}.get(action, action)
        r = await self._client.post(self._url("/power"), headers=self._headers(), json={"signal": signal})
        r.raise_for_status()
        self._stats = None

    async def test(self) -> dict:
        self._stats = None
        st = await self.stats()
        if self._cfg is not None:
            await self._client.aclose()
        if st is None:
            return {"ok": False, "error": self.error or "ServerPrism didn't say how the server is doing"}
        return {"ok": True, "name": self.cfg.get("name") or "", "state": st.get("state", ""), "node": st.get("address", "")}
