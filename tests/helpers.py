"""Builds a synthetic Crafty servers folder (world, players, mods) and a tiny fake
set of extracted Minecraft client assets, so tests never need the real game."""
import io
import json
import random
import struct
import time
import zipfile
from pathlib import Path
import nbtlib
from nbtlib import Compound, List, String, Int, Byte, Double, Float, Long, IntArray
from PIL import Image, ImageDraw

SID = "5adcec83-684c-4555-a7e9-9d913203d07e"
VERSION = "1.21.10"
PLAYERS = [("Tyler", "069a79f4-44e9-4726-a5be-fca90e38aaf5"), ("Gimli_Jr", "853c80ef-3c37-49fd-aa49-938b674adae6"),
           ("MomCrafts", "61699b2e-d327-4a01-9f1e-0ea8c3f06bc6")]


def build(root: Path) -> Path:
    random.seed(1)
    srv = root / "servers" / SID
    w = srv / "world"
    for d in ("playerdata", "stats", "advancements", "region", "DIM-1/region", "DIM1/region"):
        (w / d).mkdir(parents=True, exist_ok=True)
    (srv / "mods").mkdir(exist_ok=True)
    (srv / ".fabric").mkdir(exist_ok=True)

    (srv / "server.properties").write_text("""#Minecraft server properties
    motd=Jusczak Family Realm
    level-name=world
    enable-rcon=true
    rcon.port=25998
    rcon.password=hunter2
    max-players=10
    difficulty=normal
    gamemode=survival
    view-distance=12
    simulation-distance=10
    pvp=false
    white-list=true
    online-mode=true
    """)
    players = [("Tyler", "069a79f4-44e9-4726-a5be-fca90e38aaf5"), ("Gimli_Jr", "853c80ef-3c37-49fd-aa49-938b674adae6"),
               ("MomCrafts", "61699b2e-d327-4a01-9f1e-0ea8c3f06bc6")]
    (srv / "usercache.json").write_text(json.dumps([{"name": n, "uuid": u, "expiresOn": "2026-11-01"} for n, u in players]))
    (srv / "ops.json").write_text(json.dumps([{"uuid": players[0][1], "name": "Tyler", "level": 4}]))
    Image.new("RGBA", (64, 64), (60, 140, 80, 255)).save(srv / "server-icon.png")

    level = Compound({"Data": Compound({
        "LevelName": String("Duluth Heights"), "DataVersion": Int(4556),
        "Version": Compound({"Name": String(VERSION), "Id": Int(4556), "Snapshot": Byte(0)}),
        "WorldGenSettings": Compound({"seed": Long(-4172144997902289642)}),
        "Time": Long(1_843_212), "DayTime": Long(1_843_212 + 6000), "raining": Byte(1), "thundering": Byte(0),
        "hardcore": Byte(0), "Difficulty": Byte(2), "allowCommands": Byte(0), "LastPlayed": Long(int(time.time()*1000)),
        "spawn": Compound({"pos": IntArray([112, 71, -240]), "dimension": String("minecraft:overworld")}),
        "GameRules": Compound({"keepInventory": String("true"), "doDaylightCycle": String("true"), "mobGriefing": String("false"),
                                "playersSleepingPercentage": String("50")}),
        "DataPacks": Compound({"Enabled": List[String]([String("vanilla"), String("fabric")]), "Disabled": List[String]([])}),
    })})
    nbtlib.File(level, gzipped=True).save(w / "level.dat")

    def item(slot, iid, count=1, comps=None):
        c = Compound({"Slot": Byte(slot), "id": String(iid), "count": Int(count)})
        if comps: c["components"] = comps
        return c

    def eq_item(iid, comps=None):
        c = Compound({"id": String(iid), "count": Int(1)})
        if comps: c["components"] = comps
        return c

    def player_nbt(i):
        inv = [item(0, "minecraft:diamond_sword", 1, Compound({"minecraft:enchantments": Compound({"minecraft:sharpness": Int(5), "minecraft:looting": Int(3)}), "minecraft:damage": Int(400), "minecraft:custom_name": String("Orcrist")})),
               item(1, "minecraft:iron_pickaxe", 1, Compound({"minecraft:damage": Int(30)})),
               item(2, "minecraft:cooked_beef", 37), item(3, "minecraft:torch", 64), item(4, "minecraft:oak_log", 23),
               item(5, "minecraft:stone", 64), item(6, "minecraft:grass_block", 12), item(7, "minecraft:furnace", 2),
               item(8, "minecraft:shulker_box", 1, Compound({"minecraft:container": List[Compound]([
                   Compound({"slot": Int(0), "item": Compound({"id": String("minecraft:diamond"), "count": Int(12)})}),
                   Compound({"slot": Int(4), "item": Compound({"id": String("minecraft:oak_stairs"), "count": Int(40)})})])})),
               item(9, "minecraft:oak_stairs", 16), item(10, "minecraft:enchanted_book", 1, Compound({"minecraft:stored_enchantments": Compound({"minecraft:mending": Int(1)})})),
               item(14, "minecraft:oak_slab", 30), item(20, "minecraft:diamond", 5), item(31, "fancymod:ruby", 3)]
        return Compound({
            "DataVersion": Int(4556), "Health": Float(14.5 - i*3), "foodLevel": Int(18 - i*4), "foodSaturationLevel": Float(3.2),
            "XpLevel": Int(27 - i*9), "XpP": Float(0.42), "XpTotal": Int(1500), "Score": Int(1500), "playerGameType": Int(0),
            "Pos": List[Double]([Double(145.3 + i*50), Double(64.0), Double(-312.7)]), "Dimension": String("minecraft:overworld" if i != 1 else "minecraft:the_nether"),
            "SelectedItemSlot": Int(0), "Inventory": List[Compound](inv),
            "equipment": Compound({"head": eq_item("minecraft:iron_helmet"), "chest": eq_item("minecraft:diamond_chestplate", Compound({"minecraft:enchantments": Compound({"minecraft:protection": Int(4)})})),
                                   "legs": eq_item("minecraft:leather_leggings", Compound({"minecraft:dyed_color": Int(0x3366CC)})), "offhand": eq_item("minecraft:shield")}),
            "EnderItems": List[Compound]([item(0, "minecraft:diamond", 64), item(13, "minecraft:stone", 64)]),
            "active_effects": List[Compound]([Compound({"id": String("minecraft:speed"), "amplifier": Byte(1), "duration": Int(2400)})]) if i == 0 else List[Compound]([]),
            "attributes": List[Compound]([Compound({"id": String("minecraft:max_health"), "base": Double(20.0)})]),
            "respawn": Compound({"pos": IntArray([100, 70, -200]), "dimension": String("minecraft:overworld")}),
            "LastDeathLocation": Compound({"pos": IntArray([-40, 12, 900]), "dimension": String("minecraft:overworld")}),
        })

    for i, (_n, u) in enumerate(players):
        nbtlib.File(player_nbt(i), gzipped=True).save(w / "playerdata" / f"{u}.dat")
        stats = {"stats": {
            "minecraft:custom": {"minecraft:play_time": 72000*(30-i*9), "minecraft:deaths": 7+i*3, "minecraft:mob_kills": 412-i*100,
                                 "minecraft:walk_one_cm": 4_200_000-i*1_000_000, "minecraft:sprint_one_cm": 900_000, "minecraft:jump": 18000-i*3000,
                                 "minecraft:damage_dealt": 50000, "minecraft:damage_taken": 22000, "minecraft:fish_caught": 14*i,
                                 "minecraft:animals_bred": 40, "minecraft:time_since_death": 54000, "minecraft:sleep_in_bed": 61,
                                 "minecraft:leave_game": 80, "minecraft:open_chest": 900},
            "minecraft:mined": {"minecraft:stone": 9000-i*2000, "minecraft:oak_log": 1200, "minecraft:diamond_ore": 40, "minecraft:grass_block": 600},
            "minecraft:crafted": {"minecraft:torch": 640, "minecraft:oak_stairs": 120, "minecraft:furnace": 5},
            "minecraft:used": {"minecraft:diamond_sword": 2000, "minecraft:cooked_beef": 300},
            "minecraft:killed": {"minecraft:zombie": 180, "minecraft:skeleton": 120, "minecraft:creeper": 44, "minecraft:ender_dragon": 1 if i == 0 else 0},
            "minecraft:killed_by": {"minecraft:creeper": 3, "minecraft:skeleton": 2},
            "minecraft:picked_up": {"minecraft:diamond": 60}, "minecraft:broken": {"minecraft:iron_pickaxe": 4},
            "minecraft:dropped": {"minecraft:dirt": 64}}, "DataVersion": 4556}
        (w / "stats" / f"{u}.json").write_text(json.dumps(stats))
        adv = {"minecraft:story/root": {"criteria": {"crafting_table": "2026-08-01 18:00:00 -0500"}, "done": True},
               "minecraft:story/mine_stone": {"criteria": {"get_stone": "2026-08-01 18:05:00 -0500"}, "done": True},
               "minecraft:story/smelt_iron": {"criteria": {"iron": "2026-08-02 18:05:00 -0500"}, "done": i == 0},
               "minecraft:recipes/misc/torch": {"criteria": {"x": "2026-08-01 18:00:00 -0500"}, "done": True},
               "DataVersion": 4556}
        (w / "advancements" / f"{u}.json").write_text(json.dumps(adv))

    # region files with some chunks
    for d, n in (("region", 6), ("DIM-1/region", 2), ("DIM1/region", 1)):
        for k in range(n):
            header = bytearray(8192)
            for c in random.sample(range(1024), random.randint(100, 900)):
                struct.pack_into(">I", header, c*4, (2 << 8) | 1)
            (w / d / f"r.{k}.0.mca").write_bytes(bytes(header) + b"\0" * 4096)

    # mod jar with an item
    with zipfile.ZipFile(srv / "mods" / "fancymod-1.2.jar", "w") as z:
        z.writestr("fabric.mod.json", json.dumps({"schemaVersion": 1, "id": "fancymod", "name": "Fancy Gems", "version": "1.2.0",
                                                  "description": "Adds rubies.", "authors": ["Somebody"]}))
        img = Image.new("RGBA", (16, 16), (0, 0, 0, 0)); ImageDraw.Draw(img).polygon([(8,1),(14,8),(8,15),(2,8)], fill=(210,30,60,255))
        b = io.BytesIO()
        img.save(b, "PNG")
        z.writestr("assets/fancymod/textures/item/ruby.png", b.getvalue())
        z.writestr("assets/fancymod/models/item/ruby.json", json.dumps({"parent": "minecraft:item/generated", "textures": {"layer0": "fancymod:item/ruby"}}))
        z.writestr("assets/fancymod/lang/en_us.json", json.dumps({"item.fancymod.ruby": "Ruby"}))
    with zipfile.ZipFile(srv / "mods" / "lithium.jar", "w") as z:
        z.writestr("fabric.mod.json", json.dumps({"schemaVersion": 1, "id": "lithium", "name": "Lithium", "version": "0.16.0", "description": "Server optimization"}))

    # ---------- fake extracted client assets
    ax = root / "data" / "assets" / VERSION / "x"
    tex = ax / "assets/minecraft/textures"
    models = ax / "assets/minecraft/models"
    items = ax / "assets/minecraft/items"
    for d in (tex/"block", tex/"item", tex/"mob_effect", tex/"gui/sprites/hud/heart", models/"block", models/"item", items, ax/"data/minecraft/advancement/story"):
        d.mkdir(parents=True, exist_ok=True)

    def pattern(path, base, accent, kind="noise"):
        img = Image.new("RGBA", (16, 16), base + (255,))
        dr = ImageDraw.Draw(img); rnd = random.Random(path.name)
        for _ in range(40):
            x, y = rnd.randrange(16), rnd.randrange(16)
            dr.point((x, y), fill=accent + (255,))
        if kind == "border":
            dr.rectangle([0, 0, 15, 15], outline=accent + (255,))
        img.save(path)

    pattern(tex/"block/stone.png", (125,125,125), (100,100,100))
    pattern(tex/"block/oak_log.png", (105,80,45), (80,60,30))
    pattern(tex/"block/oak_log_top.png", (160,130,80), (110,85,50), "border")
    pattern(tex/"block/oak_planks.png", (160,130,80), (130,100,60))
    pattern(tex/"block/furnace_front.png", (60,60,60), (20,20,20), "border")
    pattern(tex/"block/furnace_side.png", (120,120,120), (90,90,90))
    pattern(tex/"block/furnace_top.png", (140,140,140), (100,100,100))
    pattern(tex/"block/grass_block_top.png", (150,150,150), (120,120,120))
    pattern(tex/"block/grass_block_side.png", (120,85,60), (90,60,40))
    pattern(tex/"block/shulker_box.png", (150,90,160), (120,60,130))
    def sword(path, blade):
        img = Image.new("RGBA", (16,16), (0,0,0,0)); dr = ImageDraw.Draw(img)
        dr.line([(3,12),(13,2)], fill=blade+(255,), width=2); dr.line([(2,10),(5,13)], fill=(90,60,30,255), width=2)
        img.save(path)
    sword(tex/"item/diamond_sword.png", (80,220,220)); sword(tex/"item/iron_pickaxe.png", (220,220,220))
    for n, c in (("diamond", (90,230,230)), ("cooked_beef", (150,70,40)), ("torch", (250,200,60)), ("enchanted_book", (120,60,160)),
                 ("iron_helmet", (210,210,210)), ("diamond_chestplate", (80,220,220)), ("leather_leggings", (200,200,200)), ("leather_leggings_overlay", (0,0,0)), ("shield", (150,110,60))):
        img = Image.new("RGBA", (16,16), (0,0,0,0)); ImageDraw.Draw(img).ellipse([3,3,12,12], fill=c+(255,) if n!="leather_leggings_overlay" else (0,0,0,0)); img.save(tex/f"item/{n}.png")
    Image.new("RGBA", (9,9), (0,0,0,0)).save(tex/"gui/sprites/hud/heart/full.png")
    pattern(tex/"mob_effect/speed.png", (120,180,230), (80,140,200))

    J = lambda p, d: (p.parent.mkdir(parents=True, exist_ok=True), p.write_text(json.dumps(d)))
    J(models/"block/block.json", {"display": {}})
    J(models/"block/cube.json", {"parent": "block/block", "elements": [{"from": [0,0,0], "to": [16,16,16], "faces": {
        "down": {"texture": "#down", "cullface": "down"}, "up": {"texture": "#up"}, "north": {"texture": "#north"},
        "south": {"texture": "#south"}, "west": {"texture": "#west"}, "east": {"texture": "#east"}}}]})
    J(models/"block/cube_all.json", {"parent": "block/cube", "textures": {"particle": "#all", "down": "#all", "up": "#all", "north": "#all", "east": "#all", "south": "#all", "west": "#all"}})
    J(models/"block/cube_column.json", {"parent": "block/cube", "textures": {"particle": "#side", "down": "#end", "up": "#end", "north": "#side", "east": "#side", "south": "#side", "west": "#side"}})
    J(models/"block/orientable.json", {"parent": "block/cube", "textures": {"particle": "#front", "down": "#bottom", "up": "#top", "north": "#front", "east": "#side", "south": "#side", "west": "#side"}})
    J(models/"block/stone.json", {"parent": "minecraft:block/cube_all", "textures": {"all": "minecraft:block/stone"}})
    J(models/"block/oak_log.json", {"parent": "minecraft:block/cube_column", "textures": {"end": "minecraft:block/oak_log_top", "side": "minecraft:block/oak_log"}})
    J(models/"block/furnace.json", {"parent": "minecraft:block/orientable", "textures": {"front": "minecraft:block/furnace_front", "side": "minecraft:block/furnace_side", "top": "minecraft:block/furnace_top", "bottom": "minecraft:block/furnace_top"}})
    J(models/"block/grass_block.json", {"parent": "block/block", "textures": {"particle": "block/dirt", "bottom": "block/dirt", "top": "block/grass_block_top", "side": "block/grass_block_side"},
        "elements": [{"from": [0,0,0], "to": [16,16,16], "faces": {"up": {"uv": [0,0,16,16], "texture": "#top", "tintindex": 0}, "north": {"texture": "#side"}, "west": {"texture": "#side"}}}]})
    J(models/"block/oak_slab.json", {"parent": "block/block", "textures": {"bottom": "block/oak_planks", "top": "block/oak_planks", "side": "block/oak_planks"},
        "elements": [{"from": [0,0,0], "to": [16,8,16], "faces": {"up": {"texture": "#top"}, "north": {"texture": "#side"}, "west": {"texture": "#side"}}}]})
    J(models/"block/oak_stairs.json", {"parent": "block/block", "textures": {"bottom": "block/oak_planks", "top": "block/oak_planks", "side": "block/oak_planks"},
        "elements": [{"from": [0,0,0], "to": [16,8,16], "faces": {"up": {"texture": "#top"}, "north": {"texture": "#side"}, "west": {"texture": "#side"}}},
                     {"from": [8,8,0], "to": [16,16,16], "faces": {"up": {"texture": "#top"}, "north": {"texture": "#side"}, "west": {"texture": "#side"}}}]})
    J(models/"item/generated.json", {"parent": "builtin/generated"})
    J(models/"item/handheld.json", {"parent": "item/generated"})
    J(models/"item/template_shulker_box.json", {"parent": "builtin/entity", "textures": {"particle": "block/shulker_box"}})
    J(models/"item/shulker_box.json", {"parent": "item/template_shulker_box"})
    for n in ("diamond_sword", "iron_pickaxe"):
        J(models/f"item/{n}.json", {"parent": "minecraft:item/handheld", "textures": {"layer0": f"minecraft:item/{n}"}})
    for n in ("diamond", "cooked_beef", "torch", "enchanted_book", "iron_helmet", "diamond_chestplate", "shield"):
        J(models/f"item/{n}.json", {"parent": "minecraft:item/generated", "textures": {"layer0": f"minecraft:item/{n}"}})
    J(models/"item/leather_leggings.json", {"parent": "minecraft:item/generated", "textures": {"layer0": "minecraft:item/leather_leggings", "layer1": "minecraft:item/leather_leggings_overlay"}})
    for n in ("stone", "oak_log", "furnace", "oak_slab", "oak_stairs"):
        J(items/f"{n}.json", {"model": {"type": "minecraft:model", "model": f"minecraft:block/{n}"}})
    J(items/"grass_block.json", {"model": {"type": "minecraft:model", "model": "minecraft:block/grass_block", "tints": [{"type": "minecraft:grass", "temperature": 0.5, "downfall": 1.0}]}})
    J(items/"shulker_box.json", {"model": {"type": "minecraft:special", "base": "minecraft:item/shulker_box", "model": {"type": "minecraft:shulker_box"}}})
    J(items/"leather_leggings.json", {"model": {"type": "minecraft:model", "model": "minecraft:item/leather_leggings", "tints": [{"type": "minecraft:dye", "default": -6265536}]}})
    for n in ("diamond_sword", "iron_pickaxe", "diamond", "cooked_beef", "torch", "enchanted_book", "iron_helmet", "diamond_chestplate", "shield"):
        J(items/f"{n}.json", {"model": {"type": "minecraft:model", "model": f"minecraft:item/{n}"}})

    lang = {"item.minecraft.diamond_sword": "Diamond Sword", "item.minecraft.iron_pickaxe": "Iron Pickaxe", "item.minecraft.cooked_beef": "Steak",
            "block.minecraft.torch": "Torch", "block.minecraft.oak_log": "Oak Log", "block.minecraft.stone": "Stone", "block.minecraft.grass_block": "Grass Block",
            "block.minecraft.furnace": "Furnace", "block.minecraft.shulker_box": "Shulker Box", "item.minecraft.diamond": "Diamond",
            "block.minecraft.oak_stairs": "Oak Stairs", "block.minecraft.oak_slab": "Oak Slab", "item.minecraft.enchanted_book": "Enchanted Book",
            "enchantment.minecraft.sharpness": "Sharpness", "enchantment.minecraft.looting": "Looting", "enchantment.minecraft.mending": "Mending",
            "enchantment.minecraft.protection": "Protection", "effect.minecraft.speed": "Speed",
            "stat.minecraft.play_time": "Time Played", "stat.minecraft.deaths": "Number of Deaths", "stat.minecraft.mob_kills": "Mob Kills",
            "stat.minecraft.walk_one_cm": "Distance Walked", "stat.minecraft.jump": "Jumps", "stat.minecraft.time_since_death": "Time Since Last Death",
            "entity.minecraft.zombie": "Zombie", "entity.minecraft.skeleton": "Skeleton", "entity.minecraft.creeper": "Creeper", "entity.minecraft.ender_dragon": "Ender Dragon",
            "advancements.story.root.title": "Minecraft", "advancements.story.root.description": "The heart and story of the game",
            "advancements.story.mine_stone.title": "Stone Age", "advancements.story.mine_stone.description": "Mine Stone with your new Pickaxe",
            "advancements.story.smelt_iron.title": "Acquire Hardware", "advancements.story.smelt_iron.description": "Smelt an Iron Ingot",
            "advancements.story.mine_diamond.title": "Diamonds!", "advancements.story.mine_diamond.description": "Acquire diamonds",
            "biome.minecraft.plains": "Plains"}
    J(ax/"assets/minecraft/lang/en_us.json", lang)
    for n, parent, icon, frame in (("root", None, "minecraft:grass_block", "task"), ("mine_stone", "minecraft:story/root", "minecraft:stone", "task"),
                                   ("smelt_iron", "minecraft:story/mine_stone", "minecraft:iron_pickaxe", "task"), ("mine_diamond", "minecraft:story/smelt_iron", "minecraft:diamond", "goal")):
        d = {"display": {"icon": {"id": icon}, "title": {"translate": f"advancements.story.{n}.title"}, "description": {"translate": f"advancements.story.{n}.description"}, "frame": frame}}
        if parent: d["parent"] = parent
        J(ax/f"data/minecraft/advancement/story/{n}.json", d)
    (root / "data" / "assets" / VERSION / ".complete").write_text(VERSION)
    return srv
