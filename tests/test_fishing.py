"""The Solstone Fishing pack: what it contains, reading catches back, and fishing contests."""
import asyncio
import io
import json
import re
import time
import zipfile

import pytest


def test_pack_contents():
    """Fishing stays vanilla: no loot tables at all, just noticing catches and giving them a weight."""
    from app import fishpack
    z = zipfile.ZipFile(io.BytesIO(fishpack.build_zip()))
    names = set(z.namelist())
    assert {"pack.mcmeta", "data/minecraft/tags/function/load.json", "data/solfish/advancement/hooked.json",
            "data/solfish/function/record.mcfunction", "data/solfish/function/size.mcfunction", "data/solfish/tags/item/fish.json"} <= names
    assert not [n for n in names if "/loot_table/" in n and "solfish" in n or "gameplay/fishing" in n]     # vanilla fish, vanilla odds
    meta = json.loads(z.read("pack.mcmeta"))["pack"]
    assert meta["min_format"] == 48 and meta["max_format"] >= 101 and meta["supported_formats"]["min_inclusive"] == 48   # 1.21 .. 26.x
    assert json.loads(z.read("data/solfish/tags/item/fish.json"))["values"] == ["minecraft:cod", "minecraft:salmon", "minecraft:tropical_fish", "minecraft:pufferfish"]
    adv = json.loads(z.read("data/solfish/advancement/hooked.json"))
    assert adv["criteria"]["hooked"]["trigger"] == "minecraft:fishing_rod_hooked" and adv["rewards"]["function"] == "solfish:hooked"
    assert "matches 5.. run return 0" in z.read("data/solfish/function/check_item.mcfunction").decode()   # old (dropped) fish never count
    rec = z.read("data/solfish/function/record.mcfunction").decode()
    assert "contents minecraft:salmon run function solfish:size {lo:20,hi:200}" in rec and "set_name" not in rec
    assert "random value $(lo)..$(hi)" in z.read("data/solfish/function/size.mcfunction").decode()
    assert "tellraw" not in "".join(z.read(n).decode() for n in names if n.startswith("data/solfish/"))       # nothing said in the game
    g = {x["key"]: x for x in fishpack.guide()}
    assert set(g) == {"cod", "salmon", "tropical_fish", "pufferfish"} and g["salmon"]["max_lb"] == 20 and g["cod"]["min_points"] == 2
    assert fishpack.qualities() == []


def test_parse_catches():
    from app import fishpack
    reply = ('Storage solstone:fish has the following contents: [{s: "trout", n: "Rainbow Trout", q: 3, ql: "Prime", w: 47, lb: "4.7", p: 42, '
             'u: [I; 110787060, 1156138790, -1514210135, 238594805], i: 7, t: 123L}]')
    c = fishpack.parse_catches(reply)[0]
    assert c["name"] == "Rainbow Trout" and c["weight"] == 4.7 and c["points"] == 42 and c["i"] == 7 and c["quality_name"] == "Prime"
    assert c["uuid"] == "069a79f4-44e9-4726-a5be-fca90e38aaf5"                # Notch: a known UUID / int array pair
    assert fishpack.parse_catches("Found no elements matching catches") == []
    plain = fishpack.parse_catches('Storage solstone:fish has the following contents: [{s: "minecraft:tropical_fish", w: 7, p: 1, '
                                   'u: [I; 1, 2, 3, 4], i: 3, t: 5L}]')[0]
    assert plain["basic"] and plain["species"] == "tropical_fish" and plain["name"] == "Tropical Fish" and plain["lb"] == "0.7"
    assert plain["quality"] == 1 and plain["points"] == 1


