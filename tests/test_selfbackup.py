"""Solstone's own backups: the database copied whole, the settings and the site's pictures, one zip a day."""
import io
import sqlite3
import zipfile


def test_backup_now_list_download_and_keep(client, viewer, tmp_path, monkeypatch):
    from app import selfbackup
    monkeypatch.setenv("SOLSTONE_BACKUP_DIR", str(tmp_path))
    monkeypatch.setattr(selfbackup, "KEEP", 2)
    assert viewer.get("/api/solstone-backups").status_code == 403
    assert selfbackup.due()
    names = []
    for _ in range(3):
        names.append(client.post("/api/solstone-backups").json()["name"])
        import time
        time.sleep(1.05)                         # names go to the second
    listed = [b["name"] for b in client.get("/api/solstone-backups").json()["backups"]]
    assert listed == names[:0:-1] and not selfbackup.due()              # newest first, only 2 kept
    r = client.get(f"/api/solstone-backups/{listed[0]}")
    assert r.status_code == 200
    z = zipfile.ZipFile(io.BytesIO(r.content))
    assert {"solstone.db", "settings.json"} <= set(z.namelist())
    out = tmp_path / "check.db"
    out.write_bytes(z.read("solstone.db"))
    c = sqlite3.connect(out)
    assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok" and c.execute("SELECT count(*) FROM sqlite_master").fetchone()[0] > 5
    c.close()
    assert viewer.get(f"/api/solstone-backups/{listed[0]}").status_code == 403
    assert client.get("/api/solstone-backups/..%2Fsettings.json").status_code == 404
