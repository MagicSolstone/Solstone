"""The compatibility check: one button that tries, on the real server, every kind of command and
file Solstone relies on, and says which work. Run it after a Minecraft update (on a copy of
the server first, ideally) so nothing breaks quietly.

Everything it does is harmless and cleaned up afterwards:
- messages, titles, sounds, items and effects go to nobody (a selector that matches no one),
  so the game still has to read and accept them, which is the point;
- blocks and entities are made for a moment high above spawn, then removed;
- scoreboards, a boss bar and a team are made and removed again.
"""
from __future__ import annotations

import asyncio
import re
import time

from . import fishing, fishpack, gather
from . import servers as S
from .control import _ERROR_HINTS
from .rcon import RconError

NOBODY = "@a[tag=solstone_check_nobody]"
TAG = "solstone_check"


async def _rc(srv, cmd: str) -> str:
    try:
        return await srv.rcon(cmd) or ""
    except RconError as e:
        return f"error: {e}"


def _bad(reply: str) -> bool:
    low = reply.lower()
    return any(h in low for h in _ERROR_HINTS) or low.startswith("error:")


def _ver(srv) -> tuple[int, int, int]:
    v = [int(x) for x in re.findall(r"\d+", srv.mc_version or "")[:3]] + [0, 0, 0]
    return v[0], v[1], v[2]


class Run:
    def __init__(self, srv):
        self.srv, self.rows = srv, []

    def add(self, area: str, label: str, ok: bool | None, detail: str = "", used_by: str = "", fix: str = "") -> None:
        self.rows.append({"area": area, "label": label, "ok": ok, "detail": detail[:400], "used_by": used_by, "fix": fix})

    async def cmd(self, area: str, label: str, cmds: list[str], used_by: str, expect: str | None = None, fix: str = "") -> bool:
        """Run commands; fine if none of the replies look like the game refusing them (and the
        last one contains `expect`, when given)."""
        replies = []
        for c in cmds:
            r = await _rc(self.srv, c)
            replies.append(r)
            if _bad(r):
                self.add(area, label, False, f"{c}\n→ {r}", used_by, fix)
                return False
        if expect and expect.lower() not in replies[-1].lower():
            self.add(area, label, False, f"{cmds[-1]}\n→ {replies[-1] or '(no reply)'}", used_by, fix)
            return False
        self.add(area, label, True, replies[-1][:160], used_by)
        return True


