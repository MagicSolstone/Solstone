"""Clearing what Solstone kept about a server (Manage → Servers): for a new world or a fresh start."""
import time

from app import db

OTHER = "clear-test-srv"          # its own rows, so the shared test server's history stays for the other tests


def test_clear_only_what_was_picked():
    now = time.time()
    db.add_event(OTHER, now - 5, "chat", "hello there", "Tyler")
    db.add_event(OTHER, now - 4, "death", "Tyler fell from a high place", "Tyler")
    db.x("INSERT INTO sessions (server_id, player, start_ts, last_seen_ts, end_ts) VALUES (?, 'Old_Kid', ?, ?, ?)", (OTHER, now - 900, now - 800, now - 800))
    db.x("INSERT INTO sessions (server_id, player, start_ts, last_seen_ts, end_ts) VALUES (?, 'On_Now', ?, ?, NULL)", (OTHER, now - 60, now))
    assert db.clear_server(OTHER, {"chat"}) == {"chat": 1}
    assert {e["type"] for e in db.events(OTHER, None, None, 50)} == {"death"}          # only chat went
    assert db.clear_server(OTHER, {"play", "activity"}) == {"activity": 1, "play": 1}
    assert [r["player"] for r in db.q("SELECT player FROM sessions WHERE server_id=?", (OTHER,))] == ["On_Now"]   # playing now stays
    db.x("DELETE FROM sessions WHERE server_id=?", (OTHER,))


def test_clearing_is_for_admins_and_needs_a_pick(client, viewer, sid):
    assert viewer.post(f"/api/servers/{sid}/clear", json={"what": ["chat"]}).status_code == 403
    assert client.post(f"/api/servers/{sid}/clear", json={"what": []}).status_code == 400
    assert client.post(f"/api/servers/{sid}/clear", json={"what": ["world"]}).status_code == 400
    r = client.post(f"/api/servers/{sid}/clear", json={"what": ["map"]})
    assert r.status_code == 200 and "map" in r.json()["cleared"]
