"""Forgetting a player who has left for good: off Solstone's pages everywhere, guarded against accidents."""
import json
import time

from app import challenges, db, forget, settings_store

UUID = "00000000-0000-0000-0000-0000000000f1"


def _seed(sid):
    now = time.time()
    db.x("INSERT INTO sessions(server_id, player, uuid, start_ts, end_ts, last_seen_ts) VALUES (?,?,?,?,?,?)", (sid, "GoneKid", UUID, now - 7200, now - 3600, now - 3600))
    db.x("INSERT INTO sessions(server_id, player, uuid, start_ts, end_ts, last_seen_ts) VALUES (?,?,?,?,?,?)", (sid, "OldGoneKid", UUID, now - 99000, now - 98000, now - 98000))
    db.x("INSERT INTO sessions(server_id, player, uuid, start_ts, end_ts, last_seen_ts) VALUES (?,?,?,?,?,?)", (sid, "StaysKid", None, now - 7200, now - 3600, now - 3600))
    db.add_event(sid, now - 3000, "chat", "hello", "GoneKid", UUID)
    db.add_event(sid, now - 2900, "chat", "hi GoneKid", "StaysKid")
    db.x("INSERT INTO positions(server_id, ts, player, dim, x, y, z) VALUES (?,?,?,?,?,?,?)", (sid, now, "GoneKid", "minecraft:overworld", 1, 64, 2))
    db.x("INSERT INTO fish_catches(server_id, ts, player, species, name, quality, quality_name, weight, points) VALUES (?,?,?,?,?,?,?,?,?)",
         (sid, now, "GoneKid", "cod", "Cod", 1, "", 3.0, 4))
    recap = {"day": "2026-10-01", "players": [{"name": "GoneKid", "seconds": 600}, {"name": "StaysKid", "seconds": 300}], "total_seconds": 900,
             "deaths": [{"player": "GoneKid", "message": "GoneKid fell"}], "advancements": [], "newcomers": ["GoneKid"]}
    db.x("INSERT OR REPLACE INTO recaps(server_id, day, data, source, created_ts) VALUES (?,?,?,?,?)", (sid, "2026-10-01", json.dumps(recap), "test", now))
    challenges._save({"items": [{"id": "c1", "server": sid, "kind": "fish", "name": "Fishing", "state": "done", "start": now - 5000,
                                 "scores": {"GoneKid": 9, "StaysKid": 3}, "players": ["GoneKid", "StaysKid"], "winners": ["GoneKid"],
                                 "result": "GoneKid won Fishing with 9 fish!"}],
                      "gifts": [{"server": sid, "player": "GoneKid", "item": "minecraft:diamond", "count": 1, "why": "won", "at": now}]})
    settings_store.save_section("fw_signatures", {"gonekid": "x", "stayskid": "y"})


def test_forgetting_a_player(client, sid):
    _seed(sid)
    try:
        p = client.get("/api/players/forget?name=gonekid").json()
        assert p["uuid"] == UUID and set(p["names"]) == {"gonekid", "oldgonekid"}
        c = p["counts"]
        assert c["sessions"] == 2 and c["events"] == 1 and c["positions"] == 1 and c["fish"] == 1 and c["recaps"] == 1
        assert c["challenges"] == 1 and c["prizes_owed"] == 1 and c["join_firework"] == 1
        # the guards: name typed again exactly, and a server backup confirmed
        assert client.post("/api/players/forget", json={"name": "GoneKid", "confirm": "Gonekid", "backed_up": True}).status_code == 400
        assert client.post("/api/players/forget", json={"name": "GoneKid", "confirm": "GoneKid"}).status_code == 400
        assert db.q("SELECT COUNT(*) AS n FROM sessions WHERE player='GoneKid'")[0]["n"] == 1     # nothing happened yet
        r = client.post("/api/players/forget", json={"name": "GoneKid", "confirm": "GoneKid", "backed_up": True}).json()
        assert r["total"] >= 9
        assert not db.q("SELECT 1 FROM sessions WHERE uuid=? OR player IN ('GoneKid','OldGoneKid')", (UUID,))
        assert db.q("SELECT 1 FROM sessions WHERE player='StaysKid'") and db.q("SELECT 1 FROM events WHERE player='StaysKid'")
        assert not db.q("SELECT 1 FROM positions WHERE player='GoneKid'") and not db.q("SELECT 1 FROM fish_catches WHERE player='GoneKid'")
        rec = json.loads(db.q("SELECT data FROM recaps WHERE server_id=? AND day='2026-10-01'", (sid,))[0]["data"])
        assert [x["name"] for x in rec["players"]] == ["StaysKid"] and rec["total_seconds"] == 300 and not rec["deaths"] and not rec["newcomers"]
        c1 = challenges._load()["items"][0]
        assert c1["scores"] == {"StaysKid": 3} and c1["winners"] == [] and c1["result"] == "a former player won Fishing with 9 fish!"
        assert not challenges._load()["gifts"] and settings_store.load()["fw_signatures"] == {"stayskid": "y"}
        assert client.get("/api/players/forget?name=GoneKid").json()["total"] == 0
    finally:
        db.x("DELETE FROM sessions WHERE player IN ('GoneKid','OldGoneKid','StaysKid')")
        db.x("DELETE FROM events WHERE player IN ('GoneKid','StaysKid')")
        db.x("DELETE FROM recaps WHERE day='2026-10-01'")
        settings_store.save_section("challenges", {})
        settings_store.save_section("fw_signatures", {})


def test_not_while_they_are_playing(client, sid, monkeypatch):
    from app import servers as S

    async def online(_s):
        return ["GoneKid"], "rcon"
    monkeypatch.setattr(S, "online_players", online)
    _seed(sid)
    try:
        assert client.get("/api/players/forget?name=GoneKid").json()["online"]
        r = client.post("/api/players/forget", json={"name": "GoneKid", "confirm": "GoneKid", "backed_up": True})
        assert r.status_code == 409 and db.q("SELECT 1 FROM sessions WHERE player='GoneKid'")
        assert forget.plan("not a name!") is None
    finally:
        db.x("DELETE FROM sessions WHERE player IN ('GoneKid','OldGoneKid','StaysKid')")
        db.x("DELETE FROM events WHERE player IN ('GoneKid','StaysKid')")
        db.x("DELETE FROM positions WHERE player='GoneKid'")
        db.x("DELETE FROM fish_catches WHERE player='GoneKid'")
        db.x("DELETE FROM recaps WHERE day='2026-10-01'")
        settings_store.save_section("challenges", {})
        settings_store.save_section("fw_signatures", {})
