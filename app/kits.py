"""Event kits, with everyone's own things kept safe (King of the Hill, the mob arena, elytra races).

Before a game hands out its gear, each player's whole inventory (36 slots, armour and off-hand) is copied, exactly,
enchantments, names and all, into two barrels of their own in a vault sealed in bedrock at the bottom of the world
under spawn. The copy is checked against what they had, item for item; only then is the player cleared and given the
kit. A player whose things couldn't be copied safely isn't cleared: they watch that game instead.

Afterwards everything they're carrying is cleared (the kit, and anything picked up in the game: none of it is theirs),
and their own things are copied back to the same slots from the vault, checked, and only then is the vault emptied.
The vault's copy is the one source of truth until then: a give-back that's tried again either finds their things
already on them (and just empties the vault) or clears them and copies everything over again. Nothing is ever handed
out on top of what they have, so nothing can come back twice.

They're put back where they were, in the game mode they were in, unless the vault was kept from before Solstone last
started (Solstone was down: they may have gone somewhere since, so they stay put).

It's kept in Solstone's settings, so it survives Solstone restarting, the server crashing, or a player leaving: anyone
with things in the vault gets them back the next time they're online (or an admin presses Give back, in Control).
The copying is done by the game itself (`item replace`), on the server, so it's the same for Java and Bedrock players.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import Counter

from . import settings_store
from . import servers as S

log = logging.getLogger("solstone.kits")

SECTION = "kit_stash"                 # {"vault": {sid: {...}}, "stash": {"<sid>:<uuid>": {...}}}
DIM = "minecraft:overworld"
MAX_SLOTS = 48                        # players with things in one server's vault at once
KIT_TAG = "solkit"                    # custom_data on every item a kit gives, so only those are taken back
# the player's slots, and where each goes: barrel A (the first 27) or barrel B
SLOTS = ([(f"container.{i}", 0, i) for i in range(27)] + [(f"container.{27 + i}", 1, i) for i in range(9)]
         + [("armor.head", 1, 9), ("armor.chest", 1, 10), ("armor.legs", 1, 11), ("armor.feet", 1, 12), ("weapon.offhand", 1, 13)])
KIT_MATCH = f"*[minecraft:custom_data={{{KIT_TAG}:1b}}]"     # every item a kit gave, and nothing else
_lock = asyncio.Lock()
STASH_TRIES = 3                       # copying someone's things into the vault: tries before they sit the game out
_STARTED = time.time()                # things kept safe before this: Solstone was down since (don't move anyone)


def _load() -> dict:
    d = settings_store.load().get(SECTION) or {}
    return {"vault": dict(d.get("vault") or {}), "stash": dict(d.get("stash") or {})}


def _save(d: dict) -> None:
    settings_store.save_section(SECTION, d)


def _floor_y(srv) -> int:
    """The bottom of the world: -64 since 1.18, 0 before."""
    nums = [int(x) for x in re.findall(r"\d+", srv.mc_version or "")[:2]] + [0, 0]
    return -64 if nums[0] >= 26 or (nums[0] == 1 and nums[1] >= 18) or not srv.mc_version else 0


async def _rcon(srv, cmd: str) -> str:
    return (await srv.rcon(cmd)) or ""


async def _vault(srv, d: dict) -> dict:
    """This server's vault: a chunk under spawn, its barrels one layer above the bottom, sealed in bedrock."""
    v = d["vault"].get(srv.id)
    if not v:
        try:
            spawn = S.world_info(srv, False).get("spawn") or {}
        except Exception:
            spawn = {}
        cx, cz = int(spawn.get("x") or 0) // 16, int(spawn.get("z") or 0) // 16
        y = _floor_y(srv)
        v = {"x": cx * 16 + 2, "z": cz * 16 + 2, "y": y + 1, "built": False}
        d["vault"][srv.id] = v
    await _rcon(srv, f"execute in {DIM} run forceload add {v['x']} {v['z']}")
    for _ in range(20):                                  # loading it takes a tick or two
        if "passed" in (await _rcon(srv, f"execute in {DIM} if loaded {v['x']} {v['y']} {v['z']}")).lower():
            break
        await asyncio.sleep(0.15)
    else:
        raise RuntimeError("The vault's chunk didn't load")
    if not v.get("built"):
        x0, z0, y = v["x"], v["z"], v["y"]
        # a box of bedrock from the bottom of the world up, with room for 12 x 4 pairs of barrels inside
        await _rcon(srv, f"execute in {DIM} run fill {x0 - 1} {y - 1} {z0 - 1} {x0 + 12} {y + 1} {z0 + 8} minecraft:bedrock")
        v["built"] = True
    return v


