"""Background recorder: play sessions, server metrics/TPS and the activity feed.

Two loops run inside the web process:
  - every POLL_INTERVAL seconds: who's online (sessions), CPU/RAM/players,
    TPS via RCON `tick query`, and server start/stop transitions;
  - every few seconds: new lines in each server's logs/latest.log become
    events (joins, leaves, chat, deaths, advancements) and notifications.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import time
from datetime import datetime, timedelta

from . import backups, board, db, fwshow, guard, music, notify, recap
from . import servers as S
from .logparse import parse_line
from .notify import maybe_notify
from .rcon import RconError

log = logging.getLogger("solstone.recorder")

POLL_INTERVAL = float(os.getenv("POLL_INTERVAL", "30"))
LOG_INTERVAL = float(os.getenv("LOG_INTERVAL", "5"))
GUARD_INTERVAL = float(os.getenv("GUARD_INTERVAL", "10"))
METRICS_DAYS = int(os.getenv("METRICS_RETENTION_DAYS", "30"))
EVENTS_DAYS = int(os.getenv("EVENTS_RETENTION_DAYS", "180"))
NOTIFY_MAX_AGE = 120  # don't push notifications for log lines older than this (restarts, backfill)
MAX_READ = 4 * 1024 * 1024

_MEM = re.compile(r"([\d.]+)\s*([KMGT]i?B)", re.I)
_TICK_TARGET = re.compile(r"Target tick rate:\s*([\d.]+)", re.I)
_CLOCK = re.compile(r"^\[(\d{2}):(\d{2}):(\d{2})")
_TICK_AVG = re.compile(r"Average time per tick:\s*([\d.]+)\s*ms", re.I)


BYTES_THRESHOLD = 100_000  # a bare number this large can't be MB (that'd be ~100 GB of heap); it's bytes


def parse_mem_mb(v) -> float | None:
    """Crafty reports memory either as text ("1.6GB") or, depending on version, a bare byte count."""
    if v is None or v == "":
        return None
    if isinstance(v, str) and re.fullmatch(r"\s*[\d.]+\s*", v):
        v = float(v)
    if isinstance(v, (int, float)):
        v = float(v)
        return round(v / 1048576, 1) if v > BYTES_THRESHOLD else v
    m = _MEM.search(str(v))
    if not m:
        return None
    n, unit = float(m.group(1)), m.group(2).upper().replace("I", "")
    return round(n * {"KB": 1 / 1024, "MB": 1, "GB": 1024, "TB": 1024 * 1024}[unit], 1)


def parse_tick_query(out: str) -> tuple[float | None, float | None]:
    """`tick query` (1.20.3+) -> (tps, mspt)."""
    avg = _TICK_AVG.search(out or "")
    if not avg:
        return None, None
    target = _TICK_TARGET.search(out)
    target_tps = float(target.group(1)) if target else 20.0
    mspt = float(avg.group(1))
    tps = min(target_tps, 1000.0 / mspt) if mspt > 0 else target_tps
    return round(tps, 2), round(mspt, 2)


def _f(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


class Recorder:
    def __init__(self) -> None:
        self._tasks: list[asyncio.Task] = []
        self._running_state: dict[str, bool] = {}
        self._tick_ok: dict[str, bool] = {}
        self.last_poll: float | None = None
        self.errors: dict[str, str] = {}   # server id -> last recorder error (cleared on success)
        self.started: float | None = None
        self._levels: dict[tuple[str, str], int] = {}  # (server, player) -> last seen level
        self._night: dict[str, bool] = {}
        self._offsets: dict[str, float] = {}     # server id -> seconds its log clock is ahead

    def start(self) -> None:
        self.started = time.time()
        db.close_stale_sessions(POLL_INTERVAL * 3)
        self._tasks = [asyncio.create_task(self._loop(self.poll_all, POLL_INTERVAL)),
                       asyncio.create_task(self._loop(self.tail_all, LOG_INTERVAL)),
                       asyncio.create_task(self._loop(self.prune, 6 * 3600)),
                       asyncio.create_task(self._loop(self.guard, GUARD_INTERVAL)),
                       asyncio.create_task(self._loop(self.recaps, 3600)),
                       asyncio.create_task(self._loop(self.music_scan, 6 * 3600))]

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    async def _loop(self, fn, interval: float) -> None:
        while True:
            try:
                await fn()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("%s failed", fn.__name__)
            await asyncio.sleep(interval)

    async def guard(self) -> None:
        await S.registry.refresh()
        visible = [s for s in S.registry.servers.values() if not s.settings.get("hidden")]
        await guard.tick(visible)
        await board.tick(visible)

    async def music_scan(self) -> None:
        """Keep the external music library's index up to date (new albums, changed tags)."""
        if music.external_root():
            await asyncio.to_thread(music.scan)

    async def recaps(self) -> None:
        """Summarise finished days, and once per server read its old logs for the days before Solstone."""
        await asyncio.sleep(20)            # let the first poll and log read land first
        await S.registry.refresh()
        for srv in list(S.registry.servers.values()):
            try:
                await asyncio.to_thread(recap.finalize, srv.id)
                if srv.is_java and db.alert_once(f"recap-backfill:{srv.id}"):
                    known = {p["name"].lower(): u for u, p in S.known_players(srv).items()}
                    n = await asyncio.to_thread(recap.backfill, srv.id, srv.dir, known)
                    if n:
                        log.info("Filled in %d days of history for %s from old logs", n, srv.id)
            except Exception:
                log.exception("recap failed for %s", srv.id)

    async def prune(self) -> None:
        db.prune(METRICS_DAYS, EVENTS_DAYS)

    # ------------------------------------------------------------ polling
    async def poll_all(self) -> None:
        await S.registry.refresh()
        servers = list(S.registry.servers.values())
        results = await asyncio.gather(*(self.poll_server(s) for s in servers), return_exceptions=True)
        for srv, r in zip(servers, results, strict=True):
            if isinstance(r, Exception):
                self.errors[srv.id] = f"{type(r).__name__}: {r}"
                log.warning("Recording %s failed: %s", srv.id, self.errors[srv.id], exc_info=r)
            else:
                self.errors.pop(srv.id, None)
        self.last_poll = time.time()
        try:
            await self.check_alerts(servers)
        except Exception:
            log.exception("alert checks failed")

    async def check_alerts(self, servers: list) -> None:
        """Screen-time limits, the weekly digest and overdue backups."""
        c = notify.get_config()
        channels = bool(c["ntfy_url"] or c["discord_webhook"])
        zone = db.tz()
        now = datetime.now(zone)
        today = now.date().isoformat()

        if c["limits"] and channels:
            totals: dict[str, int] = {}
            display: dict[str, str] = {}
            for srv in servers:
                for row in db.daily_playtime(srv.id, 1)[0]["players"].items():
                    name, secs = row
                    totals[name.lower()] = totals.get(name.lower(), 0) + secs
                    display.setdefault(name.lower(), name)
            for key, secs, limit in notify.screen_time_due(totals, c["limits"]):
                if db.alert_once(f"limit:{key}:{today}"):
                    name = display.get(key, key)
                    await notify.send("Screen time", f"{name} has played {notify._fmt(secs)} today "
                                      f"(daily limit {notify._fmt(limit * 60)})", notify.TAGS["screen_time"])

        if c["digest_enabled"] and channels and now.weekday() == c["digest_day"] and now.hour >= c["digest_hour"]:
            week = now.isocalendar()
            if db.alert_once(f"digest:{week.year}-{week.week}"):
                await notify.send("Solstone weekly digest", self.digest(servers), notify.TAGS["digest"])

        if "backup" in c["events"] and channels:
            for srv in servers:
                b = backups.status(srv)
                if b.get("found") and b.get("stale") and db.alert_once(f"backup:{srv.id}:{today}"):
                    await notify.send(srv.display_name, f"No new backup for {int(b['age_hours'])} hours "
                                      f"(last: {b['latest']['name']})", notify.TAGS["backup"])

    @staticmethod
    def digest(servers: list) -> str:
        return notify.digest_text([(s.display_name, db.week_stats(s.id)) for s in servers if not s.settings.get("hidden")])

    def status(self, server_id: str) -> dict:
        return {"running": bool(self._tasks), "started": self.started, "last_poll": self.last_poll,
                "interval": POLL_INTERVAL, "error": self.errors.get(server_id)}

    async def poll_server(self, srv: S.Server) -> None:
        now = time.time()
        stats = await S._crafty_stats(srv) if srv.crafty else None
        names, source = await S.online_players(srv)
        if srv.crafty:
            running = bool(stats and stats.get("running"))
        else:
            running = source == "rcon"  # without Crafty, a working RCON is the best "it's up" signal

        tps = mspt = None
        if running and srv.rcon_conf() and self._tick_ok.get(srv.id, True):
            try:
                out = await srv.rcon("tick query")
                tps, mspt = parse_tick_query(out or "")
                if tps is None and out and "Unknown" in out:
                    self._tick_ok[srv.id] = False  # pre-1.20.3 server; stop asking
            except RconError:
                pass

        stats = stats or {}
        db.add_metric(srv.id, now, running, len(names) if running else 0, _f(stats.get("cpu")) if running else None,
                      parse_mem_mb(stats.get("mem")) if running else None, _f(stats.get("mem_percent")) if running else None,
                      tps, mspt)

        name_to_uuid = {p["name"].lower(): u for u, p in S.known_players(srv).items()}
        online = {n: name_to_uuid.get(n.lower()) for n in names} if running else {}
        joined, left = db.update_sessions(srv.id, online, now)

        # Joins/leaves come from the log when we can read it (exact times, no 30s lag);
        # otherwise the poll is the source.
        if not srv.is_java or not self._log_path(srv).is_file():
            for n in joined:
                self._event(srv, now, "join", f"{n} joined the game", n, online.get(n))
            for n in left:
                self._event(srv, now, "leave", f"{n} left the game", n, name_to_uuid.get(n.lower()))
        # Join fireworks from the online check too, in case the log line was missed or its
        # clock is off (each join sets off one firework, whichever notices first).
        if self._running_state.get(srv.id) is not None:
            for n in joined:
                if not fwshow.pushed_recently(srv.id, "join", n):
                    fwshow.push(srv.id, srv.display_name, "join", n, f"{n} joined the game")

        if running and names and srv.is_java and srv.rcon_conf():
            await self._watch_game(srv, names)

        prev = self._running_state.get(srv.id)
        if prev is not None and prev != running:
            if running:
                self._event(srv, now, "server", "Server started")
                fwshow.push(srv.id, srv.display_name, "start", None, f"{srv.display_name} started")
            else:
                self._event(srv, now, "server", "Server crashed" if stats.get("crashed") else "Server stopped")
        self._running_state[srv.id] = running

    async def _watch_game(self, srv: S.Server, names: list[str]) -> None:
        """Level milestones and nightfall, for fireworks (levels also go in the activity feed)."""
        every = fwshow.events_cfg()["level"]["every"]
        try:
            lives = await asyncio.gather(*(S.live_player(srv, n) for n in names), return_exceptions=True)
        except Exception:
            lives = []
        for n, live in zip(names, lives, strict=False):
            if not isinstance(live, dict):
                continue
            key, lvl = (srv.id, n.lower()), int(live.get("xp_level") or 0)
            before = self._levels.get(key)
            self._levels[key] = lvl
            if before is not None and lvl > before and lvl // every > before // every:
                msg = f"{n} reached level {lvl // every * every}"
                self._event(srv, time.time(), "level", msg, n, None, notify=False)
                fwshow.push(srv.id, srv.display_name, "level", n, msg)
        try:
            w = await S.live_world(srv)
        except Exception:
            return
        t = w.get("time_of_day")
        if t is None:
            return
        night = 13000 <= t < 23000
        if self._night.get(srv.id) is False and night:
            fwshow.push(srv.id, srv.display_name, "night", None, f"Night falls on {srv.display_name}")
        self._night[srv.id] = night

    def _event(self, srv: S.Server, ts: float, etype: str, message: str, player: str | None = None,
               uuid: str | None = None, notify: bool = True) -> None:
        db.add_event(srv.id, ts, etype, message, player, uuid)
        if notify:
            maybe_notify(etype, srv.display_name, message)

    # ------------------------------------------------------------ log tailing
    @staticmethod
    def _log_path(srv: S.Server):
        return srv.dir / "logs" / "latest.log"

    async def tail_all(self) -> None:
        await S.registry.refresh()
        for srv in list(S.registry.servers.values()):
            try:
                # File reading happens in a thread; notifications need the event loop, so send them here.
                for etype, message in await asyncio.to_thread(self.tail_server, srv):
                    maybe_notify(etype, srv.display_name, message)
                    if etype == "join":
                        await board.greet(srv, message.split(" ", 1)[0])
            except Exception:
                log.exception("log tail failed for %s", srv.id)

    def _log_offset(self, sid: str, text: str, mtime: float, now: datetime) -> float:
        """The server may write its log in another time zone than Solstone's (Crafty's container
        on UTC, say). The newest line was written when the file last changed, so the gap between
        its clock and the file's time is that difference, rounded to a quarter of an hour."""
        if time.time() - mtime < 120:
            last = None
            for line in reversed(text.splitlines()[-50:]):
                m = _CLOCK.match(line)
                if m:
                    last = m
                    break
            if last:
                h, mi, se = (int(x) for x in last.groups())
                t = now.replace(hour=h, minute=mi, second=se, microsecond=0)
                if t > now + timedelta(seconds=60):
                    t -= timedelta(days=1)
                gap = t.timestamp() - mtime
                self._offsets[sid] = round(gap / 900) * 900 if abs(gap) >= 600 else 0
        return self._offsets.get(sid, 0)

    def tail_server(self, srv: S.Server) -> list[tuple[str, str]]:
        """Read new log lines into events. Returns (type, message) pairs to notify about."""
        if not srv.is_java:
            return []  # other games log in their own formats
        path = self._log_path(srv)
        state = db.get_log_state(srv.id)
        try:
            st = path.stat()
            with path.open("rb") as fh:
                first = fh.read(256)
        except OSError:
            return []

        def head_of(n: int) -> str:
            return f"{n}:{hashlib.sha1(first[:n]).hexdigest()}"

        # Identify the file by its first bytes (inode numbers are unreliable on some
        # bind mounts). Compare over the length we hashed last time, since a short
        # log keeps growing.
        same_file = False
        if state and state["head"] and ":" in state["head"]:
            n = int(state["head"].split(":", 1)[0])
            same_file = len(first) >= n and head_of(n) == state["head"]
        head = head_of(len(first))
        if same_file and st.st_size >= state["offset"]:
            offset = state["offset"]
        else:
            offset = 0  # new install or the log rotated: read the new file from the start
        if offset == st.st_size:
            if not state:
                db.set_log_state(srv.id, st.st_ino, offset, head)
            return []
        with path.open("rb") as fh:
            fh.seek(offset)
            chunk = fh.read(MAX_READ)
        end = chunk.rfind(b"\n")
        if end < 0:
            return []
        chunk = chunk[: end + 1]
        new_offset = offset + len(chunk)

        known = {p["name"].lower(): u for u, p in S.known_players(srv).items()}
        names = set(known)
        zone = db.tz()
        now = datetime.now(zone)
        text = chunk.decode("utf-8", errors="replace")
        offset = self._log_offset(srv.id, text, st.st_mtime, now)
        pending: list[tuple[str, str]] = []
        for raw in text.splitlines():
            ev = parse_line(raw, names)
            if not ev or ev.type == "server":  # start/stop comes from Crafty's state instead
                continue
            if ev.player:
                names.add(ev.player.lower())
            ts_dt = now.replace(hour=ev.hour, minute=ev.minute, second=ev.second, microsecond=0)
            if ts_dt > now + timedelta(seconds=60):
                ts_dt -= timedelta(days=1)
            ts = ts_dt.timestamp() - offset
            fresh = time.time() - ts < NOTIFY_MAX_AGE
            uuid = known.get(ev.player.lower()) if ev.player else None
            db.add_event(srv.id, ts, ev.type, ev.message, ev.player, uuid)
            if fresh and ev.type != "chat":
                pending.append((ev.type, ev.message))
            if fresh and time.time() - ts < 90:            # fireworks only for things happening now
                if ev.type == "join":
                    if not fwshow.pushed_recently(srv.id, "join", ev.player):
                        fwshow.push(srv.id, srv.display_name, "join", ev.player, ev.message)
                elif ev.type == "advancement":
                    fwshow.push(srv.id, srv.display_name, fwshow.advancement_kind(ev.message), ev.player, ev.message)
                elif ev.type == "death":
                    fwshow.push(srv.id, srv.display_name, "death", ev.player, ev.message)
        db.set_log_state(srv.id, st.st_ino, new_offset, head)
        return pending


recorder = Recorder()