async def run(srv, near: list[tuple[float, float]], assets) -> dict:
    from . import worldmap
    from .races import _text_nbt
    t0 = time.time()
    c = Run(srv)
    v = _ver(srv)
    new_text = v >= (1, 21, 5) or v[0] >= 26

    # ------------------------------------------------------------ connection
    out = await _rc(srv, "list")
    if "players online" not in out.lower() and "online" not in out.lower():
        c.add("Connection", "RCON (Solstone talking to the server)", False, out or "no reply", "everything",
              "Check enable-rcon, rcon.port and rcon.password in server.properties, and the server's RCON settings in Solstone.")
        return {"rows": c.rows, "version": srv.mc_version, "seconds": round(time.time() - t0, 1)}
    c.add("Connection", "RCON (Solstone talking to the server)", True, out[:120], "everything")
    c.add("Connection", "Minecraft version", True if srv.mc_version else None, srv.mc_version or "unknown (read from level.dat)", "picking the right command formats")

    w = await asyncio.to_thread(S.world_info, srv, False)
    sp = w.get("spawn") or {"x": 0, "y": 64, "z": 0}
    x, z, y = int(sp["x"]) + 3, int(sp["z"]) + 3, 318
    ow = "execute in minecraft:overworld run"
    try:
        await _rc(srv, f"{ow} forceload add {x} {z}")

        # -------------------------------------------------------- on screen
        await c.cmd("On screen", "Scoreboards", [
            'scoreboard objectives add solcheck dummy "Check"', "scoreboard players set #check solcheck 5",
            'scoreboard objectives modify solcheck displayname "Solstone check"', "scoreboard players get #check solcheck"],
            "contest sidebars, fishing points, spleef safety net", expect="has 5")
        await _rc(srv, "scoreboard objectives remove solcheck")
        crit = ["minecraft.custom:minecraft.fish_caught", "minecraft.custom:minecraft.mob_kills", "minecraft.killed:minecraft.creeper",
                "minecraft.used:minecraft.bow", "minecraft.used:minecraft.crossbow"]
        ok = True
        for i, cr in enumerate(crit):
            r = await _rc(srv, f"scoreboard objectives add solcheck{i} {cr}")
            await _rc(srv, f"scoreboard objectives remove solcheck{i}")
            if _bad(r):
                c.add("On screen", "Statistics the contests count", False, f"{cr}\n→ {r}", "fishing, monster and creeper contests, archery")
                ok = False
                break
        if ok:
            c.add("On screen", "Statistics the contests count", True, f"{len(crit)} statistics", "fishing, monster and creeper contests, archery")
        await c.cmd("On screen", "Boss bar countdown", [
            'bossbar add solstone:check "Check"', "bossbar set solstone:check max 100", "bossbar set solstone:check value 50",
            "bossbar set solstone:check color green", 'bossbar set solstone:check name "Check"', "bossbar get solstone:check value"],
            "contest, race and game countdowns", expect="50")
        await _rc(srv, "bossbar remove solstone:check")
        comp = '[{"text":"★ ","color":"gold","bold":true},{"text":"check","color":"yellow"}]'
        await c.cmd("On screen", "Titles, hotbar line and chat", [
            f"title {NOBODY} times 0 20 5", f"title {NOBODY} title {comp}", f"title {NOBODY} subtitle {comp}",
            f"title {NOBODY} actionbar {comp}", f"tellraw {NOBODY} {comp}"], "every announcement")
        await c.cmd("On screen", "Sounds", [f"execute as {NOBODY} at @s run playsound minecraft:block.note_block.bell master @s ~ ~ ~ 1 1",
                                            f"playsound minecraft:entity.player.levelup master {NOBODY} ~ ~ ~ 1 1"], "countdowns, big archery shots")
        await c.cmd("On screen", "Particles", [f"{ow} particle minecraft:end_rod {x} {y} {z} 1 1 1 0.01 5 force {NOBODY}",
                                               f"{ow} particle minecraft:flame {x} {y} {z} 1 0.1 1 0.01 5 force {NOBODY}",
                                               f"{ow} particle minecraft:campfire_signal_smoke {x} {y} {z} 0.3 2 0.3 0.01 2 force {NOBODY}"],
                     "race checkpoint beams, hot zones")

        # -------------------------------------------------------- in the world
        label = _text_nbt(srv, "Solstone check", "gold")
        await c.cmd("In the world", "Floating text and glowing markers", [
            f"{ow} summon minecraft:text_display {x} {y} {z} {{Tags:[\"{TAG}\"],billboard:\"center\",text:{label}}}",
            f"{ow} summon minecraft:block_display {x} {y} {z} {{Tags:[\"{TAG}\"],Glowing:1b,glow_color_override:16766720,block_state:{{Name:\"minecraft:gold_block\"}}}}",
            f"data get entity @e[type=minecraft:text_display,tag={TAG},limit=1] text"],
            "race checkpoints, hot zone signs", expect="Solstone check",
            fix="Text in entity data changed format: the race and hot zone signs need updating.")
        if v >= (1, 21, 6) or v[0] >= 26:
            await c.cmd("In the world", "Dots on the locator bar", [
                f"{ow} summon minecraft:armor_stand {x} {y} {z} {{Tags:[\"{TAG}\",\"{TAG}_wp\"],Small:1b,Marker:1b,NoGravity:1b,"
                f"attributes:[{{id:\"minecraft:waypoint_transmit_range\",base:60000000d}}]}}",
                f"waypoint modify @e[tag={TAG}_wp,limit=1] color red"], "race checkpoints, hot zones")
        else:
            c.add("In the world", "Dots on the locator bar", None, "needs Minecraft 1.21.6 or newer", "race checkpoints, hot zones")
        attrs = gather._attrs(srv)
        if attrs:
            await _rc(srv, f"{ow} summon minecraft:armor_stand {x} {y} {z} {{Tags:[\"{TAG}\",\"{TAG}_as\"],NoGravity:1b,Invisible:1b}}")
            ok = await c.cmd("In the world", "Holding players still", [
                f"attribute @e[tag={TAG}_as,limit=1] {a} modifier add {gather.FREEZE_ID} -1 add_multiplied_total" for a in attrs],
                "race starts")
            if ok:
                for a in attrs:
                    await _rc(srv, f"attribute @e[tag={TAG}_as,limit=1] {a} modifier remove {gather.FREEZE_ID}")
        else:
            c.add("In the world", "Holding players still", None, "needs Minecraft 1.21 or newer: racers are lined up but not held", "race starts")
        await _rc(srv, f"{ow} summon minecraft:marker {x} {y} {z} {{Tags:[\"{TAG}\",\"{TAG}_m\"]}}")
        await c.cmd("In the world", "Teleporting (and facing a spot)", [
            f"{ow} tp @e[tag={TAG}_m,limit=1] {x + 0.5} {y} {z + 0.5} facing {x} {y} {z + 5}"], "gathering everyone, race line-up, spleef, hide and seek")
        hm = []
        for heightmap in ("motion_blocking_no_leaves", "ocean_floor", "motion_blocking"):
            r = await _rc(srv, f"execute in minecraft:overworld positioned {sp['x']} 320 {sp['z']} positioned over {heightmap} run summon minecraft:marker ~ ~ ~ {{Tags:[\"{TAG}\",\"{TAG}_h\"]}}")
            got = await _rc(srv, f"data get entity @e[tag={TAG}_h,limit=1] Pos")
            await _rc(srv, f"kill @e[tag={TAG}_h]")
            hm.append((heightmap, r, got))
        bad = next(((h, r) for h, r, g in hm if _bad(r) or "[" not in g), None)
        c.add("In the world", "Finding the ground", bad is None, f"{bad[0]} → {bad[1]}" if bad else "3 height maps", "treasure chests, hot zones, spleef height, gathering")
        await c.cmd("In the world", "Building and removing blocks", [
            f"{ow} fill {x} {y} {z} {x + 1} {y} {z} minecraft:snow_block replace air",
            f"{ow} fill {x} {y} {z} {x + 1} {y} {z} minecraft:air replace minecraft:snow_block",
            f"{ow} setblock {x} {y} {z} minecraft:barrier", f"{ow} setblock {x} {y} {z} minecraft:air"], "spleef arena, archery target")
        await c.cmd("In the world", "Treasure chest (with items, under water)", [
            f'{ow} setblock {x} {y} {z} minecraft:chest[waterlogged=true]{{Items:[{{Slot:0b,id:"minecraft:diamond",count:3}}]}}',
            f"{ow} data get block {x} {y} {z} Items"], "treasure hunt", expect="diamond")
        await _rc(srv, f"{ow} setblock {x} {y} {z} minecraft:air")
        await c.cmd("In the world", "Checking blocks", [f"execute in minecraft:overworld if block {x} {y} {z} minecraft:air"],
                    "treasure placement, water checks, archery target", expect="passed")

        # -------------------------------------------------------- items, players
        name = '"Spleef Shovel"' if new_text else "'\"Spleef Shovel\"'"
        await c.cmd("Items and players", "Giving prizes and special items", [
            f"give {NOBODY} minecraft:diamond 1",
            f"give {NOBODY} minecraft:diamond_shovel[minecraft:custom_data={{solspleef:1b}},minecraft:unbreakable={{}},minecraft:item_name={name}]",
            f"give {NOBODY} {_rod(srv)}"], "prizes, spleef shovels, contest rods")
        await c.cmd("Items and players", "Taking special items back", [
            f"clear {NOBODY} minecraft:diamond_shovel[minecraft:custom_data={{solspleef:1b}}]",
            f"clear {NOBODY} minecraft:fishing_rod[minecraft:custom_data={{solrod:1b}}]", f"clear {NOBODY} minecraft:snowball"],
            "spleef, contest rods")
        await c.cmd("Items and players", "Effects and game modes", [
            f"effect give {NOBODY} minecraft:resistance 10 4 true", f"effect give {NOBODY} minecraft:blindness 5 0 true",
            f"effect clear {NOBODY} minecraft:resistance", f"gamemode adventure {NOBODY}"], "spleef, hide and seek")
        await c.cmd("Items and players", "Teams", [
            "team add solcheck", "team modify solcheck color red", "team modify solcheck nametagVisibility never",
            "team modify solcheck friendlyFire false"], "hide and seek, team spleef")
        await _rc(srv, "team remove solcheck")
        await c.cmd("Items and players", "Reading a player's position", [f"data get entity @e[tag={TAG}_m,limit=1] Pos"],
                    "races, games, gathering", expect="[")
    finally:
        await _rc(srv, f"kill @e[tag={TAG}]")
        await _rc(srv, f"{ow} setblock {x} {y} {z} minecraft:air")
        await _rc(srv, f"{ow} forceload remove {x} {z}")

    # ------------------------------------------------------------ the data pack
    fish_v = re.search(r"version:\s*(\d+)", await _rc(srv, "data get storage solstone:fish pack"))
    game_v = re.search(r"version:\s*(\d+)", await _rc(srv, "data get storage solstone:games pack"))
    if not fish_v and not game_v:
        c.add("Data pack", "Solstone data pack loaded", None, "not in this world (fishing, archery and spleef need it)", "fishing, archery, spleef")
    else:
        pv = int((fish_v or game_v).group(1))
        c.add("Data pack", "Solstone data pack loaded", pv >= fishpack.VERSION, f"version {pv} (newest is {fishpack.VERSION})",
              "fishing, archery, spleef", "" if pv >= fishpack.VERSION else "Download the pack again from the Contests page, replace it, restart.")
        want = "26.3" if fishing.new_format(srv) else "older"
        files = [f for f in fishing.files(srv) if f.get("version") is not None]
        fmt = next((f.get("loot_format") for f in files if f.get("loot_format")), None)
        c.add("Data pack", "Pack written for this version", (fmt == want) if fmt else None,
              f"pack: {fmt or 'unknown'}, server needs: {want}", "fishing",
              "Download the pack again (it's built for the server it's going to) and replace it." if fmt and fmt != want else "")
        from . import tide
        if tide.installed(srv):                       # the Tide build of the pack has no fishing half
            await c.cmd("Data pack", "Archery triggers", [f"advancement revoke {NOBODY} only solgames:hit_15"], "archery hits")
        else:
            await c.cmd("Data pack", "Fishing and archery triggers", [
                f"advancement revoke {NOBODY} only solfish:hooked", f"advancement revoke {NOBODY} only solgames:hit_15"], "fish catches, archery hits")
        if "found no elements" in (await _rc(srv, "data get storage solstone:games spleef")).lower():
            await c.cmd("Data pack", "Spleef safety net", ["function solgames:spleef_back"], "spleef (cleans up if Solstone stops)")
        else:
            c.add("Data pack", "Spleef safety net", None, "a spleef game is on: not tested now", "spleef")
        try:
            t = await fishing.test_catch(srv)
            n = sum(1 for r in t["rod"] if r.get("pack_fish"))
            probe = t.get("probe", {}).get("probe")
            ok = bool(n or t.get("pack_fish"))
            c.add("Data pack", "Fish from the pack (test casts)", ok,
                  f"{n} of {len(t['rod'])} rod casts were Solstone fish; probe {'tagged' if probe else 'NOT tagged'}", "every fishing feature",
                  "" if ok else "The game is ignoring the pack's loot tables: Minecraft has probably changed their format. Use Test a catch on the Contests page for details.")
        except Exception as e:
            c.add("Data pack", "Fish from the pack (test casts)", False, str(e), "every fishing feature")

    # ------------------------------------------------------------ files Solstone reads
    try:
        m = await asyncio.to_thread(worldmap.check, srv.id, srv.world_dir, "minecraft:overworld", near, assets)
        drawn = [x for x in m.get("checked", []) if x.get("picture") == "drawn"]
        c.add("Files Solstone reads", "World map", bool(drawn), m.get("error") or f"{len(drawn)} of {len(m.get('checked', []))} regions drawn, {m.get('regions', 0)} region files",
              "the map on the status page, picking spots", "" if drawn else "The world file format may have changed: the map reader needs updating.")
    except Exception as e:
        c.add("Files Solstone reads", "World map", False, str(e), "the map on the status page, picking spots")
    known = S.known_players(srv)
    if known:
        uuid = next(iter(known))
        data, _m = S.player_file_data(srv, uuid)
        good = bool(data) and any(k in data for k in ("inventory", "health", "position"))
        c.add("Files Solstone reads", "Player data (inventory, health)", good, f"{known[uuid].get('name', uuid)}: {', '.join(sorted((data or {}).keys())[:6])}",
              "player pages, status page")
        try:
            st = S.player_stats(srv, uuid)
            c.add("Files Solstone reads", "Player statistics", bool(st), f"{len(st)} kinds of statistic" if st else "none read", "leaderboards, recaps")
        except Exception as e:
            c.add("Files Solstone reads", "Player statistics", False, str(e), "leaderboards, recaps")
    else:
        c.add("Files Solstone reads", "Player data (inventory, health)", None, "no players have joined yet", "player pages")
    return {"rows": c.rows, "version": srv.mc_version, "seconds": round(time.time() - t0, 1), "at": time.time()}


def _rod(srv) -> str:
    from .challenges import _rod
    return _rod(srv, 3)
