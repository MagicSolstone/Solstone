"""Turn Minecraft NBT (from .dat files or RCON SNBT) into plain JSON-friendly data,
and normalise players/items across format changes (1.16 -> 1.21.5+)."""
from __future__ import annotations

import gzip
import io
import json
import re
from pathlib import Path
from typing import Any

import nbtlib


# ---------------------------------------------------------------- raw NBT -> python
def to_py(tag: Any) -> Any:
    if isinstance(tag, dict):
        return {str(k): to_py(v) for k, v in tag.items()}
    if isinstance(tag, (nbtlib.ByteArray, nbtlib.IntArray, nbtlib.LongArray)):
        return [int(x) for x in tag]
    if isinstance(tag, list):
        return [to_py(v) for v in tag]
    if isinstance(tag, str):
        return str(tag)
    if isinstance(tag, bool):
        return bool(tag)
    if isinstance(tag, int):
        return int(tag)
    if isinstance(tag, float):
        return float(tag)
    try:  # numpy scalars etc.
        return tag.item()
    except Exception:
        return tag


def load_dat(path: Path) -> dict:
    """Load a (usually gzipped) NBT file such as level.dat or playerdata/<uuid>.dat."""
    raw = path.read_bytes()
    gz = raw[:2] == b"\x1f\x8b"
    f = nbtlib.File.parse(io.BytesIO(gzip.decompress(raw) if gz else raw))
    return to_py(f)


_SNBT_PREFIX = re.compile(r"^.*? has the following entity data: ", re.S)


def parse_entity_snbt(output: str) -> dict | None:
    """Parse the reply of `data get entity <player>`."""
    if "has the following entity data" not in output:
        return None
    body = _SNBT_PREFIX.sub("", output, count=1).strip()
    try:
        return to_py(nbtlib.parse_nbt(body))
    except Exception:
        # Newer SNBT can contain bare true/false; convert and retry.
        body2 = re.sub(r"(?<=[:\[,])\s*true\b", "1b", body)
        body2 = re.sub(r"(?<=[:\[,])\s*false\b", "0b", body2)
        return to_py(nbtlib.parse_nbt(body2))


# ---------------------------------------------------------------- text components
def text_of(component: Any) -> str | None:
    """Flatten a chat/text component (JSON string or NBT compound) to plain text."""
    if component is None:
        return None
    if isinstance(component, str):
        s = component.strip()
        if s.startswith(("{", "[", '"')):
            try:
                return text_of(json.loads(s))
            except Exception:
                return component
        return component
    if isinstance(component, list):
        return "".join(filter(None, (text_of(c) for c in component)))
    if isinstance(component, dict):
        out = str(component.get("text", "") or component.get("", "") or "")
        if not out and "translate" in component:
            out = component.get("fallback") or f"%{component['translate']}"
        for extra in component.get("extra", []) or []:
            out += text_of(extra) or ""
        return out
    return str(component)


# ---------------------------------------------------------------- durability table
_TOOL_DUR = {"wooden": 59, "stone": 131, "iron": 250, "golden": 32, "diamond": 1561,
             "netherite": 2031, "copper": 190}
_ARMOR_BASE = {"leather": 5, "chainmail": 15, "iron": 15, "golden": 7, "diamond": 33,
               "netherite": 37, "turtle": 25, "copper": 11}
_ARMOR_MULT = {"helmet": 11, "chestplate": 16, "leggings": 15, "boots": 13}
_MISC_DUR = {"mace": 500, "bow": 384, "crossbow": 465, "trident": 250, "shield": 336,
             "fishing_rod": 64, "flint_and_steel": 64, "shears": 238, "elytra": 432,
             "carrot_on_a_stick": 25, "warped_fungus_on_a_stick": 100, "brush": 64,
             "turtle_helmet": 275, "wolf_armor": 64}


