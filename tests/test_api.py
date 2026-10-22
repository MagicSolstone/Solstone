"""End-to-end API tests against the synthetic world (no Crafty, RCON unreachable)."""


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_server_discovered_from_folder(client, sid):
    servers = client.get("/api/servers").json()
    assert [s["id"] for s in servers] == [sid]
    s = servers[0]
    assert s["managed_by_crafty"] is False
    assert s["version"] == "1.21.10"
    assert s["loader"] == "Fabric"
    assert s["level_name"] == "Duluth Heights"
    assert s["has_icon"] is True
    assert s["rcon"]["configured"] is True  # read from server.properties


def test_server_icon(client, sid):
    r = client.get(f"/api/servers/{sid}/icon.png")
    assert r.status_code == 200 and r.content[:4] == b"\x89PNG"


def test_unknown_server_404(client):
    assert client.get("/api/servers/nope").status_code == 404


def test_players_overview(client, sid):
    data = client.get(f"/api/servers/{sid}/players").json()
    names = {p["name"]: p for p in data["players"]}
    assert set(names) == {"Tyler", "Gimli_Jr", "MomCrafts"}
    tyler = names["Tyler"]
    assert tyler["op"] is True
    assert tyler["xp_level"] == 27
    assert tyler["advancements"] == 3  # recipe advancements are not counted
    assert tyler["headline"]["play_time"] == 72000 * 30
    assert tyler["position"]["dimension"] == "minecraft:overworld"
    assert names["Gimli_Jr"]["dimension"] == "minecraft:the_nether"


def test_player_detail_from_file(client, sid, tyler):
    p = client.get(f"/api/servers/{sid}/players/{tyler}").json()
    assert p["source"] == "file"  # nobody is online
    d = p["data"]
    inv = d["inventory"]
    sword = inv["hotbar"][0]
    assert sword["id"] == "minecraft:diamond_sword"
    assert sword["name"] == "Orcrist"
    assert {"id": "minecraft:sharpness", "level": 5} in sword["enchantments"]
    assert sword["max_damage"] == 1561 and sword["damage"] == 400
    shulker = inv["hotbar"][8]
    assert [c["id"] for c in shulker["contents"]] == ["minecraft:diamond", "minecraft:oak_stairs"]
    assert inv["armor"]["chest"]["id"] == "minecraft:diamond_chestplate"
    assert inv["armor"]["legs"]["color"] == 0x3366CC
    assert inv["offhand"]["id"] == "minecraft:shield"
    assert inv["main"][31 - 9]["id"] == "fancymod:ruby"
    assert len(d["ender_chest"]) == 2
    assert d["effects"][0]["id"] == "minecraft:speed"
    assert d["respawn"] == {"x": 100, "y": 70, "z": -200, "dimension": "minecraft:overworld"}
    assert p["stats"]["minecraft:killed"]["minecraft:zombie"] == 180


def test_unknown_player_404(client, sid):
    assert client.get(f"/api/servers/{sid}/players/00000000-0000-0000-0000-000000000000").status_code == 404


def test_world(client, sid):
    w = client.get(f"/api/servers/{sid}/world").json()
    assert w["seed"] == "-4172144997902289642"
    assert w["difficulty"] == "normal"
    assert w["spawn"]["x"] == 112
    assert w["raining"] is True
    assert w["game_rules"]["keepInventory"] == "true"
    dims = {d["id"]: d["chunks"] for d in w["dimensions"]}
    assert set(dims) == {"minecraft:overworld", "minecraft:the_nether", "minecraft:the_end"}
    assert all(c > 0 for c in dims.values())


def test_mods(client, sid):
    data = client.get(f"/api/servers/{sid}/mods").json()
    assert data["loader"] == "Fabric"
    assert [m["name"] for m in data["mods"]] == ["Fancy Gems", "Lithium", "Tide"]


def test_leaderboard(client, sid):
    rows = client.get(f"/api/servers/{sid}/leaderboard").json()["players"]
    best = max(rows, key=lambda r: r["mob_kills"])
    assert best["name"] == "Tyler"


def test_assets_and_icons(client, sid):
    assert client.get(f"/api/servers/{sid}/assets/status").json()["state"] == "ready"
    lang = client.get(f"/api/servers/{sid}/assets/lang").json()
    assert lang["item.minecraft.diamond_sword"] == "Diamond Sword"
    assert lang["item.fancymod.ruby"] == "Ruby"  # merged from the mod jar
    advs = client.get(f"/api/servers/{sid}/assets/advancements").json()
    assert {a["id"] for a in advs} >= {"minecraft:story/root", "minecraft:story/mine_diamond"}
    for item in ("minecraft/stone", "minecraft/oak_stairs", "minecraft/grass_block", "minecraft/diamond_sword",
                 "minecraft/shulker_box", "minecraft/leather_leggings", "fancymod/ruby"):
        r = client.get(f"/api/servers/{sid}/assets/item/{item}.png")
        assert r.status_code == 200, item
        assert r.content[:4] == b"\x89PNG"
    assert client.get(f"/api/servers/{sid}/assets/item/minecraft/not_a_real_item.png").status_code == 404


def test_texture_path_is_sanitised(client, sid):
    assert client.get(f"/api/servers/{sid}/assets/texture/mob_effect/speed.png").status_code == 200
    assert client.get(f"/api/servers/{sid}/assets/texture/../../../../etc/passwd").status_code == 404


def test_settings_require_admin(client, viewer, sid):
    url = f"/api/servers/{sid}/settings"
    assert viewer.put(url, json={"map_url": "http://map:8100"}).status_code == 403
    r = client.put(url, json={"map_url": "http://map:8100", "rcon_password": "secret", "bogus": 1})
    assert r.status_code == 200
    body = r.json()
    assert body["map_url"] == "http://map:8100"
    assert "rcon_password" not in body and body["rcon_password_set"] is True
    assert "bogus" not in body
    assert client.get(f"/api/servers/{sid}").json()["map_url"] == "http://map:8100"
    client.put(url, json={"map_url": "", "rcon_password": ""})


def test_spa_fallback(client):
    r = client.get("/s/whatever")
    assert r.status_code == 200 and "<title>Solstone</title>" in r.text
    assert client.get("/api/does-not-exist").status_code == 404


def test_one_leaderboard_list_for_app_and_status_page(client, anon, sid):
    from app import servers as S
    mine = client.get(f"/api/servers/{sid}/leaderboard").json()
    keys = [b["key"] for b in mine["boards"]]
    assert keys == [k for k, _t, _f in S.LEADERBOARDS] and len(keys) >= 20
    assert all(set(keys) <= set(p) for p in mine["players"])
    assert {b["kind"] for b in mine["boards"]} <= {"ticks", "count", "cm", "hearts", "grams"}         # all handled by hud.js fmtStat
    client.put("/api/settings/status", json={"enabled": True})
    try:
        public = anon.get(f"/api/public/leaderboard/{sid}").json()
        assert public["boards"] == mine["boards"]                    # same boards, same order, no drift
    finally:
        client.put("/api/settings/status", json={"enabled": False})
