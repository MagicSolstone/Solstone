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
