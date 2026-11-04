"""Event kits, with everyone's own things kept safe (King of the Hill, the mob arena, elytra races).

Before a game hands out its gear, each player's whole inventory (36 slots, armour and off-hand) is copied, exactly,
enchantments, names and all, into two barrels of their own in a vault sealed in bedrock at the bottom of the world
under spawn. The copy is checked against what they had, item for item; only then is the player cleared and given the
kit. A player whose things couldn't be copied safely isn't cleared: they watch that game instead.

Afterwards only the kit is taken away (every kit item is marked as the game's). Nothing else of theirs is ever
cleared: anything else they're carrying by then (picked up in the game, or gathered while Solstone was down and
couldn't give their things back) is first copied, and checked, into a second pair of barrels, their "pocket". Then
their own things are copied back to the same slots, checked again, and only then is that barrel emptied. Last, the
pocket's things go into their empty slots; whatever doesn't fit waits in the pocket, they're told to make room, and
it arrives by itself when they do. Nothing is ever dropped on the ground.

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
    async with _lock:
        d = _load()
        v = await _vault(srv, d)
        _save(d)
        for name, uuid in players.items():
            key = f"{srv.id}:{uuid}"
            if key in d["stash"]:                       # already has things in the vault (an earlier game): leave them be
                log.warning("%s already has things kept safe; not stashing again", name)
                continue
            slot = _free_slot(d, srv.id)
            back = await _where(srv, uuid)
            before = await _player_items(srv, uuid)
            if slot is None or back is None or before is None:
                continue
            a, b = _barrels(v, slot)
            for (x, y, z) in (a, b):
                await _rcon(srv, f"execute in {DIM} run setblock {x} {y} {z} minecraft:barrel")
                await _rcon(srv, f"execute in {DIM} run data merge block {x} {y} {z} {{Items:[]}}")
            for src, which, i in SLOTS:
                x, y, z = (a, b)[which]
                await _rcon(srv, f"execute in {DIM} run item replace block {x} {y} {z} container.{i} from entity {uuid} {src}")
            if await _barrel_items(srv, (a, b)) != before:
                log.error("couldn't copy %s's things safely; leaving them as they are", name)
                for (x, y, z) in (a, b):
                    await _rcon(srv, f"execute in {DIM} run data merge block {x} {y} {z} {{Items:[]}}")
                continue
            if await _player_items(srv, uuid) != before:     # picked something up while it was being copied: not this time
                log.warning("%s's things changed while being copied; leaving them as they are", name)
                for (x, y, z) in (a, b):
                    await _rcon(srv, f"execute in {DIM} run data merge block {x} {y} {z} {{Items:[]}}")
                continue
            # written down first: from here on, a crash still leaves a copy that gets given back
            d["stash"][key] = {"name": name, "uuid": uuid, "server": srv.id, "slot": slot, "game": game, "at": time.time(),
                               "back": back, "gm": await _gamemode(srv, name)}
            _save(d)
            await _rcon(srv, f"clear {uuid}")
            done.append(name)
        await _rcon(srv, f"execute in {DIM} run forceload remove {v['x']} {v['z']}")
    return done


async def _empty(srv, spots) -> None:
    for (x, y, z) in spots:
        await _rcon(srv, f"execute in {DIM} run data merge block {x} {y} {z} {{Items:[]}}")


async def _copy_out(srv, uuid: str, spots) -> None:
    """Every slot of theirs into this pair of barrels (empty ones too, so the barrels match them exactly)."""
    for (x, y, z) in spots:
        await _rcon(srv, f"execute in {DIM} run setblock {x} {y} {z} minecraft:barrel")
    await _empty(srv, spots)
    for src, which, i in SLOTS:
        x, y, z = spots[which]
        await _rcon(srv, f"execute in {DIM} run item replace block {x} {y} {z} container.{i} from entity {uuid} {src}")


async def give_back(srv, uuid: str, move: bool = True) -> bool:
    """Give one player their things back, exactly, and put them back where they were. Only the kit is taken away:
    anything else they're carrying is kept (see the top). False if they're not online (it's tried again when they
    are) or it didn't check out (everything stays where it is, safe)."""
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
            if not s.get("restored"):
                if not await _restore(srv, d, s, v, move):
                    return False
            await _pocket_out(srv, d, s, v)
            await _rcon(srv, f"clear {uuid} {KIT_MATCH}")     # and never a kit item left behind with their things
            return True
        finally:
            if not any(k.startswith(f"{srv.id}:") for k in d["stash"]):
                await _rcon(srv, f"execute in {DIM} run forceload remove {v['x']} {v['z']}")


