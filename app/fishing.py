"""Solstone's side of the fishing pack: is it in the world, install or reload it, and read the
catches it records so the web pages can show them and fishing contests can announce them."""
from __future__ import annotations

import logging
import re
import time

from . import db, fishpack
from . import servers as S
from .control import component
from .rcon import RconError

log = logging.getLogger("solstone.fishing")
QUALITY_COLOR = {0: "gray", 1: "white", 2: "green", 3: "aqua", 4: "gold"}
_state: dict[str, dict] = {}            # server id -> {"version", "checked", "last", "error"}


async def _rcon(srv, cmd: str) -> str:
    try:
        return await srv.rcon(cmd) or ""
    except RconError as e:
        raise RuntimeError(str(e)) from e


async def check(srv, force: bool = False) -> dict:
    """Is the pack loaded in this world? (Asked over RCON at most every 5 minutes.)"""
    st = _state.setdefault(srv.id, {"version": None, "checked": 0, "last": None, "error": ""})
    if not force and time.time() - st["checked"] < 300:
        return st
    st["checked"] = time.time()
    if not srv.rcon_conf():
        st.update(version=None, error="RCON is off")
        return st
    try:
        out = await _rcon(srv, "data get storage solstone:fish pack")
        m = re.search(r"version:\s*(\d+)", out)
        st.update(version=int(m.group(1)) if m else None, error="")
    except RuntimeError as e:
        st["error"] = str(e)
    return st


def datapacks_dir(srv):
    return srv.world_dir / "datapacks"


def writable(srv) -> bool:
    d = datapacks_dir(srv)
    try:
        d.mkdir(parents=True, exist_ok=True)
        probe = d / ".solstone-write-test"
        probe.write_bytes(b"")
        probe.unlink()
        return True
    except OSError:
        return False


async def install(srv) -> dict:
    """Write the pack into the world (only if that folder is writable), reload, check."""
    if writable(srv):
        (datapacks_dir(srv) / fishpack.PACK_FILE).write_bytes(fishpack.build_zip())
    return await reload(srv)


def _log_size(srv) -> int:
    try:
        return (srv.dir / "logs" / "latest.log").stat().st_size
    except OSError:
        return 0


def _log_problems(srv, since: int) -> list[str]:
    """Lines the game logged since `since` that look like it complaining about a data pack."""
    try:
        with (srv.dir / "logs" / "latest.log").open("rb") as fh:
            fh.seek(since)
            text = fh.read(400_000).decode("utf-8", "replace")
    except OSError:
        return []
    keys = ("solstone", "solfish", "solgames", "loot_table", "loot table", "gameplay/fishing", "couldn't parse", "failed to", "error")
    out = []
    for line in text.splitlines():
        low = line.lower()
        if ("/error]" in low or "/warn]" in low) and any(k in low for k in keys):
            out.append(line.strip()[:400])
    return out[:20]


async def reload(srv) -> dict:
    import asyncio
    before = _log_size(srv)
    out = await _rcon(srv, "reload")
    await _rcon(srv, f'datapack enable "file/{fishpack.PACK_FILE}"')        # in case it was added disabled
    listed = await _rcon(srv, "datapack list enabled")
    st = await check(srv, force=True)
    st["listed"] = fishpack.PACK_FILE in listed or fishpack.PACK_ID in listed
    st["reload_reply"] = out[:200]
    await asyncio.sleep(1.5)                          # let the game finish writing its log
    st["problems"] = _log_problems(srv, before)
    return st


async def test_catch(srv) -> dict:
    """Fish once from the real fishing table at spawn and say what came out: the plainest way to
    see whether the pack's fish are being used."""
    import nbtlib

    w = await __import__("asyncio").to_thread(S.world_info, srv, False)
    sp = w.get("spawn") or {"x": 0, "y": 64, "z": 0}
    x, z = int(sp["x"]), int(sp["z"])
    sel = f"@e[type=item,x={x}.5,y=330,z={z}.5,distance=..4]"
    await _rcon(srv, f"kill {sel}")
    out = await _rcon(srv, f"execute in minecraft:overworld run loot spawn {x}.5 330 {z}.5 fish minecraft:gameplay/fishing/fish {x} {int(sp.get('y', 64))} {z} minecraft:fishing_rod")
    got = await _rcon(srv, f"data get entity {sel.replace(']', ',limit=1]')} Item")
    await _rcon(srv, f"kill {sel}")
    res = {"command_reply": out[:300], "item_reply": got[:600], "item": None, "pack_fish": None}
    if "{" in got:
        try:
            item = nbtlib.parse_nbt(got[got.index("{"):].strip())
            res["item"] = str(item.get("id"))
            fish = (item.get("components") or {}).get("minecraft:custom_data", {}).get("solfish")
            if fish:
                res["pack_fish"] = {"name": str(fish["n"]), "quality": str(fish["ql"]), "lb": str(fish["lb"]), "points": int(fish["p"])}
        except Exception as e:
            res["parse_error"] = str(e)[:200]
    return res


def _names(srv) -> dict[str, str]:
    return {u.lower(): p["name"] for u, p in S.known_players(srv).items()}


def describe(c: dict, name: str) -> str:
    article = "an" if c["quality_name"][0] in "AEIOU" or (c["quality"] == 1 and c["name"][0] in "AEIOU") else "a"
    fish = c["name"] if c["quality"] == 1 else f"{c['quality_name']} {c['name']}"
    return f"{name} caught {article} {fish} · {c['lb']} lb · {c['points']} points"


async def poll(servers: list) -> None:
    """Read new catches (every few seconds while people are on): record them, tell the contest."""
    from . import challenges
    for srv in servers:
        if not srv.is_java or not srv.rcon_conf():
            continue
        st = await check(srv)
        if not st.get("version"):
            continue
        names, _src = await S.online_players(srv)
        if not names:
            continue
        try:
            got = fishpack.parse_catches(await _rcon(srv, "data get storage solstone:fish catches"))
        except RuntimeError:
            continue
        if not got:
            continue
        newest = max(c["i"] for c in got)
        if st["last"] is None or newest < st["last"]:          # first look since starting (or the world was reset)
            st["last"] = newest
            continue
        fresh = [c for c in got if c["i"] > st["last"]]
        st["last"] = newest
        lookup = _names(srv)
        for c in sorted(fresh, key=lambda c: c["i"]):
            who = lookup.get(c["uuid"].lower(), "Someone")
            c["player"] = who
            # Prime and Exquisite get their own type so the status page's feed shows only those
            db.add_event(srv.id, time.time(), "bigfish" if c["quality"] >= 3 else "fish", describe(c, who), who if who != "Someone" else None)
            contest = await challenges.on_catch(srv, who, c)
            if not contest and c["quality"] >= 3:               # Prime and Exquisite are news anyway
                fish = f"{c['quality_name']} {c['name']}"
                size = f" ({c['lb']} lb)!"
                try:
                    await _rcon(srv, f"tellraw @a {component([('★ ', 'gold'), (who, 'aqua'), (' caught a ', None), (fish, QUALITY_COLOR[c['quality']]), (size, None)])}")
                except RuntimeError:
                    pass


def status(srv) -> dict:
    st = _state.get(srv.id) or {}
    return {"version": st.get("version"), "current": fishpack.VERSION, "error": st.get("error", ""),
            "writable": writable(srv), "file": fishpack.PACK_FILE, "folder": str(datapacks_dir(srv))}
