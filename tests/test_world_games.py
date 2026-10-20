"""World info across save formats (incl. 26.1 world clocks) and non-Minecraft servers."""
import asyncio
from pathlib import Path

import nbtlib
from nbtlib import Byte, Compound, Long, String

from app import servers as S


def _server(tmp: Path, level: dict, extras: dict | None = None, props: str = "level-name=world\n", type_="minecraft-java"):
    (tmp / "world" / "data" / "minecraft").mkdir(parents=True, exist_ok=True)
    (tmp / "server.properties").write_text(props)
    nbtlib.File(Compound({"Data": Compound(level)}), gzipped=True).save(tmp / "world" / "level.dat")
    for name, data in (extras or {}).items():
        nbtlib.File(Compound(data), gzipped=True).save(tmp / "world" / "data" / "minecraft" / f"{name}.dat")
    return S.Server(id=tmp.name, name=tmp.name, dir=tmp, type=type_)


def test_classic_daytime(tmp_path):
    srv = _server(tmp_path, {"DayTime": Long(24000 * 5 + 18000), "raining": Byte(0), "Time": Long(99)})
    w = S.world_info(srv)
    assert (w["day"], w["time_of_day"], w["time_source"], w["raining"]) == (6, 18000, "file", False)


def test_world_clocks_26_1(tmp_path):
    clocks = {"data": Compound({"clocks": Compound({"minecraft:overworld": Compound({"total_ticks": Long(24000 * 9 + 1000)})})})}
    weather = {"data": Compound({"raining": Byte(1), "thundering": Byte(0)})}
    rules = {"data": Compound({"rules": Compound({"minecraft:keep_inventory": String("true"), "minecraft:mob_griefing": String("false")})})}
    gen = {"data": Compound({"seed": Long(1234)})}
    srv = _server(tmp_path, {"LevelName": String("New World")},
                  {"world_clocks": clocks, "weather": weather, "game_rules": rules, "world_gen_settings": gen})
    w = S.world_info(srv)
    assert (w["day"], w["time_of_day"]) == (10, 1000)
    assert w["raining"] is True and w["seed"] == "1234"
    assert w["game_rules"]["minecraft:keep_inventory"] == "true"


def test_unknown_time_is_not_faked(tmp_path):
    w = S.world_info(_server(tmp_path, {"LevelName": String("x")}))
    assert w["day"] is None and w["time_source"] == "unknown" and w["raining"] is None


class _FakeRcon:
    def __init__(self, replies):
        self.replies = replies

    async def command(self, cmd):
        return self.replies.get(cmd, "Unknown or incomplete command, see below for error")


def _live(tmp_path, replies):
    srv = _server(tmp_path, {}, props="level-name=world\nenable-rcon=true\nrcon.password=pw\n")
    srv._rcon = _FakeRcon(replies)
    srv._rcon.host, srv._rcon.port, srv._rcon.password = srv.rcon_conf()
    S._live_world_cache.pop(srv.id, None)
    return asyncio.run(S.live_world(srv))


def test_live_time_old_commands(tmp_path):
    out = _live(tmp_path, {"time query daytime": "The time is 6000", "time query day": "The time is 77",
                           "time query gametime": "The time is 1849212", "seed": "Seed: [-42]"})
    assert (out["day"], out["time_of_day"], out["seed"], out["time_source"]) == (78, 6000, "-42", "live")


def test_live_time_world_clocks(tmp_path):
    out = _live(tmp_path, {"time query time": "The time is 222000", "seed": "Seed: [7]"})
    assert (out["day"], out["time_of_day"]) == (10, 6000)


def test_hytale_server_is_basic(tmp_path):
    (tmp_path / "HytaleServer.jar").write_text("")
    srv = S.Server(id="hy", name="Hytale", dir=tmp_path, type="hytale")
    assert srv.game == "hytale" and not srv.is_java and srv.rcon_conf() is None
    srv2 = S.Server(id="hy2", name="Hytale", dir=tmp_path, type="")
    assert srv2.game == "hytale"  # detected from files when Crafty gives no type
