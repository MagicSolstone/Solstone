"""🩺 Check: one look at everything a server needs, tried now (Manage → Server setup → a server's 🩺 Check).

Each line: what it is, ok / warn / bad / off (not set up), and what was seen. Nothing is changed: the files are only
looked at, RCON is asked "list", and a server elsewhere is reached over SFTP the same way the mirror does.
"""
from __future__ import annotations

import asyncio
import shutil
import time

from . import servers as S
from .config import config


def _line(name: str, state: str, detail: str) -> dict:
    return {"name": name, "state": state, "detail": detail}


def _ago(ts: float | None) -> str:
    if not ts:
        return "never"
    s = max(0, time.time() - ts)
    return f"{int(s)} s ago" if s < 90 else f"{int(s // 60)} min ago" if s < 5400 else f"{s / 3600:.1f} h ago" if s < 172800 else f"{s / 86400:.0f} days ago"


async def check(srv: S.Server) -> list[dict]:
    out: list[dict] = []
    # where its files are
    if srv.remote:
        from . import remote
        cfg = remote.get(srv.id) or {}
        try:
            conn, sftp, _ident = await remote._connect(cfg)
            try:
                await sftp.stat(remote.posixpath.join(cfg.get("path") or "/", "server.properties"))
                out.append(_line("SFTP", "ok", f"Logged in to {cfg.get('host')} and found server.properties"))
            except Exception:
                out.append(_line("SFTP", "bad", f"Logged in to {cfg.get('host')}, but there's no server.properties in {cfg.get('path') or '/'}"))
            finally:
                conn.close()
        except Exception as e:
            out.append(_line("SFTP", "bad", remote._why(e)))
        m = remote.mirror(srv.id)
        st = m.status if m else {}
        secs = int(cfg.get("files_secs") or remote.FILES_SECS)
        if st.get("ok") is False:
            out.append(_line("Its files here", "bad", f"Not updating: {st.get('error')}"))
        elif st.get("synced") and time.time() - st["synced"] < max(60, secs * 3):
            out.append(_line("Its files here", "ok", f"Up to date (looked {_ago(st['synced'])}; {st.get('files', 0)} files kept)"))
        else:
            out.append(_line("Its files here", "warn", f"Last updated {_ago(st.get('synced'))}"))
    else:
        has = (srv.dir / "server.properties").is_file()
        out.append(_line("Its folder", "ok" if has else "bad", f"{srv.dir.name}: {'server.properties found' if has else 'no server.properties there'}"))
    # the world
    lvl = srv.level()
    if lvl:
        out.append(_line("World", "ok", f"{srv.world_dir.name} (Minecraft {srv.mc_version or '?'})"))
    else:
        out.append(_line("World", "bad", f"No readable level.dat in {srv.world_dir.name}: is level-name in server.properties right?"))
    # running, and what says so
    try:
        stats = await asyncio.wait_for(S._crafty_stats(srv), 15)
    except Exception:
        stats = None
    running = None
    if srv.managed:
        who = "the host's panel" if srv.panel is not None else "Crafty"
        if stats is None:
            err = getattr(srv.panel, "error", "") if srv.panel is not None else ""
            out.append(_line("Start and stop", "bad", f"{who} didn't answer{': ' + err if err else ''}"))
        else:
            running = bool(stats.get("running"))
            cpu, mem = stats.get("cpu"), stats.get("mem")
            out.append(_line("Start and stop", "ok", f"{who} says it's {'running' if running else 'stopped'}"
                             + (f" (CPU {cpu:.0f}%, memory {mem})" if running and isinstance(cpu, (int, float)) and mem else "")))
    else:
        out.append(_line("Start and stop", "off", "Nothing set up to start or stop it (Crafty, or a host's panel under Connections)"))
    # RCON
    if not srv.rcon_conf():
        out.append(_line("RCON", "off", "Not set up: no commands, who's online live, or games"))
    else:
        try:
            reply = await asyncio.wait_for(srv.rcon("list"), 15)
            out.append(_line("RCON", "ok", f"Answered: {(reply or '').strip()[:120] or '(empty reply)'}"))
        except Exception as e:
            out.append(_line("RCON", "warn" if running is False else "bad",
                             ("The server is stopped, so RCON can't answer" if running is False else f"No answer: {e}")))
    # the log
    log = srv.dir / "logs" / "latest.log"
    if log.is_file():
        out.append(_line("Log", "ok", f"latest.log, written {_ago(log.stat().st_mtime)}"))
    else:
        out.append(_line("Log", "warn", "No logs/latest.log yet (the activity feed reads it)"))
    # the map
    from . import worldmap
    d = worldmap.region_dir(srv.world_dir, "minecraft:overworld")
    n = sum(1 for _ in d.glob("r.*.*.mca")) if d else 0
    if srv.remote:
        from . import remote
        cfg = remote.get(srv.id) or {}
        m = remote.mirror(srv.id)
        mp = (m.status.get("map") if m else None) or {}
        if cfg.get("map", True) is False:
            out.append(_line("Map", "off", "Turned off"))
        elif mp.get("no_folder"):
            out.append(_line("Map", "bad", f"No world folder found on the server for {', '.join(mp['no_folder'])}"))
        elif m and m.status.get("error_the map"):
            out.append(_line("Map", "bad", m.status["error_the map"]))
        else:
            out.append(_line("Map", "ok" if n else "warn", f"{n} areas here to draw" + (f"; {mp.get('queued', 0)} waiting" if mp else "")))
    else:
        out.append(_line("Map", "ok" if n else "warn", f"{n} areas to draw" if n else "No region files found for the Overworld yet"))
    # the web map (BlueMap...), if one is set: does it answer where Solstone looks for it
    url = srv.settings.get("map_url")
    if url:
        import httpx
        try:
            async with httpx.AsyncClient(timeout=8, verify=False, follow_redirects=True) as c:
                r = await c.get(url)
            ok = r.status_code < 400
            out.append(_line("Web map", "ok" if ok else "bad", f"{url} answered" + ("" if ok else f" HTTP {r.status_code}")
                             + (" (shown through Solstone)" if srv.settings.get("map_proxy") else "")))
        except Exception as e:
            out.append(_line("Web map", "bad", f"Nothing answered at {url} ({type(e).__name__}): is BlueMap running, and its web server on that port?"))
    # the full copy, and room for it
    free = shutil.disk_usage(config.data_dir).free
    if srv.remote:
        from . import remote
        m = remote.mirror(srv.id)
        b = m.backup_status() if m else {}
        last = b.get("last") or {}
        if b.get("saving_paused"):
            out.append(_line("Full copy", "bad", "The game's saving is still paused from a full copy (RCON didn't answer save-on): Solstone keeps trying"))
        elif not b.get("on"):
            out.append(_line("Full copy", "off", "Not turned on" + (f" (last one {_ago(last.get('finished'))})" if last.get("finished") else "")))
        elif b.get("running"):
            out.append(_line("Full copy", "ok", "Running now"))
        elif not last.get("finished"):
            out.append(_line("Full copy", "warn", "On, but none yet"))
        elif not last.get("ok"):
            out.append(_line("Full copy", "bad", f"The last one ({_ago(last['finished'])}) didn't finish: {last.get('error')}"))
        elif time.time() - last["finished"] > 36 * 3600:
            out.append(_line("Full copy", "warn", f"The last good one was {_ago(last['finished'])}"))
        else:
            out.append(_line("Full copy", "warn" if last.get("warning") else "ok",
                             f"Last one {_ago(last['finished'])}: {last.get('files')} files, checked" + (f". {last['warning']}" if last.get("warning") else "")))
        need = (last.get("total_bytes") or 0) // 5           # (room to spare: a fifth of the copy again)
        state = "bad" if free < max(need, 512 * 1024 * 1024) else "warn" if free < max(need * 2, 2 * 1024 ** 3) else "ok"
    else:
        state = "bad" if free < 512 * 1024 * 1024 else "warn" if free < 2 * 1024 ** 3 else "ok"
    out.append(_line("Room for Solstone", state, f"{free / 1024 ** 3:.1f} GB free in its data folder"))
    return out
