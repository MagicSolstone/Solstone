"""Screen-time limits, weekly digest and backup status."""
import os
import time
from pathlib import Path

import helpers
from app import db, notify


def test_screen_time_due():
    due = notify.screen_time_due({"gimli_jr": 7300, "tyler": 100}, {"gimli_jr": 120, "tyler": 60})
    assert due == [("gimli_jr", 7300, 120)]


def test_alert_once():
    assert db.alert_once("test:key") is True
    assert db.alert_once("test:key") is False


def test_week_stats_and_digest_text():
    sid, now = "digest-test", time.time()
    for player, start, end in (("Tyler", now - 7200, now - 3600), ("Gimli_Jr", now - 5400, now - 1800)):
        db.x("INSERT INTO sessions(server_id, player, start_ts, last_seen_ts, end_ts) VALUES (?,?,?,?,?)",
             (sid, player, start, end, end))
    db.add_event(sid, now - 4000, "death", "Gimli_Jr drowned", "Gimli_Jr")
    db.add_event(sid, now - 3900, "advancement", "Tyler has made the advancement [Diamonds!]", "Tyler")
    st = db.week_stats(sid)
    assert st["players"]["Tyler"]["seconds"] == 3600
    assert st["players"]["Gimli_Jr"]["deaths"] == 1
    assert st["together"]["seconds"] == 1800
    text = notify.digest_text([("Family Survival", st)])
    assert "Tyler: 1h 0m" in text and "1 advancement" in text
    assert "Played together most: Gimli_Jr & Tyler (30m)" in text


def test_digest_text_empty():
    assert notify.digest_text([("X", {"players": {}, "busiest_day": None, "together": None})]) == "Nobody played this week."


def test_limits_saved_and_validated(client):
    hdr = {}
    r = client.put("/api/settings/notifications", json={"limits": {"Gimli_Jr": 120, "Tyler": "abc", "Mom": 0},
                                                        "digest_enabled": True, "digest_day": 9, "digest_hour": 18}, headers=hdr).json()
    assert r["limits"] == {"gimli_jr": 120}
    assert r["digest_enabled"] is True and r["digest_day"] == 6


def test_digest_preview_and_players(client):
    assert "text" in client.post("/api/settings/notifications/digest").json()
    names = client.get("/api/players/all").json()
    assert names == sorted([p[0] for p in helpers.PLAYERS], key=str.lower)


def test_backup_status(client, sid):
    from app import backups
    folder = Path(os.environ["BACKUPS_DIR"]) / sid / "default"
    r = client.get(f"/api/servers/{sid}/backups").json()
    assert r["configured"] is False  # nothing mounted yet
    folder.mkdir(parents=True)
    old, new = folder / "old.zip", folder / "new.zip"
    old.write_bytes(b"x" * 10)
    new.write_bytes(b"y" * 20)
    os.utime(old, (time.time() - 5 * 86400,) * 2)
    os.utime(new, (time.time() - 3 * 3600,) * 2)
    (folder / "notes.txt").write_text("ignored")
    backups._cache.clear()
    r = client.get(f"/api/servers/{sid}/backups").json()
    assert r["found"] and r["count"] == 2 and r["latest"]["name"] == "new.zip"
    assert r["stale"] is False and r["total_bytes"] == 30
    os.utime(new, (time.time() - 3 * 86400,) * 2)
    backups._cache.clear()
    assert client.get(f"/api/servers/{sid}").json()["backup"]["stale"] is True
