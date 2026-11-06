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
    monkeypatch.setattr(kits, "STARTING_GRACE", 0)                  # (each test's "game" is over unless it says)
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
    assert game.slots[U1] == before[U1]                    # exactly their own, slot for slot: no kit, no pick-ups
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
    """Solstone went down mid-game and they played on: nothing they're carrying is touched. Their things come back
    once their inventory's empty (they're told once), and never on top of what they have."""
    before = dict(game.slots[U1])
    asyncio.run(kits.stash(game, {"Alex": U1}, "g4"))
    asyncio.run(kits.give_kit(game, U1, kits.clean_kit({"sword": "iron", "armour": "none"})))
    monkeypatch.setattr(kits, "_STARTED", 9e12)                      # Solstone went down and came back since
    game.slots[U1] = {f"container.{i}": (f"minecraft:stone_{i}", 64) for i in range(36)}
    game.slots[U1]["armor.head"] = ("minecraft:iron_helmet", 1)
    gathered = dict(game.slots[U1])
    said = len(game.said)
    asyncio.run(kits.tidy(game, ["Alex"]))
    assert game.slots[U1] == gathered                                # not one thing of theirs touched
    assert any("Empty your inventory" in c for c in game.said[said:]) and kits.waiting("kit-test")
    asyncio.run(kits.tidy(game, ["Alex"]))
    assert sum("Empty your inventory" in c for c in game.said[said:]) == 1          # told once
    game.slots[U1] = {}                                              # they put the lot in a chest
    asyncio.run(kits.tidy(game, ["Alex"]))
    assert game.slots[U1] == before and not kits.waiting("kit-test") and not any(game.barrels.values())
    assert not any(" tp " in c for c in game.said[said:])           # not moved: they may have gone somewhere since


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


def test_given_back_twice_never_duplicates(game):
    """Their things landed the first time but its check didn't pass (the bug in 1.15.15): giving back again must
    notice they already have them and empty the spare copy, not hand everything over a second time."""
    before = dict(game.slots[U1])
    asyncio.run(kits.stash(game, {"Alex": U1}, "g4"))
    asyncio.run(kits.give_kit(game, U1, kits.clean_kit({"sword": "iron"})))
    game.slots[U1] = dict(before)                                   # their own things are on them again, kit gone
    assert asyncio.run(kits.give_back(game, U1)) is True
    assert game.slots[U1] == before                                 # exactly once: no copies in the free slots
    assert not kits.waiting("kit-test")                             # nothing left behind to block the next game
    assert all(not b for b in game.barrels.values())                # and the spare copy's gone from the vault


def test_nothing_given_back_on_the_death_screen(game, monkeypatch):
    asyncio.run(kits.stash(game, {"Alex": U1}, "g5"))
    real = game.rcon

    async def dead(cmd, wait=None):
        return f"{U1} has the following entity data: 0.0f" if cmd.endswith(" Health") else await real(cmd, wait)
    monkeypatch.setattr(game, "rcon", dead)
    assert asyncio.run(kits.give_back(game, U1)) is False and kits.waiting("kit-test")   # tried again after respawning


def test_an_admin_can_throw_away_leftovers(game):
    asyncio.run(kits.stash(game, {"Alex": U1}, "g6"))
    assert asyncio.run(kits.discard(game, U1)) is True
    assert not kits.waiting("kit-test") and all(not b for b in game.barrels.values())
    assert asyncio.run(kits.discard(game, U1)) is False


def test_a_busy_server_never_counts_as_everyone_leaving(monkeypatch):
    """A failed position lookup (the server busy with a wave) once ended a game for everyone and handed things back
    in the middle of it: now leaving means not on the server, two looks in a row."""
    from app import battle

    async def online(srv):
        return (["Alex"], "rcon")
    monkeypatch.setattr(battle.S, "online_players", online)
    r = {"players": {"Alex": {"uuid": U1}, "Sam": {"uuid": U2}}}
    asyncio.run(battle.left_and_back(None, r, {}))                                       # no answer: nothing changes
    assert not any(p.get("out") for p in r["players"].values())
    asyncio.run(battle.left_and_back(None, r, {"bob": ("minecraft:overworld", 0, 0, 0)}))  # Alex not placed, but on
    assert not r["players"]["Alex"].get("out") and not r["players"]["Sam"].get("out")      # Sam missing once
    asyncio.run(battle.left_and_back(None, r, {"bob": ("minecraft:overworld", 0, 0, 0)}))
    assert r["players"]["Sam"].get("out") and not r["players"]["Alex"].get("out")          # Sam really gone


