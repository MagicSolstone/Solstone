"""Music: the external library (scan, tags/folders, covers), block and approve rules, playlists,
the scheduled radio, and who may stream what."""
import io
import math
import struct
import wave
from datetime import datetime

import pytest


def _wav(path, secs=1.0, freq=440):
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(8000)
        w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * freq * i / 8000))) for i in range(int(8000 * secs))))
    path.write_bytes(buf.getvalue())


@pytest.fixture()
def library(tmp_path, monkeypatch):
    from app import music
    from app.config import config
    root = tmp_path / "music"
    _wav(root / "C418" / "Volume Alpha" / "01 - Sweden.wav", 1.5)
    _wav(root / "C418" / "Volume Alpha" / "02 - Mice on Venus.wav", 1.0)
    _wav(root / "Loud Band" / "Shouting" / "Too Loud.wav", 0.5)
    (root / "C418" / "Volume Alpha" / "cover.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
    (root / "notes.txt").write_text("not music")
    monkeypatch.setattr(config, "music_library_dir", str(root))
    assert music.scan() == 3
    yield music
    monkeypatch.setattr(config, "music_library_dir", "")
    music._index.clear(); music._index.update({"tracks": {}, "scanned": 0, "root": ""})
    from app import settings_store
    settings_store.save_section("music_rules", {})
    settings_store.save_section("playlists", [])


def test_scan_reads_folders_and_lengths(library):
    music = library
    r = music.search("sweden")
    t = r["tracks"][0]
    assert r["total"] == 1 and t["title"] == "Sweden" and t["artist"] == "C418" and t["album"] == "Volume Alpha" and t["source"] == "external"
    assert 1.4 <= t["duration"] <= 1.6
    assert {a["album"] for a in music.albums()} == {"Volume Alpha", "Shouting"}
    assert {a["name"] for a in music.artists()} == {"C418", "Loud Band"}
    art = music.art_of(t)
    assert art is not None and str(art).endswith("cover.png")
    # unchanged files aren't re-read on the next scan
    assert music.scan() == 3


def test_block_and_approve(library, client, viewer):
    music = library
    loud = music.search("too loud")["tracks"][0]
    client.post("/api/music/rule", json={"action": "blocked", "kind": "artists", "value": "Loud Band", "on": True})
    assert music.search("too loud")["total"] == 0                                # gone for everyone
    assert viewer.get("/api/music/library?q=loud").json()["total"] == 0
    admin_view = client.get("/api/music/library?q=loud&status=blocked").json()
    assert admin_view["total"] == 1 and admin_view["tracks"][0]["status"] == "blocked"
    assert viewer.get(f"/api/public/music/{loud['id']}").status_code == 404        # can't be played anywhere
    assert client.get(f"/api/public/music/{loud['id']}").status_code == 404
    assert viewer.post("/api/music/rule", json={"action": "blocked", "kind": "tracks", "value": "x"}).status_code == 403
    client.post("/api/music/rule", json={"action": "blocked", "kind": "artists", "value": "loud band", "on": False})
    assert music.search("too loud")["total"] == 1

    # Only what I approve: external music hides until approved (album or artist or song).
    client.put("/api/music/settings", json={"mode": "approved"})
    assert viewer.get("/api/music/library?source=external").json()["total"] == 0
    alpha = next(a for a in music.albums(include_hidden=True) if a["album"] == "Volume Alpha")
    assert alpha["status"] == "unapproved"
    client.post("/api/music/rule", json={"action": "approved", "kind": "albums", "value": alpha["key"], "on": True})
    assert viewer.get("/api/music/library?source=external").json()["total"] == 2
    client.put("/api/music/settings", json={"mode": "all"})


def test_playlists_radio_and_streaming(library, client, viewer, anon, sid):
    music = library
    ids = [t["id"] for t in music.search("", source="external")["tracks"]]
    mine = viewer.post("/api/music/playlists", json={"name": "  Kid   mix ", "tracks": ids[:2], "schedule": {"on": True, "from": "01-01", "to": "12-31"}}).json()
    assert mine["name"] == "Kid mix" and mine["count"] == 2 and mine["schedule"]["on"] is False        # only admins schedule the radio
    assert client.get(f"/api/music/playlists/{mine['id']}").status_code == 200                       # admins see everything
    assert viewer.put(f"/api/music/playlists/{mine['id']}", json={"add": [ids[2]], "remove": [ids[0]]}).json()["tracks"] == [ids[1], ids[2]]

    # Christmas-style radio: an admin playlist with dates that include today takes over.
    today = datetime.now().strftime("%m-%d")
    xmas = client.post("/api/music/playlists", json={"name": "Holiday", "tracks": [ids[0]], "shared": True}).json()
    r = client.put(f"/api/music/playlists/{xmas['id']}", json={"schedule": {"on": True, "from": today, "to": today}}).json()
    assert r["schedule"] == {"on": True, "from": today, "to": today}
    radio = viewer.get("/api/public/music").json()
    assert radio["radio"]["name"] == "Holiday" and [t["id"] for t in radio["tracks"]] == [ids[0]]
    assert viewer.get("/api/music/queue?type=playlist&id=" + mine["id"]).json()["name"] == "Kid mix"

    # The public status page only ever gets the radio.
    client.put("/api/settings/status", json={"enabled": True})
    client.put("/api/music/settings", json={"public": True})
    try:
        assert [t["id"] for t in anon.get("/api/public/music").json()["tracks"]] == [ids[0]]
        assert anon.get(f"/api/public/music/{ids[0]}").status_code == 200
        assert anon.get(f"/api/public/music/{ids[2]}").status_code == 404
        assert anon.get(f"/api/public/music/{ids[0]}/art").status_code == 200
        assert anon.get("/api/music/library").status_code == 401
    finally:
        client.put("/api/music/settings", json={"public": False})
        client.put("/api/settings/status", json={"enabled": False})
    assert viewer.delete(f"/api/music/playlists/{xmas['id']}").status_code == 404                     # not theirs
    assert client.delete(f"/api/music/playlists/{xmas['id']}").json() == {"ok": True}
    assert viewer.delete(f"/api/music/playlists/{mine['id']}").json() == {"ok": True}


def test_radio_date_ranges():
    from datetime import date

    from app import music
    assert music._in_range(date(2026, 12, 20), "12-01", "12-26")[0]
    assert not music._in_range(date(2026, 11, 30), "12-01", "12-26")[0]
    assert music._in_range(date(2027, 1, 2), "12-20", "01-05")[0]          # over New Year
    assert music._clean_mmdd("2-30") == "" and music._clean_mmdd("2-29") == "02-29"
