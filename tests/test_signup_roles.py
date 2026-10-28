"""Players make their own account with a code sent to them in the game; a player account sees only
its own corner of Solstone, and the old "viewer" role carries on as "trusted"."""
import re

import pytest

from app import main, signup
from app import servers as S

import helpers


@pytest.fixture()
def game(monkeypatch):
    """Tyler is playing; whatever Solstone says in the game is kept."""
    said = []

    async def online(srv):
        return ["Tyler"], "rcon"

    async def rcon(self, cmd):
        said.append(cmd)
        return ""

    monkeypatch.setattr(S, "online_players", online)
    monkeypatch.setattr(S.Server, "rcon", rcon)
    monkeypatch.setattr(S.Server, "rcon_conf", lambda self: ("127.0.0.1", 25575, "x"))
    signup._codes.clear()
    signup._sent.clear()
    return said


def _signup_on(client, on=True):
    assert client.put("/api/settings/site", json={"signup": on}).status_code == 200


def test_signup_with_a_code_from_the_game(client, anon, game):
    assert anon.post("/api/public/signup/start", json={"player": "Tyler"}).status_code == 404     # off by default
    _signup_on(client)
    try:
        nobody = anon.post("/api/public/signup/start", json={"player": "Nobody"}).json()["message"]
        r = anon.post("/api/public/signup/start", json={"player": "tyler"})
        assert r.status_code == 200 and r.json()["message"] == nobody     # same answer: can't tell who's online
        assert len(game) == 1 and game[0].startswith("tellraw Tyler ")
        code = re.search(r"\b(\d{6})\b", game[0]).group(1)

        bad = anon.post("/api/public/signup/finish", json={"player": "Tyler", "code": "000000", "username": "tyler_web", "password": "long-enough-1"})
        assert bad.status_code == 400
        ok = anon.post("/api/public/signup/finish", json={"player": "Tyler", "code": code, "username": "tyler_web", "password": "long-enough-1",
                                                          "real_name": "Tyler J", "birthday": {"month": 3, "day": 14}})
        assert ok.status_code == 200, ok.text
        me = anon.get("/api/auth/me").json()["user"]
        assert me["role"] == "player" and me["player"]["name"] == "Tyler" and me["shown"] == "Tyler"
        assert me["real_name"] == "Tyler J"                         # their own, and the admins' (below)
        assert next(u for u in client.get("/api/users").json() if u["username"] == "tyler_web")["real_name"] == "Tyler J"
        bdays = client.get("/api/board").json()["birthdays"]
        assert {"player": "Tyler", "month": 3, "day": 14} == {k: v for k, v in next(b for b in bdays if b["player"] == "Tyler").items() if k in ("player", "month", "day")}
        assert me["servers"] == [helpers.SID]                       # the server they signed up on
        # the code is used up, and a second account for the same player isn't made
        again = anon.post("/api/public/signup/finish", json={"player": "Tyler", "code": code, "username": "tyler2", "password": "long-enough-1"})
        assert again.status_code == 400
        anon.post("/api/public/signup/start", json={"player": "Tyler"})
        assert "already have an account" in game[-1] and "tyler_web" in game[-1]
    finally:
        _signup_on(client, False)
        client.put("/api/board", json={"birthdays": [b for b in client.get("/api/board").json()["birthdays"] if b["player"] != "Tyler"]})
        for u in client.get("/api/users").json():
            if u["username"] == "tyler_web":
                client.delete(f"/api/users/{u['id']}")


def test_codes_are_limited(client, anon, game):
    _signup_on(client)
    try:
        for _ in range(5):
            anon.post("/api/public/signup/start", json={"player": "Tyler"})
        assert len(game) == signup.PER_PLAYER             # nobody can flood a player's chat
        code_msg = game[-1]
        code = re.search(r"\b(\d{6})\b", code_msg).group(1)
        wrong = "111111" if code != "111111" else "222222"
        for _ in range(signup.CODE_TRIES):
            anon.post("/api/public/signup/finish", json={"player": "Tyler", "code": wrong, "username": "x_web", "password": "long-enough-1"})
        late = anon.post("/api/public/signup/finish", json={"player": "Tyler", "code": code, "username": "x_web", "password": "long-enough-1"})
        assert late.status_code == 400                    # five wrong tries and the code is gone
    finally:
        _signup_on(client, False)


