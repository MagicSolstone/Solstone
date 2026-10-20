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
    "ADMIN_TOKEN": "letmein",
})


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def sid():
    return helpers.SID


@pytest.fixture(scope="session")
def tyler():
    return helpers.PLAYERS[0][1]
