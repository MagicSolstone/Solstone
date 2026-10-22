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
