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
