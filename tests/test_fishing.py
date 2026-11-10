"""The Solstone Fishing pack: what it contains, reading catches back, and fishing contests."""
import asyncio
import re

import pytest


class FakeServer:
    is_java = True

    def __init__(self):
        self.id, self.display_name, self.mc_version = "fish-srv", "Family", "26.1"
        self.catches, self.said, self.scores, self.reset = [], [], {}, []

    def rcon_conf(self):
        return {"host": "x"}

    async def rcon(self, cmd):
        if cmd == "data get storage solstone:fish pack":
            return "Storage solstone:fish has the following contents: {version: 1}"
        if cmd == "data get storage solstone:fish catches":
            body = ", ".join((f'{{s: "{c[0]}", w: {c[4]}, p: {c[5]}, u: [I; 1, 2, 3, 4], i: {i + 1}}}' if c[1] is None else
                              f'{{s: "{c[0]}", n: "{c[1]}", q: {c[2]}, ql: "{c[3]}", w: {c[4]}, lb: "{c[4] / 10}", p: {c[5]}, u: [I; 1, 2, 3, 4], i: {i + 1}}}')
                             for i, c in enumerate(self.catches))
            return f"Storage solstone:fish has the following contents: [{body}]"
        m = re.match(r"scoreboard players get (\S+) (\S+)", cmd)
        if m:
            v = self.scores.get((m.group(1), m.group(2)))
            return f"{m.group(1)} has {v} [{m.group(2)}]" if v is not None else "none is set"
        if cmd.startswith("scoreboard players reset"):
            self.reset.append(cmd)
        if cmd.startswith("tellraw"):
            self.said.append(cmd)
        if cmd.startswith("give"):
            return "Gave 1 [x] to someone"
        return ""


@pytest.fixture()
def pond(monkeypatch):
    from app import challenges, fishing, gather, settings_store
    from app import servers as S
    monkeypatch.setattr(gather, "LEAD", 0)
    settings_store.save_section("challenges", {})
    srv = FakeServer()
    srv.settings = {"fishing_journal": True}            # these tests are about the journal (off by default: see below)
    fishing._retired.discard(srv.id)

    async def online(_s):
        return ["Tyler", "Gimli_Jr"], "rcon"
    monkeypatch.setattr(S, "online_players", online)
    monkeypatch.setattr(S, "known_players", lambda _s: {"00000001-0000-0002-0000-000300000004": {"name": "Gimli_Jr"}})
    yield fishing, challenges, srv
    settings_store.save_section("challenges", {})


def test_fishing_api(client, viewer, sid):
    assert viewer.get(f"/api/servers/{sid}/fishing").status_code == 403
    d = client.get(f"/api/servers/{sid}/fishing").json()
    assert len(d["guide"]) == 4 and "status" not in d                    # (no data pack any more: nothing to report on)
    assert client.get("/api/fishing/solstone-pack.zip").status_code in (404, 405)


def test_journal_and_backfill_from_old_feed():
    from app import db, fishing
    sid = "journal-srv"
    db.add_event(sid, 100.0, "fish", "Gimli_Jr caught a Salmon · 4.7 lb · 5 points", "Gimli_Jr")
    db.add_event(sid, 101.0, "fish", "Gimli_Jr caught a Cod · 0.5 lb · 1 points", "Gimli_Jr")
    db.add_event(sid, 102.0, "fish", "Tyler caught a Cod · 0.9 lb · 1 points", "Tyler")
    j = fishing.journal(sid)                                            # old catches read from the feed once
    g = next(p for p in j["players"] if p["name"] == "Gimli_Jr")
    assert set(g["species"]) == {"salmon", "cod"} and g["total"] == 2
    assert j["records"]["cod"]["player"] == "Tyler" and j["records"]["cod"]["lb"] == 0.9
    assert len(j["species"]) == 4 and j["qualities"] == []
    assert len(fishing.journal(sid)["recent"]) == 3                     # not filled twice


def test_fishing_left_alone_without_tide(pond):
    """Without the Tide mod fishing stays plain vanilla: no journal, no Fishing tab (and no data pack to track it)."""
    fishing, _challenges, srv = pond
    assert fishing.journal_on(srv) is False and fishing.available(srv) is None


def test_the_old_data_pack_is_switched_off_and_removed(tmp_path):
    """Solstone's own pack was taken out in 1.16: a copy still in a world is disabled in the game and its file removed,
    once; a world without one is left alone."""
    from types import SimpleNamespace

    from app import fishing, fishpack
    said = []

    async def rcon(cmd):
        said.append(cmd)
        return ""
    (tmp_path / "datapacks").mkdir()
    pack = tmp_path / "datapacks" / fishpack.PACK_FILE
    pack.write_bytes(b"PK")
    other = tmp_path / "datapacks" / "someone-elses.zip"
    other.write_bytes(b"PK")
    srv = SimpleNamespace(id="retire-test", display_name="T", world_dir=tmp_path, rcon=rcon, rcon_conf=lambda: True)
    fishing._retired.discard(srv.id)
    assert asyncio.run(fishing.retire_pack(srv)) is True
    assert said == ['datapack disable "file/solstone-pack.zip"'] and not pack.exists() and other.exists()
    assert asyncio.run(fishing.retire_pack(srv)) is False and len(said) == 1          # once
