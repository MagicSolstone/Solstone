"""Manage → Activity: the admin log filtered, a page at a time, and kept for as long as chosen."""
import time

from app import auth, db


def test_search_pages_and_keep(client, viewer):
    db.x("DELETE FROM audit")
    now = time.time()
    for i in range(120):
        db.x("INSERT INTO audit(ts, username, server_id, action, detail, result) VALUES (?,?,?,?,?,?)",
             (now - i * 3600, "mum" if i % 2 else "dad", "s1" if i < 60 else "s2",
              "player:bring" if i % 3 == 0 else "command", f"say hello {i}", "failed: nope" if i == 5 else "ok"))
    assert viewer.get("/api/audit/search").status_code == 403
    d = client.get("/api/audit/search").json()
    assert d["total"] == 120 and len(d["rows"]) == 50 and d["rows"][0]["detail"] == "say hello 0"
    d = client.get("/api/audit/search?offset=100").json()
    assert len(d["rows"]) == 20 and d["rows"][-1]["detail"] == "say hello 119"
    assert client.get("/api/audit/search?oldest=true&limit=1").json()["rows"][0]["detail"] == "say hello 119"
    assert client.get("/api/audit/search?who=mum").json()["total"] == 60
    assert client.get("/api/audit/search?server=s2").json()["total"] == 60
    assert client.get("/api/audit/search?action=player").json()["total"] == 40          # the group
    assert client.get("/api/audit/search?action=command").json()["total"] == 80
    assert client.get("/api/audit/search?q=hello 11").json()["total"] == 11              # 11, 110-119
    assert client.get("/api/audit/search?q=50%").json()["total"] == 0                    # % is just a character
    assert client.get("/api/audit/search?failed=true").json()["rows"][0]["detail"] == "say hello 5"
    assert client.get(f"/api/audit/search?since={now - 10 * 3600 + 1}").json()["total"] == 10
    f = client.get("/api/audit/facets").json()
    assert f["people"] == ["dad", "mum"] and "player:bring" in f["actions"] and f["keep_days"] == 0 and f["count"] == 120
    assert client.put("/api/audit/keep", json={"days": 7}).status_code == 400
    f = client.put("/api/audit/keep", json={"days": 30}).json()                           # 30 days: older ones go now
    assert f["keep_days"] == 30 and client.get("/api/audit/search?action=command&who=dad").json()["total"] > 0
    assert client.get(f"/api/audit/search?until={now - 31 * 86400}").json()["total"] == 0
    client.put("/api/audit/keep", json={"days": 0})
    assert auth.audit_keep_days() == 0