@pytest.fixture()
def player(client):
    """Signed in as a player account linked to Tyler."""
    from fastapi.testclient import TestClient

    u = client.post("/api/users", json={"username": "pl_tyler", "password": "player-pass-1", "role": "player"}).json()
    assert client.patch(f"/api/users/{u['id']}", json={"player": "Tyler"}).json()["player"]["name"] == "Tyler"
    c = TestClient(main.app, headers={"X-Solstone": "1"})
    assert c.post("/api/auth/login", json={"username": "pl_tyler", "password": "player-pass-1"}).status_code == 200
    yield c
    client.delete(f"/api/users/{u['id']}")


def test_player_sees_only_their_corner(player, viewer, sid, tyler):
    other = helpers.PLAYERS[1][1]
    srv = player.get(f"/api/servers/{sid}").json()
    assert srv["name"] and "folder" not in srv and "rcon" not in srv and "port" not in srv
    assert "rcon" in viewer.get(f"/api/servers/{sid}").json()          # trusted still sees it all
    rows = {p["name"]: p for p in player.get(f"/api/servers/{sid}/players").json()["players"]}
    assert "position" not in rows["Gimli_Jr"] and "dimension" not in rows["Gimli_Jr"]
    assert player.get(f"/api/servers/{sid}/players/{tyler}").status_code == 200       # their own page
    assert player.get(f"/api/servers/{sid}/players/{other}").status_code == 404
    assert player.get(f"/api/servers/{sid}/players/{other}/history").status_code == 404
    act = player.get(f"/api/servers/{sid}/activity").json()          # which days, never sessions or lengths
    assert act["sessions"] == [] and act["durations"] is False
    for path in ("chat", "events", "timeline", "world", "backups"):
        assert player.get(f"/api/servers/{sid}/{path}").status_code == 403, path
    assert player.post(f"/api/servers/{sid}/chat", json={"text": "hi"}).status_code == 403
    assert player.get("/api/players/all").status_code == 403
    assert player.get("/api/status").status_code == 403
    for path in ("leaderboard", "metrics", "mods"):
        assert player.get(f"/api/servers/{sid}/{path}").status_code == 200, path
    assert player.get("/api/auth/me").status_code == 200


def test_every_api_route_is_judged_for_players():
    """A route a player may use must exist: catches typos in the list when routes are renamed."""
    paths = {getattr(r, "path", "") for r in main.app.routes}
    assert set(main.PLAYER_ROUTES) <= paths



def test_a_login_can_be_limited_to_some_servers(client, viewer, sid):
    me = viewer.get("/api/auth/me").json()["user"]
    assert me["servers"] is None and any(s["id"] == sid for s in viewer.get("/api/servers").json())
    assert client.patch(f"/api/users/{me['id']}", json={"servers": ["somewhere-else"]}).json()["servers"] == ["somewhere-else"]
    try:
        assert not any(s.get("id") == sid for s in viewer.get("/api/servers").json())
        for path in ("", "/players", "/leaderboard", "/chat"):
            assert viewer.get(f"/api/servers/{sid}{path}").status_code == 404, path
        assert client.get(f"/api/servers/{sid}").status_code == 200          # admins see every server
    finally:
        assert client.patch(f"/api/users/{me['id']}", json={"servers": None}).json()["servers"] is None
    assert viewer.get(f"/api/servers/{sid}").status_code == 200


def test_only_admins_see_how_long_anyone_played(client, viewer, player, anon, sid, tyler):
    """Who played and which days, yes; for how long, only admins (screen-time limits)."""
    assert "today_seconds" in client.get(f"/api/servers/{sid}/players").json()["players"][0]
    for c in (viewer, player):
        rows = c.get(f"/api/servers/{sid}/players").json()["players"]
        assert rows and not any("today_seconds" in r or "play_time" in r.get("headline", {}) for r in rows)
        recap = c.get(f"/api/servers/{sid}/recap").json()["recap"]
        assert "total_seconds" not in recap and not any("seconds" in p for p in recap["players"])
    me = player.get(f"/api/servers/{sid}/players/{tyler}").json()
    assert "play_time" not in me["headline"] and "minecraft:play_time" not in (me.get("stats") or {}).get("minecraft:custom", {})
    hist = player.get(f"/api/servers/{sid}/players/{tyler}/history").json()
    assert hist["durations"] is False and all(set(d) == {"date", "played"} for d in hist["daily"])
    act = viewer.get(f"/api/servers/{sid}/activity").json()
    assert act["durations"] is False and all(set(v.values()) <= {1} for d in act["daily"] for v in [d["players"]])
    assert all(b["key"] != "play_time" for b in client.get(f"/api/servers/{sid}/leaderboard").json()["boards"])


