"""Fishing with the Tide mod: its fish read from the jar, the family journal from save files,
levels, leaderboards, the player page, and catches read from the server log."""
import json


def test_species_from_the_jar(client, sid):
    from app import servers as S, tide
    import asyncio
    srv = asyncio.run(S.registry.get(sid))
    assert tide.installed(srv)
    sp = tide.species(srv)
    assert [s["id"] for s in sp] == ["tide:bluegill", "tide:largemouth_bass", "tide:great_white_shark"]   # by water, then rarity
    assert sp[0]["name"] == "Bluegill" and sp[0]["rarity"] == "common" and sp[0]["where"] == "Lakes and Rivers"
    assert sp[2]["stars"] == 4


def test_level_curve_matches_the_mod():
    from app import tide
    cfg = {"base": 20.0, "growth": 0.2}
    assert tide.xp_for_level(1, cfg) == 0 and tide.xp_for_level(2, cfg) == 20                 # ~2 fish
    assert tide.xp_for_level(29, cfg) - tide.xp_for_level(28, cfg) == round(20 + 0.2 * 28 * 28)  # ~15 fish
    assert 60_000 < tide.xp_for_level(99, cfg) < 70_000
    assert tide.level_for_xp(19, cfg) == 1 and tide.level_for_xp(20, cfg) == 2
    assert tide.title(9) == "Novice Angler" and tide.title(30) == "Angler" and tide.title(95) == "Grandmaster Angler" and tide.title(99) == "Legendary Angler"


def test_family_journal(client, sid):
    d = client.get(f"/api/servers/{sid}/fishing/journal").json()
    assert d["source"] == "tide" and len(d["species"]) == 3 and d["family_species"] == 2
    bass = d["records"]["tide:largemouth_bass"]
    assert bass["player"] == "Gimli_Jr" and bass["weight_g"] == 3400.0                    # heaviest wins the record
    assert bass["fish_quality"] == 3                                                       # the quality of that very fish
    assert [e["player"] for e in d["top"]["tide:largemouth_bass"]] == ["Gimli_Jr", "Tyler"]
    assert "tide:great_white_shark" not in d["records"]
    tiers = {t["key"]: t for t in d["tiers"]}
    assert tiers["common"]["family"] == 1 and tiers["common"]["total"] == 1 and tiers["very_rare"]["family"] == 0
    tyler = next(p for p in d["players"] if p["name"] == "Tyler")
    assert tyler["level"] == 11 and tyler["title"] == "Apprentice Angler" and tyler["caught"] == 16
    assert tyler["qualities"] == [4, 8, 3, 1, 0, 0] and tyler["species"]["tide:bluegill"]["shortest_cm"] > 0
    assert d["tackle_total"] == 3 + 6 and tyler["tackle"] == 3                              # unknown names don't count
    assert d["players"][0]["name"] == "Tyler"                                               # most XP first
    assert all(p["name"] != "MomCrafts" for p in d["players"])                             # never fished with Tide


def test_leaderboards_and_player_page(client, sid, tyler):
    lb = client.get(f"/api/servers/{sid}/leaderboard").json()
    keys = [b["key"] for b in lb["boards"]]
    assert "fishing_level" in keys and next(b for b in lb["boards"] if b["key"] == "heaviest_fish")["kind"] == "grams"
    rows = {r["name"]: r for r in lb["players"]}
    assert rows["Tyler"]["fishing_level"] == 11 and rows["Gimli_Jr"]["heaviest_fish"] == 3400 and rows["MomCrafts"]["fishing_level"] == 0
    assert rows["Tyler"]["fish_caught"] == 16 and rows["Gimli_Jr"]["fish_caught"] == 2      # the journal, not Minecraft's count
    p = client.get(f"/api/servers/{sid}/players/{tyler}").json()
    f = p["fishing"]
    assert f["level"] == 11 and f["species"] == 2 and f["species_total"] == 3 and f["biggest"]["name"] == "Largemouth Bass"
    assert 0 < f["progress"] < 1 and f["next"] > 0


