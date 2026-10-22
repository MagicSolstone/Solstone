"""The Solstone Fishing pack: what it contains, reading catches back, and fishing contests."""
import asyncio
import io
import json
import re
import time
import zipfile

import pytest


def test_pack_contents():
    from app import fishpack
    z = zipfile.ZipFile(io.BytesIO(fishpack.build_zip()))
    names = set(z.namelist())
    assert {"pack.mcmeta", "data/minecraft/loot_table/gameplay/fishing/fish.json", "data/minecraft/tags/function/load.json",
            "data/solfish/advancement/hooked.json", "data/solfish/function/record.mcfunction"} <= names
    meta = json.loads(z.read("pack.mcmeta"))["pack"]
    assert meta["min_format"] == 48 and meta["max_format"] >= 101 and meta["supported_formats"]["min_inclusive"] == 48   # 1.21 .. 26.x
    loot = json.loads(z.read("data/minecraft/loot_table/gameplay/fishing/fish.json"))
    entries = loot["pools"][0]["entries"]
    assert len(entries) == len(fishpack.SPECIES) * len(fishpack.QUALITIES) * len(fishpack.STEPS)
    assert all(isinstance(e["weight"], int) and e["weight"] > 0 for e in entries)
    assert len({e["functions"][2]["tag"] for e in entries}) == len(entries)                  # every catch distinct
    koi = [e for e in entries if '"koi"' in e["functions"][2]["tag"]]
    assert koi and all("conditions" not in e for e in koi)                                  # koi anywhere: never an empty table
    adv = json.loads(z.read("data/solfish/advancement/hooked.json"))
    assert adv["criteria"]["hooked"]["trigger"] == "minecraft:fishing_rod_hooked" and adv["rewards"]["function"] == "solfish:hooked"
    rec = z.read("data/solfish/function/check_item.mcfunction").decode()
    assert "matches 5.. run return 0" in rec                                                # old (dropped) fish never count
    g = {x["key"]: x for x in fishpack.guide()}
    assert g["koi"]["rarity"] == "very rare" and g["bluegill"]["max_lb"] < g["sturgeon"]["min_lb"]
    assert sum(q["chance"] for q in fishpack.qualities()) == 100


def test_parse_catches():
    from app import fishpack
    reply = ('Storage solstone:fish has the following contents: [{s: "trout", n: "Rainbow Trout", q: 3, ql: "Prime", w: 47, lb: "4.7", p: 42, '
             'u: [I; 110787060, 1156138790, -1514210135, 238594805], i: 7, t: 123L}]')
    c = fishpack.parse_catches(reply)[0]
    assert c["name"] == "Rainbow Trout" and c["weight"] == 4.7 and c["points"] == 42 and c["i"] == 7 and c["quality_name"] == "Prime"
    assert c["uuid"] == "069a79f4-44e9-4726-a5be-fca90e38aaf5"                # Notch: a known UUID / int array pair
    assert fishpack.parse_catches("Found no elements matching catches") == []


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
            body = ", ".join(f'{{s: "{c[0]}", n: "{c[1]}", q: {c[2]}, ql: "{c[3]}", w: {c[4]}, lb: "{c[4] / 10}", p: {c[5]}, u: [I; 1, 2, 3, 4], i: {i + 1}}}'
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
    from app import challenges, fishing, settings_store
    from app import servers as S
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
    assert len(srv.said) == 1 and "Exquisite Golden Koi" in srv.said[0]                    # only the big one, outside a contest
    asyncio.run(fishing.poll([srv]))
    assert len(db.events(srv.id, ["fish", "bigfish"], None, 10)) == 2                     # nothing twice


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
    assert len(d["guide"]) >= 20 and d["status"]["current"] >= 1 and "writable" in d["status"]
    r = client.get("/api/fishing/solstone-pack.zip")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip" and r.content[:2] == b"PK"
    assert viewer.get("/api/fishing/solstone-pack.zip").status_code == 403