def test_players_can_see_the_map_when_allowed(player, client, viewer, sid):
    other = helpers.PLAYERS[1][1]
    assert viewer.put("/api/settings/players", json={"see_map": True}).status_code == 403
    assert client.get("/api/settings/players").json() == {"see_map": False}
    assert player.get(f"/api/servers/{sid}/world").status_code == 403           # off: no World tab
    assert "player_map" not in player.get(f"/api/servers/{sid}").json()
    try:
        assert client.put("/api/settings/players", json={"see_map": True}).json() == {"see_map": True}
        assert player.get(f"/api/servers/{sid}/world").status_code == 200
        assert player.get(f"/api/servers/{sid}").json()["player_map"] is True
        assert any(s.get("player_map") for s in player.get("/api/servers").json())
        them = next(p for p in player.get(f"/api/servers/{sid}/players").json()["players"] if p["uuid"] == other)
        assert "position" in them                                               # where everyone is, on the map
        assert player.get(f"/api/servers/{sid}/players/{other}").status_code == 404   # still not their page
    finally:
        client.put("/api/settings/players", json={"see_map": False})


def test_on_the_whitelist_means_its_in_their_account(client, player, sid, tyler):
    """A player account limited to another server still gets this one once Tyler is on its whitelist."""
    import json as _json

    from app import servers as S
    me = player.get("/api/auth/me").json()["user"]
    client.patch(f"/api/users/{me['id']}", json={"servers": ["somewhere-else"]})
    wl = S.registry.servers[sid].dir / "whitelist.json"
    old = wl.read_text() if wl.exists() else None
    try:
        wl.write_text("[]")
        assert player.get(f"/api/servers/{sid}").status_code == 404
        wl.write_text(_json.dumps([{"uuid": tyler, "name": "Tyler"}]))          # let in, from the game or Crafty
        assert player.get(f"/api/servers/{sid}").status_code == 200
        assert any(s["id"] == sid for s in player.get("/api/servers").json())
        client.put(f"/api/servers/{sid}/settings", json={"private": True})
        assert player.get(f"/api/servers/{sid}").status_code == 404                # never a private one
    finally:
        client.put(f"/api/servers/{sid}/settings", json={"private": ""})
        if old is None:
            wl.unlink(missing_ok=True)
        else:
            wl.write_text(old)
        client.patch(f"/api/users/{me['id']}", json={"servers": None})


def test_where_everyone_is_only_on_your_own_servers(client, player, sid):
    """Players can see the map, but not on a server their login doesn't have."""
    from app import main
    me = player.get("/api/auth/me").json()["user"]
    client.put("/api/settings/players", json={"see_map": True})
    client.put("/api/settings/status", json={"enabled": True, "show_positions": True})
    main._board_cache.clear()
    try:
        b = player.get(f"/api/public/status/{sid}").json()
        assert b["spawn"] is not None or any("position" in p for p in b["players"] + b["recently"])
        client.patch(f"/api/users/{me['id']}", json={"servers": ["somewhere-else"]})
        b = player.get(f"/api/public/status/{sid}").json()
        assert b["spawn"] is None and not any("position" in p for p in b["players"] + b["recently"])
    finally:
        client.patch(f"/api/users/{me['id']}", json={"servers": None})
        client.put("/api/settings/players", json={"see_map": False})
        client.put("/api/settings/status", json={"enabled": False, "show_positions": False})
        main._board_cache.clear()