def test_no_kit_left_after_giving_back(game):
    """Whatever happened in the game, nobody walks away with the kit (diamond armour and a shield turned up after one)."""
    asyncio.run(kits.stash(game, {"Alex": U1}, "g7"))
    asyncio.run(kits.give_kit(game, U1, kits.clean_kit({"sword": "diamond", "armour": "diamond", "shield": True})))
    assert asyncio.run(kits.give_back(game, U1)) is True
    assert not any("solkit" in v[0] for v in game.slots[U1].values())


def test_kit_taken_even_where_clear_doesnt_understand_its_mark(game, monkeypatch):
    """Some versions don't take `clear <who> *[custom_data=...]`: then the kit came back as "things picked up in the
    game" (diamond armour and a shield, after a match). It's taken slot by slot now."""
    real = game.rcon

    async def rcon(cmd, wait=None):
        if cmd.startswith("clear ") and "solkit" in cmd:
            return "Unknown item component"                          # this version can't do it
        if m := re.fullmatch(r"item replace entity (\S+) (\S+) with minecraft:air", cmd):
            game.slots[m.group(1)].pop(m.group(2), None)
            return ""
        return await real(cmd, wait)
    monkeypatch.setattr(game, "rcon", rcon)
    before = dict(game.slots[U1])
    asyncio.run(kits.stash(game, {"Alex": U1}, "g8"))
    asyncio.run(kits.give_kit(game, U1, kits.clean_kit({"sword": "diamond", "armour": "diamond", "shield": True})))
    assert any("solkit" in v[0] for v in game.slots[U1].values())
    assert asyncio.run(kits.give_back(game, U1)) is True
    assert game.slots[U1] == before                                  # exactly theirs: no kit, nothing twice
    assert not kits.waiting("kit-test")


def test_a_retry_after_a_failed_check_never_duplicates_a_small_inventory(game):
    """Their things went over but the check didn't pass; on the retry they already have them. With only a couple of
    kinds of item the "already back" guess didn't apply and everything came twice: now it's written down."""
    before = dict(game.slots[U2])                                    # a cake and a helmet: two kinds
    asyncio.run(kits.stash(game, {".LongBedrockNameX": U2}, "g9"))
    d = settings_store.load()[kits.SECTION]
    d["stash"][f"kit-test:{U2}"]["landed"] = True                    # the earlier give-back got this far
    settings_store.save_section(kits.SECTION, d)
    game.slots[U2] = dict(before)                                    # and their things did arrive
    assert asyncio.run(kits.give_back(game, U2)) is True
    assert game.slots[U2] == before and not kits.waiting("kit-test")


def test_an_old_pocket_never_hands_out_copies_or_keeps_anyone_out(game):
    """Before 1.15.18 an old "pocket" of copies (their own hotbar, from the earlier bugs) handed things out whenever
    there was room, and kept them out of the next game (no kit, their own things kept on). Now it's emptied."""
    before = dict(game.slots[U1])
    asyncio.run(kits.stash(game, {"Alex": U1}, "old"))
    d = settings_store.load()[kits.SECTION]
    s = d["stash"][f"kit-test:{U1}"]
    s["restored"], s["pocket"] = True, 5                             # their things back, an old pocket left over
    settings_store.save_section(kits.SECTION, d)
    v = d["vault"]["kit-test"]
    for spot in kits._barrels(v, 5):
        game.barrels[spot] = {0: ("minecraft:diamond_sword", 1)}     # a copy of their own sword
    game.slots[U1] = dict(before)
    done = asyncio.run(kits.stash(game, {"Alex": U1}, "new"))        # the next game: they're in it
    assert done == ["Alex"] and game.slots[U1] == {}
    assert all(not game.barrels[spot] for spot in kits._barrels(v, 5))   # the copies are gone, never handed out
    asyncio.run(kits.give_kit(game, U1, kits.clean_kit({"sword": "iron"})))
    assert asyncio.run(kits.give_back(game, U1)) is True
    assert game.slots[U1] == before and not kits.waiting("kit-test")     # exactly once


def test_a_prize_won_in_a_game_waits_till_theyre_home(game, monkeypatch):
    """Handed over mid-game it'd be cleared with the kit on the way home: it waits, then arrives."""
    from app import challenges
    asyncio.run(kits.stash(game, {"Alex": U1}, "g10"))
    monkeypatch.setattr(challenges.S, "online_players", lambda srv: _online(["Alex"]))
    d0 = challenges._load()
    asyncio.run(challenges.award(game, "Alex", {"item": "minecraft:diamond", "count": 3, "name": "Diamond"}, "won the arena"))
    assert not any(c.startswith("give ") and "diamond " in c for c in game.said)      # not handed over in the game
    assert any(g["player"] == "Alex" for g in challenges._load()["gifts"])            # kept for them
    assert asyncio.run(kits.give_back(game, U1)) is True
    assert not kits.has_things_kept("kit-test", "Alex")                               # home: it can come now
    challenges._save(d0)


async def _online(names):
    return (names, "rcon")


