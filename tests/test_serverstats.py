"""Server stats over time: each day's totals, kept for good, from the events and sessions."""
from datetime import datetime, timedelta

from app import db, serverstats

SID = "stats-test"


def _clear():
    serverstats._ensure()
    for t in ("events", "sessions", "metrics", "daily_stats"):
        db.x(f"DELETE FROM {t} WHERE server_id=?", (SID,))
    serverstats._done.pop(SID, None)


def test_each_days_totals_and_they_stay():
    _clear()
    zone = db.tz()
    today = datetime.now(zone).replace(hour=12, minute=0, second=0, microsecond=0)
    old = today - timedelta(days=5)
    try:
        db.add_event(SID, old.timestamp(), "progress", "Alex defeated 3 zombies, 2 skeletons · chopped 12 logs · travelled 1.5 km", "Alex")
        db.add_event(SID, old.timestamp() + 60, "death", "Alex was slain by Zombie", "Alex")
        db.add_event(SID, old.timestamp() + 120, "fish", "Sam caught a cod", "Sam")
        db.add_event(SID, today.timestamp(), "progress", "Sam dug 40 blocks", "Sam")
        db.x("INSERT INTO sessions(server_id, player, start_ts, last_seen_ts, end_ts) VALUES (?,?,?,?,?)",
             (SID, "Alex", old.timestamp(), old.timestamp() + 7200, old.timestamp() + 7200))          # 2 hours, 5 days ago
        db.x("INSERT INTO sessions(server_id, player, start_ts, last_seen_ts, end_ts) VALUES (?,?,?,?,?)",
             (SID, "Sam", old.timestamp(), old.timestamp() + 1800, old.timestamp() + 1800))
        db.x("INSERT INTO sessions(server_id, player, start_ts, last_seen_ts, end_ts) VALUES (?,?,?,?,?)",
             (SID, "Sam", today.timestamp(), today.timestamp() + 3600, today.timestamp() + 3600))
        h = serverstats.history(SID)
        by = {d["day"]: d for d in h["days"]}
        o, t = by[old.date().isoformat()], by[today.date().isoformat()]
        assert o["mobs"] == 5 and o["logs"] == 12 and o["travelled"] == 1500 and o["deaths"] == 1 and o["fish"] == 1
        assert o["players"] == 2 and o["play_hours"] == 2.5 and o["new_players"] == 2
        assert t["mined"] == 40 and t["players"] == 1 and "new_players" not in t        # Sam's been here before
        assert len(h["days"]) == 6                                                          # every day since the first, even quiet ones
        assert sum(sum(row) for row in h["heat"]) == 3.5 and "records" not in h
        # the detail goes (it's kept 180 days): the stored day stays as it was
        db.x("DELETE FROM events WHERE server_id=? AND ts<?", (SID, today.timestamp() - 86400))
        serverstats.rollup(SID, force=True)
        assert {d["day"]: d for d in serverstats.days(SID)}[old.date().isoformat()]["mobs"] == 5
        assert "Alex" not in str(h) and "Sam" not in str(h)                                  # no names, ever
    finally:
        _clear()
