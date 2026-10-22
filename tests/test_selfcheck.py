"""The compatibility check runs every step, cleans up after itself, and flags what the game refuses."""
import asyncio

import pytest


class Srv:
    """Answers the way a healthy 26.3 server would, except for anything listed in `refuse`."""
    is_java = True

    def __init__(self, refuse=()):
        self.id, self.mc_version, self.refuse, self.cmds = "ck", "26.3", refuse, []

    def rcon_conf(self):
        return {"host": "x"}

    async def rcon(self, cmd):
        self.cmds.append(cmd)
        if any(r in cmd for r in self.refuse):
            return "Incorrect argument for command ...<--[HERE]"
        if cmd == "list":
            return "There are 1 of a max of 10 players online: Tyler"
        if cmd.startswith("scoreboard players get"):
            return "#check has 5 [Solstone check]"
        if cmd.startswith("bossbar get"):
            return "Custom bossbar [Check] has a value of 50"
        if "data get entity" in cmd and " text" in cmd:
            return 'Text Display has the following entity data: {text: "Solstone check", color: "gold"}'
        if "data get entity" in cmd and "Pos" in cmd:
            return "Marker has the following entity data: [3.5d, 70.0d, 3.5d]"
        if "data get block" in cmd:
            return '3, 318, 3 has the following block data: [{Slot: 0b, id: "minecraft:diamond", count: 3}]'
        if " if block " in cmd:
            return "Test passed"
        if "storage solstone:fish pack" in cmd or "storage solstone:games pack" in cmd:
            return "Storage has the following contents: {version: 99}"
        if "storage solstone:games spleef" in cmd:
            return "Found no elements matching spleef"
        if cmd.startswith(("give", "clear", "effect", "gamemode", "title", "tellraw", "advancement")):
            return "No player was found"
        return "ok"


@pytest.fixture()
def patched(monkeypatch, tmp_path):
    from app import fishing, selfcheck, worldmap
    from app import servers as S
    monkeypatch.setattr(S, "world_info", lambda srv, dims=False: {"spawn": {"x": 0, "y": 64, "z": 0}})
    monkeypatch.setattr(S, "known_players", lambda srv: {})
    monkeypatch.setattr(fishing, "files", lambda srv: [])

    async def catch(srv):
        return {"rod": [{"pack_fish": {"name": "Bluegill"}}, {}], "probe": {"probe": True}}
    monkeypatch.setattr(fishing, "test_catch", catch)
    monkeypatch.setattr(worldmap, "check", lambda *a: {"checked": [{"picture": "drawn"}], "regions": 4})
    return selfcheck


def _run(selfcheck, srv):
    srv.world_dir = None
    return asyncio.run(selfcheck.run(srv, [], None))


def test_healthy_server_all_green_and_tidied(patched):
    srv = Srv()
    out = _run(patched, srv)
    bad = [r for r in out["rows"] if r["ok"] is False]
    assert not bad, bad
    assert len(out["rows"]) >= 25
    assert "kill @e[tag=solstone_check]" in srv.cmds and any("forceload remove" in c for c in srv.cmds)
    assert "scoreboard objectives remove solcheck" in srv.cmds and "bossbar remove solstone:check" in srv.cmds and "team remove solcheck" in srv.cmds
    assert not any(c.startswith(("give @a ", "give Tyler", "tellraw @a ")) for c in srv.cmds)      # nothing reaches real players


def test_a_changed_command_is_flagged_with_what_the_game_said(patched):
    srv = Srv(refuse=("nametagVisibility", "waypoint modify"))
    rows = {r["label"]: r for r in _run(patched, srv)["rows"]}
    assert rows["Teams"]["ok"] is False and "nametagVisibility" in rows["Teams"]["detail"] and "<--[HERE]" in rows["Teams"]["detail"]
    assert rows["Dots on the locator bar"]["ok"] is False
    assert rows["Boss bar countdown"]["ok"] is True


def test_no_rcon_stops_early(patched):
    class Dead(Srv):
        async def rcon(self, cmd):
            return ""
    rows = _run(patched, Dead())["rows"]
    assert len(rows) == 1 and rows[0]["ok"] is False and "rcon" in rows[0]["fix"].lower()