def _barrels(v: dict, slot: int) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    x, z = v["x"] + slot % 12, v["z"] + 2 * (slot // 12)
    return (x, v["y"], z), (x, v["y"], z + 1)


def _free_slot(d: dict, sid: str) -> int | None:
    used = set()
    for k, s in d["stash"].items():
        if k.startswith(f"{sid}:"):
            if not s.get("restored"):
                used.add(s["slot"])
            if s.get("pocket") is not None:
                used.add(s["pocket"])
    return next((i for i in range(MAX_SLOTS) if i not in used), None)


# ------------------------------------------------------------------ comparing what's where
_ID = re.compile(r'\bid:\s*"([^"]+)"')
_SLOT = re.compile(r"\bSlot:\s*(-?\d+)b")            # a top-level slot (items inside a shulker box use "slot")
_COUNT = re.compile(r"\b[cC]ount:\s*(\d+)")


def _items(text: str) -> tuple[Counter, Counter]:
    """Every item id and stack size in a `data get` answer (nested ones too, like a shulker box's)."""
    text = text.split("data:", 1)[-1] if "has the following" in text else text
    return Counter(_ID.findall(text)), Counter(_COUNT.findall(text))


def _top_level(text: str) -> list[str]:
    """The items of an SNBT list or the entries of a compound, at the top level (nested ones stay inside theirs)."""
    out, depth, start, quote, esc_ = [], 0, None, "", False
    for i, ch in enumerate(text):
        if quote:
            if esc_:
                esc_ = False
            elif ch == "\\":
                esc_ = True
            elif ch == quote:
                quote = ""
            continue
        if ch in "\"'":
            quote = ch
        elif ch in "[{":
            depth += 1
            if depth == 2 and start is None:
                start = i
        elif ch in "]}":
            if depth == 2 and start is not None and ch == "}":
                out.append(text[start:i + 1])
                start = None
            depth -= 1
    return out


_ARMOUR_SLOT = {100: "armor.feet", 101: "armor.legs", 102: "armor.chest", 103: "armor.head", -106: "weapon.offhand"}
_EQUIP_SLOT = {"head": "armor.head", "chest": "armor.chest", "legs": "armor.legs", "feet": "armor.feet", "offhand": "weapon.offhand"}


async def strip_kit(srv, uuid: str) -> int:
    """Take every kit item off someone, slot by slot (doesn't depend on `clear` understanding the kit's mark, which
    not every version does: kit armour once came back with someone's own things). Returns how many were taken."""
    await _rcon(srv, f"clear {uuid} {KIT_MATCH}")       # the quick way, where the version understands it
    slots = []
    inv = await _rcon(srv, f"data get entity {uuid} Inventory")
    if "has the following" in inv:
        for item in _top_level(inv.split("data:", 1)[-1]):
            m = _SLOT.search(item)
            if m and KIT_TAG in item:
                n = int(m.group(1))
                slots.append(f"container.{n}" if 0 <= n < 36 else _ARMOUR_SLOT.get(n))
    eq = await _rcon(srv, f"data get entity {uuid} equipment")
    if "has the following" in eq:
        body = eq.split("data:", 1)[-1]
        for key, slot in _EQUIP_SLOT.items():
            m = re.search(rf"\b{key}:\s*\{{", body)
            if m:
                part = _top_level("{" + body[m.start():])[:1]
                if part and KIT_TAG in part[0]:
                    slots.append(slot)
    for slot in filter(None, slots):
        await _rcon(srv, f"item replace entity {uuid} {slot} with minecraft:air")
    return len([s for s in slots if s])


async def _player_items(srv, uuid: str) -> tuple[Counter, Counter] | None:
    inv = await _rcon(srv, f"data get entity {uuid} Inventory")
    if "has the following" not in inv:
        return None                                      # not online (or the game didn't answer)
    eq = await _rcon(srv, f"data get entity {uuid} equipment")         # armour and off-hand, 1.21.5+
    ids, counts = _items(inv)
    if "has the following" in eq:
        i2, c2 = _items(eq)
        ids, counts = ids + i2, counts + c2
    return ids, counts


async def _alive(srv, uuid: str) -> bool:
    """Not on the death screen (anything given to someone dead can go astray): their health is above 0."""
    m = re.search(r"(-?[\d.]+)f?\s*$", (await _rcon(srv, f"data get entity {uuid} Health")).strip())
    return not m or float(m.group(1)) > 0


def _has_all(have: tuple[Counter, Counter], need: tuple[Counter, Counter]) -> bool:
    """Everything in `need` is in `have` (and maybe more)."""
    return all(have[0][k] >= v for k, v in need[0].items()) and all(have[1][k] >= v for k, v in need[1].items())


async def _barrel_items(srv, spots) -> tuple[Counter, Counter]:
    ids, counts = Counter(), Counter()
    for (x, y, z) in spots:
        i, c = _items(await _rcon(srv, f"execute in {DIM} run data get block {x} {y} {z} Items"))
        ids, counts = ids + i, counts + c
    return ids, counts


async def _where(srv, uuid: str) -> dict | None:
    pos = await _rcon(srv, f"data get entity {uuid} Pos")
    dim = await _rcon(srv, f"data get entity {uuid} Dimension")
    m = re.search(r"\[\s*(-?[\d.]+)d?,\s*(-?[\d.]+)d?,\s*(-?[\d.]+)d?\s*\]", pos)
    if not m:
        return None
    dm = re.search(r'"([a-z0-9_.-]+:[a-z0-9_/.-]+)"', dim)
    return {"x": round(float(m.group(1)), 2), "y": round(float(m.group(2)), 2), "z": round(float(m.group(3)), 2), "d": dm.group(1) if dm else DIM}


# ------------------------------------------------------------------ keeping things safe, and giving them back
async def stash(srv, players: dict[str, str], game: str) -> list[str]:
    """Keep each player's things safe ({name: uuid}). Returns the names whose things are in the vault and who are now
    empty-handed, ready for a kit. Anyone not in the list wasn't touched."""
    from .games import _gamemode
    done = []
    _starting[game] = time.time()                       # from now the game counts as on (see _in_live_game)
    async with _lock:
        d = _load()
        v = await _vault(srv, d)
        _save(d)
        for name, uuid in players.items():
            key = f"{srv.id}:{uuid}"
            old = d["stash"].get(key)
            if old and old.get("restored"):             # their things are back: only an old pocket was left (emptied)
                await _drop_old_pocket(srv, d, old, v)
                d["stash"].pop(key, None)
                _save(d)
            if key in d["stash"]:                       # already has things in the vault (an earlier game): leave them be
                log.warning("%s already has things kept safe; not stashing again", name)
                continue
            slot = _free_slot(d, srv.id)
            back = await _where(srv, uuid)
            if slot is None or back is None:
                continue
            from .control import component
            await _rcon(srv, f"title {uuid} actionbar " + component([("Keeping your things safe… hold still a moment", "gold")]))
            a, b = _barrels(v, slot)
            copied = False
            # Picked something up (or dropped something) while it was being copied? Nothing's lost: the copy's thrown
            # away and made again, a few times, before they sit this one out with their things untouched.
            for attempt in range(STASH_TRIES):
                before = await _player_items(srv, uuid)
                if before is None:
                    break
                for (x, y, z) in (a, b):
                    await _rcon(srv, f"execute in {DIM} run setblock {x} {y} {z} minecraft:barrel")
                    await _rcon(srv, f"execute in {DIM} run data merge block {x} {y} {z} {{Items:[]}}")
                for src, which, i in SLOTS:
                    x, y, z = (a, b)[which]
                    await _rcon(srv, f"execute in {DIM} run item replace block {x} {y} {z} container.{i} from entity {uuid} {src}")
                if await _barrel_items(srv, (a, b)) == before and await _player_items(srv, uuid) == before:
                    copied = True
                    break
                log.warning("%s's things changed while being copied (try %d of %d)", name, attempt + 1, STASH_TRIES)
                for (x, y, z) in (a, b):
                    await _rcon(srv, f"execute in {DIM} run data merge block {x} {y} {z} {{Items:[]}}")
                await asyncio.sleep(1)
            if not copied:
                log.error("couldn't copy %s's things safely; leaving them as they are", name)
                continue
            # written down first: from here on, a crash still leaves a copy that gets given back
            d["stash"][key] = {"name": name, "uuid": uuid, "server": srv.id, "slot": slot, "game": game, "at": time.time(),
                               "back": back, "gm": await _gamemode(srv, name)}
            _save(d)
            await _rcon(srv, f"clear {uuid}")
            left = await _player_items(srv, uuid)
            if left is None or sum(left[0].values()):        # not empty (the clear didn't take): slot by slot, then
                log.warning("clearing %s didn't empty their inventory; emptying it slot by slot", name)
                for src, _w, _i in SLOTS:
                    await _rcon(srv, f"item replace entity {uuid} {src} with minecraft:air")
            done.append(name)
        await _rcon(srv, f"execute in {DIM} run forceload remove {v['x']} {v['z']}")
    return done


async def _empty(srv, spots) -> None:
    for (x, y, z) in spots:
        await _rcon(srv, f"execute in {DIM} run data merge block {x} {y} {z} {{Items:[]}}")


async def give_back(srv, uuid: str, move: bool = True) -> bool:
    """Give one player their things back, exactly, and put them back where they were: everything else they're
    carrying (the kit, what they picked up) is cleared first (see the top). False if they're not online or are on
    the death screen (it's tried again when they're back) or it didn't check out (the vault's copy stays, safe)."""
    async with _lock:
        d = _load()
        key = f"{srv.id}:{uuid}"
        s = d["stash"].get(key)
        if not s:
            return True
        if await _player_items(srv, uuid) is None:
            return False                                 # not online
        if not await _alive(srv, uuid):
            return False                                 # on the death screen: tried again once they've respawned
        v = await _vault(srv, d)
        try:
            if not s.get("restored") and not await _restore(srv, d, s, v, move):
                return False
            await _drop_old_pocket(srv, d, s, v)
            d["stash"].pop(key, None)
            _save(d)
            return True
        finally:
            if not any(k.startswith(f"{srv.id}:") for k in d["stash"]):
                await _rcon(srv, f"execute in {DIM} run forceload remove {v['x']} {v['z']}")


async def _restore(srv, d: dict, s: dict, v: dict, move: bool) -> bool:
    uuid = s["uuid"]
    a, b = _barrels(v, s["slot"])
    kept = await _barrel_items(srv, (a, b))
    now = await _player_items(srv, uuid)
    if now is None:
        return False
    if s.get("landed") and sum(kept[0].values()) and _has_all(now, kept):
        # An earlier try copied their things over (its check didn't pass): they have them. The vault's copy is only a
        # spare now: emptied, never handed over again. (Anything else on them now is theirs since: left alone.)
        log.warning("%s already has their things back; emptying the spare copy in the vault", s["name"])
        await strip_kit(srv, uuid)
        await _empty(srv, (a, b))
        s["restored"] = True
        _save(d)
        await _rcon(srv, f"gamemode {s.get('gm') or 'survival'} {uuid}")
        return True
    if s.get("at", 0) < _STARTED:
        # Solstone was down since the game: they may have played on and gathered real things. Nothing on them is
        # touched: their things come back once their inventory is empty (asked once; tried again every so often).
        await strip_kit(srv, uuid)
        now = await _player_items(srv, uuid)
        if now is None or sum(now[0].values()):
            if not s.get("told"):
                s["told"] = True
                _save(d)
                await _rcon(srv, f"tellraw {uuid} " + _msg("Your things from the last game are kept safe. Empty your inventory "
                                                           "(put everything in a chest) and they'll come straight back."))
            return False
    # Everything on them goes: the kit, and anything picked up in the game. Their own things are all in the vault.
    await _rcon(srv, f"clear {uuid}")
    s["landed"] = True                                   # written down first: a retry knows their things went over
    _save(d)
    for src, which, i in SLOTS:
        x, y, z = (a, b)[which]
        await _rcon(srv, f"execute in {DIM} run item replace entity {uuid} {src} from block {x} {y} {z} container.{i}")
    got = await _player_items(srv, uuid)
    if got != kept:
        missing = (kept[0] - got[0]) if got else kept[0]
        extra = (got[0] - kept[0]) if got else Counter()
        log.error("giving %s's things back didn't check out (missing %s, extra %s); their copy stays in the vault",
                  s["name"], dict(missing), dict(extra))
        return False
    await _empty(srv, (a, b))
    s["restored"] = True
    _save(d)
    late = s.get("at", 0) < _STARTED                     # Solstone was down since: they may have gone somewhere
    if move and not late and s.get("back"):
        bk = s["back"]
        await _rcon(srv, f"execute in {bk['d']} run tp {uuid} {bk['x']} {bk['y']} {bk['z']}")
    await _rcon(srv, f"gamemode {s.get('gm') or 'survival'} {uuid}")
    await _rcon(srv, f"effect give {uuid} minecraft:instant_health 1 10 true")
    await _rcon(srv, f"effect give {uuid} minecraft:saturation 1 10 true")
    if s.get("spawn_moved"):
        await _put_spawn_back(srv, s)                    # their own bed (or the world's spawn) again
    return True


async def move_spawn(srv, uuid: str, name: str, spot: dict, dim: str) -> None:
    """For a fight: dying brings them back in the game, not home to their bed first (and then back: a blink). Their own
    respawn point is written down with their things, and put back when they're home (_put_spawn_back)."""
    async with _lock:
        d = _load()
        s = d["stash"].get(f"{srv.id}:{uuid}")
        if not s or s.get("restored"):
            return                                       # (their things aren't in the vault: nothing to put it back with)
        if not s.get("spawn_moved"):
            live = await S.live_player(srv, name)
            s["respawn"] = (live or {}).get("respawn")   # None: they hadn't one of their own (the world's spawn)
            s["spawn_moved"] = True
            _save(d)
    await _rcon(srv, f"execute in {dim} run spawnpoint {uuid} {int(spot['x'])} {int(spot['y'])} {int(spot['z'])}")


async def _put_spawn_back(srv, s: dict) -> None:
    r = s.get("respawn")
    if not r:
        w = await asyncio.to_thread(S.world_info, srv, False)
        r = w.get("spawn")
    if r:
        dim = r.get("dimension") or "minecraft:overworld"
        await _rcon(srv, f"execute in {dim} run spawnpoint {s['uuid']} {int(r['x'])} {int(r['y'])} {int(r['z'])}")


async def _drop_old_pocket(srv, d: dict, s: dict, v: dict) -> None:
    """Before 1.15.18, things someone was carrying at the end went into a "pocket" handed out later; earlier bugs
    put their own things in it, so it handed out copies. Any old pocket is emptied, not handed out."""
    if s.get("pocket") is not None:
        log.warning("emptying %s's old pocket (copies from before 1.15.18), not handing it out", s["name"])
        await _empty(srv, _barrels(v, s["pocket"]))
        s.pop("pocket", None)


async def discard(srv, uuid: str) -> bool:
    """An admin, by hand: empty what's kept for this player and forget it. For leftovers that are only copies of
    things they already have (as after the duplication bug fixed in 1.15.16). Nothing is given to or taken from them."""
    async with _lock:
        d = _load()
        key = f"{srv.id}:{uuid}"
        s = d["stash"].get(key)
        if not s:
            return False
        v = await _vault(srv, d)
        if not s.get("restored"):
            await _empty(srv, _barrels(v, s["slot"]))
        if s.get("pocket") is not None:
            await _empty(srv, _barrels(v, s["pocket"]))
        d["stash"].pop(key, None)
        _save(d)
        if not any(k.startswith(f"{srv.id}:") for k in d["stash"]):
            await _rcon(srv, f"execute in {DIM} run forceload remove {v['x']} {v['z']}")
        return True


def _msg(text: str) -> str:
    from .control import component
    return component([("★ ", "gold"), (text, "yellow")])


def waiting(sid: str) -> list[dict]:
    """Who has things in the vault on this server (for Control, and for the tidy-up)."""
    return [s for k, s in _load()["stash"].items() if k.startswith(f"{sid}:")]


async def on_join(srv, name: str) -> None:
    """Back after leaving in the middle of a game (or after a crash): their things, a moment after they arrive."""
    mine = [s for s in waiting(srv.id) if s["name"].lower() == name.lower() and (s.get("restored") or not _in_live_game(s))]
    if mine and mine[0].get("told"):                     # told again on a fresh join, if there's still no room
        d = _load()
        d["stash"].get(f"{srv.id}:{mine[0]['uuid']}", {}).pop("told", None)
        _save(d)
    if mine:
        asyncio.get_running_loop().create_task(_welcome_back(srv, mine[0]))


async def _welcome_back(srv, s: dict) -> None:
    await asyncio.sleep(3)                               # let them finish joining
    try:
        if not s.get("restored") and await give_back(srv, s["uuid"]):
            from .games import _say
            await _say(srv, [("★ ", "gold"), ("Your things are back, just as you left them.", "yellow")], who=s["uuid"])
        elif s.get("restored"):
            await give_back(srv, s["uuid"])
    except Exception:
        log.exception("giving %s their things back failed (it's tried again in a moment)", s["name"])


def _in_live_game(s: dict) -> bool:
    """Their game (or race) is still on, or everyone's on the way home from it: leave their things to that."""
    from .games import ACTIVE, _load as games_load
    from .races import _load as races_load
    if s.get("game") in _heading_home:
        return True
    if time.time() - _starting.get(s.get("game"), 0) < STARTING_GRACE:
        return True          # just kept safe: the game's still getting going (not marked running yet)
    return (any(r["id"] == s.get("game") and r["state"] in ACTIVE for r in games_load()["runs"])
            or any(r["id"] == s.get("game") and r["state"] in ("countdown", "running") for r in races_load()["runs"]))


# ------------------------------------------------------------------ every game: in with nothing, home with everything
_heading_home: dict[str, float] = {}       # game id -> when its trip home started (the tidy-up leaves those alone)
# game id -> when things were last kept safe for it. A game saves everyone's things, then takes a few seconds (kits,
# monsters) before it's marked running; the tidy-up, on its own loop, once took that for a game that was over and
# handed everything back at the start (own things kept through the game, the kit on top). Not any more.
_starting: dict[str, float] = {}
STARTING_GRACE = 120
_tasks: set = set()
HOME_SECS = 8


async def keep_safe(srv, names: list[str], game_id: str) -> dict[str, str]:
    """The start of any game: everyone's own things, where they are and their game mode, kept safe; they're cleared,
    ready for the game's kit. Returns {name: uuid} of who's in. Anyone whose things couldn't be kept safe watches,
    untouched, and is told why."""
    from . import battle
    from .games import _say
    ids = battle.uuids_of(srv, names)
    before = {x["name"].lower() for x in waiting(srv.id)}
    try:
        playing = await stash(srv, ids, game_id)
    except Exception:                                    # (the vault couldn't be reached: nobody's touched)
        log.exception("couldn't keep things safe for %s", game_id)
        playing = []
    for n in names:
        if n not in playing:
            why = ("Some of your things are still kept safe from an earlier game, so you're watching this one."
                   if n.lower() in before else "Your things couldn't be kept safe just now, so you're watching this one.")
            await _say(srv, [("★ ", "gold"), (f"{why} Nothing of yours was touched.", "yellow")], who=n)
    return {n: ids[n] for n in playing}


def send_home(srv, kept: dict[str, str], game_id: str, secs: int = HOME_SECS, after=None):
    """The end of any game: a few seconds' countdown, then everyone's kit and pick-ups cleared, their own things back
    exactly, and back where they were in the game mode they were in. Prizes wait until then (challenges.award)."""
    if not kept and not after:
        return None
    _heading_home[game_id] = time.time()
    task = asyncio.get_running_loop().create_task(_home(srv, dict(kept), game_id, secs, after))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return task


# Every mark a game puts on what it hands out: kits (arena, King of the Hill, races' elytra, rockets and boats, the
# treasure compass), archery's match bow and arrow, spleef's shovel. Only ever on a game's things, never anyone's own.
GAME_TAGS = (KIT_TAG, "solmatch", "solspleef")


def _dropped(tag: str) -> str:
    """Every item lying about with this game's mark."""
    return f'@e[type=minecraft:item,nbt={{Item:{{components:{{"minecraft:custom_data":{{{tag}:1b}}}}}}}}]'


def _ground(tag: str) -> str:
    return f"kill {_dropped(tag)}"


async def hand_back_dropped(srv, reach: int = 16) -> None:
    """During a game, each second: a game's thing dropped (by accident, or on purpose) goes straight back to whoever's
    nearest, normally whoever dropped it, so a slip of the Q key doesn't cost a sword mid-fight or an elytra mid-race.
    It can't be left lying about to pick up later; with nobody near (thrown off a cliff, say) it's simply gone."""
    near = f"@p[distance=..{reach},gamemode=!spectator]"
    for tag in GAME_TAGS:
        sel = _dropped(tag)
        await _rcon(srv, f"execute as {sel} at @s if entity {near} run data merge entity @s {{PickupDelay:0s}}")
        await _rcon(srv, f"execute as {sel} at @s run tp @s {near}")
        await _rcon(srv, f"execute as {sel} at @s unless entity {near} run kill @s")


async def sweep(srv) -> None:
    """The game's things left lying about go: thrown down in a game (to pick up after), or anywhere at all. A kit's
    item on the ground is never meant to be there (dying keeps it, with keep-inventory on for games), so this runs
    every second of a fight, and on every check of the server besides. Nothing of anyone's own: only items marked as a kit's."""
    for tag in GAME_TAGS:
        await _rcon(srv, _ground(tag))


async def _home(srv, kept: dict[str, str], game_id: str, secs: int, after) -> None:
    from . import challenges
    from .control import component
    try:
        for left in range(secs, 0, -1):
            for u in kept.values():
                await _rcon(srv, f"title {u} actionbar {component([(f'Back home with your things in {left}…', 'gold')])}")
            await asyncio.sleep(1)
        for n, u in kept.items():
            try:
                if await give_back(srv, u, move=True):           # offline: when they're next on (on_join)
                    await challenges.deliver_now(srv, n)         # a prize won, now there's somewhere safe for it
            except Exception:
                log.exception("sending %s home failed (tried again when they're next on)", n)
        await sweep(srv)
        if after:
            await after()
    except Exception:
        log.exception("the trip home from %s failed", game_id)
    finally:
        _heading_home.pop(game_id, None)


def has_things_kept(sid: str, player: str) -> bool:
    """In a game right now (their own things in the vault): nothing should be handed to them till they're home."""
    return any(s["name"].lower() == player.lower() and not s.get("restored") for s in waiting(sid))


async def tidy(srv, online: list[str]) -> None:
    """Every so often: anyone online with things still in the vault from a game that's over gets them back."""
    lower = {n.lower() for n in online}
    for s in waiting(srv.id):
        if s["name"].lower() in lower and (s.get("restored") or not _in_live_game(s)):
            await give_back(srv, s["uuid"], move=False)  # (Solstone's catching up: they may have gone somewhere since)


async def no_stray_kit(srv, online: list[str]) -> None:
    """Every poll: a game's things never stay with anyone after it. Lying on the ground: gone. In the hands of
    someone who isn't in a game (dropped in the game, then picked up after walking out, say): taken back."""
    playing = {s["name"].lower() for s in waiting(srv.id) if not s.get("restored")}
    if not playing:                                    # (during a game, what's dropped goes back to its player instead)
        await sweep(srv)
    from . import challenges
    if not challenges.rods_out(srv.id):                # a fishing contest's rods: not while one's on (they're fishing with them)
        await _rcon(srv, _ground("solrod"))
    for n in online:
        if n.lower() not in playing:
            for tag in GAME_TAGS:
                await _rcon(srv, f"clear {n} *[minecraft:custom_data={{{tag}:1b}}]")


# ------------------------------------------------------------------ the kits themselves
def kit_item(item: str) -> str:
    """An item marked as the game's (taken back afterwards; never mixed up with their own)."""
    return f"{item}[minecraft:custom_data={{{KIT_TAG}:1b}},minecraft:unbreakable={{}}]"


TIERS = ("wooden", "stone", "iron", "diamond", "netherite")
ARMOUR = {"leather": "leather", "chainmail": "chainmail", "iron": "iron", "diamond": "diamond", "netherite": "netherite"}


MAX_ARROWS = 256                     # four stacks


def clean_kit(body: dict) -> dict:
    k = body if isinstance(body, dict) else {}
    sword = k.get("sword") if k.get("sword") in TIERS else "iron"
    armour = k.get("armour") if k.get("armour") in (*ARMOUR, "none") else "iron"
    try:
        arrows = max(0, min(MAX_ARROWS, int(k.get("arrows", 16))))
    except (TypeError, ValueError):
        arrows = 16
    # infinite: an Infinity bow and one arrow, like the archery games' Match Bow (it never runs out)
    return {"sword": sword, "armour": armour, "bow": bool(k.get("bow", True)), "arrows": arrows, "infinite": bool(k.get("infinite")),
            "shield": bool(k.get("shield", False)), "food": bool(k.get("food", True))}


async def give_kit(srv, uuid: str, kit: dict) -> None:
    """Hand out a kit to someone whose things are safe in the vault (their hands are empty)."""
    sword = kit_item(f"minecraft:{kit['sword']}_sword")
    await _rcon(srv, f"give {uuid} {sword} 1")
    if kit.get("bow") and kit.get("infinite"):           # never runs out: Infinity, and the one arrow it needs
        from .races import _new_text
        ench = '{"minecraft:infinity":1}' if _new_text(srv) else '{levels:{"minecraft:infinity":1}}'
        await _rcon(srv, f"give {uuid} {kit_item('minecraft:bow')[:-1]},minecraft:enchantments={ench}] 1")
        await _rcon(srv, f"give {uuid} {kit_item('minecraft:arrow')} 1")
    elif kit.get("bow"):
        await _rcon(srv, f"give {uuid} {kit_item('minecraft:bow')} 1")
        if kit.get("arrows"):
            await _rcon(srv, f"give {uuid} {kit_item('minecraft:arrow')} {kit['arrows']}")
    if kit.get("food"):
        await _rcon(srv, f"give {uuid} {kit_item('minecraft:cooked_beef')} 16")
    worn: list[tuple[str, str]] = []                   # (slot, item) put straight on, checked below
    if kit.get("shield"):
        worn.append(("weapon.offhand", kit_item("minecraft:shield")))
    if kit.get("armour") and kit["armour"] != "none":
        m = ARMOUR[kit["armour"]]
        for slot, piece in (("armor.head", "helmet"), ("armor.chest", "chestplate"), ("armor.legs", "leggings"), ("armor.feet", "boots")):
            worn.append((slot, kit_item(f"minecraft:{m}_{piece}")))
    replies = {}
    for slot, item in worn:
        replies[slot] = await _rcon(srv, f"item replace entity {uuid} {slot} with {item}")
    await _check_kit(srv, uuid, kit, worn, replies)


def _kit_ids(kit: dict, worn: list[tuple[str, str]]) -> list[str]:
    """Every item a kit should have handed over, by id."""
    ids = [f"minecraft:{kit['sword']}_sword"]
    if kit.get("bow"):
        ids += ["minecraft:bow"] + (["minecraft:arrow"] if kit.get("infinite") or kit.get("arrows") else [])
    if kit.get("food"):
        ids.append("minecraft:cooked_beef")
    return ids + [item.split("[", 1)[0] for _slot, item in worn]


async def _check_kit(srv, uuid: str, kit: dict, worn: list[tuple[str, str]], replies: dict) -> None:
    """Did it all arrive? Armour or the shield that didn't go on is put on again, and if it still won't, it goes in
    their inventory (they can wear it from there); anything else missing is given again. What the game said goes in
    the log, so a version that turns something away shows up."""
    have = await _player_items(srv, uuid)
    if have is None:
        return                                          # couldn't look: (they left, say) nothing more to do
    missing = [i for i in _kit_ids(kit, worn) if not have[0].get(i)]
    if not missing:
        return
    log.warning("the kit for %s arrived without %s (the game said: %s)", uuid, ", ".join(missing),
                "; ".join(f"{k}: {v[:120]}" for k, v in replies.items()) or "nothing")
    for slot, item in worn:
        if item.split("[", 1)[0] in missing:
            await _rcon(srv, f"item replace entity {uuid} {slot} with {item}")
    have = await _player_items(srv, uuid) or have
    for _slot, item in worn:
        if not have[0].get(item.split("[", 1)[0]):
            await _rcon(srv, f"give {uuid} {item} 1")      # still not on: in their inventory, to put on themselves
    for i in missing:
        if i in [it.split("[", 1)[0] for _s, it in worn] or have[0].get(i):
            continue
        n = {"minecraft:arrow": 1 if kit.get("infinite") else kit.get("arrows", 16), "minecraft:cooked_beef": 16}.get(i, 1)
        await _rcon(srv, f"give {uuid} {kit_item(i)} {n}")
