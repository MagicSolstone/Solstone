"""Solstone Fishing: a data pack that turns fishing into a game of species, sizes and quality.

Everything is generated here from the tables below, so the fish guide on the web pages and the
pack in the game can never disagree. Minecraft 1.21+ (one pack.mcmeta covers 1.21 to 26.x).

In the game
- The fish loot table (gameplay/fishing/fish) is replaced: what you can catch depends on where
  the bobber lands (rivers and lakes, oceans, warm or cold water, swamps, jungle rivers, deep
  ocean) and every catch has a species, a weight and one of five qualities: Poor, Normal,
  Quality, Prime, Exquisite. Rarer quality = heavier fish = more points. The item keeps its
  vanilla kind (cod, salmon, tropical fish, pufferfish), so it can still be cooked or eaten;
  its name, colour and lore say what it is.
- Scoring can't be gamed by dropping and picking up fish: an advancement fires when a fish is
  hooked, and one tick later a function finds that freshly spawned fish (age a few ticks, not
  seen before), records it, and adds its points to scoreboards:
    solfish_points  lifetime points       solfish_count  fish caught
    solfish_cp      points this challenge solfish_cb     heaviest this challenge (tenths of lb)
- Each catch is appended to storage solstone:fish catches (with a sequence number and the
  catcher's UUID) for Solstone to read over RCON: the web pages show catches, and during a
  fishing challenge Solstone announces every catch to everyone.
"""
from __future__ import annotations

import io
import json
import zipfile

PACK_ID = "solstone-pack"                     # one pack: fishing and the archery games
PACK_FILE = f"{PACK_ID}.zip"
VERSION = 2                                   # bump when the pack's content changes

# ------------------------------------------------------------------ the water
_OCEAN = ["ocean", "deep_ocean", "cold_ocean", "deep_cold_ocean", "lukewarm_ocean", "deep_lukewarm_ocean",
          "warm_ocean", "frozen_ocean", "deep_frozen_ocean"]
WATERS = {
    "fresh": ("Rivers & lakes", None),                                      # anywhere that isn't ocean
    "river": ("Rivers", ["river", "frozen_river"]),
    "ocean": ("Oceans", _OCEAN),
    "deep": ("Deep ocean", ["deep_ocean", "deep_cold_ocean", "deep_lukewarm_ocean", "deep_frozen_ocean"]),
    "warm": ("Warm water", ["warm_ocean", "lukewarm_ocean", "deep_lukewarm_ocean", "mangrove_swamp", "beach"]),
    "cold": ("Cold water", ["cold_ocean", "deep_cold_ocean", "frozen_ocean", "deep_frozen_ocean", "frozen_river",
                            "snowy_taiga", "snowy_plains", "snowy_beach", "ice_spikes", "grove", "taiga", "old_growth_pine_taiga",
                            "old_growth_spruce_taiga"]),
    "swamp": ("Swamps", ["swamp", "mangrove_swamp"]),
    "jungle": ("Jungle", ["jungle", "sparse_jungle", "bamboo_jungle"]),
    "any": ("Anywhere", None),
}

# key: (name, vanilla item, typical weight lb, base points, waters, how common 1-30)
SPECIES: dict[str, tuple[str, str, float, int, list[str], int]] = {
    "bluegill": ("Bluegill", "cod", 0.5, 5, ["fresh"], 30),
    "perch": ("Yellow Perch", "cod", 1.0, 8, ["fresh"], 25),
    "bass": ("Largemouth Bass", "cod", 3.0, 15, ["fresh"], 20),
    "trout": ("Rainbow Trout", "salmon", 2.5, 15, ["fresh"], 18),
    "carp": ("Common Carp", "cod", 8.0, 18, ["fresh"], 12),
    "walleye": ("Walleye", "cod", 3.0, 20, ["river"], 12),
    "pike": ("Northern Pike", "salmon", 6.0, 25, ["fresh", "cold"], 8),
    "catfish": ("Channel Catfish", "cod", 10.0, 25, ["swamp", "river"], 14),
    "salmon": ("Atlantic Salmon", "salmon", 8.0, 20, ["river", "cold"], 14),
    "sturgeon": ("Lake Sturgeon", "salmon", 40.0, 60, ["river"], 2),
    "cod": ("Atlantic Cod", "cod", 6.0, 10, ["ocean"], 30),
    "mackerel": ("Mackerel", "cod", 1.5, 8, ["ocean"], 25),
    "seabass": ("Sea Bass", "cod", 5.0, 15, ["ocean"], 18),
    "halibut": ("Halibut", "cod", 25.0, 35, ["cold"], 6),
    "char": ("Arctic Char", "salmon", 4.0, 20, ["cold"], 14),
    "tuna": ("Bluefin Tuna", "salmon", 60.0, 50, ["deep"], 6),
    "swordfish": ("Swordfish", "salmon", 120.0, 80, ["deep", "warm"], 2),
    "clownfish": ("Clownfish", "tropical_fish", 0.3, 12, ["warm"], 20),
    "angelfish": ("Angelfish", "tropical_fish", 0.6, 14, ["warm"], 15),
    "puffer": ("Pufferfish", "pufferfish", 1.0, 12, ["warm", "ocean"], 8),
    "arapaima": ("Arapaima", "salmon", 100.0, 90, ["jungle"], 3),
    "koi": ("Golden Koi", "tropical_fish", 3.0, 120, ["any"], 1),
}

