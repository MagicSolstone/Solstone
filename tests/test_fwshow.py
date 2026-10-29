"""Game-event fireworks and the holiday calendar."""
from datetime import date, datetime


def test_calendar_dates():
    from app import fwshow
    assert fwshow.easter(2026) == date(2026, 4, 5) and fwshow.easter(2027) == date(2027, 3, 28)
    assert fwshow._nth(2026, 11, 3, 4) == date(2026, 11, 26)          # Thanksgiving
    assert fwshow._nth(2026, 5, 0, -1) == date(2026, 5, 25)           # Memorial Day (last Monday)


def test_today_state_themes_and_new_year_countdown():
    from app import db, fwshow
    zone = db.tz()
    xmas = fwshow.today_state(datetime(2026, 12, 25, 12, 0, tzinfo=zone))
    assert xmas["theme"]["id"] == "christmas" and "#3fbf5a" in xmas["theme"]["colors"]
    eve = fwshow.today_state(datetime(2026, 12, 31, 23, 30, tzinfo=zone))
    ny = next(f for f in eve["finales"] if f["id"] == "newyear")
    assert ny["countdown"] and datetime.fromtimestamp(ny["start"], zone) == datetime(2027, 1, 1, 0, 0, tzinfo=zone)
    assert fwshow.today_state(datetime(2026, 8, 12, 12, tzinfo=zone))["theme"] is None


def test_calendar_cleaning():
    from app import fwshow
    e = fwshow._clean_entry({"name": "x" * 99, "date": {"type": "nth", "month": 99, "weekday": 9, "n": 0}, "days": 40,
                             "colors": ["#FFFFFF", "nope"], "kinds": ["heart", "bogus", "custom:abc"],
                             "finale": {"on": 1, "time": "25:99", "day": 30, "minutes": 999}})
    assert len(e["name"]) == 40 and e["date"] == {"type": "nth", "month": 12, "weekday": 6, "n": 1} and e["days"] == 14
    assert e["colors"] == ["#ffffff"] and e["kinds"] == ["heart", "custom:abc"]
    assert e["finale"] == {"on": True, "day": 13, "show": "", "time": "20:00", "minutes": 30, "countdown": False}


def test_event_feed_and_settings(client, viewer, anon):
    from app import fwshow
    first = anon.get("/api/public/fireworks/feed").json()
    assert first["items"] == []
    last = first["last"]
    fwshow.push("s1", "Family", "challenge", "Tyler", "Tyler has completed the challenge [How Did We Get Here?]")
    fwshow.push("s1", "Family", "death", "Tyler", "Tyler fell")
    items = client.get(f"/api/public/fireworks/feed?since={last}").json()["items"]
    assert [i["show"] for i in items] == [{"kind": "showpiece", "count": 3}, {"kind": "dud", "count": 1}]
    assert items[0]["player"] == "Tyler"
    # Without the status page on, anonymous visitors don't get names.
    assert all(i["player"] is None and i["text"] == "" for i in anon.get(f"/api/public/fireworks/feed?since={last}").json()["items"])

    assert viewer.get("/api/fireworks/show").status_code == 403
    show = client.get("/api/fireworks/show").json()
    assert show["events"]["join"]["firework"] == "signature" and len(show["calendar"]) >= 8
    d = client.post("/api/fireworks", json={"name": "Tyler's", "colors": ["#ff0000"], "in_show": False}).json()
    r = client.put("/api/fireworks/show", json={"events": {"death": {"on": False}, "level": {"every": 5}}, "signatures": {"Tyler": d["id"], "bad name!": "x"}})
    assert r.json()["events"]["death"]["on"] is False and r.json()["events"]["level"]["every"] == 5
    assert r.json()["signatures"] == {"tyler": d["id"]}
    last = client.get("/api/public/fireworks/feed").json()["last"]
    assert client.post("/api/fireworks/test-event", json={"event": "join", "player": "Tyler"}).json() == {"ok": True}
    fwshow.push("s1", "Family", "death", "Tyler", "Tyler fell")                     # turned off: nothing
    items = client.get(f"/api/public/fireworks/feed?since={last}").json()["items"]
    assert len(items) == 1 and items[0]["show"]["design"]["name"] == "Tyler's"       # signature, even though not in the show
    client.put("/api/fireworks/show", json={"events": {"death": {"on": True}, "level": {"every": 10}}, "signatures": {}})
    client.delete(f"/api/fireworks/{d['id']}")


