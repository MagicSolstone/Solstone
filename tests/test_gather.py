"""Gathering everyone for an event and sending them home: the countdowns, the trip back,
anyone offline sent back on joining, and nobody left frozen."""
import asyncio
import re
import time

import pytest


class Srv:
    def __init__(self):
        self.id, self.mc_version = "g-srv", "26.3"
        self.online = ["Tyler", "Gimli_Jr"]
        self.pos = {"Tyler": [10.0, 70.0, 10.0], "Gimli_Jr": [-5.0, 64.0, 3.0]}
        self.cmds = []

    def rcon_conf(self):
        return {"host": "x"}

    async def rcon(self, cmd):
        self.cmds.append(cmd)
        m = re.match(r"data get entity (\w+) Pos", cmd)
        if m and m.group(1) in self.pos:
            x, y, z = self.pos[m.group(1)]
            return f"{m.group(1)} has the following entity data: [{x}d, {y}d, {z}d]"
        if "data get entity @e[tag=solgather" in cmd:
            return "Marker has the following entity data: [0.5d, 80.0d, 0.5d]"
        if re.match(r"data get entity \w+ Dimension", cmd):
            return 'x has the following entity data: "minecraft:overworld"'
        m = re.search(r" run tp (\w+) (-?[\d.]+) (-?[\d.]+) (-?[\d.]+)", cmd)
        if m:
            if m.group(1) not in self.online:
                return "No entity was found"
            self.pos[m.group(1)] = [float(m.group(2)), float(m.group(3)), float(m.group(4))]
            return "Teleported"
        if " if block " in cmd:
            return "Test failed"
        return ""


@pytest.fixture()
def g(monkeypatch):
    from app import gather, settings_store
    from app import servers as S
    settings_store.save_section("gather", {})
    srv = Srv()

    async def online(_s):
        return list(srv.online), "rcon"
    monkeypatch.setattr(S, "online_players", online)
    yield gather, srv
    settings_store.save_section("gather", {})


def test_lead_in_counts_down_once_per_number(g):
    gather, srv = g
    item = {"start": 1000.0}
    for now in (990.0, 990.4, 995.0, 999.2):
        asyncio.run(gather.lead_in(srv, item, now, "Fishing contest", "you'll be teleported there"))
    titles = [c for c in srv.cmds if c.startswith("title @a title")]
    assert [re.search(r'"text": "(\d+)"', t).group(1) for t in titles] == ["10", "5", "1"]
    assert any("starts in 10 seconds" in c for c in srv.cmds)


def test_there_and_back_again(g):
    gather, srv = g
    spot = gather.clean_spot({"x": 0, "y": 79, "z": 0, "r": 3})
    back = asyncio.run(gather.send(srv, spot))
    assert back["Tyler"] == {"x": 10.0, "y": 70.0, "z": 10.0, "d": "minecraft:overworld"}
    assert all(abs(srv.pos[n][0]) <= 3.6 and abs(srv.pos[n][2]) <= 3.6 and srv.pos[n][1] == pytest.approx(80.1) for n in srv.online)
    gather.come_home(srv, back, "Fishing contest", delay=10)
    d = gather._load(); d["returns"][0]["at"] = time.time() + 4.5; gather._save(d)
    asyncio.run(gather.tick([srv]))                                       # a countdown first
    assert any(c.startswith("title Tyler title") and '"5"' in c for c in srv.cmds) and srv.pos["Tyler"][0] != 10.0
    srv.online.remove("Gimli_Jr")                                          # Gimli logs off before the trip home
    d = gather._load(); d["returns"][0]["at"] = time.time() - 1; gather._save(d)
    asyncio.run(gather.tick([srv]))
    assert srv.pos["Tyler"] == [10.0, 70.0, 10.0] and not gather._load()["returns"]
    assert "Gimli_Jr" in gather._load()["owed"]["g-srv"]
    srv.online.append("Gimli_Jr")
    asyncio.run(gather.on_join(srv, "Gimli_Jr"))
    assert srv.pos["Gimli_Jr"] == [-5.0, 64.0, 3.0] and not gather._load()["owed"]["g-srv"]


def test_nobody_stays_frozen(g):
    gather, srv = g
    asyncio.run(gather.freeze(srv, ["Tyler"], 10))
    assert "attribute Tyler minecraft:movement_speed modifier add solstone:freeze -1 add_multiplied_total" in srv.cmds
    d = gather._load(); d["frozen"][0]["until"] = time.time() - 1; gather._save(d)   # GO never came (Solstone away)
    asyncio.run(gather.tick([srv]))
    assert "attribute Tyler minecraft:jump_strength modifier remove solstone:freeze" in srv.cmds and not gather._load()["frozen"]


def test_line_up_across_the_way(g):
    gather, srv = g
    asyncio.run(gather.line_up(srv, {"x": 0, "y": 79, "z": 0}, {"x": 0, "y": 79, "z": 50}, "minecraft:overworld", ["Tyler", "Gimli_Jr"]))
    xs = sorted(round(srv.pos[n][0]) for n in ("Tyler", "Gimli_Jr"))
    assert xs == [-1, 1] and all(round(srv.pos[n][2]) == 0 for n in ("Tyler", "Gimli_Jr"))     # side by side, across a north-south run
