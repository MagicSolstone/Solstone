"""Solstone's data pack: the archery and games half, and a light touch on fishing.

Fishing stays vanilla: the same items, odds, names and loot (nothing is written on the fish). The pack only notices
each fish someone catches and gives it a weight, kept for Solstone (contests, the fishing journal on the website):
- An advancement fires when a fish is hooked; one tick later a function finds that freshly spawned fish item (a few
  ticks old, not seen before: dropping and picking up fish never counts) and records it with a weight: a random
  size for its kind, big ones rarer. Points are a point per pound (and one for catching it).
- Scoreboards: solfish_points lifetime points, solfish_count fish caught, solfish_cp points this contest,
  solfish_cb heaviest this contest (tenths of lb). Only a contest shows them (and announces catches in chat).
- Each catch is appended to storage solstone:fish catches (a sequence number, the catcher's UUID) for Solstone to
  read over RCON.
On a server with the Tide fishing mod the pack leaves fishing alone completely: Tide's own catches are used.
Minecraft 1.21+ (one pack.mcmeta covers 1.21 to 26.x).

The pack doesn't depend on the game's shared #minecraft:load / #minecraft:tick lists working: every pack and mod adds
to them, and one entry pointing at something missing can make the game drop a whole list. Solstone runs the load
functions itself when it can't see the version marker (fishing.check), and the games' tick keeps itself going with
`schedule` instead of being on the tick list.
"""
from __future__ import annotations

import io
import json
import re
import zipfile

PACK_ID = "solstone-pack"                     # one pack: fishing and the archery games
PACK_FILE = f"{PACK_ID}.zip"
VERSION = 13                                   # bump when the pack's content changes

# ------------------------------------------------------------------ the fish (vanilla)
# key (the vanilla item): (name, smallest lb, biggest lb)
SPECIES: dict[str, tuple[str, float, float]] = {
    "cod": ("Cod", 1.0, 12.0),
    "salmon": ("Salmon", 2.0, 20.0),
    "tropical_fish": ("Tropical Fish", 0.2, 1.5),
    "pufferfish": ("Pufferfish", 0.5, 3.0),
}
# Older catches (from the pack's fancier days) kept their quality; new ones are all "Normal" (index 1).
QUALITIES = [("Poor", "gray"), ("Normal", "white"), ("Fine", "green"), ("Trophy", "aqua"), ("Legendary", "gold"), ("Mythic", "light_purple")]


def fmt_lb(w: float) -> str:
    return f"{w:.2f}".rstrip("0").rstrip(".") if w < 1 else f"{w:.1f}"


def points(lb: float) -> int:
    return int(lb) + 1


def guide() -> list[dict]:
    """For the web page: each fish and its size range."""
    return [{"key": k, "name": n, "item": f"minecraft:{k}", "waters": [], "min_lb": lo, "max_lb": hi,
             "min_points": points(lo), "max_points": points(hi), "rarity": ""} for k, (n, lo, hi) in SPECIES.items()]


def qualities() -> list[dict]:
    return []                                 # vanilla fish have no quality


def new_loot_format(version: str | None, data_version: int | None = None) -> bool:
    """26.3 rewrote loot tables: functions are `modifier` with `type`, conditions are `condition`
    with `type`. Older games silently ignore the new spelling and 26.3 silently ignores the old
    one, so the pack is built for the server it's going to."""
    nums = [int(x) for x in re.findall(r"\d+", version or "")[:2]]
    if len(nums) == 2 and nums[0] >= 26:
        return tuple(nums) >= (26, 3)
    if len(nums) == 2 and nums[0] == 1:
        return False
    return bool(data_version and data_version >= 5023)


def to_263(o):
    """A loot table in the pre-26.3 shape -> the 26.3 shape."""
    if isinstance(o, list):
        return [to_263(x) for x in o]
    if not isinstance(o, dict):
        return o
    out = {}
    for k, v in o.items():
        if k == "functions":
            out["modifier"] = to_263(v)
        elif k == "conditions":
            cs = to_263(v)
            out["condition"] = cs[0] if len(cs) == 1 else {"type": "minecraft:all_of", "terms": cs}
        elif k in ("function", "condition") and isinstance(v, str):
            out["type"] = v
        else:
            out[k] = to_263(v)
    return out


def _size(item: str) -> str:
    _n, lo, hi = SPECIES[item]
    return f"execute if items entity @s contents minecraft:{item} run function solfish:size {{lo:{int(lo * 10)},hi:{int(hi * 10)}}}"