class FakeServer:
    is_java = True

    def __init__(self):
        self.id, self.display_name, self.mc_version = "fish-srv", "Family", "26.1"
        self.catches, self.said, self.scores, self.reset = [], [], {}, []

    def rcon_conf(self):
        return {"host": "x"}

    async def rcon(self, cmd):
        if cmd == "data get storage solstone:fish pack":
            return "Storage solstone:fish has the following contents: {version: 1}"
        if cmd == "data get storage solstone:fish catches":
            body = ", ".join((f'{{s: "{c[0]}", w: {c[4]}, p: {c[5]}, u: [I; 1, 2, 3, 4], i: {i + 1}}}' if c[1] is None else
                              f'{{s: "{c[0]}", n: "{c[1]}", q: {c[2]}, ql: "{c[3]}", w: {c[4]}, lb: "{c[4] / 10}", p: {c[5]}, u: [I; 1, 2, 3, 4], i: {i + 1}}}')
                             for i, c in enumerate(self.catches))
            return f"Storage solstone:fish has the following contents: [{body}]"
        m = re.match(r"scoreboard players get (\S+) (\S+)", cmd)
        if m:
            v = self.scores.get((m.group(1), m.group(2)))
            return f"{m.group(1)} has {v} [{m.group(2)}]" if v is not None else "none is set"
        if cmd.startswith("scoreboard players reset"):
            self.reset.append(cmd)
        if cmd.startswith("tellraw"):
            self.said.append(cmd)
        if cmd.startswith("give"):
            return "Gave 1 [x] to someone"
        return ""


@pytest.fixture()
def pond(monkeypatch):
    from app import challenges, fishing, gather, settings_store
    from app import servers as S
    monkeypatch.setattr(gather, "LEAD", 0)
    settings_store.save_section("challenges", {})
    srv = FakeServer()
    fishing._state.pop(srv.id, None)

    async def online(_s):
        return ["Tyler", "Gimli_Jr"], "rcon"
    monkeypatch.setattr(S, "online_players", online)
    monkeypatch.setattr(S, "known_players", lambda _s: {"00000001-0000-0002-0000-000300000004": {"name": "Gimli_Jr"}})
    monkeypatch.setattr(challenges.fwshow, "push", lambda *a, **k: None)
    yield fishing, challenges, srv
    settings_store.save_section("challenges", {})


def test_catches_recorded_and_big_ones_announced(pond):
    from app import db
    fishing, _ch, srv = pond
    srv.catches = [("perch", "Yellow Perch", 1, "Normal", 10, 8)]
    asyncio.run(fishing.poll([srv]))                                     # first look: just remembers where it's up to
    assert not db.events(srv.id, ["fish", "bigfish"], None, 10)
    srv.catches += [("bass", "Largemouth Bass", 1, "Normal", 30, 15), ("koi", "Golden Koi", 4, "Exquisite", 69, 480)]
    asyncio.run(fishing.poll([srv]))
    evs = db.events(srv.id, ["fish", "bigfish"], None, 10)
    assert [e["type"] for e in evs] == ["bigfish", "fish"] and evs[0]["player"] == "Gimli_Jr"
    assert "Gimli_Jr caught an Exquisite Golden Koi · 6.9 lb · 480 points" == evs[0]["message"]
    to_all = [x for x in srv.said if x.startswith("tellraw @a")]
    assert len(to_all) == 1 and "Exquisite Golden Koi" in to_all[0]                         # only the big one, outside a contest
    journal = [x for x in srv.said if "fishing journal" in x]
    assert len(journal) == 2 and all(x.startswith("tellraw Gimli_Jr") for x in journal) and "(2 of 4 species)" in journal[-1]
    assert [c["species"] for c in db.fish_catches(srv.id, "Gimli_Jr")] == ["bass", "koi"]
    asyncio.run(fishing.poll([srv]))
    assert len(db.events(srv.id, ["fish", "bigfish"], None, 10)) == 2                     # nothing twice
    assert len(db.fish_catches(srv.id)) == 2


