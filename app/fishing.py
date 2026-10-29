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
QUALITY_COLOR = {0: "gray", 1: "white", 2: "green", 3: "aqua", 4: "gold", 5: "light_purple"}
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
        if not m:
            # Loaded but never started? The game's shared start-up list (#minecraft:load) can be dropped whole when
            # another pack or mod's entry in it is broken: start the pack ourselves. "Unknown function": not loaded.
            replies = [await _rcon(srv, f"function {ns}:load") for ns in ("solfish", "solgames")]
            st["load_reply"] = " / ".join(r.strip()[:120] for r in replies if r)
            out = await _rcon(srv, "data get storage solstone:fish pack")
            m = re.search(r"version:\s*(\d+)", out)
            st["started_by_solstone"] = bool(m)
        st.update(version=int(m.group(1)) if m else None, error="")
    except RuntimeError as e:
        st["error"] = str(e)
    return st


def new_format(srv) -> bool:
    try:
        dv = srv.level().get("DataVersion")
    except Exception:
        dv = None
    return fishpack.new_loot_format(srv.mc_version, int(dv) if dv else None)


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
            fish = next((n for n in names if n.endswith("data/minecraft/loot_table/gameplay/fishing/fish.json")), None)
            row["fish_table"] = bool(fish)
            if fish:
                row["loot_format"] = "26.3" if '"modifier"' in read(fish) else "older"
            row["mcmeta"] = "pack.mcmeta" in names
        except (OSError, zipfile.BadZipFile, ValueError) as e:
            row["error"] = str(e)[:120]
        out.append(row)
    return out


def available(srv) -> str | None:
    """What this server fishes with, for showing the Fishing tab: "tide" (the mod), "pack" (the
    Solstone data pack is in the world, or catches from it were recorded), or None (plain vanilla:
    no Fishing tab; the plain fishing contest still works)."""
    from . import tide
    if not srv.is_java:
        return None
    if tide.installed(srv):
        return "tide"
    try:
        if any(p.name.startswith(fishpack.PACK_ID) for p in datapacks_dir(srv).iterdir()):
            return "pack"
    except OSError:
        pass
    if db.q("SELECT 1 FROM fish_catches WHERE server_id=? LIMIT 1", (srv.id,)):
        return "pack"
    return None


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
        from . import tide
        (datapacks_dir(srv) / fishpack.PACK_FILE).write_bytes(fishpack.build_zip(new_format(srv), fishing=not tide.installed(srv)))
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
    # only what's about this pack, or the game's shared start-up/tick lists it relies on (other mods' and packs'
    # own errors, Flan's compatibility files for mods that aren't installed say, aren't ours to show)
    keys = ("solstone", "solfish", "solgames", "minecraft:load", "minecraft:tick")
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
            # Trophy and Legendary get their own type so the status page's feed shows only those
            db.add_event(srv.id, time.time(), "bigfish" if c["quality"] >= 3 else "fish", describe(c, who), who if who != "Someone" else None)
            contest = await challenges.on_catch(srv, who, c)
            try:
                await _celebrate(srv, who, c, contest)
                if who != "Someone":
                    await _journal(srv, who, c)
            except RuntimeError:
                pass


async def _celebrate(srv, who: str, c: dict, contest: bool) -> None:
    """Trophy and up are news (a contest already announces every catch); Legendary gets a sound
    for everyone; Mythic (1 in 1000) stops the world: a title on every screen and fireworks."""
    q, lb = c["quality"], c["lb"]
    fish = f"{c['quality_name']} {c['name']}"
    colour = QUALITY_COLOR.get(q, "white")
    if q >= 3 and not contest:
        stars = "★" * (q - 2) + " "
        line = component([(stars, colour), (who, "aqua"), (" caught a ", None), (fish, colour + ("!" if q >= 4 else "")), (f" ({lb} lb)!", None)])
        await _rcon(srv, f"tellraw @a {line}")
    if q >= 4:
        await _rcon(srv, "execute as @a at @s run playsound minecraft:ui.toast.challenge_complete master @s ~ ~ ~ 0.8 1")
    if q >= 5:
        sub = component([(f"{who} caught a {fish}! ({lb} lb)", "yellow")])
        await _rcon(srv, "title @a times 10 70 20")
        await _rcon(srv, f"title @a subtitle {sub}")
        await _rcon(srv, f"title @a title {component([('✦ MYTHIC CATCH ✦', 'light_purple!')])}")
        from . import fwshow
        fwshow.push(srv.id, srv.display_name, "challenge", who, f"{who} caught a {fish}!")


