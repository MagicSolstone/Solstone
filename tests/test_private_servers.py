"""A private server (an admin's home server): admins see and manage it, nobody else does."""


def _set(client, sid, **kw):
    r = client.put(f"/api/servers/{sid}/settings", json=kw)
    assert r.status_code == 200, r.text


def test_private_server_is_for_admins_only(client, viewer, anon, sid):
    client.put("/api/settings/status", json={"enabled": True})
    try:
        _set(client, sid, private=True)
        # admins still see and manage it
        assert any(s["id"] == sid for s in client.get("/api/servers").json())
        assert client.get(f"/api/servers/{sid}").status_code == 200
        # a signed-in player doesn't
        assert not any(s.get("id") == sid for s in viewer.get("/api/servers").json())
        assert viewer.get(f"/api/servers/{sid}").status_code == 404
        assert viewer.get(f"/api/servers/{sid}/players").status_code == 404
        # nor do the public pages
        assert not any(s["id"] == sid for s in anon.get("/api/public/status").json()["servers"])
        assert anon.get(f"/api/public/status/{sid}").status_code == 404
        assert anon.get(f"/api/public/leaderboard/{sid}").status_code == 404
        # nor its announcements
        client.put("/api/board", json={"items": [{"text": "Home only", "where": ["home", "status"], "server": sid},
                                                 {"text": "For everyone", "where": ["home"]}]})
        texts = lambda c, **q: [i["text"] for i in c.get("/api/public/board", params=q).json()["items"]]  # noqa: E731
        assert "For everyone" in texts(anon, where="home") and "Home only" not in texts(anon, where="home")
        assert "Home only" not in texts(anon, where="status", sid=sid)
        assert "Home only" in texts(client, where="status", sid=sid)
    finally:
        client.put("/api/board", json={"items": [], "birthdays": []})
        _set(client, sid, private="")
    assert viewer.get(f"/api/servers/{sid}").status_code == 200
