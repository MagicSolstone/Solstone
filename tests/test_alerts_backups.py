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


def test_each_server_its_own_notifications(client, sid, monkeypatch):
    from app import notify
    sent = []

    async def fake_send(title, message, tag="video_game", force=False, sid=None, click=None, kind=""):
        sent.append((title, message, sid))
        return []
    try:
        client.put("/api/settings/notifications", json={"ntfy_url": "https://ntfy.example/t", "events": ["join"],
                                                         "servers": {sid: {"mode": "off"}, "other": {"mode": "own", "events": ["death", "blocked"],
                                                                     "quiet_enabled": True, "quiet_start": "00:00", "quiet_end": "23:59"}}})
        c = notify.get_config()
        assert notify.for_server(c, sid) is None                               # off: nothing from it
        assert notify.for_server(c, "other")["events"] == ["death", "blocked"]
        assert notify.for_server(c, "third")["events"] == ["join"]             # not set: same as everywhere
        assert notify._in_quiet_hours(notify.for_server(c, "other"))           # its own quiet hours
        assert client.get("/api/settings/notifications").json()["servers"][sid]["mode"] == "off"
    finally:
        client.put("/api/settings/notifications", json={"ntfy_url": "", "events": ["join"], "servers": {}})


def test_switches_added_later_start_on():
    from app import settings_store
    before = settings_store.load().get("notify", {})
    try:
        settings_store.save_section("notify", {"events": ["join"]})            # saved before these had a switch
        assert notify.get_config()["events"] == ["join", "requests", "fireworks", "screen_time"]
        notify.save_config({"events": ["join"]})                               # once saved here, an unticked one stays off
        assert notify.get_config()["events"] == ["join"]
    finally:
        settings_store.save_section("notify", before)


def test_notification_log_and_switches(client, viewer, monkeypatch):
    import asyncio

    import httpx

    class Resp:
        status_code, text = 200, ""
    posted = []

    async def fake_post(self, url, **kw):
        posted.append((url, kw))
        return Resp()
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    url = "/api/settings/notifications"
    try:
        client.delete(f"{url}/log")
        client.put(url, json={"ntfy_url": "https://ntfy.example/t", "events": ["requests"], "quiet_enabled": False, "servers": {}})
        asyncio.run(notify.send("Asking to join", "Tyler would like to join", "wave", click="https://x/app#/manage/whitelist", kind="requests"))
        asyncio.run(notify.send("Firework to look at", "a picture", "art", kind="fireworks"))         # switched off: not sent
        assert len(posted) == 1 and posted[0][1]["headers"]["Click"] == "https://x/app#/manage/whitelist"
        assert viewer.get(f"{url}/log").status_code == 403
        log = client.get(f"{url}/log").json()
        assert [e["kind"] for e in log["entries"]] == ["requests"]
        assert log["entries"][0]["status"] == "sent" and log["entries"][0]["to"] == ["ntfy"]
        assert log["counts"]["requests"] == {"day": 1, "week": 1, "month": 1}
        # quiet hours: held back, but in the log
        client.put(url, json={"quiet_enabled": True, "quiet_start": "00:00", "quiet_end": "23:59"})
        asyncio.run(notify.send("Asking to join", "again", "wave", kind="requests"))
        assert len(posted) == 1
        assert client.get(f"{url}/log").json()["entries"][0]["status"] == "quiet"
        assert viewer.delete(f"{url}/log").status_code == 403
        client.delete(f"{url}/log")
        assert client.get(f"{url}/log").json()["entries"] == []
    finally:
        client.put(url, json={"ntfy_url": "", "events": ["join"], "quiet_enabled": False, "servers": {}})