FUNCTIONS = {
    "load": """
scoreboard objectives add solfish_points dummy "Fishing points"
scoreboard objectives add solfish_count dummy "Fish caught"
scoreboard objectives add solfish_cp dummy "Contest points"
scoreboard objectives add solfish_cb dummy "Heaviest catch"
scoreboard objectives add solfish_tmp dummy
scoreboard players set #ten solfish_tmp 10
execute unless data storage solstone:fish catches run data modify storage solstone:fish catches set value []
data modify storage solstone:fish pack set value {version:%VERSION%}
""",
    # The advancement fires as the fish is hooked, before the fish exists: look one tick later.
    "hooked": """
advancement revoke @s only solfish:hooked
tag @s add solfish_pending
schedule function solfish:scan 1t append
""",
    "scan": """
execute as @a[tag=solfish_pending] at @s run function solfish:scan_player
""",
    "scan_player": """
tag @s remove solfish_pending
tag @s add solfish_catcher
data modify storage solstone:fish who set from entity @s UUID
scoreboard players set #done solfish_tmp 0
execute as @e[type=item,distance=..64,tag=!solfish_seen,sort=nearest] if items entity @s contents #solfish:fish run function solfish:check_item
tag @s remove solfish_catcher
""",
    # Each hook claims one fish: the nearest that has only just appeared (a dropped fish is old,
    # and anything looked at once is never counted again).
    "check_item": """
execute if score #done solfish_tmp matches 1 run return 0
execute store result score #age solfish_tmp run data get entity @s Age
tag @s add solfish_seen
execute if score #age solfish_tmp matches 5.. run return 0
scoreboard players set #done solfish_tmp 1
function solfish:record
""",
    # A size for its kind (tenths of a pound): the smaller of two rolls, so big ones are rarer.
    "size": """
$execute store result score #w solfish_tmp run random value $(lo)..$(hi)
$execute store result score #b solfish_tmp run random value $(lo)..$(hi)
scoreboard players operation #w solfish_tmp < #b solfish_tmp
""",
    "record": "\n".join(["data modify storage solstone:fish e set value {}",
                          "data modify storage solstone:fish e.s set from entity @s Item.id",
                          *[_size(k) for k in SPECIES], """
execute store result storage solstone:fish e.w int 1 run scoreboard players get #w solfish_tmp
scoreboard players operation #p solfish_tmp = #w solfish_tmp
scoreboard players operation #p solfish_tmp /= #ten solfish_tmp
scoreboard players add #p solfish_tmp 1
execute store result storage solstone:fish e.p int 1 run scoreboard players get #p solfish_tmp
data modify storage solstone:fish e.u set from storage solstone:fish who
data modify storage solstone:fish e.pos set from entity @s Pos
execute store result storage solstone:fish e.i int 1 run scoreboard players add #seq solfish_tmp 1
execute store result storage solstone:fish e.t long 1 run time query gametime
data modify storage solstone:fish catches append from storage solstone:fish e
execute if data storage solstone:fish catches[80] run data remove storage solstone:fish catches[0]
scoreboard players operation @a[tag=solfish_catcher,limit=1] solfish_points += #p solfish_tmp
scoreboard players operation @a[tag=solfish_catcher,limit=1] solfish_cp += #p solfish_tmp
scoreboard players add @a[tag=solfish_catcher,limit=1] solfish_count 1
scoreboard players operation @a[tag=solfish_catcher,limit=1] solfish_cb > #w solfish_tmp
"""]),
}