def test_catch_lines_from_the_log(client, sid):
    from app import db, servers as S, tide
    import asyncio
    line = '[14:02:11] [Server thread/INFO]: [Tide catch] ' + json.dumps({"player": "Gimli_Jr", "fish": "tide:great_white_shark", "rarity": "very_rare",
                                                                          "quality": 5, "quality_name": "Mythic", "length_cm": 700.0, "weight_g": 2_900_000.0, "x": 1, "y": 62, "z": 3})
    h, m, s, c = tide.parse_log_line(line)
    assert (h, m, s) == (14, 2, 11) and c["fish"] == "tide:great_white_shark"
    dev = '[14:02:11] [Server thread/INFO] (Tide) [Tide catch] {"player": "Tyler", "fish": "tide:bluegill"}'   # the dev log layout too
    assert tide.parse_log_line(dev)[3]["player"] == "Tyler"
    assert tide.parse_log_line("[14:02:11] [Server thread/INFO]: <Tyler> [Tide catch] hi") is None
    srv = asyncio.run(S.registry.get(sid))
    rec = tide.record_catch(srv, 1_000_000.0, c)
    assert rec[0] == "bigfish" and rec[1].startswith("Gimli_Jr caught a Mythic Great White Shark · 6,393 lb")
    assert tide.record_catch(srv, 1_000_000.5, c) is None                                   # the same line read twice
    catch = tide.to_catch(srv, c)
    assert catch["points"] == 640 and catch["pos"] == [1, 62, 3]                             # very rare 80 x Mythic 8
    d = client.get(f"/api/servers/{sid}/fishing/journal").json()
    assert d["records"]["tide:great_white_shark"]["player"] == "Gimli_Jr" and d["recent"][0]["name"] == "Great White Shark"
    assert next(t for t in d["tiers"] if t["key"] == "very_rare")["family"] == 1
    assert d["recent"][0]["quality_name"] == "Mythic"
    assert any(e["type"] == "bigfish" for e in db.events(sid, ["bigfish"], None, 10))


def test_recorder_reads_tide_lines(client, sid):
    """The log tailer turns [Tide catch] lines into catches; ordinary lines still become events."""
    from app import db, servers as S
    from app.recorder import recorder
    import asyncio
    srv = asyncio.run(S.registry.get(sid))
    log = srv.dir / "logs" / "latest.log"
    log.parent.mkdir(exist_ok=True)
    before = len([r for r in db.fish_catches(sid) if r["species"] == "tide:bluegill"])
    with log.open("a") as fh:
        fh.write('[10:00:01] [Server thread/INFO]: [Tide catch] {"player": "Tyler", "fish": "tide:bluegill", "rarity": "common", "quality": 2, "weight_g": 300.0}\n')
    recorder.tail_server(srv)
    after = [r for r in db.fish_catches(sid) if r["species"] == "tide:bluegill"]
    assert len(after) == before + 1 and after[-1]["quality_name"] == "Good" and after[-1]["points"] == 15


# ------------------------------------------------------------------ contests scored from Tide catches
import asyncio  # noqa: E402
import time  # noqa: E402

import pytest  # noqa: E402


class TideServer:
    is_java = True

    def __init__(self):
        self.id, self.display_name, self.mc_version = "tide-srv", "Family", "26.3"
        self.cmds, self.online = [], ["Tyler", "Gimli_Jr"]

    def rcon_conf(self):
        return {"host": "x"}

    async def rcon(self, cmd):
        self.cmds.append(cmd)
        if cmd.startswith("fishinglevel fair"):
            return f"Fair play {'on' if cmd.endswith('true') else 'off'} for 1 player(s)"
        if cmd.startswith("give"):
            return "Gave 1 [x] to someone"
        return ""


@pytest.fixture()
def lake(monkeypatch):
    from app import challenges, gather, settings_store, tide
    from app import servers as S
    monkeypatch.setattr(gather, "LEAD", 0)
    settings_store.save_section("challenges", {})
    srv = TideServer()

    async def online(_s):
        return list(srv.online), "rcon"
    monkeypatch.setattr(S, "online_players", online)
    monkeypatch.setattr(tide, "installed", lambda _s: True)
    monkeypatch.setattr(tide, "species", lambda _s: [{"id": "tide:pike", "name": "Pike"}, {"id": "tide:bluegill", "name": "Bluegill"}])
    monkeypatch.setattr(challenges.fwshow, "push", lambda *a, **k: None)
    yield challenges, tide, srv
    settings_store.save_section("challenges", {})


def _end(challenges):
    d = challenges._load()
    d["items"][0]["ends_at"] = time.time() - 1
    challenges._save(d)


