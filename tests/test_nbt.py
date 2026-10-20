"""Item/player normalisation across Minecraft format versions."""
from app.nbtutil import max_durability, norm_item, norm_player, parse_entity_snbt, text_of


def test_item_1_21_5_components():
    it = norm_item({"id": "minecraft:diamond_pickaxe", "count": 1, "Slot": 3, "components": {
        "minecraft:enchantments": {"minecraft:efficiency": 5},
        "minecraft:custom_name": {"text": "Digger", "italic": 0},
        "minecraft:damage": 10}})
    assert it["slot"] == 3 and it["name"] == "Digger"
    assert it["enchantments"] == [{"id": "minecraft:efficiency", "level": 5}]
    assert it["damage"] == 10 and it["max_damage"] == 1561


def test_item_1_20_5_components():
    it = norm_item({"id": "minecraft:bow", "count": 1, "components": {
        "minecraft:enchantments": {"levels": {"minecraft:power": 4}, "show_in_tooltip": True},
        "minecraft:custom_name": '{"text":"Zinger"}'}})
    assert it["name"] == "Zinger"
    assert it["enchantments"] == [{"id": "minecraft:power", "level": 4}]
    assert it["max_damage"] == 384


def test_item_legacy_tag_format():
    it = norm_item({"id": "minecraft:shulker_box", "Count": 1, "Slot": 2, "tag": {
        "display": {"Name": '{"text":"Loot"}'},
        "BlockEntityTag": {"Items": [{"id": "minecraft:diamond", "Count": 3, "Slot": 0}]}}})
    assert it["name"] == "Loot"
    assert it["contents"][0]["count"] == 3


def test_air_and_empty_items_are_dropped():
    assert norm_item({"id": "minecraft:air", "count": 1}) is None
    assert norm_item({}) is None


def test_bundle_and_potion():
    b = norm_item({"id": "minecraft:bundle", "count": 1, "components": {
        "minecraft:bundle_contents": [{"id": "minecraft:arrow", "count": 12}]}})
    assert b["contents"][0]["id"] == "minecraft:arrow"
    p = norm_item({"id": "minecraft:potion", "count": 1, "components": {"minecraft:potion_contents": {"potion": "minecraft:swiftness"}}})
    assert p["potion"] == "minecraft:swiftness"


def test_legacy_player_slots():
    d = norm_player({"Inventory": [
        {"id": "minecraft:iron_helmet", "Count": 1, "Slot": 103},
        {"id": "minecraft:shield", "Count": 1, "Slot": -106},
        {"id": "minecraft:stone", "Count": 64, "Slot": 9},
    ], "Dimension": -1, "Attributes": [{"Name": "minecraft:generic.max_health", "Base": 30.0}]})
    inv = d["inventory"]
    assert inv["armor"]["head"]["id"] == "minecraft:iron_helmet"
    assert inv["offhand"]["id"] == "minecraft:shield"
    assert inv["main"][0]["count"] == 64
    assert d["position"]["dimension"] == "minecraft:the_nether"
    assert d["max_health"] == 30.0


def test_rcon_entity_snbt():
    out = ('Tyler has the following entity data: {Health: 7.5f, XpLevel: 12, Inventory: [{Slot: 0b, count: 2, '
           'id: "minecraft:diamond_sword", components: {"minecraft:custom_name": {text: \'Orc\\\'rist\'}}}], '
           'UUID: [I; 1, 2, 3, 4], Pos: [1.5d, 64.0d, -3.2d], abilities: {flying: false}}')
    d = norm_player(parse_entity_snbt(out))
    assert d["health"] == 7.5 and d["xp_level"] == 12
    assert d["inventory"]["hotbar"][0]["name"] == "Orc'rist"
    assert d["flying"] is False


def test_non_entity_reply_is_ignored():
    assert parse_entity_snbt("No entity was found") is None


def test_text_and_durability_helpers():
    assert text_of({"text": "a", "extra": [{"text": "b"}]}) == "ab"
    assert max_durability("minecraft:netherite_boots") == 481
    assert max_durability("minecraft:stick") is None