def test_a_login_with_a_java_and_a_bedrock_player(client, player, sid, tyler, game):
    """Two Minecraft players, one login: both pages are theirs; another one is linked with a code from the game."""
    other_name, other = helpers.PLAYERS[1]
    assert player.get(f"/api/servers/{sid}/players/{other}").status_code == 404
    me = player.get("/api/auth/me").json()
    uid = (me.get("user") or me)["id"]
    known = client.get("/api/users/players").json()
    assert any(p["name"] == "Tyler" and p["linked_to"] == "pl_tyler" for p in known)
    assert player.get("/api/users/players").status_code == 403
    u = client.patch(f"/api/users/{uid}", json={"add_player": other_name}).json()
    assert [p["name"] for p in u["players"]] == ["Tyler", other_name] and u["player"]["name"] == "Tyler"
    assert player.get(f"/api/servers/{sid}/players/{other}").status_code == 200         # both are theirs now
    u = client.patch(f"/api/users/{uid}", json={"remove_player": u["players"][1]["uuid"]}).json()
    assert [p["name"] for p in u["players"]] == ["Tyler"]
    # a player can't drop their only one
    assert player.delete(f"/api/auth/players/{u['players'][0]['uuid']}").status_code == 400
    # linking one themselves: a code in the game, for that player only (Tyler is online in the fake game)
    other_u = client.post("/api/users", json={"username": "pl_other", "password": "player-pass-1", "role": "player"}).json()
    try:
        from fastapi.testclient import TestClient
        c = TestClient(main.app, headers={"X-Solstone": "1"})
        assert c.post("/api/auth/login", json={"username": "pl_other", "password": "player-pass-1"}).status_code == 200
        c.post("/api/auth/players/start", json={"player": "Tyler"})
        assert "another login" in game[-1]                                                # Tyler is pl_tyler's
        client.patch(f"/api/users/{uid}", json={"player": ""})                            # unlink Tyler from pl_tyler
        signup._sent.clear()
        c.post("/api/auth/players/start", json={"player": "tyler"})
        code = re.search(r"\b(\d{6})\b", game[-1]).group(1)
        assert c.post("/api/auth/players/finish", json={"player": "Tyler", "code": "000000"}).status_code == 400
        r = c.post("/api/auth/players/finish", json={"player": "Tyler", "code": code})
        assert r.status_code == 200 and [p["name"] for p in r.json()["user"]["players"]] == ["Tyler"]
        assert c.get(f"/api/servers/{sid}/players/{tyler}").status_code == 200
    finally:
        client.delete(f"/api/users/{other_u['id']}")


def test_players_see_their_own_adventures(player, client, sid):
    """Only the sessions they were in; their own trail and lines, others' public lines, never others' chat."""
    import time

    from app import db
    t0 = time.time() - 4 * 3600
    db.x("INSERT INTO sessions(server_id, player, start_ts, last_seen_ts, end_ts) VALUES (?, 'Tyler', ?, ?, ?)", (sid, t0, t0 + 1800, t0 + 1800))
    db.x("INSERT INTO sessions(server_id, player, start_ts, last_seen_ts, end_ts) VALUES (?, 'Gimli_Jr', ?, ?, ?)", (sid, t0 + 60, t0 + 1700, t0 + 1700))
    db.x("INSERT INTO sessions(server_id, player, start_ts, last_seen_ts, end_ts) VALUES (?, 'Gimli_Jr', ?, ?, ?)", (sid, t0 + 7200, t0 + 9000, t0 + 9000))
    for who, x in (("Tyler", 1), ("Gimli_Jr", 2)):
        db.x("INSERT INTO positions(server_id, ts, player, dim, x, y, z) VALUES (?,?,?,?,?,?,?)", (sid, t0 + 100, who, "minecraft:overworld", x, 64, x))
    db.add_event(sid, t0 + 200, "chat", "secret plans", "Gimli_Jr")
    db.add_event(sid, t0 + 210, "advancement", "Gimli_Jr has made the advancement [Stone Age]", "Gimli_Jr")
    db.add_event(sid, t0 + 220, "progress", "Gimli_Jr mined 3 diamond ore", "Gimli_Jr")
    db.add_event(sid, t0 + 230, "progress", "Tyler chopped 5 logs", "Tyler")
    try:
        mine = [s for s in player.get(f"/api/servers/{sid}/adventures").json()["sessions"] if t0 - 1 <= s["start"] <= t0 + 9001]
        assert [s["start"] for s in mine] == [t0]                                      # not Gimli's later one
        tl = player.get(f"/api/servers/{sid}/adventures/timeline", params={"start": t0, "end": t0 + 1800}).json()
        msgs = [e["message"] for e in tl["events"]]
        assert "Tyler chopped 5 logs" in msgs and any("Stone Age" in m for m in msgs)
        assert "secret plans" not in msgs and "Gimli_Jr mined 3 diamond ore" not in msgs
        assert set(tl["trails"]) == {"Tyler"}                                          # players can't see the map
        assert player.get(f"/api/servers/{sid}/adventures/timeline", params={"start": t0 + 7200, "end": t0 + 9000}).status_code == 404
        assert set(client.get(f"/api/servers/{sid}/adventures/timeline", params={"start": t0, "end": t0 + 1800}).json()["trails"]) == {"Tyler", "Gimli_Jr"}
    finally:
        db.x("DELETE FROM sessions WHERE server_id=? AND start_ts >= ? AND start_ts <= ?", (sid, t0 - 1, t0 + 7201))
        db.x("DELETE FROM positions WHERE server_id=? AND ts = ?", (sid, t0 + 100))
        db.x("DELETE FROM events WHERE server_id=? AND ts BETWEEN ? AND ?", (sid, t0 + 199, t0 + 231))
