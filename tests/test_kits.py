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
        """items: [(slot, (id, count))]"""
        return "[" + ", ".join(f'{{Slot: {i}b, id: "{iid}", count: {n}}}' for i, (iid, n) in items) + "]"

    @staticmethod
    def _num(slot: str) -> int:
        return int(slot.split(".")[1]) if slot.startswith("container.") else 100 + ["armor.head", "armor.chest", "armor.legs", "armor.feet", "weapon.offhand"].index(slot)

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
            return f"{u} has the following entity data: {self._snbt([(self._num(k), v) for k, v in self.slots[u].items() if want(k)])}"
        if m := re.search(r"data get block (-?\d+) (-?\d+) (-?\d+) Items", cmd):
            return f"block has the following block data: {self._snbt(sorted(self.barrels[tuple(map(int, m.groups()))].items()))}"
        if m := re.search(r"item replace block (-?\d+) (-?\d+) (-?\d+) container\.(\d+) with minecraft:air", cmd):
            self.barrels[tuple(map(int, m.groups()[:3]))].pop(int(m.group(4)), None)
            return ""
        if m := re.fullmatch(r"clear (\S+) \*\[minecraft:custom_data=\{solkit:1b\}\]", cmd):
            self.slots[m.group(1)] = {k: v for k, v in self.slots[m.group(1)].items() if "solkit" not in v[0]}
            return ""
        if m := re.fullmatch(r"clear (\S+)", cmd):
            self.slots[m.group(1)] = {}
        if m := re.fullmatch(r"give (\S+) (\S+?)(?: (\d+))?", cmd):
            u = m.group(1)
            if u in self.slots:
                free = next(i for i in range(36) if f"container.{i}" not in self.slots[u])
                self.slots[u][f"container.{free}"] = (m.group(2), int(m.group(3) or 1))
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
    assert not any("solkit" in v[0] for v in game.slots[U1].values())                  # the kit's gone
    flesh = {k: v for k, v in game.slots[U1].items() if v[0] == "minecraft:rotten_flesh"}
    assert list(flesh.values()) == [("minecraft:rotten_flesh", 4)]                     # what they picked up is kept
    assert {k: v for k, v in game.slots[U1].items() if k not in flesh} == before[U1]  # and their own, exactly, slot for slot
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
    assert k["sword"] == "iron" and k["armour"] == "iron" and k["arrows"] == kits.MAX_ARROWS


def own(slots: dict) -> dict:
    """What's theirs (not the kit's)."""
    return {k: v for k, v in slots.items() if "solkit" not in v[0]}


def test_things_gathered_while_solstone_was_down_are_never_lost(game, monkeypatch):
    before = dict(game.slots[U1])
    asyncio.run(kits.stash(game, {"Alex": U1}, "g4"))
    asyncio.run(kits.give_kit(game, U1, kits.clean_kit({"sword": "iron", "armour": "none"})))
    monkeypatch.setattr(kits, "_STARTED", 9e12)                      # Solstone went down and came back since
    # meanwhile they died out of the kit, and gathered things: a full inventory's worth, armour on too
    game.slots[U1] = {f"container.{i}": (f"minecraft:stone_{i}", 64) for i in range(36)}
    game.slots[U1]["armor.head"] = ("minecraft:iron_helmet", 1)
    gathered = dict(game.slots[U1])
    said = len(game.said)
    asyncio.run(kits.tidy(game, ["Alex"]))
    # their things from before the game are back exactly; nothing of what they gathered is gone: it's in the pocket
    assert {k: v for k, v in game.slots[U1].items() if k in before} == before
    held = [v for b in game.barrels.values() for v in b.values()]
    assert sorted(held + [v for k, v in game.slots[U1].items() if k not in before]) == sorted(gathered.values())
    assert not any(" tp " in c for c in game.said[said:])           # not moved: they may have gone somewhere since
    assert any("kept safe until you have room" in c for c in game.said[said:]) and kits.waiting("kit-test")
    # they make room (put the lot in a chest): the rest arrives by itself, and nothing's left behind
    game.slots[U1] = dict(before)
    asyncio.run(kits.tidy(game, ["Alex"]))
    assert sorted(own(game.slots[U1]).values()) == sorted(list(before.values()) + held)    # the rest that was waiting
    assert not kits.waiting("kit-test") and not any(game.barrels.values())


def test_the_kit_alone_is_taken_back(game):
    asyncio.run(kits.stash(game, {".LongBedrockNameX": U2}, "g5"))
    asyncio.run(kits.give_kit(game, U2, kits.clean_kit({"sword": "stone", "armour": "none"})))
    assert own(game.slots[U2]) == {}
    asyncio.run(kits.give_back(game, U2))
    assert game.slots[U2] == {"container.3": ("minecraft:cake", 1), "armor.head": ("minecraft:turtle_helmet", 1)}
    assert not kits.waiting("kit-test") and not any(game.barrels.values())


def test_more_arrows_or_never_running_out():
    from app import kits
    assert kits.clean_kit({"arrows": 200})["arrows"] == 200 and kits.clean_kit({"arrows": 9999})["arrows"] == kits.MAX_ARROWS
    sent = []

    class Game:
        id, mc_version, settings = "kit-test", "1.21.10", {}

        async def rcon(self, cmd):
            sent.append(cmd)
            return ""

    async def fake_rcon(srv, cmd):
        sent.append(cmd)
        return ""
    import pytest
    mp = pytest.MonkeyPatch()
    mp.setattr(kits, "_rcon", fake_rcon)
    try:
        asyncio.run(kits.give_kit(Game(), "u-1", kits.clean_kit({"bow": True, "infinite": True, "arrows": 200})))
        bow = next(c for c in sent if "minecraft:bow[" in c)
        assert "minecraft:infinity" in bow and "solkit:1b" in bow and bow.endswith("] 1")
        assert any("minecraft:arrow[" in c and c.endswith(" 1") for c in sent)               # just the one arrow
        sent.clear()
        asyncio.run(kits.give_kit(Game(), "u-1", kits.clean_kit({"bow": True, "arrows": 200})))
        assert any("minecraft:arrow[" in c and c.endswith(" 200") for c in sent) and not any("infinity" in c for c in sent)
    finally:
        mp.undo()


def test_bigger_mob_arena_waves():
    import pytest

    from app import arena
    assert arena.clean_waves([{"baby_spear_zombie": 70}]) == [{"baby_spear_zombie": 70}]
    assert arena.clean_waves([{"zombie": 500}]) == [{"zombie": arena.MAX_PER_KIND}]
    with pytest.raises(ValueError, match="150 is the most"):
        arena.clean_waves([{"zombie": 100, "skeleton": 100}])
