"""Waypoint races: markers placed and removed, checkpoints in order, finish places, prizes."""
import asyncio
import re
import time

import pytest


class FakeServer:
    def __init__(self, version="1.20.4"):
        self.id, self.display_name, self.mc_version = "race-srv", "Family", version
        self.online = ["Tyler", "Gimli_Jr"]
        self.pos = {"Tyler": [0, 64, 0], "Gimli_Jr": [0, 64, 0]}
        self.entities, self.forced, self.cmds, self.given = [], set(), [], []

    def rcon_conf(self):
        return {"host": "x"}

    async def rcon(self, cmd):
        self.cmds.append(cmd)
        if "solgather" in cmd:                                        # height probes for lining up: not race markers
            return "Summoned new Marker" if "summon" in cmd else ""
        m = re.search(r"summon minecraft:(\w+) ", cmd)
        if m:
            self.entities.append(m.group(1))
            return "Summoned new Block Display"
        if cmd.startswith("kill @e[tag="):
            n = len(self.entities); self.entities.clear()
            return f"Killed {n} entities"
        m = re.search(r"forceload (add|remove) (-?\d+) (-?\d+)", cmd)
        if m:
            (self.forced.add if m.group(1) == "add" else self.forced.discard)((m.group(2), m.group(3)))
            return "ok"
        m = re.match(r"data get entity (\S+) Pos", cmd)
        if m and m.group(1) in self.pos:
            x, y, z = self.pos[m.group(1)]
            return f"{m.group(1)} has the following entity data: [{x}d, {y}d, {z}d]"
        m = re.search(r" run tp (\w+) (-?[\d.]+) (-?[\d.]+) (-?[\d.]+)", cmd)
        if m:
            self.pos[m.group(1)] = [float(m.group(2)), float(m.group(3)), float(m.group(4))]
            return f"Teleported {m.group(1)}"
        m = re.match(r"give (\S+) (\S+) (\d+)", cmd)
        if m:
            self.given.append((m.group(1), m.group(2), int(m.group(3))))
            return f"Gave {m.group(3)} [x] to {m.group(1)}"
        return ""


@pytest.fixture()
def race(monkeypatch):
    from app import challenges, races, settings_store
    from app import servers as S
    settings_store.save_section("races", {}); settings_store.save_section("challenges", {}); settings_store.save_section("gather", {})
    srv = FakeServer()

    async def online(_s):
        return list(srv.online), "rcon"
    monkeypatch.setattr(S, "online_players", online)
    monkeypatch.setattr(races.fwshow, "push", lambda *a, **k: None)
    yield races, srv, challenges
    settings_store.save_section("races", {}); settings_store.save_section("challenges", {})


def _course(races, srv):
    return races.save_course(srv.id, {"name": "Mountain loop", "points": [
        {"x": 0, "y": 64, "z": 0}, {"x": 100, "y": 90, "z": 0, "name": "Peak"}, {"x": 100, "y": 64, "z": 100}, {"x": 0, "y": 64, "z": 0, "radius": 5}]})


def _shift(races, **k):
    d = races._load()
    for r in d["runs"]:
        for key, v in k.items():
            r[key] = r[key] + v if isinstance(v, (int, float)) and key in r else v
    races._save(d)