async def _journal(srv, who: str, c: dict) -> None:
    """Into the fishing journal; a new species or a personal best gets a line for that player."""
    j = db.add_catch(srv.id, time.time(), who, c)
    if c.get("basic"):                                # vanilla fishing: kept quietly, nothing said in the game
        return
    total, have, lb = len(fishpack.SPECIES), j["species_caught"], c["lb"]
    if j["new_species"]:
        line = component([("✎ ", "gold"), ("New in your fishing journal: ", "yellow"), (c["name"], "aqua"), (f" ({have} of {total} species)", "gray")])
        await _rcon(srv, f"tellraw {who} {line}")
        if have == total:
            await _rcon(srv, f"tellraw @a {component([('★ ', 'gold'), (who, 'aqua'), (f' has caught every one of the {total} kinds of fish!', 'gold!')])}")
            db.add_event(srv.id, time.time(), "bigfish", f"{who} has caught every kind of fish ({total})", who)
    elif j["personal_best"]:
        line = component([("✎ ", "gold"), ("Personal best ", "yellow"), (c["name"], "aqua"), (f": {lb} lb", "yellow")])
        await _rcon(srv, f"tellraw {who} {line}")


_OLD_QUALITY = {"Poor": 0, "Normal": 1, "Quality": 2, "Fine": 2, "Prime": 3, "Good": 2, "Great": 3, "Trophy": 3, "Exquisite": 4, "Legendary": 4, "Mythic": 5}
_CAUGHT = re.compile(r"^(?P<who>\S+) caught an? (?P<fish>.+?) · (?P<lb>[\d.]+) lb · (?P<p>\d+) points$")


def _backfill(sid: str) -> None:
    """Fill the journal from the activity feed once (catches from before it existed)."""
    if db.q("SELECT 1 FROM fish_catches WHERE server_id=? LIMIT 1", (sid,)):
        return
    by_name = {v[0]: k for k, v in fishpack.SPECIES.items()}
    for e in db.events(sid, ["fish", "bigfish"], None, 5000):
        m = _CAUGHT.match(e["message"] or "")
        if not m:
            continue
        fish, quality = m.group("fish"), 1
        for qn, qi in _OLD_QUALITY.items():
            if fish.startswith(qn + " ") and fish[len(qn) + 1:] in by_name:
                fish, quality = fish[len(qn) + 1:], qi
                break
        if fish not in by_name:
            continue
        db.x("INSERT INTO fish_catches(server_id, ts, player, species, name, quality, quality_name, weight, points) VALUES (?,?,?,?,?,?,?,?,?)",
             (sid, e["ts"], m.group("who"), by_name[fish], fish, quality, fishpack.QUALITIES[min(quality, len(fishpack.QUALITIES) - 1)][0],
              float(m.group("lb")), int(m.group("p"))))


def journal(sid: str) -> dict:
    """Everyone's fishing journal: which species each player has caught, their best of each,
    family records, and the latest catches."""
    _backfill(sid)
    rows = db.fish_catches(sid)
    players: dict[str, dict] = {}
    records: dict[str, dict] = {}
    for r in rows:
        p = players.setdefault(r["player"], {"name": r["player"], "species": {}, "total": 0, "points": 0, "qualities": [0] * len(fishpack.QUALITIES)})
        p["total"] += 1
        p["points"] += r["points"]
        if 0 <= r["quality"] < len(p["qualities"]):
            p["qualities"][r["quality"]] += 1
        sp = p["species"].setdefault(r["species"], {"count": 0, "best_lb": 0, "best_quality": 0, "first": r["ts"]})
        sp["count"] += 1
        sp["best_lb"] = max(sp["best_lb"], r["weight"])
        sp["best_quality"] = max(sp["best_quality"], r["quality"])
        rec = records.get(r["species"])
        if not rec or r["weight"] > rec["lb"]:
            records[r["species"]] = {"player": r["player"], "lb": r["weight"], "quality": r["quality"], "ts": r["ts"]}
    recent = [{"player": r["player"], "species": r["species"], "name": r["name"], "quality": r["quality"], "lb": r["weight"], "points": r["points"], "ts": r["ts"]}
              for r in rows[-20:]][::-1]
    return {"species": fishpack.guide(), "qualities": fishpack.qualities(), "players": sorted(players.values(), key=lambda p: (-len(p["species"]), -p["points"])),
            "records": records, "recent": recent}


def status(srv) -> dict:
    st = _state.get(srv.id) or {}
    return {"version": st.get("version"), "current": fishpack.VERSION, "error": st.get("error", ""),
            "writable": writable(srv), "file": fishpack.PACK_FILE, "folder": str(datapacks_dir(srv)), "files": files(srv),
            "loot_format": "26.3" if new_format(srv) else "older", "mc_version": srv.mc_version}
