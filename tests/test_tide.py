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
    assert [e["player"] for e in d["top"]["tide:largemouth_bass"]] == ["Gimli_Jr", "Tyler"]
    assert "tide:great_white_shark" not in d["records"]
    tiers = {t["key"]: t for t in d["tiers"]}
    assert tiers["common"]["family"] == 1 and tiers["common"]["total"] == 1 and tiers["very_rare"]["family"] == 0
    tyler = next(p for p in d["players"] if p["name"] == "Tyler")
    assert tyler["level"] == 11 and tyler["title"] == "Apprentice Angler" and tyler["caught"] == 16
    assert tyler["qualities"] == [4, 8, 3, 1, 0, 0] and tyler["species"]["tide:bluegill"]["shortest_cm"] > 0
    assert d["players"][0]["name"] == "Tyler"                                               # most XP first
    assert all(p["name"] != "MomCrafts" for p in d["players"])                             # never fished with Tide


def test_leaderboards_and_player_page(client, sid, tyler):
    lb = client.get(f"/api/servers/{sid}/leaderboard").json()
    keys = [b["key"] for b in lb["boards"]]
    assert "fishing_level" in keys and next(b for b in lb["boards"] if b["key"] == "heaviest_fish")["kind"] == "grams"
    rows = {r["name"]: r for r in lb["players"]}
    assert rows["Tyler"]["fishing_level"] == 11 and rows["Gimli_Jr"]["heaviest_fish"] == 3400 and rows["MomCrafts"]["fishing_level"] == 0
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
    assert len(after) == before + 1 and after[-1]["quality_name"] == "Fine" and after[-1]["points"] == 15


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
    assert any("Prime Pike" in x and "10 lb 3 oz" in x and "new best" in x for x in srv.cmds)
    srv.online = ["Tyler"]                                                               # Gimli_Jr logs off before the end
    _end(challenges)
    asyncio.run(challenges.tick([srv]))
    c = challenges.list_for(srv.id)[0]
    assert c["winners"] == ["Gimli_Jr"] and c["scores"]["Gimli_Jr"] == 102 and c["scores"]["Tyler"] == 4
    assert c["result"] == "Gimli_Jr won Biggest catch with a 10 lb 3 oz Pike!"
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
    assert c["scores"]["Tyler"] == 30 and c["winners"] == ["Tyler"]                       # Fine common: 10 x 1.5 = 15 each


def test_plain_fishing_contest_still_uses_the_game_stat_with_tide(lake):
    challenges, _tide, srv = lake
    challenges.create(srv.id, {"kind": "fish", "start": time.time(), "minutes": 10, "prize": {"item": "diamond"}})
    asyncio.run(challenges.tick([srv]))
    c = challenges.list_for(srv.id)[0]
    assert c["tide"] and c.get("tscore") is None and any("minecraft.custom:minecraft.fish_caught" in x for x in srv.cmds)
    assert "fishinglevel fair Tyler true" in srv.cmds                                    # fair play applies to every fishing contest