def test_vanilla_catches_are_quiet(pond):
    """With the vanilla pack nothing is said in the game outside a contest; the catch is still kept."""
    from app import db
    fishing, _ch, srv = pond
    srv.basic = True
    srv.catches = [("minecraft:cod", None, 1, None, 40, 5)]
    asyncio.run(fishing.poll([srv]))
    srv.catches += [("minecraft:salmon", None, 1, None, 155, 16)]
    asyncio.run(fishing.poll([srv]))
    assert srv.said == []
    assert [(c["species"], c["name"], c["weight"]) for c in db.fish_catches(srv.id, "Gimli_Jr")][-1] == ("salmon", "Salmon", 15.5)
    assert db.events(srv.id, ["fish"], None, 1)[0]["message"] == "Gimli_Jr caught a Salmon · 15.5 lb · 16 points"


def test_vanilla_catches_in_a_contest_go_in_chat(pond):
    fishing, challenges, srv = pond
    challenges.create(srv.id, {"kind": "fish_heaviest", "start": time.time(), "minutes": 10, "prize": {"item": "diamond", "count": 1}})
    asyncio.run(challenges.tick([srv]))
    srv.said.clear()
    asyncio.run(challenges.on_catch(srv, "Tyler", {"name": "Salmon", "lb": "15.5", "weight": 15.5, "quality": 1, "quality_name": "Normal",
                                                   "points": 16, "basic": True}))
    assert any(x.startswith("tellraw @a") and "Salmon" in x and "15.5 lb" in x for x in srv.said)


def test_biggest_catch_contest(pond):
    fishing, challenges, srv = pond
    c = challenges.create(srv.id, {"kind": "fish_heaviest", "start": time.time(), "minutes": 10, "prize": {"item": "diamond", "count": 2}})
    asyncio.run(challenges.tick([srv]))
    assert any("solfish_cb" in r for r in srv.reset)                                     # the pack's objective cleared
    c = challenges.list_for(srv.id)[0]
    assert c["state"] == "running" and c["objectives"] == ["solfish_cb"]
    asyncio.run(challenges.on_catch(srv, "Gimli_Jr", {"name": "Northern Pike", "lb": "10.2", "weight": 10.2, "quality": 3, "quality_name": "Prime", "points": 60}))
    asyncio.run(challenges.on_catch(srv, "Gimli_Jr", {"name": "Bluegill", "lb": "0.5", "weight": 0.5, "quality": 1, "quality_name": "Normal", "points": 5}))
    assert any("Prime Northern Pike" in s and "new best" in s for s in srv.said)
    srv.scores[("Gimli_Jr", "solfish_cb")] = 102; srv.scores[("Tyler", "solfish_cb")] = 40
    d = challenges._load(); d["items"][0]["ends_at"] = time.time() - 1; challenges._save(d)
    asyncio.run(challenges.tick([srv]))
    c = challenges.list_for(srv.id)[0]
    assert c["winners"] == ["Gimli_Jr"] and c["result"] == "Gimli_Jr won Biggest catch with a 10.2 lb Northern Pike!"
    assert c["best"]["Gimli_Jr"]["name"] == "Northern Pike"


def test_fishing_api(client, viewer, sid):
    assert viewer.get(f"/api/servers/{sid}/fishing").status_code == 403
    d = client.get(f"/api/servers/{sid}/fishing").json()
    assert len(d["guide"]) == 4 and d["status"]["current"] >= 1 and "writable" in d["status"]
    r = client.get("/api/fishing/solstone-pack.zip")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip" and r.content[:2] == b"PK"
    assert viewer.get("/api/fishing/solstone-pack.zip").status_code == 403