# ------------------------------------------------------------------ archery (games)
# Where each shot was taken from (the bow/crossbow "used" statistic ticks up on release; a tick
# function notes the shooter's position), and every target hit with its ring (signal strength
# 1-15, 15 = bullseye) via one advancement per strength. Both go to storage solstone:games log
# for Solstone to pair up: a shot, then a hit from the same player within a few seconds.
GAME_FUNCTIONS = {
    "load": """
scoreboard objectives add solg_bow minecraft.used:minecraft.bow
scoreboard objectives add solg_xbow minecraft.used:minecraft.crossbow
scoreboard objectives add solg_tmp dummy
execute unless data storage solstone:games log run data modify storage solstone:games log set value []
data modify storage solstone:games pack set value {version:%VERSION%}
schedule function solgames:tick 1t replace
""",
    # every tick, by scheduling itself again (not on #minecraft:tick: see the top of this file)
    "tick": """
execute as @a[scores={solg_bow=1..}] at @s run function solgames:shot
execute as @a[scores={solg_xbow=1..}] at @s run function solgames:shot
execute if score #spleef_hb solg_tmp matches 1.. run scoreboard players remove #spleef_hb solg_tmp 1
execute if score #spleef_hb solg_tmp matches ..0 if data storage solstone:games spleef.arena run function solgames:spleef_failsafe
execute if score #spleef_hb solg_tmp matches ..0 if data storage solstone:games spleef.zone run function solgames:spleef_guard with storage solstone:games spleef.zone
schedule function solgames:tick 1t replace
""",
    # Spleef's safety net. Solstone sets #spleef_hb every few seconds while a game is on; if that
    # stops for two minutes (Solstone down), everyone goes back and the arena comes down, here.
    "spleef_failsafe": """
function solgames:spleef_back
function solgames:spleef_clear with storage solstone:games spleef.arena
data remove storage solstone:games spleef.arena
team remove solsp_red
team remove solsp_blue
tellraw @a [{"text":"★ ","color":"gold"},{"text":"Spleef stopped (Solstone went quiet), so everyone was sent back and the arena was taken down.","color":"yellow"}]
""",
    "spleef_back": """
execute unless data storage solstone:games spleef.back[0] run return 0
function solgames:spleef_back1 with storage solstone:games spleef.back[0]
data remove storage solstone:games spleef.back[0]
function solgames:spleef_back
""",
    "spleef_back1": """
$execute in $(d) run tp $(n) $(x) $(y) $(z)
$gamemode $(g) $(n)
$clear $(n) minecraft:diamond_shovel[minecraft:custom_data={solspleef:1b}]
$effect clear $(n) minecraft:resistance
$effect clear $(n) minecraft:saturation
""",
    "spleef_clear": """
$execute in $(d) run fill $(x1) $(yb) $(z1) $(x2) $(yt) $(z2) minecraft:air replace minecraft:snow_block
$execute in $(d) run fill $(bx1) $(yb) $(bz1) $(bx2) $(yt2) $(bz2) minecraft:air replace minecraft:barrier
$execute in $(d) run fill $(px1) $(py1) $(pz1) $(px2) $(py2) $(pz2) minecraft:air replace minecraft:water
$execute in $(d) run fill $(px1) $(py1) $(pz1) $(px2) $(py2) $(pz2) minecraft:air replace minecraft:glass
$execute in $(d) run forceload remove $(px1) $(pz1) $(px2) $(pz2)
""",
    # anyone found up where the arena was (offline when it came down) goes to spawn
    "spleef_guard": """
$execute in $(d) as @a[x=$(x),y=$(y),z=$(z),dx=$(dx),dy=$(dy),dz=$(dz),gamemode=!creative,gamemode=!spectator] run tp @s $(sx) $(sy) $(sz)
""",
    "shot": """
scoreboard players set @s solg_bow 0
scoreboard players set @s solg_xbow 0
data modify storage solstone:games e set value {k:"shot"}
data modify storage solstone:games e.u set from entity @s UUID
data modify storage solstone:games e.p set from entity @s Pos
execute store result storage solstone:games e.i int 1 run scoreboard players add #seq solg_tmp 1
data modify storage solstone:games log append from storage solstone:games e
execute if data storage solstone:games log[150] run data remove storage solstone:games log[0]
""",
}


def _hit_function(n: int) -> str:
    return f"""advancement revoke @s only solgames:hit_{n}
data modify storage solstone:games e set value {{k:"hit",s:{n}}}
data modify storage solstone:games e.u set from entity @s UUID
data modify storage solstone:games e.p set from entity @s Pos
execute store result storage solstone:games e.i int 1 run scoreboard players add #seq solg_tmp 1
data modify storage solstone:games log append from storage solstone:games e
execute if data storage solstone:games log[150] run data remove storage solstone:games log[0]
"""