def max_durability(item_id: str) -> int | None:
    name = item_id.split(":", 1)[-1]
    if name in _MISC_DUR:
        return _MISC_DUR[name]
    parts = name.rsplit("_", 1)
    if len(parts) == 2:
        mat, kind = parts
        if kind in ("sword", "pickaxe", "axe", "shovel", "hoe") and mat in _TOOL_DUR:
            return _TOOL_DUR[mat]
        if kind in _ARMOR_MULT and mat in _ARMOR_BASE:
            return _ARMOR_BASE[mat] * _ARMOR_MULT[kind]
    return None


# ---------------------------------------------------------------- items
def _ench_map(raw: Any) -> list[dict]:
    """Enchantments from 1.20.5 ({levels:{..}}), 1.21.5+ ({id: lvl}) or legacy list."""
    out = []
    if isinstance(raw, dict):
        levels = raw.get("levels", raw) if "levels" in raw else raw
        for k, v in levels.items():
            if k in ("show_in_tooltip",):
                continue
            if isinstance(v, (int, float)):
                out.append({"id": _ns(k), "level": int(v)})
    elif isinstance(raw, list):
        for e in raw:
            if isinstance(e, dict) and "id" in e:
                lvl = e.get("lvl", e.get("level", 1))
                eid = e["id"]
                if isinstance(eid, int):
                    eid = f"minecraft:legacy_{eid}"
                out.append({"id": _ns(eid), "level": int(lvl)})
    return out


def _attribute_modifiers(raw: Any) -> list[dict]:
    """1.20.5+ attribute modifiers (list, or {modifiers: [...]}), as used by gear from
    RPG mods: [{type, amount, operation, slot}]."""
    if isinstance(raw, dict):
        raw = raw.get("modifiers")
    out = []
    for m in raw if isinstance(raw, list) else []:
        if not isinstance(m, dict) or "type" not in m:
            continue
        try:
            amount = float(m.get("amount", 0))
        except (TypeError, ValueError):
            continue
        out.append({"type": _ns(m["type"]), "amount": round(amount, 3),
                    "operation": str(m.get("operation", "add_value")), "slot": str(m.get("slot", "any"))})
    return out[:16]


# Player NBT keys the vanilla game uses for items; anything item-shaped outside these
# comes from a mod (Trinkets, Accessories, Curios-style slots, backpacks...).
_VANILLA_KEYS = {"Inventory", "EnderItems", "equipment", "ShoulderEntityLeft", "ShoulderEntityRight",
                 "RootVehicle", "recipeBook", "Brain", "attributes", "Attributes", "active_effects",
                 "ActiveEffects", "LastDeathLocation", "respawn", "warden_spawn_tracker", "enteredNetherPosition"}


def _looks_like_item(d: Any) -> bool:
    return (isinstance(d, dict) and isinstance(d.get("id"), str) and ":" in d["id"]
            and ("count" in d or "Count" in d))


def extra_items(nbt: dict, limit: int = 120) -> list[dict]:
    """Items stored by mods in the player's data, grouped by where they were found."""
    groups: dict[str, list[dict]] = {}
    seen = 0

    def walk(node: Any, path: tuple[str, ...], depth: int) -> None:
        nonlocal seen
        if seen >= limit or depth > 8:
            return
        if _looks_like_item(node):
            it = norm_item(node)
            if it:
                label = " › ".join(p for p in path if not p.isdigit()) or "Mod slots"
                groups.setdefault(label, []).append(it)
                seen += 1
            return
        if isinstance(node, dict):
            for k, v in node.items():
                if depth == 0 and k in _VANILLA_KEYS:
                    continue
                walk(v, (*path, str(k)), depth + 1)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, (*path, str(i)), depth + 1)

    walk(nbt, (), 0)
    out = []
    for label, items in groups.items():
        # Drop wrapper words mods commonly use so labels read like "trinkets › chest › back".
        parts = [p for p in label.split(" › ") if p not in ("cardinal_components", "Items", "items", "stack", "Stack", "item", "Item", "inventory", "Inventory")]
        out.append({"label": " › ".join(parts) or "Mod slots", "items": items})
    return out


def _ns(s: str) -> str:
    s = str(s)
    return s if ":" in s else f"minecraft:{s}"


