"""Two-step sign-in (an authenticator app's codes), the server-side recovery commands, and resetting a forgotten
password through the game."""
import asyncio
import base64

import pytest
from fastapi.testclient import TestClient

HDR = {"X-Solstone": "1"}


def test_codes_match_the_standard():
    """RFC 6238's test vector (SHA-1, 30 s): at 59 seconds the 8-digit code is 94287082, so the 6-digit one is 287082."""
    from app import twostep
    secret = base64.b32encode(b"12345678901234567890").decode()
    assert twostep.code_now(secret, now=59) == "287082"
    assert twostep._match(secret, "287082", now=59 + 30) is not None          # a little clock drift is fine
    assert twostep._match(secret, "287082", now=59 + 120) is None              # but not minutes later
    assert twostep._match(secret, "287082", now=59, after=1) is None           # never twice


@pytest.fixture()
def admin2(client):
    """A second admin, signed in, with two-step off at the end."""
    from app import main
    from app.auth import create_user, get_user
    from app.db import q
    rows = q("SELECT id FROM users WHERE username='ts_admin'")
    uid = rows[0]["id"] if rows else create_user("ts_admin", "ts-admin-pass-1", "admin").id
    c = TestClient(main.app, headers=HDR)
    assert c.post("/api/auth/login", json={"username": "ts_admin", "password": "ts-admin-pass-1"}).status_code == 200
    yield c, get_user(uid)
    from app import twostep
    twostep.turn_off(uid)


def _turn_on(c):
    from app import twostep
    s = c.post("/api/auth/two-step/begin", json={}).json()
    assert "<svg" in s["svg"] and s["uri"].startswith("otpauth://totp/")
    secret = s["secret"].replace(" ", "")
    assert c.post("/api/auth/two-step/confirm", json={"code": "000000" if twostep.code_now(secret) != "000000" else "111111"}).status_code == 400
    r = c.post("/api/auth/two-step/confirm", json={"code": twostep.code_now(secret)}).json()
    assert r["on"] and len(r["backup_codes"]) == 10
    return secret, r["backup_codes"]


def test_signing_in_with_a_code_a_backup_code_and_a_trusted_device(admin2):
    from app import main, twostep
    c, u = admin2
    secret, backups = _turn_on(c)
    fresh = TestClient(main.app, headers=HDR)
    r = fresh.post("/api/auth/login", json={"username": "ts_admin", "password": "ts-admin-pass-1"}).json()
    assert r["two_step"] and "user" not in r and fresh.get("/api/auth/me").status_code == 401      # no session yet
    assert fresh.post("/api/auth/login/code", json={"ticket": r["ticket"], "code": "12"}).status_code == 400
    # the code the app showed when it was turned on was used already (never twice): the next one's needed
    twostep.db.x("UPDATE users SET totp_last=? WHERE id=?", (0, u.id))
    ok = fresh.post("/api/auth/login/code", json={"ticket": r["ticket"], "code": twostep.code_now(secret), "trust": True})
    assert ok.status_code == 200 and ok.json()["user"]["username"] == "ts_admin" and twostep.TRUST_COOKIE in ok.cookies
    # this browser's trusted now: just the password
    again = fresh.post("/api/auth/login", json={"username": "ts_admin", "password": "ts-admin-pass-1"}).json()
    assert again.get("user", {}).get("username") == "ts_admin"
    # another browser: a backup code works, once
    other = TestClient(main.app, headers=HDR)
    t = other.post("/api/auth/login", json={"username": "ts_admin", "password": "ts-admin-pass-1"}).json()["ticket"]
    assert other.post("/api/auth/login/code", json={"ticket": t, "code": backups[0].upper()}).status_code == 200
    t2 = TestClient(main.app, headers=HDR).post("/api/auth/login", json={"username": "ts_admin", "password": "ts-admin-pass-1"}).json()["ticket"]
    assert TestClient(main.app, headers=HDR).post("/api/auth/login/code", json={"ticket": t2, "code": backups[0]}).status_code == 400
    assert c.get("/api/auth/two-step").json()["backup_left"] == 9
    # the Users list shows it
    assert any(x["username"] == "ts_admin" and x["two_step"] for x in c.get("/api/users").json())