def test_datapack_folder_listing_finds_copies(tmp_path):
    import io
    import zipfile
    from types import SimpleNamespace

    from app import fishing, fishpack
    dp = tmp_path / "datapacks"
    dp.mkdir()
    (dp / "solstone-pack.zip").write_bytes(fishpack.build_zip())
    old = io.BytesIO()
    with zipfile.ZipFile(old, "w") as z:                               # an old copy, re-zipped inside a folder
        z.writestr("solstone-pack/pack.mcmeta", "{}")
        z.writestr("solstone-pack/data/solfish/function/load.mcfunction", "data modify storage solstone:fish pack set value {version:2}\n")
    (dp / "solstone-pack (1).zip").write_bytes(old.getvalue())
    (dp / "other").mkdir()
    rows = {r["name"]: r for r in fishing.files(SimpleNamespace(world_dir=tmp_path))}
    assert rows["solstone-pack.zip"]["version"] == fishpack.VERSION and not rows["solstone-pack.zip"]["nested"]
    assert rows["solstone-pack (1).zip"]["version"] == 2 and rows["solstone-pack (1).zip"]["nested"]
    assert rows["other"]["version"] is None


def test_reading_a_barrel_slot():
    from app import fishing
    got = ('0, 319, 0 has the following block data: [{Slot: 0b, components: {"minecraft:custom_data": {solfish: {s: "bluegill", n: "Bluegill", '
           'q: 0, ql: "Poor", w: 3, lb: "0.27", p: 2}}, "minecraft:item_name": {color: "gray", italic: 0b, text: "Poor Bluegill"}}, count: 1, id: "minecraft:cod"}]')
    r = fishing._read_item(got)
    assert r["item"] == "minecraft:cod" and r["named"] == "Poor Bluegill" and r["pack_fish"]["name"] == "Bluegill"
    plain = fishing._read_item('0, 319, 0 has the following block data: [{Slot: 0b, count: 1, id: "minecraft:cod"}]')
    assert plain["item"] == "minecraft:cod" and plain["pack_fish"] is None and plain["named"] is None
    assert fishing._read_item("0, 319, 0 has the following block data: []")["item"] is None


def test_new_loot_format_detected():
    """26.3 renamed loot table fields; the pack itself has no fishing loot tables any more, but still knows."""
    from app import fishpack
    assert fishpack.new_loot_format("26.3") and fishpack.new_loot_format("26.4") and not fishpack.new_loot_format("26.1")
    assert not fishpack.new_loot_format("1.21.11") and fishpack.new_loot_format(None, 5023) and not fishpack.new_loot_format(None, 4440)


def test_catch_position_read_back():
    from app import fishpack
    reply = ('Storage solstone:fish has the following contents: [{s: "trout", n: "Rainbow Trout", q: 3, ql: "Trophy", w: 47, lb: "4.7", p: 42, '
             'u: [I; 1, 2, 3, 4], i: 9, t: 100L, pos: [12.5d, 62.1d, -40.25d]}]')
    assert fishpack.parse_catches(reply)[0]["pos"] == [12.5, 62.1, -40.25]
    assert "e.pos set from entity @s Pos" in fishpack.FUNCTIONS["record"]


def test_journal_and_backfill_from_old_feed():
    from app import db, fishing
    sid = "journal-srv"
    db.add_event(sid, 100.0, "fish", "Gimli_Jr caught a Salmon · 4.7 lb · 5 points", "Gimli_Jr")
    db.add_event(sid, 101.0, "fish", "Gimli_Jr caught a Cod · 0.5 lb · 1 points", "Gimli_Jr")
    db.add_event(sid, 102.0, "fish", "Tyler caught a Cod · 0.9 lb · 1 points", "Tyler")
    j = fishing.journal(sid)                                            # old catches read from the feed once
    g = next(p for p in j["players"] if p["name"] == "Gimli_Jr")
    assert set(g["species"]) == {"salmon", "cod"} and g["total"] == 2
    assert j["records"]["cod"]["player"] == "Tyler" and j["records"]["cod"]["lb"] == 0.9
    assert len(j["species"]) == 4 and j["qualities"] == []
    assert len(fishing.journal(sid)["recent"]) == 3                     # not filled twice