# (name, colour, size factor, points factor, how common)
QUALITIES = [
    ("Poor", "gray", 0.6, 0.5, 30),
    ("Normal", "white", 1.0, 1.0, 40),
    ("Quality", "green", 1.3, 1.5, 18),
    ("Prime", "aqua", 1.7, 2.5, 9),
    ("Exquisite", "gold", 2.3, 4.0, 3),
]
STEPS = (0.9, 1.0, 1.12)                       # a little spread inside each quality


def fmt_lb(w: float) -> str:
    return f"{w:.2f}".rstrip("0").rstrip(".") if w < 1 else f"{w:.1f}"


def variants():
    """Every catch the pack can give: (species key, quality index, weight lb, points)."""
    for key, (_n, _i, base, pts, _w, _c) in SPECIES.items():
        for qi, (_q, _col, size, pf, _qc) in enumerate(QUALITIES):
            for st in STEPS:
                w = round(base * size * st, 2 if base * size * st < 1 else 1)
                yield key, qi, w, max(1, round(pts * pf * st))


def guide() -> list[dict]:
    """For the web page: each species, where it lives, its size range and points range."""
    out = []
    for key, (name, item, _base, _pts, waters, common) in SPECIES.items():
        ws = [w for k, qi, w, p in variants() if k == key]
        ps = [p for k, qi, w, p in variants() if k == key]
        out.append({"key": key, "name": name, "item": f"minecraft:{item}", "waters": [WATERS[w][0] for w in waters],
                    "min_lb": min(ws), "max_lb": max(ws), "min_points": min(ps), "max_points": max(ps),
                    "rarity": "very rare" if common <= 2 else "rare" if common <= 6 else "uncommon" if common <= 12 else "common"})
    return out


def qualities() -> list[dict]:
    total = sum(q[4] for q in QUALITIES)
    return [{"name": n, "color": c, "chance": round(qc * 100 / total)} for n, c, _s, _p, qc in QUALITIES]


# ------------------------------------------------------------------ building the pack
def _water_condition(waters: list[str]) -> list[dict]:
    if "any" in waters:
        return []
    terms = []
    for w in waters:
        biomes = WATERS[w][1]
        if biomes is None:                    # fresh water: anywhere that isn't an ocean
            terms.append({"condition": "minecraft:inverted", "term": {"condition": "minecraft:location_check",
                          "predicate": {"biomes": [f"minecraft:{b}" for b in _OCEAN]}}})
        else:
            terms.append({"condition": "minecraft:location_check", "predicate": {"biomes": [f"minecraft:{b}" for b in biomes]}})
    return [terms[0]] if len(terms) == 1 else [{"condition": "minecraft:any_of", "terms": terms}]


def _text(text: str, color: str, italic: bool = False) -> dict:
    return {"text": text, "color": color, "italic": italic}


