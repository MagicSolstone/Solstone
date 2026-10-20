"""Game-event fireworks, the holiday calendar and the music playlist."""
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
    assert e["finale"] == {"on": True, "day": 13, "time": "20:00", "minutes": 30, "countdown": False}


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


def test_music_playlist(client, viewer, anon):
    from app import main
    assert viewer.post("/api/music?filename=a.mp3", content=b"ID3abc", headers={"Content-Type": "audio/mpeg"}).status_code == 403
    assert client.post("/api/music?filename=a.txt", content=b"hello", headers={"Content-Type": "text/plain"}).status_code == 415
    t1 = client.post("/api/music?filename=Song%20One.mp3", content=b"ID3" + b"x" * 5000, headers={"Content-Type": "audio/mpeg"}).json()
    t2 = client.post("/api/music?filename=two.ogg&title=Second", content=b"OggS" + b"y" * 100, headers={"Content-Type": "application/octet-stream"}).json()
    assert t1["title"] == "Song One" and t1["ext"] == "mp3" and t2["title"] == "Second" and t2["ext"] == "ogg"
    assert [t["id"] for t in viewer.get("/api/public/music").json()] == [t1["id"], t2["id"]]
    r = viewer.get(f"/api/public/music/{t1['id']}")
    assert r.status_code == 200 and r.content.startswith(b"ID3") and r.headers["content-type"] == "audio/mpeg"
    assert "content-encoding" not in r.headers
    assert anon.get("/api/public/music").status_code == 404                           # not public by default
    out = client.put("/api/music", json={"order": [t2["id"], t1["id"]], "titles": {t1["id"]: "Renamed"}, "public": True}).json()
    assert [t["title"] for t in out["tracks"]] == ["Second", "Renamed"] and out["public"] is True
    client.put("/api/settings/status", json={"enabled": True}); main._board_cache.clear()
    assert anon.get("/api/public/music").status_code == 200 and anon.get("/api/public/fireworks").json()["music"] is True
    client.put("/api/settings/status", json={"enabled": False})
    client.put("/api/music", json={"public": False})
    assert client.delete(f"/api/music/{t1['id']}").json() == {"ok": True}
    assert client.delete(f"/api/music/{t2['id']}").status_code == 200
    assert client.get("/api/public/music").json() == []
