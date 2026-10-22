"""Per-step sounds on "then…" steps and the shape of "burst again" pieces survive saving."""
from app import fireworks


def test_stage_sound_and_second_pattern():
    d = fireworks.sanitize({"second": 0.5, "second_pattern": "star", "stages": [
        {"action": "burst", "sound": "crack"}, {"action": "shatter", "sound": "custom", "sfx": {"wave": "noise", "freq": 900}},
        {"action": "implode", "sound": "laser"}]})
    assert d["second_pattern"] == "star"
    assert [st["sound"] for st in d["stages"]] == ["crack", "custom", "auto"]
    assert d["stages"][1]["sfx"]["wave"] == "noise" and "sfx" not in d["stages"][0]
    assert fireworks.sanitize({"second_pattern": "picture"})["second_pattern"] == "ball"


def test_collections_and_the_per_person_limit():
    import pytest

    from app import settings_store
    settings_store.save_section("custom_fireworks", [])
    settings_store.save_section("firework_limit", 2)
    try:
        a = fireworks.create({"name": "One", "group": "  Christmas   lights "}, "kid", fireworks.per_person())
        assert a["group"] == "Christmas lights"
        fireworks.create({"name": "Two"}, "kid", fireworks.per_person())
        with pytest.raises(ValueError, match="most each person can keep"):
            fireworks.create({"name": "Three"}, "kid", fireworks.per_person())
        fireworks.create({"name": "Admin's"}, "dad", None)                       # admins aren't limited
        assert fireworks.update(a["id"], {"group": "Halloween"})["group"] == "Halloween"
        assert fireworks.count_by("kid") == 2 and fireworks.set_per_person(0) == 0 and fireworks.per_person() == 0
        fireworks.create({"name": "Three"}, "kid", fireworks.per_person() or None)  # 0 means no limit
    finally:
        settings_store.save_section("custom_fireworks", [])
        settings_store.save_section("firework_limit", None)
