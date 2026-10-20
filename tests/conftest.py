"""Test setup: a synthetic world on disk, with env vars set before the app is imported.

Crafty is deliberately not configured, so the app falls back to scanning the
servers folder -- that path is exercised here, and the Crafty client itself is
covered separately with a mock transport.
"""
import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(tempfile.mkdtemp(prefix="lodestone-test-"))
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

import helpers  # noqa: E402

helpers.build(ROOT)

os.environ.update({
    "SERVERS_DIR": str(ROOT / "servers"),
    "DATA_DIR": str(ROOT / "data"),
    "DOWNLOAD_ASSETS": "false",
    "CRAFTY_URL": "",
    "CRAFTY_TOKEN": "",
    "RCON_HOST": "127.0.0.1",
    "RCON_TIMEOUT": "1",
    "ADMIN_USERNAME": "admin",
    "ADMIN_PASSWORD": "admin-pass-123",
    "RECORDER_ENABLED": "false",
    "BACKUPS_DIR": str(ROOT / "backups"),
    "TZ": "America/Chicago",
})


HDR = {"X-Lodestone": "1"}


@pytest.fixture(scope="session")
def client():
    """Signed in as the first admin."""
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app, headers=HDR) as c:
        r = c.post("/api/auth/login", json={"username": "admin", "password": "admin-pass-123"})
        assert r.status_code == 200, r.text
        yield c


@pytest.fixture(scope="session")
def viewer(client):
    """Signed in as a read-only user."""
    from fastapi.testclient import TestClient

    from app.main import app

    client.post("/api/users", json={"username": "kiddo", "password": "viewer-pass-1", "role": "viewer"})
    c = TestClient(app, headers=HDR)
    assert c.post("/api/auth/login", json={"username": "kiddo", "password": "viewer-pass-1"}).status_code == 200
    return c


@pytest.fixture()
def anon(client):
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app, headers=HDR)


@pytest.fixture(scope="session")
def sid():
    return helpers.SID


@pytest.fixture(scope="session")
def tyler():
    return helpers.PLAYERS[0][1]
