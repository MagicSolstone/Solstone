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
        assert viewer.get(f"/api/public/status/{sid}").status_code == 404
        assert viewer.get(f"/api/public/leaderboard/{sid}").status_code == 404
        # nor its announcements
        client.put("/api/board", json={"items": [{"text": "Home only", "where": ["home", "status"], "server": sid},
                                                 {"text": "For everyone", "where": ["home"]}]})
        texts = lambda c, **q: [i["text"] for i in c.get("/api/public/board", params=q).json()["items"]]  # noqa: E731
        assert "For everyone" in texts(anon, where="home") and "Home only" not in texts(anon, where="home")
        assert "Home only" not in texts(anon, where="status", sid=sid)
        assert "Home only" in texts(client, where="status", sid=sid)
    finally:
        client.put("/api/board", json={"items": []})
        _set(client, sid, private="")
    assert viewer.get(f"/api/servers/{sid}").status_code == 200


def test_only_servers_keeps_one_solstone_to_its_own(monkeypatch, sid):
    """ONLY_SERVERS: two Solstones against one Crafty, each with its own servers."""
    import asyncio

    from app import servers as S
    from app.config import config

    try:
        monkeypatch.setattr(config, "only_servers", ("some-other-server",))
        asyncio.run(S.registry.refresh(force=True))
        assert sid not in S.registry.servers
        monkeypatch.setattr(config, "only_servers", (sid.lower(),))
        asyncio.run(S.registry.refresh(force=True))
        assert sid in S.registry.servers
    finally:
        monkeypatch.setattr(config, "only_servers", ())
        asyncio.run(S.registry.refresh(force=True))


def test_whereabouts_and_the_map_need_sign_in(client, anon, viewer, sid):
    from app import main
    client.put("/api/settings/status", json={"enabled": True, "show_positions": True})
    main._board_cache.clear()
    try:
        assert anon.get(f"/api/public/status/{sid}").status_code == 401                  # strangers: nothing at all
        assert anon.get(f"/api/public/map/{sid}/regions").status_code == 404           # no map pictures for strangers
        assert anon.get(f"/api/public/map/{sid}/tile?x=0&z=0").status_code == 404
        assert viewer.get(f"/api/public/map/{sid}/regions").status_code == 200         # signed in: there it is
        signed = viewer.get(f"/api/public/status/{sid}").json()
        assert signed["spawn"] is not None or any("position" in p for p in signed["players"] + signed["recently"])
    finally:
        client.put("/api/settings/status", json={"enabled": False, "show_positions": False})
        main._board_cache.clear()


def test_public_requests_are_limited_per_address(anon, monkeypatch):
    from app import main
    monkeypatch.setattr(main, "PUBLIC_PER_MINUTE", 5)
    main._public_hits.clear()
    codes = [anon.get("/api/public/site").status_code for _ in range(7)]
    assert codes[:5] == [200] * 5 and codes[5:] == [429, 429]
    main._public_hits.clear()