def test_biggest_catch_with_tide_and_fair_play(lake):
    challenges, tide, srv = lake
    challenges.create(srv.id, {"kind": "fish_heaviest", "start": time.time(), "minutes": 10, "prize": {"item": "diamond"}})
    asyncio.run(challenges.tick([srv]))
    c = challenges.list_for(srv.id)[0]
    assert c["state"] == "running" and c["tide"] and c["objectives"] == [] and c["fair"]
    assert not any("solfish" in x for x in srv.cmds)                                      # the pack isn't involved
    assert {"fishinglevel fair Tyler true", "fishinglevel fair Gimli_Jr true"} <= set(srv.cmds)
    assert any("Fair play: everyone fishes at the same level" in x for x in srv.cmds)
    pike = tide.to_catch(srv, {"player": "Gimli_Jr", "fish": "tide:pike", "rarity": "rare", "quality": 3, "weight_g": 4627.0})
    small = tide.to_catch(srv, {"player": "Gimli_Jr", "fish": "tide:bluegill", "quality": 1, "weight_g": 200.0})
    asyncio.run(challenges.on_catch(srv, "Gimli_Jr", pike))
    asyncio.run(challenges.on_catch(srv, "Gimli_Jr", small))
    asyncio.run(challenges.on_catch(srv, "Tyler", small))
    assert any("Great Pike" in x and "10.2 lb" in x and "new best" in x for x in srv.cmds)
    srv.online = ["Tyler"]                                                               # Gimli_Jr logs off before the end
    _end(challenges)
    asyncio.run(challenges.tick([srv]))
    c = challenges.list_for(srv.id)[0]
    assert c["winners"] == ["Gimli_Jr"] and c["scores"]["Gimli_Jr"] == 102 and c["scores"]["Tyler"] == 4
    assert c["result"] == "Gimli_Jr won Biggest catch with a 10.2 lb Pike!"
    assert "fishinglevel fair Tyler false" in srv.cmds and "fishinglevel fair Gimli_Jr false" not in srv.cmds
    assert c["fair_owed"] == ["gimli_jr"]
    asyncio.run(challenges.on_join(srv, "Gimli_Jr"))                                     # their own level back on joining
    assert srv.cmds[-1] == "fishinglevel fair Gimli_Jr false" or "fishinglevel fair Gimli_Jr false" in srv.cmds
    assert challenges.list_for(srv.id)[0]["fair_owed"] == []


def test_tournament_points_from_tide_and_no_fair_play(lake):
    challenges, tide, srv = lake
    challenges.create(srv.id, {"kind": "fish_points", "start": time.time(), "minutes": 10, "fair": False, "prize": {"item": "diamond"},
                               "hot": True, "hot_bonus": 2})
    asyncio.run(challenges.tick([srv]))
    assert not any(x.startswith("fishinglevel") for x in srv.cmds)
    d = challenges._load(); d["items"][0].setdefault("hot_zone", None); challenges._save(d)
    catch = tide.to_catch(srv, {"player": "Tyler", "fish": "tide:bluegill", "rarity": "common", "quality": 2, "weight_g": 300.0})
    asyncio.run(challenges.on_catch(srv, "Tyler", catch))
    asyncio.run(challenges.on_catch(srv, "Tyler", catch))
    asyncio.run(challenges.on_join(srv, "Gimli_Jr"))                                     # no fair play: nothing sent on join
    assert not any(x.startswith("fishinglevel") for x in srv.cmds)
    _end(challenges)
    asyncio.run(challenges.tick([srv]))
    c = challenges.list_for(srv.id)[0]
    assert c["scores"]["Tyler"] == 30 and c["winners"] == ["Tyler"]                       # Good common: 10 x 1.5 = 15 each


def test_plain_fishing_contest_still_uses_the_game_stat_with_tide(lake):
    challenges, _tide, srv = lake
    challenges.create(srv.id, {"kind": "fish", "start": time.time(), "minutes": 10, "prize": {"item": "diamond"}})
    asyncio.run(challenges.tick([srv]))
    c = challenges.list_for(srv.id)[0]
    assert c["tide"] and c.get("tscore") is None and any("minecraft.custom:minecraft.fish_caught" in x for x in srv.cmds)
    assert "fishinglevel fair Tyler true" in srv.cmds                                    # fair play applies to every fishing contest


def test_pack_without_fishing_for_tide_servers():
    from app import fishpack
    full, games = fishpack.pack_files(True), fishpack.pack_files(True, fishing=False)
    assert "data/minecraft/loot_table/gameplay/fishing.json" in full and "data/solfish/advancement/hooked.json" in full
    assert not any("loot_table" in p or p.endswith("hooked.json") or p.endswith("scan.mcfunction") for p in games)
    assert "data/solfish/function/load.mcfunction" in games                          # still says which version is in
    assert "data/solgames/advancement/hit_15.json" in games and "archery" in games["pack.mcmeta"]


