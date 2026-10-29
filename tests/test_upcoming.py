"""Coming up: contests and the fireworks calendar's holidays and shows, in order."""
from datetime import datetime


def test_coming_up_lists_everything_in_order(monkeypatch):
    from app import challenges, db, settings_store, upcoming
    settings_store.save_section("challenges", {})
    settings_store.save_section("board", {"birthdays": [{"player": "Gimli_Jr", "month": 11, "day": 2}]})     # saved by an older version
    now = datetime(2026, 10, 22, 9, 0, tzinfo=db.tz())
    monkeypatch.setattr(challenges.time, "time", lambda: now.timestamp())     # contests can't start in the past
    c = challenges.create("s1", {"kind": "fish", "start": now.timestamp() + 86400 + 3600, "minutes": 10, "prize": {"item": "diamond"}})
    challenges.create("elsewhere", {"kind": "mobs", "start": now.timestamp() + 7200, "minutes": 10, "prize": {"item": "diamond"}})
    try:
        items = upcoming.items({"s1": "Family"}, now=now)
    finally:
        settings_store.save_section("challenges", {})
        settings_store.save_section("board", {})
    titles = [x["title"] for x in items]
    assert c["name"] in titles and "Monster hunt" not in titles                  # only servers that exist
    contest = next(x for x in items if x["title"] == c["name"])
    assert contest["server"] == "Family" and contest["date"] == "2026-10-23" and contest["link"] == "#/s/s1/challenges"
    assert not any("birthday" in x["title"] for x in items) and "birthdays" not in settings_store.load().get("board", {})
    assert any(x["title"] == "Halloween" for x in items) and any(x["title"] == "Halloween fireworks show" for x in items)
    assert [x["at"] for x in items] == sorted(x["at"] for x in items)              # nothing on right now, so all in date order