def test_frequencies_for_kinds_people_and_designs(client, viewer, anon):
    cfg = anon.get("/api/public/fireworks").json()
    assert cfg["weights"]["ball"] == 2 and cfg["weights"]["star"] == 1
    r = client.put("/api/settings/fireworks", json={"weights": {"star": 4, "ring": 0, "heart": 0.7, "nope": 3}}).json()
    assert r["weights"]["star"] == 4 and r["weights"]["ring"] == 0 and r["weights"]["heart"] == 0.5
    assert r["kinds"]["ring"] is False and "nope" not in r["weights"]
    client.put("/api/settings/fireworks", json={"weights": {"star": 1, "ring": 1, "heart": 1}})

    kid = viewer.post("/api/fireworks", json={"name": "Kid one", "in_show": True}).json()
    mine = client.post("/api/fireworks", json={"name": "Admin one", "in_show": True}).json()
    # Makers can't set how often their own firework shows; admins can.
    assert viewer.put(f"/api/fireworks/{kid['id']}", json={"weight": 4}).json().get("weight", 1) == 1
    assert client.put(f"/api/fireworks/{kid['id']}", json={"weight": 2}).json()["weight"] == 2
    show = {d["id"]: d for d in anon.get("/api/public/fireworks").json()["custom"]}
    assert show[kid["id"]]["weight"] == 2 and show[mine["id"]]["weight"] == 1
    # A maker set to Off takes all of theirs out; Often doubles them.
    client.put("/api/fireworks/show", json={"creators": {"kiddo": 0, "admin": 2}})
    show = {d["id"]: d for d in anon.get("/api/public/fireworks").json()["custom"]}
    assert kid["id"] not in show and show[mine["id"]]["weight"] == 2
    creators = {c["name"]: c for c in client.get("/api/fireworks/show").json()["creators"]}
    assert creators["kiddo"]["weight"] == 0 and creators["kiddo"]["designs"] >= 1
    client.put("/api/fireworks/show", json={"creators": {"kiddo": 1, "admin": 1}})
    client.delete(f"/api/fireworks/{kid['id']}"); client.delete(f"/api/fireworks/{mine['id']}")


def test_shows_base_shows_and_links(client, viewer, anon):
    from app import fwshow
    show = client.get("/api/fireworks/show").json()
    assert any(s["id"] == "grand-finale" for s in show["shows"]) and show["base_shows"] == {"day": "", "night": ""}
    d = client.post("/api/fireworks", json={"name": "Mine", "in_show": False}).json()
    shows = show["shows"] + [{"name": "Test show", "steps": [{"at": 5, "what": f"custom:{d['id']}", "count": 99, "where": "nowhere"},
                                                            {"at": -3, "what": "bogus", "count": 2, "where": "sides"}]}]
    r = client.put("/api/fireworks/show", json={"shows": shows, "base_shows": {"night": "grand-finale"}}).json()
    mine = next(s for s in r["shows"] if s["name"] == "Test show")
    assert mine["steps"] == [{"at": 0, "what": "random", "count": 2, "where": "sides"},
                             {"at": 5, "what": f"custom:{d['id']}", "count": 12, "where": "random"}]
    pub = anon.get("/api/public/fireworks").json()
    assert pub["base_shows"]["night"]["id"] == "grand-finale" and pub["base_shows"]["day"] is None
    # Events can play a show; editor fireworks in it travel with it.
    client.put("/api/fireworks/show", json={"events": {"challenge": {"firework": f"show:{mine['id']}"}}})
    last = client.get("/api/public/fireworks/feed").json()["last"]
    fwshow.push("s1", "Family", "challenge", "Tyler", "x")
    play = client.get(f"/api/public/fireworks/feed?since={last}").json()["items"][0]["show"]["play"]
    assert play["steps"][1]["design"]["name"] == "Mine"
    assert viewer.put("/api/fireworks/show", json={"shows": []}).status_code == 403
    client.put("/api/fireworks/show", json={"events": {"challenge": {"firework": "showpiece"}}, "base_shows": {"night": ""},
                                           "shows": [s for s in r["shows"] if s["name"] != "Test show"]})
    client.delete(f"/api/fireworks/{d['id']}")