async def _restore(srv, d: dict, s: dict, v: dict, move: bool) -> bool:
    uuid = s["uuid"]
    a, b = _barrels(v, s["slot"])
    kept = await _barrel_items(srv, (a, b))
    await _rcon(srv, f"clear {uuid} {KIT_MATCH}")       # the game's kit: nothing else
    now = await _player_items(srv, uuid)
    if now is None:
        return False
    # (exactly theirs, or theirs plus a few things picked up: at least 3 kinds of item, so a stray block picked up in
    # a game is never mistaken for someone's whole inventory)
    if sum(kept[0].values()) and (now == kept or (len(kept[0]) >= 3 and _has_all(now, kept))):
        # Their own things are on them already (an earlier give-back landed but its check didn't pass): the copy in
        # the vault is only a spare now. Emptied, not handed over again: handing it over again duplicated things.
        log.warning("%s already has their things back; emptying the spare copy in the vault", s["name"])
        await _empty(srv, (a, b))
        s["restored"] = True
        _save(d)
        await _rcon(srv, f"gamemode {s.get('gm') or 'survival'} {uuid}")
        return True
    if sum(now[0].values()):                             # carrying something: into their pocket first, checked
        if s.get("pocket") is not None:
            log.error("%s is carrying things and already has a pocket; leaving everything as it is", s["name"])
            return False
        slot = _free_slot(d, srv.id)
        if slot is None:
            log.error("no room in the vault for %s's pocket; leaving everything as it is", s["name"])
            return False
        pocket = _barrels(v, slot)
        await _copy_out(srv, uuid, pocket)
        if await _barrel_items(srv, pocket) != now or await _player_items(srv, uuid) != now:
            log.error("couldn't keep what %s is carrying safely; leaving everything as it is", s["name"])
            await _empty(srv, pocket)
            return False
        s["pocket"] = slot
        _save(d)                                         # written down before anything of theirs is touched
    await _rcon(srv, f"clear {uuid}")                    # (only what's now safe in the pocket, or nothing)
    for src, which, i in SLOTS:
        x, y, z = (a, b)[which]
        await _rcon(srv, f"execute in {DIM} run item replace entity {uuid} {src} from block {x} {y} {z} container.{i}")
    if await _player_items(srv, uuid) != kept:
        log.error("giving %s's things back didn't check out; their copy stays in the vault", s["name"])
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
    return True


async def _pocket_out(srv, d: dict, s: dict, v: dict) -> None:
    """What they were carrying, into their empty slots. What doesn't fit waits; they're told once."""
    key, uuid = f"{srv.id}:{s['uuid']}", s["uuid"]
    if s.get("pocket") is not None:
        spots = _barrels(v, s["pocket"])
        inv = await _rcon(srv, f"data get entity {uuid} Inventory")
        if "has the following" not in inv:
            return
        used = {n for n in (int(x) for x in _SLOT.findall(inv.split("data:", 1)[-1])) if 0 <= n < 36}
        free = [n for n in range(36) if n not in used]
        left = 0
        for spot in spots:
            x, y, z = spot
            for i in sorted({int(n) for n in _SLOT.findall(await _rcon(srv, f"execute in {DIM} run data get block {x} {y} {z} Items"))}):
                if not free:
                    left += 1
                    continue
                to = free.pop(0)
                await _rcon(srv, f"execute in {DIM} run item replace entity {uuid} container.{to} from block {x} {y} {z} container.{i}")
                got = await _rcon(srv, f"data get entity {uuid} Inventory")
                if to in {int(n) for n in _SLOT.findall(got.split("data:", 1)[-1])}:
                    await _rcon(srv, f"execute in {DIM} run item replace block {x} {y} {z} container.{i} with minecraft:air")
                else:
                    left += 1                            # (didn't arrive: it stays in the pocket)
        if left:
            if not s.get("told"):
                s["told"] = True
                await _rcon(srv, f"tellraw {uuid} " + _msg(f"{left} more of your things are kept safe until you have room. "
                                                           "Make some space and they'll arrive by themselves."))
            _save(d)
            return
        await _empty(srv, spots)
    d["stash"].pop(key, None)
    _save(d)


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
    from .games import ACTIVE, _load as games_load
    return any(r["id"] == s.get("game") and r["state"] in ACTIVE for r in games_load()["runs"])


async def tidy(srv, online: list[str]) -> None:
    """Every so often: anyone online with things still in the vault from a game that's over gets them back."""
    lower = {n.lower() for n in online}
    for s in waiting(srv.id):
        if s["name"].lower() in lower and (s.get("restored") or not _in_live_game(s)):
            await give_back(srv, s["uuid"], move=False)  # (Solstone's catching up: they may have gone somewhere since)


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
    if kit.get("shield"):
        await _rcon(srv, f"item replace entity {uuid} weapon.offhand with {kit_item('minecraft:shield')}")
    if kit.get("armour") and kit["armour"] != "none":
        m = ARMOUR[kit["armour"]]
        for slot, piece in (("armor.head", "helmet"), ("armor.chest", "chestplate"), ("armor.legs", "leggings"), ("armor.feet", "boots")):
            item = kit_item(f"minecraft:{m}_{piece}")
            await _rcon(srv, f"item replace entity {uuid} {slot} with {item}")