def test_the_tidy_up_never_hands_things_back_while_a_game_is_starting(game, monkeypatch):
    """The game's still getting ready (not marked running yet) when the tidy-up comes by: it once handed everything
    straight back, so they played with their own things and the kit on top."""
    monkeypatch.setattr(kits, "STARTING_GRACE", 120)
    asyncio.run(kits.stash(game, {"Alex": U1}, "arena-starting"))
    assert game.slots[U1] == {}
    asyncio.run(kits.tidy(game, ["Alex"]))                           # (no run marked running yet)
    assert game.slots[U1] == {} and kits.waiting("kit-test")         # left alone: the game's on
    kits._starting["arena-starting"] = 0                             # long past, and still not running: really over
    asyncio.run(kits.tidy(game, ["Alex"]))
    assert game.slots[U1] and not kits.waiting("kit-test")


def test_a_kit_that_didnt_all_arrive_is_put_right():
    """Armour that didn't go on is tried again, then handed over to put on; anything else missing is given again."""
    import asyncio

    from app import kits
    said = []

    class Srv:
        mc_version = "26.3"

        async def rcon(self, cmd, wait=None):
            said.append(cmd)
            if cmd.endswith(" Inventory"):                      # the sword, bow and arrows arrived; not the food
                return ('Tyler has the following entity data: [{Slot: 0b, id: "minecraft:iron_sword", count: 1}, '
                        '{Slot: 1b, id: "minecraft:bow", count: 1}, {Slot: 2b, id: "minecraft:arrow", count: 16}]')
            if cmd.endswith(" equipment"):                      # only the shield went on
                return 'Tyler has the following entity data: {offhand: {id: "minecraft:shield", count: 1}}'
            return ""
    kit = kits.clean_kit({"sword": "iron", "armour": "iron", "bow": True, "arrows": 16, "shield": True, "food": True})
    asyncio.run(kits.give_kit(Srv(), "u-1", kit))
    gives = [c for c in said if c.startswith("give u-1 ")]
    assert any("iron_helmet" in c for c in gives) and any("iron_boots" in c for c in gives)          # armour, to wear
    assert any("cooked_beef" in c and c.endswith(" 16") for c in gives)                             # the food, again
    assert not any("shield" in c for c in gives) and sum("iron_sword" in c for c in gives) == 1      # nothing doubled


def test_a_copy_that_changed_midway_is_simply_made_again(game, monkeypatch):
    """Something picked up (or dropped) while the copy was made: it's thrown away and made again, so they still play."""
    game.break_copy = True

    async def wait(_secs):
        game.break_copy = False                    # they stood still the second time
    monkeypatch.setattr(kits.asyncio, "sleep", wait)
    before = dict(game.slots[U1])
    assert asyncio.run(kits.stash(game, {"Alex": U1}, "g-retry")) == ["Alex"]
    assert game.slots[U1] == {} and any("hold still" in c for c in game.said)
    assert asyncio.run(kits.give_back(game, U1)) and game.slots[U1] == before          # all of it, once


def test_a_games_things_never_stay_with_anyone_after(game):
    """Dropped in a game, then picked up after walking out: taken back. Lying about anywhere: gone. Nobody in a game
    right now is touched."""
    asyncio.run(kits.stash(game, {"Alex": U1}, "g-stray"))
    game.slots.setdefault("Steve", {}); game.slots.setdefault("Alex", {})              # (by name, for the pretend server)
    game.said.clear()
    asyncio.run(kits.no_stray_kit(game, ["Alex", "Steve"]))
    assert not any(c.startswith("kill @e[type=minecraft:item,nbt=") and "solkit:1b" in c for c in game.said)   # a game's on: hands back, not this
    assert f"clear Steve {kits.KIT_MATCH}" in game.said and not any(c.startswith("clear Alex") for c in game.said)
    asyncio.run(kits.give_back(game, U1))
    game.said.clear()
    asyncio.run(kits.no_stray_kit(game, ["Alex"]))
    assert f"clear Alex {kits.KIT_MATCH}" in game.said                                  # home now: not kept by them
    assert any(c.startswith("kill @e[type=minecraft:item,nbt=") and "solkit:1b" in c for c in game.said)      # and none lying about


def test_the_arena_floor_doesnt_fill_up_with_monster_drops():
    from app import battle
    said = []

    class Srv:
        async def rcon(self, cmd, wait=None):
            said.append(cmd)
            return ""
    r = {"dim": "minecraft:overworld", "zone": {"x": 10, "y": 64, "z": -5, "r": 15}, "ticks": 5}
    asyncio.run(battle.tidy_ground(Srv(), r, monster_drops=True))
    assert any("solkit:1b" in c and "run tp @s @p[distance=..16" in c for c in said)      # dropped: back to the player
    assert any("kill @e[type=minecraft:item,x=10,y=64,z=-5,distance=..27]" in c for c in said)
    said.clear()
    asyncio.run(battle.tidy_ground(Srv(), {**r, "ticks": 6}, monster_drops=False))
    assert len(said) == 3 * len(kits.GAME_TAGS) and not any("x=10" in c for c in said)  # King of the Hill: just games' things
    assert {t for t in kits.GAME_TAGS if any(f"{t}:1b" in c for c in said)} == set(kits.GAME_TAGS)