def test_fishing_tab_only_with_something_to_fish_with(client, sid, tmp_path):
    from app import fishing
    s = client.get(f"/api/servers/{sid}").json()
    assert s["fishing"] == "tide"

    class Plain:                                    # a vanilla server with no pack and no catches
        is_java, id = True, "plain-srv"
        dir = tmp_path
        world_dir = tmp_path / "world"
    assert fishing.available(Plain()) is None
    (tmp_path / "world" / "datapacks").mkdir(parents=True)
    (tmp_path / "world" / "datapacks" / "solstone-pack.zip").write_bytes(b"PK")
    assert fishing.available(Plain()) == "pack"


def test_fishing_reset(client, sid, viewer, monkeypatch):
    """Admins can send someone back to level 1, or to a completely fresh start (journal, tackle log and
    Solstone's catch history too). The mod does the save, so the player has to be online."""
    from app import db
    from app import servers as S
    sent = []

    async def online(self, cmd):
        sent.append(cmd)
        return "Reset 1 player(s) to a fresh start" if cmd.startswith("fishinglevel") else ""
    monkeypatch.setattr(S.Server, "rcon", online)
    monkeypatch.setattr(S.Server, "rcon_conf", lambda self: {"host": "127.0.0.1", "port": 1, "password": "x"})
    db.add_catch(sid, 1.0, "Tyler", {"species": "tide:bluegill", "name": "Bluegill", "quality": 2, "quality_name": "Good", "weight": 300.0, "points": 3})
    db.add_event(sid, 1.0, "fish", "Tyler caught a Good Bluegill", "Tyler")
    url = f"/api/servers/{sid}/fishing/reset"

    resets = lambda: [c for c in sent if c.startswith("fishinglevel")]   # noqa: E731 (other tests' background loops send commands too)
    r = client.post(url, json={"player": "Tyler"}).json()
    assert resets() == ["fishinglevel reset Tyler"] and r["catches_removed"] == 0
    had = len(db.fish_catches(sid, "Tyler"))
    r = client.post(url, json={"player": "Tyler", "everything": True}).json()
    assert resets()[-1] == "fishinglevel reset Tyler everything" and "save-all" in sent and r["catches_removed"] == had >= 1
    assert not db.fish_catches(sid, "Tyler") and not db.events(sid, ["fish"], "Tyler")
    r = client.post(url, json={"player": "Tyler", "level": 99}).json()
    assert resets()[-1] == "fishinglevel set Tyler 99" and r["catches_removed"] == 0
    assert client.post(url, json={"player": "Tyler", "level": 100}).status_code == 400
    assert client.post(url, json={"player": "Tyler", "level": "99"}).status_code == 400

    async def offline(self, cmd):
        return "No player was found"
    monkeypatch.setattr(S.Server, "rcon", offline)
    r = client.post(url, json={"player": "Tyler"})
    assert r.status_code == 409 and "online" in r.json()["detail"]
    assert client.post(url, json={"player": "not a name!"}).status_code == 400
    assert viewer.post(url, json={"player": "Tyler"}).status_code == 403


# ---------------------------------------------------------------- item descriptions
class _DescServer:
    id = "desc"

    def __init__(self, reply=None, fail=False):
        self.reply, self.fail, self.cmds = reply, fail, []

    def rcon_conf(self):
        return ("localhost", 25575, "pw")

    async def rcon(self, cmd):
        self.cmds.append(cmd)
        if self.fail:
            from app.rcon import RconError
            raise RconError("Nothing is listening")
        return self.reply


def test_describe_uses_the_game_tooltip(monkeypatch):
    from app import tide
    tide._described.clear()
    monkeypatch.setattr(tide, "installed", lambda _s: True)
    srv = _DescServer("tooltip tide:golden_hook\nFF55FF\t+1 luck\nAAAAAA\titem.tide.golden_hook.desc\nAAAAAA\t ")
    d = asyncio.run(tide.describe_item(srv, "tide:golden_hook", {"item.tide.golden_hook.desc": "Shiny."}))
    assert srv.cmds == ["fishing describe tide:golden_hook"] and d["source"] == "game"
    assert d["lines"] == [{"text": "+1 luck", "color": "#FF55FF"}, {"text": "Shiny.", "color": "#AAAAAA"}]
    asyncio.run(tide.describe_item(srv, "tide:golden_hook", {}))                    # cached
    assert len(srv.cmds) == 1