def norm_item(raw: dict | None) -> dict | None:
    if not raw or not isinstance(raw, dict):
        return None
    item_id = raw.get("id")
    if not item_id or item_id == "minecraft:air":
        return None
    item: dict[str, Any] = {"id": _ns(item_id), "count": int(raw.get("count", raw.get("Count", 1)) or 1)}
    if "Slot" in raw:
        item["slot"] = int(raw["Slot"])
    comps: dict = raw.get("components") or {}
    tag: dict = raw.get("tag") or {}

    def c(key: str) -> Any:
        return comps.get(f"minecraft:{key}", comps.get(key))

    name = c("custom_name")
    if name is None and isinstance(tag.get("display"), dict):
        name = tag["display"].get("Name")
    if name is not None:
        item["name"] = text_of(name)

    ench = _ench_map(c("enchantments")) or _ench_map(tag.get("Enchantments") or tag.get("ench"))
    stored = _ench_map(c("stored_enchantments")) or _ench_map(tag.get("StoredEnchantments"))
    if ench:
        item["enchantments"] = ench
    if stored:
        item["stored_enchantments"] = stored
    if c("enchantment_glint_override"):
        item["glint"] = True

    dmg = c("damage")
    if dmg is None:
        dmg = tag.get("Damage")
    max_dmg = c("max_damage") or max_durability(item["id"])
    if c("unbreakable") is not None or tag.get("Unbreakable"):
        item["unbreakable"] = True
    elif max_dmg:
        item["max_damage"] = int(max_dmg)
        item["damage"] = int(dmg or 0)

    color = c("dyed_color")
    if isinstance(color, dict):
        color = color.get("rgb")
    if color is None and isinstance(tag.get("display"), dict):
        color = tag["display"].get("color")
    if isinstance(color, int):
        item["color"] = color & 0xFFFFFF

    potion = c("potion_contents")
    if isinstance(potion, dict):
        potion = potion.get("potion") or potion.get("custom_color")
    if potion is None:
        potion = tag.get("Potion")
    if isinstance(potion, str):
        item["potion"] = _ns(potion)

    trim = c("trim")
    if isinstance(trim, dict):
        item["trim"] = {"pattern": str(trim.get("pattern", "")), "material": str(trim.get("material", ""))}

    lore = c("lore") or (tag.get("display") or {}).get("Lore")
    if isinstance(lore, list) and lore:
        item["lore"] = [text_of(line) for line in lore]

    attrs = _attribute_modifiers(c("attribute_modifiers"))
    if attrs:
        item["attributes"] = attrs
    # Components added by mods (RPG stats, backpack contents, ...): we can't interpret
    # them, but listing which mods touched the item helps explain what it is.
    mod_ns = sorted({k.split(":", 1)[0] for k in comps if ":" in k and not k.startswith("minecraft:")})
    if mod_ns:
        item["mod_data"] = mod_ns

    # Containers: shulker boxes, bundles
    contents: list = []
    container = c("container")
    if isinstance(container, list):
        for entry in container:
            if isinstance(entry, dict) and "item" in entry:
                sub = norm_item(entry["item"])
                if sub:
                    sub["slot"] = int(entry.get("slot", 0))
                    contents.append(sub)
    bundle = c("bundle_contents")
    if isinstance(bundle, list):
        for i, entry in enumerate(bundle):
            sub = norm_item(entry)
            if sub:
                sub["slot"] = i
                contents.append(sub)
    bet = tag.get("BlockEntityTag")
    if isinstance(bet, dict) and isinstance(bet.get("Items"), list):
        contents += [x for x in (norm_item(i) for i in bet["Items"]) if x]
    if contents or container is not None or bundle is not None:
        item["contents"] = contents
    return item


# ---------------------------------------------------------------- players
GAMEMODES = {0: "survival", 1: "creative", 2: "adventure", 3: "spectator"}
_LEGACY_DIM = {0: "minecraft:overworld", -1: "minecraft:the_nether", 1: "minecraft:the_end"}


def _dim(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, int):
        return _LEGACY_DIM.get(v, str(v))
    return _ns(v)


