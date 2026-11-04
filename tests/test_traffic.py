"""Website traffic: counted by who asked, how much and how quick; visitors counted without keeping an address."""
import time

from app import db, traffic


class U:
    def __init__(self, username, role):
        self.username, self.role = username, role


def test_counted_by_who_and_how_quick():
    traffic._ensure()
    for t in ("traffic", "traffic_daily", "traffic_net"):
        db.x(f"DELETE FROM {t}")
    traffic._pending.clear()
    traffic._visitors.clear()
    now = time.time()
    me, other, kid = U("tyler", "admin"), U("mom", "admin"), U("kid", "player")
    traffic.record("/app", me, "10.0.0.1", 5000, 0, 0.02, now)
    traffic.record("/api/servers/x/players", me, "10.0.0.1", 1200, 0, 0.05, now)
    traffic.record("/api/servers/x/webmap/tiles/1.png", other, "10.0.0.2", 30000, 0, 0.4, now)
    traffic.record("/api/servers/x/leaderboard", kid, "10.0.0.3", 800, 0, 1.5, now)
    for ip in ("1.1.1.1", "2.2.2.2", "1.1.1.1"):
        traffic.record("/", None, ip, 9000, 0, 0.01, now)
    r = traffic.report("tyler", 1, now)
    g = r["groups"]
    assert g["you"]["requests"] == 2 and g["admins"]["requests"] == 1 and g["players"]["requests"] == 1 and g["visitors"]["requests"] == 3
    assert g["visitors"]["bytes"] == 27000 and r["visitors"] == 2                       # two different visitors today
    assert r["speed"]["buckets"] == [5, 0, 1, 1] and r["kinds"]["map"] == 1 and r["kinds"]["pages"] == 4
    assert sum(h["you"] for h in r["hours"]) == 2 and len(r["hours"]) == 24
    # seen by the other admin, "you" is them
    assert traffic.report("mom", 1, now)["groups"]["you"]["requests"] == 1
    # no address anywhere in what's stored
    stored = str(db.q("SELECT * FROM traffic")) + str(db.q("SELECT * FROM traffic_daily"))
    assert "1.1.1.1" not in stored and "10.0.0" not in stored
