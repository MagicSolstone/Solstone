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


def test_fireworks_settings(client, viewer, anon):
    cfg = anon.get("/api/public/fireworks").json()
    assert cfg["pace"] == "normal" and all(cfg["kinds"].values()) and len(cfg["colors"]) == 10
    assert viewer.put("/api/settings/fireworks", json={"pace": "calm"}).status_code == 403
    r = client.put("/api/settings/fireworks", json={"kinds": {"dragon": False, "nope": True}, "colors": ["#ffe45c", "#bad"], "pace": "lively"})
    assert r.status_code == 200
    cfg = anon.get("/api/public/fireworks").json()
    assert cfg["kinds"]["dragon"] is False and "nope" not in cfg["kinds"]
    assert cfg["colors"] == ["#ffe45c"] and cfg["pace"] == "lively"
    assert client.put("/api/settings/fireworks", json={"colors": []}).status_code == 400
    assert client.put("/api/settings/fireworks", json={"kinds": {k: False for k in cfg["kinds"]}}).status_code == 400
    client.put("/api/settings/fireworks", json={"kinds": {"dragon": True}, "colors": list(dict.fromkeys(
        ["#ff5a4f", "#ffa13d", "#ffe45c", "#9be34a", "#4fd7e6", "#5d8bff", "#c46cf0", "#ff8fc0", "#ffffff", "#3fd1b0"])), "pace": "normal"})


def test_skins_from_mojang(client, anon, monkeypatch):
    from app import skins
    png = b"\x89PNG fake skin"
    calls = []

    async def fake_fetch(uuid):
        calls.append(uuid)
        return png if uuid.startswith("069a") else None
    monkeypatch.setattr(skins, "_fetch", fake_fetch)
    u = "069a79f4-44e9-4726-a5be-fca90e38aaf5"
    r = client.get(f"/api/skins/{u}.png")
    assert r.status_code == 200 and r.content == png
    assert client.get(f"/api/skins/{u}.png").content == png and len(calls) == 1      # cached on disk
    assert client.get("/api/skins/00000000000000000000000000000001.png").status_code == 404
    assert client.get("/api/skins/not-a-uuid.png").status_code == 404
    assert anon.get(f"/api/skins/{u}.png").status_code == 401


def test_skin_profile_parsing(monkeypatch):
    import asyncio
    import base64

    import httpx

    from app import skins
    tex = base64.b64encode(json.dumps({"textures": {"SKIN": {"url": "http://textures.minecraft.net/texture/abc"}}}).encode()).decode()

    def handler(req):
        if req.url.host == "sessionserver.mojang.com":
            return httpx.Response(200, json={"id": "x", "properties": [{"name": "textures", "value": tex}]})
        assert str(req.url) == "https://textures.minecraft.net/texture/abc"
        return httpx.Response(200, content=b"\x89PNGskin")
    real = httpx.AsyncClient
    monkeypatch.setattr(skins.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    assert asyncio.run(skins._fetch("069a79f444e94726a5befca90e38aaf5")) == b"\x89PNGskin"


def test_custom_firework_editor(client, viewer, anon):
    from app.fireworks import sanitize
    # Clamping and cleaning: nothing can escape the ranges.
    d = sanitize({"name": "  Big   one ", "pattern": "nope", "sparks": 99999, "life": -4, "colors": ["#ABCDEF", "red", "#123456"] * 3,
                  "gravity": "NaN", "picture": ["..0", "x1", "3.3"]})
    assert d["name"] == "Big one" and d["pattern"] == "ball" and d["sparks"] == 160 and d["life"] == 0.4
    assert d["colors"] == ["#abcdef", "#123456", "#abcdef", "#123456"] and d["gravity"] == 1.0
    assert d["picture"] == ["..0", "3.3"]
    assert sanitize({"pattern": "picture", "picture": ["...", "..."]})["pattern"] == "ball"   # empty picture

    # A viewer (the kids) can make fireworks; they land in the public show.
    r = viewer.post("/api/fireworks", json={"name": "Spidey", "pattern": "picture", "picture": [".0.", "000"], "colors": ["#ff0000"]})
    assert r.status_code == 200, r.text
    fid = r.json()["id"]
    assert r.json()["author"] == "kiddo" and r.json()["in_show"] is True
    pub = anon.get("/api/public/fireworks").json()["custom"]
    assert any(x["id"] == fid and x["picture"] == [".0.", "000"] for x in pub)
    assert anon.post("/api/fireworks", json={}).status_code == 401

    # Only the maker or an admin can change or delete it.
    other = client.post("/api/fireworks", json={"name": "Admin's"}).json()
    assert viewer.put(f"/api/fireworks/{other['id']}", json={"name": "mine now"}).status_code == 403
    assert viewer.delete(f"/api/fireworks/{other['id']}").status_code == 403
    listed = {x["id"]: x for x in viewer.get("/api/fireworks").json()}
    assert listed[fid]["can_edit"] and not listed[other["id"]]["can_edit"]
    assert viewer.put(f"/api/fireworks/{fid}", json={"in_show": False, "size": 2}).json()["size"] == 2
    assert all(x["id"] != fid for x in anon.get("/api/public/fireworks").json()["custom"])
    assert client.put(f"/api/fireworks/{fid}", json={"name": "Renamed by admin"}).json()["name"] == "Renamed by admin"
    assert client.delete(f"/api/fireworks/{fid}").json() == {"ok": True}
    assert client.delete(f"/api/fireworks/{other['id']}").status_code == 200
    assert client.get(f"/api/fireworks/{fid}").status_code in (404, 405)


def test_firework_stages_launches_and_frames():
    from app.fireworks import MAX_STAGES, sanitize
    d = sanitize({"launch": "wheel", "rocket_style": "corkscrew", "mirror": 1, "rockets": 40, "interval": 0, "hang": 9,
                  "picture": ["0"], "picture2": ["1.", "bad!"], "pattern": "picture",
                  "stages": [{"action": "implode", "pattern": "picture", "delay": 99, "sparks": 3, "colors": ["#FFFFFF", "nope"]}] * 5})
    assert d["launch"] == "wheel" and d["rocket_style"] == "corkscrew" and d["mirror"] is True
    assert d["rockets"] == 12 and d["interval"] == 0.05 and d["hang"] == 3
    assert d["picture2"] == ["1."] and len(d["stages"]) == MAX_STAGES
    st = d["stages"][0]
    assert st == {"action": "implode", "pattern": "ball", "delay": 4, "size": 0.8, "sparks": 8, "colors": ["#ffffff"], "sound": "auto"}
    assert sanitize({"launch": "cannon", "rocket_style": "laser"})["launch"] == "rocket"