def test_full_race(race):
    races, srv, challenges = race
    c = _course(races, srv)
    assert races.courses_for(srv.id)[0]["points"][1]["name"] == "Peak"
    races.schedule(srv.id, {"course": c["id"], "start": time.time(), "minutes": 10, "teleport": True,
                            "prizes": [{"item": "diamond", "count": 3}, {"item": "cookie", "count": 8}]})
    assert races.busy()
    asyncio.run(races.tick([srv]))                                   # countdown: markers, teleport
    r = races.runs_for(srv.id)[0]
    assert r["state"] == "countdown" and srv.entities.count("block_display") == 4 and srv.entities.count("text_display") == 4
    assert len(srv.forced) == 3
    # lined up side by side on the start line (2 blocks apart, across the way to the first checkpoint)
    assert sorted(round(srv.pos[n][2]) for n in ("Tyler", "Gimli_Jr")) == [-1, 1] and all(round(srv.pos[n][0]) == 0 for n in ("Tyler", "Gimli_Jr"))
    assert any(re.search(r"facing 100(\.0)? 91(\.0)? 0", cmd) for cmd in srv.cmds)
    assert any("text:{text:" not in cmd and "text:'" in cmd for cmd in srv.cmds if "text_display" in cmd)     # pre-1.21.5 JSON text
    _shift(races, go_at=-11)
    asyncio.run(races.tick([srv]))                                   # GO
    r = races.runs_for(srv.id)[0]
    assert r["state"] == "running" and set(r["racers"]) == {"Tyler", "Gimli_Jr"}
    srv.pos["Gimli_Jr"] = [99, 88, 1]                                # Gimli reaches the peak
    srv.pos["Tyler"] = [100, 64, 100]                               # Tyler skips ahead: doesn't count
    asyncio.run(races.tick([srv]))
    r = races.runs_for(srv.id)[0]
    assert r["racers"]["Gimli_Jr"]["next"] == 2 and r["racers"]["Tyler"]["next"] == 1
    assert any("actionbar" in cmd and "Next: Checkpoint 2 of 2" in cmd for cmd in srv.cmds)
    srv.pos["Gimli_Jr"] = [100, 64, 98]; asyncio.run(races.tick([srv]))
    srv.pos["Gimli_Jr"] = [2, 64, 1]; asyncio.run(races.tick([srv]))    # finish
    r = races.runs_for(srv.id)[0]
    assert r["racers"]["Gimli_Jr"]["finished"] is not None and r["state"] == "running"
    assert races.banners(srv.id)[0]["text"] == "Mountain loop: Gimli_Jr leads (finished)"
    assert races.live_for_map(srv.id)["racers"]["Gimli_Jr"]["finished"] is not None
    _shift(races, ends_at=-10000)
    asyncio.run(races.tick([srv]))                                   # time's up
    r = races.runs_for(srv.id)[0]
    assert r["state"] == "done" and [x["name"] for x in r["results"]] == ["Gimli_Jr", "Tyler"]
    assert ("Gimli_Jr", "minecraft:diamond", 3) in srv.given and not any(g[0] == "Tyler" for g in srv.given)   # Tyler didn't finish
    assert not srv.entities and not srv.forced                       # markers and force-loading gone
    from app import gather
    home = gather._load()["returns"]
    assert len(home) == 1 and set(home[0]["back"]) == {"Tyler", "Gimli_Jr"}   # everyone heads back after a countdown
    assert not races.busy()


def test_new_text_format_and_validation(race):
    races, srv, _ = race
    srv.mc_version = "26.1"
    c = _course(races, srv)
    races.schedule(srv.id, {"course": c["id"], "start": time.time()})
    asyncio.run(races.tick([srv]))
    assert any("text:{text:" in cmd for cmd in srv.cmds if "text_display" in cmd)   # 1.21.5+/26.x: SNBT text
    # held still until GO (movement and jumping), let go at GO
    assert "attribute Tyler minecraft:movement_speed modifier add solstone:freeze -1 add_multiplied_total" in srv.cmds
    assert "attribute Gimli_Jr minecraft:jump_strength modifier add solstone:freeze -1 add_multiplied_total" in srv.cmds
    _shift(races, go_at=-11)
    asyncio.run(races.tick([srv]))
    assert "attribute Tyler minecraft:movement_speed modifier remove solstone:freeze" in srv.cmds
    rid = races.runs_for(srv.id)[0]["id"]
    assert asyncio.run(races.cancel(srv, rid)) and not srv.entities
    with pytest.raises(ValueError):
        races.save_course(srv.id, {"points": [{"x": 0, "z": 0}]})
    with pytest.raises(ValueError):
        races.schedule(srv.id, {"course": "nope"})
    assert races._direction(0, -10) == "north" and races._direction(10, 0) == "east" and races._direction(-5, 5) == "south-west"


def test_race_api(client, viewer, sid):
    assert viewer.get(f"/api/servers/{sid}/races").status_code == 403
    c = client.post(f"/api/servers/{sid}/races/courses", json={"name": "Loop", "points": [{"x": 0, "z": 0}, {"x": 10, "z": 10}]}).json()
    assert client.get(f"/api/servers/{sid}/races").json()["courses"][0]["id"] == c["id"]
    assert client.put(f"/api/servers/{sid}/races/courses/{c['id']}", json={"name": "Loop 2", "points": c["points"]}).json()["name"] == "Loop 2"
    spot = client.get(f"/api/servers/{sid}/races/spot?x=5&z=5").json()
    assert spot["x"] == 5 and "y" in spot
    assert client.delete(f"/api/servers/{sid}/races/courses/{c['id']}").json() == {"ok": True}
    from app import settings_store
    settings_store.save_section("races", {})
