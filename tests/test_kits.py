"""Event kits: everyone's own things kept safe in the vault, and given back exactly (even after leaving mid-game)."""
import asyncio
import re

import pytest

from app import kits, settings_store

U1, U2 = "00000000-0000-0000-0009-000000000001", "11111111-2222-3333-4444-555555555555"


class FakeGame:
    """Enough of a Minecraft server for the vault: players' slots, barrels, and the commands that move items."""

    def __init__(self):
        self.id, self.display_name, self.mc_version = "kit-test", "Test", "1.21.10"
        self.online = {U1: "Alex", U2: ".LongBedrockNameX"}
        self.slots = {U1: {"container.0": ("minecraft:diamond_sword", 1), "container.5": ("minecraft:torch", 37),
                           "armor.chest": ("minecraft:elytra", 1), "weapon.offhand": ("minecraft:shield", 1)},
                      U2: {"container.3": ("minecraft:cake", 1), "armor.head": ("minecraft:turtle_helmet", 1)}}
        self.barrels: dict[tuple, dict] = {}
        self.said: list[str] = []
        self.break_copy = False

    def rcon_conf(self):
        return True

    @staticmethod
    def _snbt(items):
        return "[" + ", ".join(f'{{Slot: {i}b, id: "{iid}", count: {n}}}' for i, (iid, n) in enumerate(items)) + "]"

    async def rcon(self, cmd: str, wait=None) -> str:
        self.said.append(cmd)
        if " if loaded " in cmd:
            return "Test passed"
        if m := re.search(r"setblock (-?\d+) (-?\d+) (-?\d+) minecraft:barrel", cmd):
            self.barrels.setdefault(tuple(map(int, m.groups())), {})
            return ""
        if m := re.search(r"data merge block (-?\d+) (-?\d+) (-?\d+) \{Items:\[\]\}", cmd):
            self.barrels[tuple(map(int, m.groups()))] = {}
            return ""
        if m := re.search(r"item replace block (-?\d+) (-?\d+) (-?\d+) container\.(\d+) from entity (\S+) (\S+)", cmd):
            b, u = self.barrels[tuple(map(int, m.groups()[:3]))], m.group(5)
            item = self.slots[u].get(m.group(6))
            if item and not (self.break_copy and "sword" in item[0]):
                b[int(m.group(4))] = item
            else:
                b.pop(int(m.group(4)), None)
            return ""
        if m := re.search(r"item replace entity (\S+) (\S+) from block (-?\d+) (-?\d+) (-?\d+) container\.(\d+)", cmd):
            item = self.barrels[tuple(map(int, m.groups()[2:5]))].get(int(m.group(6)))
            if item:
                self.slots[m.group(1)][m.group(2)] = item
            else:
                self.slots[m.group(1)].pop(m.group(2), None)
            return ""
        if m := re.search(r"data get entity (\S+) (Inventory|equipment|Pos|Dimension)", cmd):
            u, what = m.groups()
            if u not in self.online:
                return "No entity was found"
            if what == "Pos":
                return f"{u} has the following entity data: [10.5d, 64.0d, -3.5d]"
            if what == "Dimension":
                return f'{u} has the following entity data: "minecraft:overworld"'
            want = (lambda k: k.startswith("container.")) if what == "Inventory" else (lambda k: not k.startswith("container."))
            return f"{u} has the following entity data: {self._snbt([v for k, v in self.slots[u].items() if want(k)])}"
        if m := re.search(r"data get block (-?\d+) (-?\d+) (-?\d+) Items", cmd):
            return f"block has the following block data: {self._snbt(list(self.barrels[tuple(map(int, m.groups()))].values()))}"
        if m := re.fullmatch(r"clear (\S+)", cmd):
            self.slots[m.group(1)] = {}
        return ""


def setup_vault(monkeypatch) -> None:
    """A fresh vault, with the bits of the game a pretend server can't answer."""
    from app import games

    async def gm(srv, name):
        return "survival"
    monkeypatch.setattr(games, "_gamemode", gm)
    monkeypatch.setattr(kits.S, "world_info", lambda srv, *_a: {"spawn": {"x": 40, "y": 70, "z": -20}})
    settings_store.save_section(kits.SECTION, {})


@pytest.fixture
def game(monkeypatch):
    setup_vault(monkeypatch)
    yield FakeGame()
    settings_store.save_section(kits.SECTION, {})


def test_things_kept_safe_then_given_back_exactly(game):
    before = {u: dict(s) for u, s in game.slots.items()}
    done = asyncio.run(kits.stash(game, {"Alex": U1, ".LongBedrockNameX": U2}, "g1"))
    assert sorted(done) == [".LongBedrockNameX", "Alex"]
    assert game.slots[U1] == {} and game.slots[U2] == {}                                # empty-handed for the kit
    assert any(c.startswith("execute in minecraft:overworld run fill ") and c.endswith("minecraft:bedrock") for c in game.said)   # sealed in
    assert len(kits.waiting("kit-test")) == 2
    asyncio.run(kits.give_kit(game, U1, kits.clean_kit({"sword": "diamond", "armour": "iron"})))
    game.slots[U1]["container.9"] = ("minecraft:rotten_flesh", 4)                     # picked up in the game
    assert asyncio.run(kits.give_back(game, U1)) is True
    assert game.slots[U1] == before[U1]                                                 # exactly as it was, slot for slot
    assert any(c == f"execute in minecraft:overworld run tp {U1} 10.5 64.0 -3.5" for c in game.said)   # back where they were
    assert [s["name"] for s in kits.waiting("kit-test")] == [".LongBedrockNameX"]


def test_someone_who_left_gets_them_back_when_they_return(game):
    asyncio.run(kits.stash(game, {".LongBedrockNameX": U2}, "g2"))
    del game.online[U2]                                                                 # gone mid-game
    assert asyncio.run(kits.give_back(game, U2)) is False and kits.waiting("kit-test")  # kept until they're back
    game.online[U2] = ".LongBedrockNameX"
    asyncio.run(kits.tidy(game, [".LongBedrockNameX"]))
    assert game.slots[U2] == {"container.3": ("minecraft:cake", 1), "armor.head": ("minecraft:turtle_helmet", 1)}
    assert not kits.waiting("kit-test")


def test_a_copy_that_doesnt_check_out_leaves_them_untouched(game):
    game.break_copy = True                                                               # the sword didn't make it across
    done = asyncio.run(kits.stash(game, {"Alex": U1}, "g3"))
    assert done == [] and "container.0" in game.slots[U1] and not kits.waiting("kit-test")


def test_the_kit_is_marked_as_the_games():
    item = kits.kit_item("minecraft:iron_sword")
    assert "custom_data={solkit:1b}" in item and "unbreakable" in item
    k = kits.clean_kit({"sword": "laser", "armour": "gold", "arrows": 999})
    assert k["sword"] == "iron" and k["armour"] == "iron" and k["arrows"] == 64
