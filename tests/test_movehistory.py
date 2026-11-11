"""Moving a server's history to another (a server moved to a game host is a new server to Solstone): every kind moves,
an event both have is kept once, the days both have are worked out again from the two together, a backup comes first."""
import json
from datetime import datetime

from app import db, movehistory, selfbackup, serverstats


def _clear(*sids):
    movehistory._ensure()
    for t, _l in movehistory.TABLES:
        db.x(f"DELETE FROM {t} WHERE server_id IN ({','.join('?' * len(sids))})", sids)


def _day(ts):
    return datetime.fromtimestamp(ts, db.tz()).date().isoformat()


def test_a_servers_history_moves_to_another_and_shared_days_are_put_together(client):
    home, far = "mv-home", "mv-far"
    _clear(home, far)
    now = datetime.now(db.tz()).replace(hour=12, minute=0, second=0, microsecond=0).timestamp()   # (midday: no session crosses midnight)
    old = now - 40 * 86400                                                   # only home has this day
    for sid, start in ((home, old), (home, now - 3600), (far, now - 7200)):
        db.x("INSERT INTO sessions(server_id, player, uuid, start_ts, last_seen_ts, end_ts) VALUES (?,?,?,?,?,?)",
             (sid, "Ann", "u-1", start, start + 1800, start + 1800))
    db.x("INSERT INTO events(server_id, ts, type, player, message) VALUES (?,?,?,?,?)", (home, old, "join", "Ann", "Ann joined"))
    for sid in (home, far):                                                  # the same moment, seen by both
        db.x("INSERT INTO events(server_id, ts, type, player, message) VALUES (?,?,?,?,?)", (sid, now - 600, "chat", "Ann", "hi"))
    db.x("INSERT INTO stat_tally(server_id, ts, player, travelled, advancements, deaths) VALUES (?,?,?,?,?,?)", (home, now - 3000, "Ann", 300, 1, 0))
    db.x("INSERT INTO stat_tally(server_id, ts, player, travelled, advancements, deaths) VALUES (?,?,?,?,?,?)", (far, now - 5000, "Ann", 200, 0, 1))
    db.x("INSERT INTO positions(server_id, ts, player, dim, x, y, z) VALUES (?,?,?,?,?,?,?)", (home, old, "Ann", "minecraft:overworld", 1, 2, 3))
    db.x("INSERT INTO metrics(server_id, ts, running, players) VALUES (?,?,?,?)", (home, old, 1, 1))
    for sid, ts in ((home, old), (home, now), (far, now)):
        db.x("INSERT OR REPLACE INTO daily_stats(server_id, day, data) VALUES (?,?,?)", (sid, _day(ts), json.dumps({"play_hours": 0.1})))
        db.x("INSERT OR REPLACE INTO recaps(server_id, day, data, source, created_ts) VALUES (?,?,?,?,?)", (sid, _day(ts), "{}", "live", now))
    before = len(selfbackup.backups())

    look = movehistory.preview(home, far)
    assert look["both_days"] == [_day(now)] and next(c for c in look["from"]["counts"] if c["table"] == "sessions")["rows"] == 2

    res = movehistory.move(home, far)
    assert all(c["rows"] == 0 for c in movehistory.counts(home))             # home: nothing left
    got = {c["table"]: c["rows"] for c in movehistory.counts(far)}
    assert got["sessions"] == 3 and got["events"] == 2 and res["moved"]["events_same"] == 1     # "hi" kept once
    assert got["stat_tally"] == 2 and got["positions"] == 1 and got["metrics"] == 1
    assert res["both_days"] == [_day(now)] and res["backup"] and len(selfbackup.backups()) == before + 1
    # home's old day moved as it was; the shared day worked out again from both: an hour played, 500 blocks
    days = {r["day"]: json.loads(r["data"]) for r in db.q("SELECT day, data FROM daily_stats WHERE server_id=?", (far,))}
    assert days[_day(old)] == {"play_hours": 0.1}
    today = days[_day(now)]
    assert today["play_hours"] == 1.0 and today["travelled"] == 500 and today["deaths"] == 1
    assert [r["day"] for r in db.q("SELECT day FROM recaps WHERE server_id=?", (far,))] == [_day(old)]   # (made again on its round)
    assert serverstats.compute(far, [datetime.fromtimestamp(now, db.tz()).date()])[_day(now)]["play_hours"] == 1.0
    _clear(home, far)


def test_moving_history_through_the_page(client, viewer):
    _clear("mv-a", "mv-b")
    assert viewer.get("/api/manage/history/move?src=mv-a&dst=mv-b").status_code == 403
    assert client.get("/api/manage/history/move?src=mv-a&dst=mv-a").status_code == 400
    assert client.post("/api/manage/history/move", json={"src": "mv-a", "dst": "not-a-server"}).status_code == 400
    sid = client.get("/api/manage/servers").json()[0]["id"]
    db.x("INSERT INTO sessions(server_id, player, uuid, start_ts, last_seen_ts, end_ts) VALUES (?,?,?,?,?,?)",
         ("mv-a", "Bo", "u-2", 1_700_000_000, 1_700_000_600, 1_700_000_600))
    n = db.q("SELECT COUNT(*) AS n FROM sessions WHERE server_id=?", (sid,))[0]["n"]
    r = client.post("/api/manage/history/move", json={"src": "mv-a", "dst": sid})
    assert r.status_code == 200 and r.json()["moved"]["sessions"] == 1
    assert db.q("SELECT COUNT(*) AS n FROM sessions WHERE server_id=?", (sid,))[0]["n"] == n + 1
    assert db.q("SELECT action FROM audit WHERE action='history:move' ORDER BY id DESC LIMIT 1")
    db.x("DELETE FROM sessions WHERE server_id=? AND player='Bo'", (sid,))