def loot_table() -> dict:
    entries = []
    for key, qi, w, p in variants():
        name, item, _b, _p, waters, common = SPECIES[key]
        q, color, _s, _pf, qc = QUALITIES[qi]
        tag = f'{{solfish:{{s:"{key}",n:"{name}",q:{qi},ql:"{q}",w:{int(round(w * 10))},lb:"{fmt_lb(w)}",p:{p}}}}}'
        entries.append({
            "type": "minecraft:item", "name": f"minecraft:{item}", "weight": common * qc,
            "conditions": _water_condition(waters),
            "functions": [
                {"function": "minecraft:set_name", "target": "item_name", "name": _text(f"{q} {name}" if q != "Normal" else name, color)},
                {"function": "minecraft:set_lore", "mode": "replace_all", "lore": [
                    _text(f"{fmt_lb(w)} lb · {q}", color), _text(f"{p} points", "yellow"), _text("Solstone Fishing", "dark_gray", True)]},
                {"function": "minecraft:set_custom_data", "tag": tag},
            ],
        })
        if not entries[-1]["conditions"]:
            del entries[-1]["conditions"]
    return {"type": "minecraft:fishing", "pools": [{"rolls": 1, "entries": entries}],
            "random_sequence": "minecraft:gameplay/fishing/fish"}


FUNCTIONS = {
    "load": """
scoreboard objectives add solfish_points dummy "Fishing points"
scoreboard objectives add solfish_count dummy "Fish caught"
scoreboard objectives add solfish_cp dummy "Challenge points"
scoreboard objectives add solfish_cb dummy "Heaviest catch"
scoreboard objectives add solfish_tmp dummy
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
execute as @e[type=item,distance=..64,tag=!solfish_seen,sort=nearest,nbt={Item:{components:{"minecraft:custom_data":{solfish:{}}}}}] run function solfish:check_item
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
    "record": """
data modify storage solstone:fish e set from entity @s Item.components."minecraft:custom_data".solfish
data modify storage solstone:fish e.u set from storage solstone:fish who
execute store result storage solstone:fish e.i int 1 run scoreboard players add #seq solfish_tmp 1
execute store result storage solstone:fish e.t long 1 run time query gametime
data modify storage solstone:fish catches append from storage solstone:fish e
execute if data storage solstone:fish catches[80] run data remove storage solstone:fish catches[0]
execute store result score #p solfish_tmp run data get storage solstone:fish e.p
execute store result score #w solfish_tmp run data get storage solstone:fish e.w
scoreboard players operation @a[tag=solfish_catcher,limit=1] solfish_points += #p solfish_tmp
scoreboard players operation @a[tag=solfish_catcher,limit=1] solfish_cp += #p solfish_tmp
scoreboard players add @a[tag=solfish_catcher,limit=1] solfish_count 1
scoreboard players operation @a[tag=solfish_catcher,limit=1] solfish_cb > #w solfish_tmp
""",
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
""",
    "tick": """
execute as @a[scores={solg_bow=1..}] at @s run function solgames:shot
execute as @a[scores={solg_xbow=1..}] at @s run function solgames:shot
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


def pack_files() -> dict[str, str]:
    files = {
        "pack.mcmeta": json.dumps({"pack": {
            "description": "Solstone: fishing (species, sizes, quality) and archery games",
            # 1.21 (48) up to anything newer; old fields for <1.21.9, min/max for 1.21.9+
            "pack_format": 48, "supported_formats": {"min_inclusive": 48, "max_inclusive": 999},
            "min_format": 48, "max_format": 999}}, indent=1),
        "data/minecraft/loot_table/gameplay/fishing/fish.json": json.dumps(loot_table()),
        "data/minecraft/tags/function/load.json": json.dumps({"values": ["solfish:load", "solgames:load"]}),
        "data/minecraft/tags/function/tick.json": json.dumps({"values": ["solgames:tick"]}),
        "data/solfish/advancement/hooked.json": json.dumps({
            "criteria": {"hooked": {"trigger": "minecraft:fishing_rod_hooked"}},
            "rewards": {"function": "solfish:hooked"}}),
    }
    for name, body in FUNCTIONS.items():
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


def build_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for path, body in sorted(pack_files().items()):
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
            out.append({"i": int(c["i"]), "species": str(c["s"]), "name": str(c["n"]), "quality": int(c["q"]), "quality_name": str(c["ql"]),
                        "weight": int(c["w"]) / 10, "lb": str(c["lb"]), "points": int(c["p"]), "uuid": uuid})
        except (KeyError, ValueError, TypeError):
            continue
    return out