def test_describe_falls_back_to_the_language_files(monkeypatch):
    from app import tide
    tide._described.clear()
    monkeypatch.setattr(tide, "installed", lambda _s: True)
    lang = {"item.tide.fish_satchel.desc_0": "Holds fish.", "item.tide.fish_satchel.desc_1": "§7Right-click to open."}
    for srv in (_DescServer("Unknown or incomplete command"), _DescServer(fail=True)):   # older Tide; server down
        d = asyncio.run(tide.describe_item(srv, "tide:fish_satchel", lang))
        assert d["source"] == "lang" and [x["text"] for x in d["lines"]] == ["Holds fish.", "Right-click to open."]
        assert ("Update it to 1.0.5" in d["why"]) if not srv.fail else ("isn't answering" in d["why"])
    d = asyncio.run(tide.describe_item(_DescServer(), "minecraft:stone", lang))
    assert d["lines"] == [] and d["source"] == "none"
    d = asyncio.run(tide.describe_item(_DescServer(), "bad id; op me", lang))
    assert d["source"] == "none"


GUIDE = {"rigs": [{"name": "Storm", "when": "THUNDER", "when_text": "in a thunderstorm", "two": "+8% bite speed in a thunderstorm",
                   "full": "+15% bite speed, +1 luck in a thunderstorm", "members": ["tide:copper_bobber", "tide:storm_line"]}],
         "whens": {"THUNDER": "in a thunderstorm", "NIGHT": "at night"},
         "items": [{"id": "tide:copper_bobber", "name": "item.tide.copper_bobber", "category": "Bobbers",
                    "lines": [["#FF55FF", "Part of: Storm rig"], ["#AAAAAA", ""]], "when": ["THUNDER"], "rig": "Storm",
                    "recipe": {"kind": "crafting", "width": 1, "height": 2, "slots": [["minecraft:copper_ingot"], ["minecraft:string", "bad id!"]], "note": ""}},
                   {"id": "tide:echo_fishing_rod", "name": "Echo Fishing Rod", "category": "Rods", "lines": [], "when": [], "rig": "",
                    "recipe": {"kind": "found", "width": 0, "height": 0, "slots": [], "note": "Found in ancient city chests."}},
                   {"id": "nope", "name": "x"}]}


def test_tackle_guide_from_the_game_then_the_saved_copy(monkeypatch):
    from app import tide
    from app import servers as S
    tide._guide_mem.clear()
    monkeypatch.setattr(tide, "installed", lambda _s: True)
    monkeypatch.setattr(tide, "jar", lambda _s: None)
    monkeypatch.setattr(S, "known_players", lambda _s: {"u1": {"name": "Tyler"}})
    monkeypatch.setattr(tide, "_player_tide", lambda _s, _u: {"tackle": {"copper_bobber"}})
    srv = _DescServer("tackleguide " + json.dumps(GUIDE))
    srv.id = "guide-test"
    lang = {"item.tide.copper_bobber": "Copper Bobber"}
    g = asyncio.run(tide.guide(srv, lang))
    assert srv.cmds == ["fishing guide"] and g["live"] and not g["why"]
    assert [x["id"] for x in g["items"]] == ["tide:copper_bobber", "tide:echo_fishing_rod"]
    cb = g["items"][0]
    assert cb["name"] == "Copper Bobber" and cb["lines"] == [{"text": "Part of: Storm rig", "color": "#FF55FF"}]
    assert cb["recipe"]["slots"] == [["minecraft:copper_ingot"], ["minecraft:string"]] and cb["when"] == ["THUNDER"]
    assert g["rigs"][0]["members"] == ["tide:copper_bobber", "tide:storm_line"]
    assert g["found"] == {"tide:copper_bobber": ["Tyler"]}
    # the server goes away: the saved copy still opens, and says why it isn't live
    tide._guide_mem.clear()
    down = _DescServer(fail=True)
    down.id = "guide-test"
    g2 = asyncio.run(tide.guide(down, lang))
    assert not g2["live"] and "isn't answering" in g2["why"] and len(g2["items"]) == 2
    # an older Tide+ that doesn't know the command, and no saved copy
    old = _DescServer("Unknown or incomplete command, see below for error")
    old.id = "guide-test-old"
    g3 = asyncio.run(tide.guide(old, lang))
    assert g3["items"] == [] and "older than 1.0.6" in g3["why"]
