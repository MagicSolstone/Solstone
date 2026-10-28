"""Which mods have newer builds on Modrinth (faked here), by each jar's fingerprint."""
import asyncio

from app import modupdates, settings_store
from app import servers as S


def _srv(sid):
    return asyncio.run(S.registry.get(sid))


def test_updates_by_fingerprint(client, viewer, sid, monkeypatch):
    srv = _srv(sid)
    mods = S.mods(srv)
    assert len(mods) >= 2
    first, second = mods[0], mods[1]
    h1 = modupdates._sha512(srv.dir / "mods" / first["file"])
    h2 = modupdates._sha512(srv.dir / "mods" / second["file"])
    calls = []

    async def fake(url, body):
        calls.append((url, body))
        if url.endswith("/version_files"):
            return {h1: {"id": "v1", "project_id": "p1", "date_published": "2026-01-01T00:00:00Z"},
                    h2: {"id": "w1", "project_id": "p2", "date_published": "2026-01-01T00:00:00Z"}}
        return {h1: {"id": "v2", "project_id": "p1", "version_number": "9.9.9", "date_published": "2026-03-01T00:00:00Z"},
                h2: {"id": "w1", "project_id": "p2", "date_published": "2026-01-01T00:00:00Z"}}
    monkeypatch.setattr(modupdates, "_post", fake)
    modupdates._cache.clear()
    assert viewer.get(f"/api/servers/{sid}/mods/updates").status_code == 403
    r = client.get(f"/api/servers/{sid}/mods/updates").json()
    rows = r["mods"]
    assert rows[first["file"]]["status"] == "update" and rows[first["file"]]["latest"] == "9.9.9"
    assert rows[first["file"]]["url"] == "https://modrinth.com/project/p1/version/v2"
    assert rows[second["file"]]["status"] == "ok"
    assert all(x["status"] == "unknown" for f, x in rows.items() if f not in (first["file"], second["file"]))   # not on Modrinth
    upd = calls[1][1]
    assert upd["loaders"] == ["fabric"] and upd["game_versions"] == [srv.mc_version]      # only builds this server can run
    n = len(calls)
    client.get(f"/api/servers/{sid}/mods/updates")
    assert len(calls) == n                                                                # kept for an hour
    # a notification line, once per new build
    try:
        line = modupdates.updates_line(r, server_id=sid)
        assert line and "9.9.9" in line
        assert modupdates.updates_line(r, server_id=sid) is None
    finally:
        settings_store.save_section("mod_updates_told", {})
        modupdates._cache.clear()


def test_geyser_and_floodgate_count_most():
    assert modupdates.important({"id": "geyser-fabric", "name": "Geyser"})
    assert modupdates.important({"id": "floodgate", "name": "Floodgate"})
    assert not modupdates.important({"id": "lithium", "name": "Lithium"})


def test_modrinth_down_says_so(client, sid, monkeypatch):
    import httpx

    async def down(url, body):
        raise httpx.ConnectError("no network")
    monkeypatch.setattr(modupdates, "_post", down)
    modupdates._cache.clear()
    r = client.get(f"/api/servers/{sid}/mods/updates?force=1").json()
    assert r["error"] and "Modrinth" in r["error"]
