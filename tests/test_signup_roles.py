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
        ok = anon.post("/api/public/signup/finish", json={"player": "Tyler", "code": code, "username": "tyler_web", "password": "long-enough-1"})
        assert ok.status_code == 200, ok.text
        me = anon.get("/api/auth/me").json()["user"]
        assert me["role"] == "player" and me["player"]["name"] == "Tyler" and me["shown"] == "Tyler"
        assert me["servers"] == [helpers.SID]                       # the server they signed up on
        # the code is used up, and a second account for the same player isn't made
        again = anon.post("/api/public/signup/finish", json={"player": "Tyler", "code": code, "username": "tyler2", "password": "long-enough-1"})
        assert again.status_code == 400
        anon.post("/api/public/signup/start", json={"player": "Tyler"})
        assert "already have an account" in game[-1] and "tyler_web" in game[-1]
    finally:
        _signup_on(client, False)
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
    for path in ("chat", "activity", "events", "timeline", "adventures", "world", "backups"):
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