def test_sky_and_player_skins(client, viewer, anon):
    sky = anon.get("/api/public/sky").json()
    assert sky["mode"] in ("game", "night")
    if sky["mode"] == "game":
        assert 0 <= sky["time_of_day"] < 24000 and 0 <= sky["moon"] < 8 and isinstance(sky["raining"], bool)
    client.put("/api/settings/fireworks", json={"sky": {"mode": "night"}})
    assert anon.get("/api/public/sky").json() == {"mode": "night"}
    cfg = client.put("/api/settings/fireworks", json={"sky": {"mode": "game", "daytime": "pause", "bogus": 1}}).json()["sky"]
    assert cfg == {"mode": "game", "server": "auto", "daytime": "pause"}
    client.put("/api/settings/fireworks", json={"sky": {"daytime": "smoke"}})
    skins = viewer.get("/api/players/skins").json()
    assert skins and {"name", "uuid"} <= set(skins[0])
    assert anon.get("/api/players/skins").status_code == 401


def test_custom_sounds_are_cleaned(client):
    from app import fireworks
    d = fireworks.sanitize({"sound_launch": "custom", "sound_burst": "custom",
                            "sfx_launch": {"wave": "laser", "freq": 99999, "repeat": 3.6, "attack": 1, "sustain": 2, "decay": 3, "bogus": 1},
                            "sfx_burst": "nope"})
    s = d["sfx_launch"]
    assert s["wave"] == "noise" and s["freq"] == 5000 and s["repeat"] == 4 and "bogus" not in s
    assert round(s["attack"] + s["sustain"] + s["decay"], 2) <= 5.0
    assert d["sfx_burst"]["volume"] == 0.6                       # junk -> defaults
    plain = fireworks.sanitize({"sound_burst": "pop", "sfx_burst": {"freq": 100}})
    assert "sfx_burst" not in plain and "sfx_launch" not in plain   # only kept when used
    r = client.post("/api/fireworks", json={"name": "Synth", "sound_burst": "custom", "sfx_burst": {"wave": "square", "duty": 0.25}}).json()
    assert r["sfx_burst"]["wave"] == "square" and r["sfx_burst"]["duty"] == 0.25
    client.delete(f"/api/fireworks/{r['id']}")


def test_ground_sounds_and_sound_library(client, viewer, anon):
    from app import fireworks
    g = fireworks.sanitize({"launch": "fountain", "sound_ground": "custom", "sfx_ground": {"wave": "sine", "repeat": 2}})
    assert g["sound_ground"] == "custom" and g["sfx_ground"]["wave"] == "sine"
    assert fireworks.sanitize({"sound_ground": "kazoo"})["sound_ground"] == "hiss"
    assert anon.get("/api/sounds").status_code == 401
    s = viewer.post("/api/sounds", json={"name": "  Big   boom ", "sfx": {"wave": "noise", "decay": 9}}).json()
    assert s["name"] == "Big boom" and s["author"] == "kiddo" and s["sfx"]["decay"] <= 3
    listed = client.get("/api/sounds").json()
    assert any(x["id"] == s["id"] and x["can_delete"] for x in listed)                      # admins can remove anyone's
    assert not next(x for x in viewer.get("/api/sounds").json() if x["id"] == s["id"])["can_delete"] is False
    other = client.post("/api/sounds", json={"name": "Admin's", "sfx": {}}).json()
    assert viewer.delete(f"/api/sounds/{other['id']}").status_code == 404                     # not theirs
    assert viewer.delete(f"/api/sounds/{s['id']}").json() == {"ok": True}
    assert client.delete(f"/api/sounds/{other['id']}").json() == {"ok": True}
    assert client.get("/api/sounds").json() == []


