"""Removing a server from Solstone: its settings, map pictures and (if asked) history go; a server still in the servers
folder isn't found again until it's brought back; the game server's own files aren't touched."""
import asyncio
import shutil

from app import db, movehistory, notify, selfbackup, settings_store
from app import servers as S
from app.config import config


def test_removing_an_old_server_and_bringing_it_back(client, viewer, sid):
    old = config.servers_dir / "old-home"
    shutil.copytree(S.registry.servers[sid].dir if sid in S.registry.servers else next(config.servers_dir.iterdir()), old)
    try:
        asyncio.run(S.registry.refresh(force=True))
        assert "old-home" in S.registry.servers
        client.put("/api/servers/old-home/settings", json={"display_name": "The old one"})
        data = settings_store.load()
        data.setdefault("mod_updates_skip", {})["old-home"] = {"p1": "v2"}
        data.setdefault("notify", {}).setdefault("servers", {})["old-home"] = {"mode": "off"}
        settings_store._write(data)
        db.x("INSERT INTO sessions(server_id, player, uuid, start_ts, last_seen_ts, end_ts) VALUES (?,?,?,?,?,?)",
             ("old-home", "Ann", "u-1", 1000, 2000, 2000))
        from app import worldmap
        tiles = config.data_dir / "maptiles" / f"v{worldmap.RENDER_VERSION}" / "old-home" / "minecraft_overworld"
        tiles.mkdir(parents=True, exist_ok=True)
        (tiles / "0_0.png").write_bytes(b"x" * 100)

        assert viewer.get("/api/manage/servers/old-home/remove").status_code == 403
        plan = client.get("/api/manage/servers/old-home/remove").json()
        assert plan["name"] == "The old one" and plan["history_rows"] >= 1 and plan["map_bytes"] == 100 and not plan["remote"]
        before = len(selfbackup.backups())
        assert viewer.post("/api/manage/servers/old-home/remove", json={}).status_code == 403
        r = client.post("/api/manage/servers/old-home/remove", json={"history": True}).json()
        assert r["ok"] and r["history"] and r["map_pictures"] == 1 and len(selfbackup.backups()) == before + 1
        assert "old-home" not in S.registry.servers and not tiles.exists()
        assert old.is_dir() and (old / "server.properties").is_file()                    # the server's own files: untouched
        assert "old-home" not in settings_store.load().get("servers", {})
        assert "old-home" not in settings_store.load()["mod_updates_skip"] and "old-home" not in notify.get_config()["servers"]
        assert all(c["rows"] == 0 for c in movehistory.counts("old-home") if c["table"] != "audit")   # (but the removal's own log line)
        assert [g["id"] for g in client.get("/api/manage/servers-removed").json()] == ["old-home"]
        asyncio.run(S.registry.refresh(force=True))
        assert "old-home" not in S.registry.servers                                      # still in the folder: not found again
        assert sid in S.registry.servers                                                 # (the others are)
        # brought back: found again, hidden like any new one
        assert client.delete("/api/manage/servers-removed/old-home").status_code == 200
        assert "old-home" in S.registry.servers and client.get("/api/manage/servers-removed").json() == []
    finally:
        shutil.rmtree(old, ignore_errors=True)
        data = settings_store.load()
        for k in ("servers_removed", "mod_updates_skip"):
            data.get(k, {}).pop("old-home", None)
        data.get("servers", {}).pop("old-home", None)
        settings_store._write(data)
        db.x("DELETE FROM sessions WHERE server_id='old-home'")
        asyncio.run(S.registry.refresh(force=True))
