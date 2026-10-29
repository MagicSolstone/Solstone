"""Events: a named lineup of contests, races and games, one after another, kept in step and brought back each week."""
import time

import pytest

from app import challenges, community, eventgroups, races, settings_store, upcoming

FISH = {"kind": "fish", "minutes": 5, "prize": {"item": "diamond", "count": 1}}


@pytest.fixture(autouse=True)
def clean():
    for sec in ("challenges", "races", "games", "eventgroups"):
        settings_store.save_section(sec, {})
    yield
    for sec in ("challenges", "races", "games", "eventgroups"):
        settings_store.save_section(sec, {})


def _contests():
    return sorted(challenges._load()["items"], key=lambda c: c["start"])


def test_lineup_made_in_order_and_shown_as_one_event():
    t = time.time() + 3600
    g = eventgroups.create("s1", {"title": "Fishing Fridays", "desc": "Bring a rod!", "start": t, "gap": 2, "repeat": "weekly",
                                  "items": [{"type": "contest", "body": {**FISH, "name": "Warm-up"}, "note": "Any fish counts"}]})
    g = eventgroups.add_items("s1", g["id"], {"type": "contest", "body": {**FISH, "kind": "fish_points"}, "count": 2})
    cs = _contests()
    assert [round(c["start"] - t) for c in cs] == [0, 420, 840] and all(c["group"] == g["id"] and c["optin"] for c in cs)
    assert all(c["repeat"] == "" for c in cs)                          # the event repeats, not each contest
    assert [p["title"] for p in g["parts"]] == ["Warm-up", "Fishing tournament", "Fishing tournament"] and g["parts"][0]["note"] == "Any fish counts"
    assert all(p["exact"] for p in g["parts"]) and round(g["end"] - t) == 1140
    # one card on Events (and the next weeks'), not three contests of their own
    items = upcoming.items({"s1": "Family"})
    ev = [i for i in items if i["kind"] == "event"]
    assert not [i for i in items if i["kind"] == "contest"]
    assert ev[0]["title"] == "Fishing Fridays" and ev[0]["detail"] == "Bring a rod!" and len(ev[0]["parts"]) == 3 and len(ev) >= 4
    assert ev[0]["parts"][1]["key"] == community.item_key("contest", "x", cs[1])      # "I'm coming!" matches the game's joining
    assert ev[1]["parts"][1]["key"] != ev[0]["parts"][1]["key"] and abs(ev[1]["at"] - t - 7 * 86400) < 1


def test_changing_the_lineup_and_the_event():
    t = time.time() + 3600
    g = eventgroups.create("s1", {"title": "Night", "start": t, "gap": 2, "items": [{"type": "contest", "body": FISH}] * 3})
    a, b, c = (p["id"] for p in g["parts"])
    g = eventgroups.change_item("s1", g["id"], b, {"body": {"prize": {"item": "emerald", "count": 4}}, "note": "Big prize"})
    by = {x["gitem"]: x for x in challenges._load()["items"]}
    assert by[b]["prize"]["item"] == "minecraft:emerald" and by[a]["prize"]["item"] == "minecraft:diamond" and len(by) == 3
    g = eventgroups.change_item("s1", g["id"], c, {"step": -1})                    # c before b
    assert [p["id"] for p in g["parts"]] == [a, c, b]
    assert round({x["gitem"]: x for x in challenges._load()["items"]}[c]["start"] - t) == 420
    g = eventgroups.change_item("s1", g["id"], a, {"copy": True})
    assert len(g["parts"]) == 4 and len(challenges._load()["items"]) == 4
    g = eventgroups.change_item("s1", g["id"], a, {"remove": True})
    assert len(g["parts"]) == 3 and a not in {x["gitem"] for x in challenges._load()["items"]}
    g = eventgroups.update("s1", g["id"], {"start": t + 600, "gap": 5, "title": "Big night", "desc": "Line one\nLine two"})
    assert round(_contests()[0]["start"] - t) == 600 and round(_contests()[1]["start"] - _contests()[0]["start"]) == 600
    assert g["title"] == "Big night" and g["desc"] == "Line one\nLine two"
    with pytest.raises(ValueError):
        eventgroups.add_items("s1", g["id"], {"type": "contest", "body": {"kind": "nope"}})
    assert eventgroups.remove("s1", g["id"]) and challenges._load()["items"] == []      # called off: nothing left to start


def test_after_a_race_the_next_one_waits_for_it_to_end():
    course = races.save_course("s1", {"name": "Loop", "points": [{"x": 0, "y": 64, "z": 0}, {"x": 20, "y": 64, "z": 0}, {"x": 40, "y": 64, "z": 0}]})
    t = time.time() + 600
    g = eventgroups.create("s1", {"title": "Mixed", "start": t, "gap": 2, "items": [
        {"type": "race", "body": {"course": course["id"], "minutes": 10}}, {"type": "contest", "body": FISH}]})
    assert [p["exact"] for p in g["parts"]] == [True, False]                       # after a race: an estimate
    assert g["parts"][0]["title"] == "Loop race"
    now = t + 30 * 60                                                                 # the race ran long
    d = races._load()
    d["runs"][0].update(state="running", started_at=t, ends_at=t + 600)
    races._save(d)
    eventgroups.tick(now)
    assert _contests()[0]["start"] >= now + 120                                       # still waiting for it
    d = races._load()
    d["runs"][0]["state"] = "done"
    races._save(d)
    eventgroups.tick(now + 60)
    assert abs(_contests()[0]["start"] - (now + 60 + 120)) < 1                       # two minutes after it actually ended


def test_a_weekly_event_comes_back_when_its_over(client, sid):
    t = time.time() + 3600
    g = client.post(f"/api/servers/{sid}/eventgroups", json={"title": "Fishing Fridays", "start": t, "gap": 2, "repeat": "weekly"}).json()
    client.post(f"/api/servers/{sid}/eventgroups/{g['id']}/items", json={"type": "contest", "body": FISH, "count": 2})
    assert len(client.get(f"/api/servers/{sid}/eventgroups").json()["groups"][0]["parts"]) == 2
    d = challenges._load()
    for c in d["items"]:
        c.update(state="done", ends_at=c["start"] + 300)
    challenges._save(d)
    eventgroups.tick()
    gs = eventgroups._load()["groups"]
    assert [x["state"] for x in gs] == ["done", "scheduled"] and abs(gs[1]["start"] - t - 7 * 86400) < 1
    nxt = [c for c in challenges._load()["items"] if c["state"] == "scheduled"]
    assert len(nxt) == 2 and all(c["group"] == gs[1]["id"] for c in nxt)
    assert client.delete(f"/api/servers/{sid}/eventgroups/{gs[1]['id']}").json() == {"ok": True}
    assert client.post(f"/api/servers/{sid}/eventgroups", json={"title": ""}).status_code == 400
