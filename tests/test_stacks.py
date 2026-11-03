"""An account's Minecraft names count as one player on leaderboards, the time-played chart and the daily recap."""
from app import auth, stacks


def test_linked_names_stack_under_the_main_name():
    u = auth.create_user("stacker", "long-enough-1", "player", check=False)
    auth.add_player(u.id, ("00000000-0000-0000-0000-0000000000b1", "JavaKid"))
    auth.add_player(u.id, ("00000000-0000-0000-0000-0000000000b2", ".BedrockKid"))
    auth.set_main_player(u.id, "00000000-0000-0000-0000-0000000000b2")
    try:
        lb = {"boards": [{"key": "mob_kills"}, {"key": "xp_level"}],
              "players": [{"uuid": "a", "name": "JavaKid", "mob_kills": 10, "xp_level": 30},
                          {"uuid": "b", "name": ".BedrockKid", "mob_kills": 5, "xp_level": 12},
                          {"uuid": "c", "name": "Other", "mob_kills": 7, "xp_level": 3}]}
        rows = {r["name"]: r for r in stacks.leaderboard(lb)["players"]}
        assert set(rows) == {".BedrockKid", "Other"}                                     # the main name, once
        kid = rows[".BedrockKid"]
        assert kid["mob_kills"] == 15 and kid["xp_level"] == 30 and kid["also"] == ["JavaKid"]   # kills added, the best level
        assert kid["uuid"] == "00000000-0000-0000-0000-0000000000b2" and "also" not in rows["Other"]
        days = stacks.daily([{"date": "2026-11-01", "players": {"JavaKid": 600, ".BedrockKid": 300, "Other": 60}}])
        assert days[0]["players"] == {".BedrockKid": 900, "Other": 60}
        r = stacks.recap({"players": [{"name": "JavaKid", "seconds": 600, "first": 50}, {"name": "Other", "seconds": 700, "first": 10},
                                      {"name": ".BedrockKid", "seconds": 300, "first": 20}]})
        assert [(p["name"], p["seconds"], p["first"]) for p in r["players"]] == [(".BedrockKid", 900, 20), ("Other", 700, 10)]
    finally:
        auth.delete_user(u.id)
    assert stacks.stacks() == {} or "javakid" not in stacks.stacks()


def test_player_page_all_together(client, sid):
    from app import servers as S
    u = auth.create_user("together_kid", "long-enough-1", "player", check=False)
    tyler, gimli = "069a79f4-44e9-4726-a5be-fca90e38aaf5", "853c80ef-3c37-49fd-aa49-938b674adae6"
    auth.add_player(u.id, (tyler, "Tyler"))
    auth.add_player(u.id, (gimli, "Gimli_Jr"))
    try:
        p = client.get(f"/api/servers/{sid}/players/{tyler}").json()
        t = p["together"]
        assert [a["name"] for a in t["accounts"]] == ["Tyler", "Gimli_Jr"]
        srv = S.registry.servers[sid]
        one, two = S.player_stats(srv, tyler), S.player_stats(srv, gimli)
        k = "minecraft:mob_kills"
        assert t["stats"]["minecraft:custom"].get(k, 0) == (one.get("minecraft:custom") or {}).get(k, 0) + (two.get("minecraft:custom") or {}).get(k, 0)
        mine, theirs = S.player_advancements(srv, tyler), S.player_advancements(srv, gimli)
        for key in {k for k, v in {**mine, **theirs}.items() if v["done"]}:
            assert t["advancements"][key]["done"] and t["advancements"][key]["by"] in ("Tyler", "Gimli_Jr")
        h = client.get(f"/api/servers/{sid}/players/{tyler}/history?together=1").json()
        assert h["names"] == ["Tyler", "Gimli_Jr"]
        assert client.get(f"/api/servers/{sid}/players/{tyler}/history").json()["names"] == ["Tyler"]
        assert client.get(f"/api/servers/{sid}/timeline?player=Tyler,Gimli_Jr").status_code == 200
    finally:
        auth.delete_user(u.id)
