"""Notices when the website stops answering for a while, and writes down why.

Solstone is one process: if something holds up its main loop (a slow disk read, say, while the server's disks
are busy), every page waits behind it, and from outside the site looks down. A small thread watches the loop's
heartbeat; when it stops for a few seconds, the log gets a warning with what the loop was doing at that moment,
and another line when it's going again. Slow requests are logged too (see main.py).
"""
from __future__ import annotations

import asyncio
import logging
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor

log = logging.getLogger("solstone.watchdog")

STALL_SECONDS = 3.0
SLOW_REQUEST_SECONDS = 5.0
# Background work handed to threads (file reads, RCON, sign-in checks...). Python's default pool is small
# (cpu count + 4), so a burst of slow jobs could leave every page waiting for a free thread.
POOL_THREADS = 64


async def _heartbeat(beat: list[float]) -> None:
    while True:
        beat[0] = time.monotonic()
        await asyncio.sleep(0.5)


def _watch(loop: asyncio.AbstractEventLoop, loop_thread: int, beat: list[float]) -> None:
    stalled_since = None
    while not loop.is_closed():
        time.sleep(1)
        behind = time.monotonic() - beat[0]
        if behind > STALL_SECONDS and stalled_since is None:
            stalled_since = time.monotonic() - behind
            frame = sys._current_frames().get(loop_thread)
            where = "".join(traceback.format_stack(frame)[-8:]) if frame else "(unknown)"
            log.warning("The website has been held up for %.0f s. It was busy with:\n%s", behind, where)
        elif behind <= STALL_SECONDS and stalled_since is not None:
            log.warning("The website is answering again after %.0f s", time.monotonic() - stalled_since)
            stalled_since = None


def start() -> None:
    """Call from inside the running event loop (the app's startup)."""
    loop = asyncio.get_running_loop()
    loop.set_default_executor(ThreadPoolExecutor(max_workers=POOL_THREADS, thread_name_prefix="solstone"))
    beat = [time.monotonic()]                  # this loop's last heartbeat
    loop.create_task(_heartbeat(beat))
    threading.Thread(target=_watch, args=(loop, threading.get_ident(), beat), daemon=True, name="watchdog").start()