def test_turning_it_off_needs_the_password_and_a_code(admin2):
    from app import twostep
    c, u = admin2
    secret, backups = _turn_on(c)
    assert c.post("/api/auth/two-step/off", json={"password": "wrong", "code": backups[1]}).status_code == 400
    assert c.post("/api/auth/two-step/off", json={"password": "ts-admin-pass-1", "code": "nope"}).status_code == 400
    assert c.post("/api/auth/two-step/off", json={"password": "ts-admin-pass-1", "code": backups[1]}).json()["on"] is False
    assert not twostep.is_on(u.id)


def test_an_admin_can_turn_it_off_for_someone(admin2, client):
    from app import twostep
    c, u = admin2
    _turn_on(c)
    assert client.post(f"/api/users/{u.id}/two-step-off", json={}).json() == {"ok": True}
    assert not twostep.is_on(u.id)
    assert c.get("/api/auth/me").status_code == 401                         # signed out everywhere


def test_the_server_console_gets_anyone_back_in(admin2, capsys):
    from app import cli, twostep
    c, u = admin2
    _turn_on(c)
    assert cli.main(["two-step-off", "ts_admin"]) == 0 and not twostep.is_on(u.id)
    assert cli.main(["reset-password", "ts_admin"]) == 0
    out = capsys.readouterr().out
    new = out.split("New password for ts_admin: ")[1].split()[0]
    from app import main
    fresh = TestClient(main.app, headers=HDR)
    assert fresh.post("/api/auth/login", json={"username": "ts_admin", "password": new}).status_code == 200
    assert cli.main(["make-admin", "ts_rescue"]) == 0 and "New admin login ts_rescue" in capsys.readouterr().out
    assert cli.main(["reset-password", "nobody_here"]) == 1
    from app.db import x
    x("DELETE FROM users WHERE username='ts_rescue'")
    # put the fixture's password back
    from app.auth import update_user
    update_user(u.id, password="ts-admin-pass-1")


def test_a_forgotten_password_is_reset_through_the_game(client, monkeypatch):
    from app import auth, signup
    u = auth.create_user("reset_kid", "old-password-1", "player", player=("0a0b0c0d-0000-4000-8000-0000000000aa", "ResetKid"))
    told = []

    class Srv:
        id = "s"

        async def rcon(self, cmd, wait=None):
            told.append(cmd)
            return ""

    async def found(servers, typed):
        return (Srv(), "0a0b0c0d-0000-4000-8000-0000000000aa", "ResetKid") if typed.lower() == "resetkid" else None
    monkeypatch.setattr(signup, "_find_online", found)
    try:
        from starlette.requests import Request
        req = Request({"type": "http", "headers": [], "client": ("1.2.3.4", 1)})
        assert asyncio.run(signup.start_reset(req, "Nobody", []))["state"] == "offline"
        r = asyncio.run(signup.start_reset(req, "ResetKid", []))
        assert r["state"] == "sent" and told and "new password for" in told[-1] and "reset_kid" in told[-1]
        code = signup._reset_codes["0a0b0c0d-0000-4000-8000-0000000000aa"]
        real = next(f"{n:06d}" for n in range(10**6) if signup._hash(f"{n:06d}") == code["hash"])
        from fastapi import HTTPException
        with pytest.raises(HTTPException):
            signup.finish_reset("ResetKid", "000000" if real != "000000" else "111111", "new-password-1")
        signup.finish_reset("ResetKid", real, "new-password-1")
        assert auth.verify_password("new-password-1", auth.db.q("SELECT password_hash FROM users WHERE id=?", (u.id,))[0]["password_hash"])
        assert client.post("/api/public/password-reset/finish", json={"player": "ResetKid", "code": real, "password": "x" * 9}).status_code == 400
    finally:
        auth.delete_user(u.id)
