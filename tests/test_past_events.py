"""Events that finished in the last few days stay on the Events page with how they went, never who."""
import time

from app import challenges, games, races, upcoming


def test_past_events_how_they_went_no_names(monkeypatch):
    now = time.time()
    monkeypatch.setattr(challenges, "_load", lambda: {"items": [
        {"state": "done", "kind": "mobs", "name": "Monster hunt", "scores": {"Alex": 12, "Sam": 30, "Kim": 0}, "ends_at": now - 3600, "server": "s1"},
        {"state": "done", "kind": "mobs", "name": "Old one", "scores": {"Alex": 3}, "ends_at": now - 10 * 86400, "server": "s1"},
        {"state": "skipped", "kind": "mobs", "name": "Didn't run", "ends_at": now - 60, "server": "s1"}], "gifts": []})
    monkeypatch.setattr(races, "_load", lambda: {"courses": [], "runs": [
        {"state": "done", "name": "Elytra dash", "results": [{"name": "Alex", "finished": 72}, {"name": "Sam", "finished": None}],
         "ends_at": now - 7200, "server": "s1"}]})
    monkeypatch.setattr(games, "_load", lambda: {"runs": [
        {"state": "done", "game": "arena", "name": "Mob arena", "coop": True, "waves": [{}, {}], "survived": 2,
         "players": {"Alex": {"kills": 9}}, "ended": now - 60, "server": "s1"}]})
    past = upcoming.past({"s1": "Family"}, now=now)
    assert [p["title"] for p in past] == ["Mob arena", "Monster hunt", "Elytra dash"]          # newest first, recent only
    assert past[0]["how"] == "Survived all 2 waves · 1 player"
    assert past[1]["how"] == "2 took part · best 30 monsters"
    assert past[2]["how"] == "2 racers · 1 finished · fastest 1:12"
    assert not any(n in str(past) for n in ("Alex", "Sam", "Kim"))                             # never who


def test_how_long_past_events_stay_is_an_admin_setting(monkeypatch):
    from app import site
    now = time.time()
    monkeypatch.setattr(challenges, "_load", lambda: {"items": [
        {"state": "done", "kind": "mobs", "name": "Last week", "scores": {"Alex": 3}, "ends_at": now - 6 * 86400, "server": "s1"}], "gifts": []})
    monkeypatch.setattr(races, "_load", lambda: {"courses": [], "runs": []})
    monkeypatch.setattr(games, "_load", lambda: {"runs": []})
    saved = site.config().get("past_days")
    try:
        assert site.config()["past_days"] == 3 and upcoming.past({"s1": "Family"}, now=now) == []      # 3 days to start
        site.save_config({"past_days": 7})
        assert [p["title"] for p in upcoming.past({"s1": "Family"}, now=now)] == ["Last week"]
        site.save_config({"past_days": 0})
        assert upcoming.past({"s1": "Family"}, now=now) == []                                          # off
        site.save_config({"past_days": 999})
        assert site.config()["past_days"] == 30                                                        # at most a month
    finally:
        site.save_config({"past_days": saved if saved is not None else 3})