def pack_files(new: bool = False, fishing: bool = True) -> dict[str, str]:
    """`new`: the 26.3+ loot format (the games' tables). `fishing=False` (a server with the Tide fishing mod,
    which does fishing its own way): just the archery and games half, plus the version marker."""
    files = {
        "pack.mcmeta": json.dumps({"pack": {
            "description": "Solstone: archery games, and fish weights for contests" if fishing else "Solstone: archery and games",
            # 1.21 (48) up to anything newer; old fields for <1.21.9, min/max for 1.21.9+
            "pack_format": 48, "supported_formats": {"min_inclusive": 48, "max_inclusive": 999},
            "min_format": 48, "max_format": 999}}, indent=1),
        "data/minecraft/tags/function/load.json": json.dumps({"values": ["solfish:load", "solgames:load"]}),
    }
    if fishing:                                    # fishing itself stays vanilla: no loot tables, just noticing catches
        files.update({
            "data/solfish/tags/item/fish.json": json.dumps({"values": [f"minecraft:{k}" for k in SPECIES]}),
            "data/solfish/advancement/hooked.json": json.dumps({
                "criteria": {"hooked": {"trigger": "minecraft:fishing_rod_hooked"}},
                "rewards": {"function": "solfish:hooked"}}),
        })
    for name, body in FUNCTIONS.items():
        if fishing or name == "load":                  # load: the scoreboards and the version marker
            files[f"data/solfish/function/{name}.mcfunction"] = body.replace("%VERSION%", str(VERSION)).strip() + "\n"
    for name, body in GAME_FUNCTIONS.items():
        files[f"data/solgames/function/{name}.mcfunction"] = body.replace("%VERSION%", str(VERSION)).strip() + "\n"
    for n in range(1, 16):
        files[f"data/solgames/advancement/hit_{n}.json"] = json.dumps({
            "criteria": {"hit": {"trigger": "minecraft:target_hit", "conditions": {"signal_strength": n}}},
            "rewards": {"function": f"solgames:hit_{n}"}})
        files[f"data/solgames/function/hit_{n}.mcfunction"] = _hit_function(n)
    return files


def parse_game_log(reply: str) -> list[dict]:
    """`data get storage solstone:games log` -> [{k: shot|hit, uuid, pos (x, y, z), s (ring), i}]."""
    import nbtlib
    if not reply or "[" not in reply:
        return []
    try:
        data = nbtlib.parse_nbt(reply[reply.index("["):].strip())
    except Exception:
        return []
    out = []
    for e in data:
        try:
            u = [int(x) & 0xFFFFFFFF for x in e.get("u", [])]
            h = "".join(f"{x:08x}" for x in u)
            uuid = f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}" if len(u) == 4 else ""
            p = [float(v) for v in e.get("p", [])]
            out.append({"k": str(e["k"]), "uuid": uuid, "pos": tuple(p) if len(p) == 3 else None, "s": int(e.get("s", 0)), "i": int(e["i"])})
        except (KeyError, ValueError, TypeError):
            continue
    return out


def build_zip(new: bool = False, fishing: bool = True) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for path, body in sorted(pack_files(new, fishing).items()):
            z.writestr(path, body)
    return buf.getvalue()


# ------------------------------------------------------------------ reading catches back
def parse_catches(reply: str) -> list[dict]:
    """`data get storage solstone:fish catches` -> plain dicts (uuid as a normal UUID string)."""
    import nbtlib
    if not reply or ":" not in reply or "[" not in reply:
        return []
    try:
        data = nbtlib.parse_nbt(reply[reply.index("["):].strip())
    except Exception:
        return []
    out = []
    for c in data:
        try:
            u = [int(x) & 0xFFFFFFFF for x in c.get("u", [])]
            uuid = "".join(f"{x:08x}" for x in u) if len(u) == 4 else ""
            uuid = f"{uuid[:8]}-{uuid[8:12]}-{uuid[12:16]}-{uuid[16:20]}-{uuid[20:]}" if uuid else ""
            species = str(c["s"]).removeprefix("minecraft:")
            w = int(c["w"]) / 10
            basic = c.get("n") is None                     # a vanilla fish with a weight (pack v12+)
            out.append({"i": int(c["i"]), "species": species, "name": str(c["n"]) if not basic else SPECIES.get(species, (species.replace("_", " ").title(),))[0],
                        "quality": int(c.get("q", 1)), "quality_name": str(c.get("ql", "Normal")), "basic": basic,
                        "weight": w, "lb": str(c["lb"]) if not basic else fmt_lb(w), "points": int(c["p"]), "uuid": uuid,
                        # where the fish came out of the water (a fresh catch is still at the bobber); pack v9+
                        "pos": [float(v) for v in c["pos"]] if c.get("pos") is not None and len(c["pos"]) == 3 else None})
        except (KeyError, ValueError, TypeError):
            continue
    return out
