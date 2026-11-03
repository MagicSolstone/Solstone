"""Manage → Solstone: how much room Solstone takes."""


def test_storage_report(client, viewer):
    assert viewer.get("/api/solstone-storage").status_code == 403
    d = client.get("/api/solstone-storage").json()
    assert d["total"] > 0 and d["disk"]["free"] > 0
    assert any(p["name"] == "solstone.db" for p in d["parts"])
    pos = next(t for t in d["tables"] if t["name"] == "positions") if any(t["name"] == "positions" for t in d["tables"]) else None
    assert pos is None or "Adventures" in pos["what"]