def test_every_games_things_not_just_the_kit(game, monkeypatch):
    """Archery's match bow and arrow, spleef's shovel, and (when no contest is on) a contest's rod: the same."""
    from app import challenges
    game.slots.setdefault("Steve", {})
    monkeypatch.setattr(challenges, "rods_out", lambda sid: False)
    game.said.clear()
    asyncio.run(kits.no_stray_kit(game, ["Steve"]))
    for tag in ("solkit", "solmatch", "solspleef", "solrod"):                         # (no game on: swept)
        assert any(c.startswith("kill @e[type=minecraft:item") and f"{tag}:1b" in c for c in game.said), tag
    assert "clear Steve *[minecraft:custom_data={solmatch:1b}]" in game.said
    monkeypatch.setattr(challenges, "rods_out", lambda sid: True)                       # a fishing contest is on
    game.said.clear()
    asyncio.run(kits.no_stray_kit(game, ["Steve"]))
    assert not any("solrod" in c for c in game.said)


def test_something_dropped_mid_game_goes_straight_back():
    said = []

    class Srv:
        async def rcon(self, cmd, wait=None):
            said.append(cmd)
            return ""
    asyncio.run(kits.hand_back_dropped(Srv(), 48))
    kit = [c for c in said if "solkit:1b" in c]
    assert "PickupDelay:0s" in kit[0] and "run tp @s @p[distance=..48,gamemode=!spectator]" in kit[1]
    assert "unless entity @p[distance=..48" in kit[2] and kit[2].endswith("run kill @s")           # nobody near: gone


def test_dying_in_a_fight_brings_you_back_in_it_and_your_bed_is_yours_again_after(game, monkeypatch):
    async def live(srv, name):
        return {"respawn": {"x": 120, "y": 70, "z": -40, "dimension": "minecraft:overworld"}}     # their bed
    monkeypatch.setattr(kits.S, "live_player", live)
    asyncio.run(kits.stash(game, {"Alex": U1}, "g-spawn"))
    asyncio.run(kits.move_spawn(game, U1, "Alex", {"x": 5, "y": 64, "z": 9}, "minecraft:overworld"))
    assert f"execute in minecraft:overworld run spawnpoint {U1} 5 64 9" in game.said                 # respawn: in the arena
    game.said.clear()
    assert asyncio.run(kits.give_back(game, U1))
    assert f"execute in minecraft:overworld run spawnpoint {U1} 120 70 -40" in game.said             # their own bed again


def test_trigger_leave_in_the_middle_of_a_game(game, monkeypatch):
    """/trigger leave while playing: asked once, the game takes them out and sends them home with their things."""
    from app import optin
    asyncio.run(kits.stash(game, {"Alex": U1}, "g-leave"))
    monkeypatch.setattr(kits, "_in_live_game", lambda s: True)
    told = []

    async def tell(srv, name, text, e, st=None):
        told.append(text)
    monkeypatch.setattr(optin, "_tell", tell)
    assert asyncio.run(optin.leave(game, "Alex")) == "game" and "on the way back" in told[0]
    assert kits.wants_out("kit-test", "alex") and not kits.wants_out("kit-test", "alex")     # used up once taken
    kits.ask_out("kit-test", "Alex")
    kits._quitting[("kit-test", "alex")] -= kits.QUIT_SECS + 1                               # nobody acted on it in time
    assert not kits.wants_out("kit-test", "Alex")


def test_the_mob_arena_lets_someone_leave(monkeypatch):
    from app import battle
    said, gave = [], []

    class Srv:
        id = "leave-srv"

        async def rcon(self, cmd, wait=None):
            said.append(cmd)
            return ""

    async def online(srv):
        return ["Alex", "Steve"], "rcon"

    async def give_back(srv, uuid, move=True):
        gave.append((uuid, move))
        return True
    monkeypatch.setattr(battle.S, "online_players", online)
    monkeypatch.setattr(kits, "give_back", give_back)
    r = {"players": {"Alex": {"uuid": "u-a"}, "Steve": {"uuid": "u-s"}}}
    kits.ask_out("leave-srv", "Alex")
    asyncio.run(battle.left_and_back(Srv(), r, {"alex": 1, "steve": 1}))
    assert r["players"]["Alex"]["out"] and gave == [("u-a", True)] and not r["players"]["Steve"].get("out")