def _pos_from(d: Any) -> dict | None:
    if isinstance(d, dict) and "pos" in d:
        p = d["pos"]
        if isinstance(p, list) and len(p) == 3:
            return {"x": p[0], "y": p[1], "z": p[2], "dimension": _dim(d.get("dimension"))}
    return None


def norm_player(nbt: dict) -> dict:
    inv = nbt.get("Inventory") or []
    hotbar: list = [None] * 9
    main: list = [None] * 27
    armor: dict = {"head": None, "chest": None, "legs": None, "feet": None}
    offhand = None
    armor_slots = {103: "head", 102: "chest", 101: "legs", 100: "feet"}
    for raw in inv:
        it = norm_item(raw)
        if not it:
            continue
        s = it.get("slot", -999)
        if 0 <= s <= 8:
            hotbar[s] = it
        elif 9 <= s <= 35:
            main[s - 9] = it
        elif s in armor_slots:
            armor[armor_slots[s]] = it
        elif s == -106:
            offhand = it
    eq = nbt.get("equipment")  # 1.21.5+
    if isinstance(eq, dict):
        for k in armor:
            if k in eq:
                armor[k] = norm_item(eq[k])
        if "offhand" in eq:
            offhand = norm_item(eq["offhand"])

    ender = [x for x in (norm_item(i) for i in nbt.get("EnderItems") or []) if x]

    max_health = 20.0
    for a in nbt.get("attributes") or nbt.get("Attributes") or []:
        aid = str(a.get("id") or a.get("Name") or "")
        if aid.endswith("max_health"):
            max_health = float(a.get("base", a.get("Base", 20)))

    effects = []
    for e in nbt.get("active_effects") or nbt.get("ActiveEffects") or []:
        eid = e.get("id", e.get("Id"))
        if isinstance(eid, int):
            eid = f"minecraft:legacy_{eid}"
        effects.append({
            "id": _ns(eid),
            "amplifier": int(e.get("amplifier", e.get("Amplifier", 0))),
            "duration": int(e.get("duration", e.get("Duration", 0))),
            "ambient": bool(e.get("ambient", e.get("Ambient", 0))),
        })

    pos = nbt.get("Pos") or [0, 0, 0]
    respawn = _pos_from(nbt.get("respawn"))
    if not respawn and "SpawnX" in nbt:
        respawn = {"x": nbt["SpawnX"], "y": nbt["SpawnY"], "z": nbt["SpawnZ"],
                   "dimension": _dim(nbt.get("SpawnDimension", "minecraft:overworld"))}
    abilities = nbt.get("abilities") or {}

    return {
        "data_version": nbt.get("DataVersion"),
        "health": round(float(nbt.get("Health", 20)), 1),
        "max_health": max_health,
        "absorption": round(float(nbt.get("AbsorptionAmount", 0)), 1),
        "food": int(nbt.get("foodLevel", 20)),
        "saturation": round(float(nbt.get("foodSaturationLevel", 0)), 1),
        "air": int(nbt.get("Air", 300)),
        "xp_level": int(nbt.get("XpLevel", 0)),
        "xp_progress": float(nbt.get("XpP", 0)),
        "xp_total": int(nbt.get("XpTotal", 0)),
        "score": int(nbt.get("Score", 0)),
        "gamemode": GAMEMODES.get(int(nbt.get("playerGameType", 0)), "survival"),
        "position": {"x": round(pos[0], 1), "y": round(pos[1], 1), "z": round(pos[2], 1),
                     "dimension": _dim(nbt.get("Dimension", "minecraft:overworld"))},
        "respawn": respawn,
        "last_death": _pos_from(nbt.get("LastDeathLocation")),
        "flying": bool(abilities.get("flying", 0)),
        "selected_slot": int(nbt.get("SelectedItemSlot", 0)),
        "inventory": {"hotbar": hotbar, "main": main, "armor": armor, "offhand": offhand},
        "ender_chest": ender,
        "effects": effects,
        "mod_items": extra_items(nbt),
    }
