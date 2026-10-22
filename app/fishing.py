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


def files(srv) -> list[dict]:
    """What's actually in the world's datapacks folder, and which version of the Solstone pack
    each one is (read from its load function): two copies, or an old one, explain a lot."""
    import zipfile
    d = datapacks_dir(srv)
    out = []
    try:
        entries = sorted(d.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        return out
    for p in entries[:60]:
        if p.name.startswith("."):
            continue
        row = {"name": p.name, "folder": p.is_dir(), "version": None, "fish_table": False, "nested": False}
        try:
            row["modified"] = p.stat().st_mtime
            if p.is_dir():
                names = [str(x.relative_to(p)).replace("\\", "/") for x in p.rglob("*") if x.is_file()][:5000]
                read = lambda n, p=p: (p / n).read_text("utf-8", "replace")  # noqa: E731
            elif p.suffix.lower() == ".zip":
                z = zipfile.ZipFile(p)
                names = z.namelist()
                read = lambda n, z=z: z.read(n).decode("utf-8", "replace")  # noqa: E731
            else:
                out.append(row)
                continue
            load = next((n for n in names if n.endswith("data/solfish/function/load.mcfunction")), None)
            if load:
                m = re.search(r"version:\s*(\d+)", read(load))
                row["version"] = int(m.group(1)) if m else 0
                row["nested"] = load != "data/solfish/function/load.mcfunction"      # zipped inside an extra folder
            row["fish_table"] = any(n.endswith("data/minecraft/loot_table/gameplay/fishing/fish.json") for n in names)
            row["mcmeta"] = "pack.mcmeta" in names
        except (OSError, zipfile.BadZipFile, ValueError) as e:
            row["error"] = str(e)[:120]
        out.append(row)
    return out


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
    st["packs"] = (listed + "\n" + await _rcon(srv, "datapack list available"))[:2000]
    await asyncio.sleep(1.5)                          # let the game finish writing its log
    st["problems"] = _log_problems(srv, before)
    return st


def _read_item(reply: str) -> dict:
    """The first item in a `data get block ... Items` reply: its id, and the pack's fish data if any."""
    import nbtlib

    res = {"item": None, "pack_fish": None, "named": None}
    if "[" not in reply:
        return res
    try:
        items = nbtlib.parse_nbt(reply[reply.index("["):].strip())
        if not len(items):
            return res
        item = items[0]
        res["item"] = str(item.get("id"))
        comps = item.get("components") or {}
        nm = comps.get("minecraft:item_name") or comps.get("minecraft:custom_name")
        res["named"] = (str(nm.get("text", "")) if hasattr(nm, "get") else str(nm)) if nm is not None else None
        data = comps.get("minecraft:custom_data", {})
        fish = data.get("solfish")
        if fish:
            res["pack_fish"] = {"name": str(fish["n"]), "quality": str(fish["ql"]), "lb": str(fish["lb"]), "points": int(fish["p"])}
        res["probe"] = bool(hasattr(data, "get") and data.get("solprobe"))
    except Exception as e:
        res["parse_error"] = str(e)[:200]
    return res


async def test_catch(srv) -> dict:
    """Roll the tables into a barrel (put up at the top of the world for a moment, so there's
    nothing to fall or get picked up) and read exactly what came out:
    the vanilla-named fish table, the pack's own copy, a one-line probe table (do the pack's
    loot functions work at all?), and the rod's whole table a few times."""
    from .races import _pos
    names, _src = await S.online_players(srv)
    forced = None
    q = await _pos(srv, names[0]) if names else None
    if q:
        pre, where = f"execute at {names[0]}", f"at {names[0]}"
        x, y, z = int(q[0] // 1), int(q[1] // 1), int(q[2] // 1)
    else:
        w = await __import__("asyncio").to_thread(S.world_info, srv, False)
        sp = w.get("spawn") or {"x": 0, "y": 64, "z": 0}
        x, y, z = int(sp["x"]), int(sp.get("y", 64)), int(sp["z"])
        forced = (x, z)
        pre, where = "execute in minecraft:overworld", "at spawn"
        await _rcon(srv, f"{pre} run forceload add {x} {z}")
    top = 319
    placed = await _rcon(srv, f"{pre} run setblock {x} {top} {z} minecraft:barrel")

    async def roll(kind: str, table: str) -> dict:
        src = f"fish {table} {x} {y} {z} minecraft:fishing_rod" if kind == "fish" else f"loot {table}"
        out = await _rcon(srv, f"{pre} run loot replace block {x} {top} {z} container.0 {src}")
        got = await _rcon(srv, f"{pre} run data get block {x} {top} {z} Items")
        await _rcon(srv, f"{pre} run item replace block {x} {top} {z} container.0 with minecraft:air")
        return {"table": table, "command_reply": out[:300], "item_reply": got[:600], **_read_item(got)}

    try:
        fish = await roll("fish", "minecraft:gameplay/fishing/fish")
        own = await roll("fish", "solfish:fish")
        probe = await roll("loot", "solfish:probe")
        probes: dict = {}
        rod = [await roll("fish", "minecraft:gameplay/fishing") for _ in range(4)]
    finally:
        await _rcon(srv, f"{pre} run setblock {x} {top} {z} minecraft:air")
        if forced:
            await _rcon(srv, f"{pre} run forceload remove {forced[0]} {forced[1]}")
    packs = await _rcon(srv, "datapack list enabled")
    return {**fish, "where": where, "barrel": placed[:200], "rod": rod, "own": own, "probe": probe, "probes": probes, "packs": packs[:1500],
            "version": (await check(srv, force=True)).get("version"), "log": _log_mentions(srv)}


def _log_mentions(srv) -> list[str]:
    """Every line in the game's current log about our pack or loot tables, at any level (startup
    errors scroll by unnoticed)."""
    try:
        with (srv.dir / "logs" / "latest.log").open("rb") as fh:
            fh.seek(max(0, fh.seek(0, 2) - 3_000_000))
            text = fh.read().decode("utf-8", "replace")
    except OSError:
        return []
    keys = ("solstone", "solfish", "solgames", "loot_table", "loot table", "gameplay/fishing", "couldn't parse", "failed to parse", "validation problem")
    return [ln.strip()[:400] for ln in text.splitlines() if any(k in ln.lower() for k in keys) and "rcon" not in ln.lower()][-30:]


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
            "writable": writable(srv), "file": fishpack.PACK_FILE, "folder": str(datapacks_dir(srv)), "files": files(srv)}