def test_makers_only_for_people_signed_in(client, anon):
    d = client.post("/api/fireworks", json={"name": "Maker test", "in_show": True}).json()
    try:
        pub = next(x for x in anon.get("/api/public/fireworks").json()["custom"] if x["id"] == d["id"])
        assert "author" not in pub and "maker" not in pub                 # no public list of who's on the server
        mine = next(x for x in client.get("/api/public/fireworks").json()["custom"] if x["id"] == d["id"])
        assert mine["mine"] is True and mine["maker"]
    finally:
        client.delete(f"/api/fireworks/{d['id']}")


def test_players_pick_their_own_join_firework(client):
    from fastapi.testclient import TestClient

    from app import fwshow, main
    u = client.post("/api/users", json={"username": "fw_player", "password": "player-pass-1", "role": "player"}).json()
    d = client.post("/api/fireworks", json={"name": "My entrance", "in_show": True}).json()
    try:
        c = TestClient(main.app, headers={"X-Solstone": "1"})
        c.post("/api/auth/login", json={"username": "fw_player", "password": "player-pass-1"})
        assert c.put("/api/fireworks/my-join", json={"firework": d["id"]}).status_code == 400    # no Minecraft account yet
        client.patch(f"/api/users/{u['id']}", json={"player": "Tyler"})
        assert c.put("/api/fireworks/my-join", json={"firework": "nope"}).status_code == 404
        r = c.put("/api/fireworks/my-join", json={"firework": d["id"]}).json()
        assert r["firework"] == d["id"] and r["players"] == ["Tyler"]
        assert fwshow.signatures()["tyler"] == d["id"]
        assert c.put("/api/fireworks/my-join", json={"firework": ""}).json()["firework"] == ""   # back to random
        assert "tyler" not in fwshow.signatures()
    finally:
        client.delete(f"/api/users/{u['id']}")
        client.delete(f"/api/fireworks/{d['id']}")


def test_in_the_show_limit(client, viewer):
    """Keep up to the keep limit, but only so many in the show at once (admins: no limit)."""
    client.put("/api/fireworks/limit", json={"show_per_person": 2})
    made = []
    try:
        for n in range(3):
            made.append(viewer.post("/api/fireworks", json={"name": f"Kid {n}", "in_show": True}).json())
        assert [d["in_show"] for d in made] == [True, True, False] and made[2].get("show_full")
        r = viewer.put(f"/api/fireworks/{made[2]['id']}", json={"in_show": True})
        assert r.status_code == 400 and "in the show" in r.json()["detail"]
        saved = viewer.put(f"/api/fireworks/{made[2]['id']}", json={"name": "Kid 2b", "in_show": True}).json()
        assert saved["name"] == "Kid 2b" and saved["in_show"] is False and saved["show_full"]     # changes kept
        viewer.put(f"/api/fireworks/{made[0]['id']}", json={"in_show": False})
        assert viewer.put(f"/api/fireworks/{made[2]['id']}", json={"in_show": True}).status_code == 200
        lim = viewer.get("/api/fireworks/limit").json()
        assert lim["show_per_person"] == 2 and lim["mine_in_show"] == 2
    finally:
        client.put("/api/fireworks/limit", json={"show_per_person": 5})
        for d in made:
            client.delete(f"/api/fireworks/{d['id']}")
