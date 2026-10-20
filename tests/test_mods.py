"""Modded content: items stored by mods, RPG attribute stats, and mod advancements."""
import json
import zipfile

from app.nbtutil import extra_items, norm_item, norm_player


def test_attribute_modifiers_and_mod_components():
    it = norm_item({"id": "rpgmod:flame_sword", "count": 1, "components": {
        "minecraft:attribute_modifiers": [
            {"type": "minecraft:attack_damage", "amount": 7.0, "operation": "add_value", "slot": "mainhand", "id": "x"},
            {"type": "spell_power:fire", "amount": 0.25, "operation": "add_multiplied_base", "slot": "mainhand", "id": "y"},
        ],
        "rpgmod:rarity": "epic",
        "spell_engine:spells": {"ids": ["a"]},
    }})
    assert it["attributes"][0] == {"type": "minecraft:attack_damage", "amount": 7.0, "operation": "add_value", "slot": "mainhand"}
    assert it["attributes"][1]["type"] == "spell_power:fire"
    assert it["mod_data"] == ["rpgmod", "spell_engine"]
    # 1.20.5 wrapped form
    wrapped = norm_item({"id": "minecraft:diamond_sword", "count": 1, "components": {
        "minecraft:attribute_modifiers": {"modifiers": [{"type": "generic.attack_speed", "amount": -2.4, "operation": "add_value"}]}}})
    assert wrapped["attributes"][0]["type"] == "minecraft:generic.attack_speed"


def test_trinket_and_accessory_slots_are_found():
    nbt = {
        "Inventory": [{"Slot": 0, "id": "minecraft:stone", "count": 3}],
        "EnderItems": [{"Slot": 0, "id": "minecraft:dirt", "count": 1}],
        "cardinal_components": {"trinkets:trinkets": {
            "chest": {"back": {"Items": [{"id": "travelersbackpack:standard", "count": 1}]}},
            "hand": {"ring": {"Items": [{"id": "artifacts:gold_ring", "count": 1}, {"id": "minecraft:air", "count": 0}]}},
        }},
        "ShoulderEntityLeft": {"id": "minecraft:parrot"},
    }
    groups = extra_items(nbt)
    labels = {g["label"]: [i["id"] for i in g["items"]] for g in groups}
    assert labels == {"trinkets:trinkets › chest › back": ["travelersbackpack:standard"],
                      "trinkets:trinkets › hand › ring": ["artifacts:gold_ring"]}
    assert norm_player(nbt)["mod_items"] == groups
    assert extra_items({"Inventory": [{"id": "minecraft:stone", "count": 1}]}) == []


def test_mod_advancements_grouped_under_their_root(tmp_path):
    from app.assets import Assets

    jar = tmp_path / "farmersdelight.jar"
    with zipfile.ZipFile(jar, "w") as z:
        def adv(path, parent, title, icon="farmersdelight:tomato"):
            d = {"display": {"title": {"translate": title}, "description": "x", "icon": {"id": icon}}}
            if parent:
                d["parent"] = parent
            z.writestr(f"data/farmersdelight/advancement/{path}.json", json.dumps(d))
        adv("main/root", None, "farmersdelight.advancement.root")
        adv("main/plant_food", "farmersdelight:main/root", "farmersdelight.advancement.plant_food")
        adv("main/feast", "farmersdelight:main/plant_food", "farmersdelight.advancement.feast")
        z.writestr("data/farmersdelight/advancement/recipes/misc/knife.json", json.dumps({"criteria": {}}))
        z.writestr("assets/farmersdelight/lang/en_us.json", json.dumps({"item.farmersdelight.tomato": "Tomato"}))
    a = Assets("0.0.0-test", [jar], "t")
    mods = a._mod_advancements()
    assert {m["id"] for m in mods} == {"farmersdelight:main/root", "farmersdelight:main/plant_food", "farmersdelight:main/feast"}
    assert all(m["category"] == "farmersdelight:main/root" for m in mods)
    assert all(m["category_title"] == {"translate": "farmersdelight.advancement.root"} for m in mods)
    assert a.lang()["item.farmersdelight.tomato"] == "Tomato"
