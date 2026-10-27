"""Log lines from Bedrock players (Geyser + Floodgate put a dot in front of their names) count like anyone's."""
from app import logparse


def test_bedrock_names_in_the_log():
    known = {"tyler", ".steve_k"}
    j = logparse.parse_line("[12:00:00] [Server thread/INFO]: .Steve_K joined the game", known)
    assert j and j.type == "join" and j.player == ".Steve_K"
    a = logparse.parse_line("[12:01:00] [Server thread/INFO]: .Steve_K has made the advancement [Stone Age]", known)
    assert a and a.type == "advancement" and a.player == ".Steve_K"
    d = logparse.parse_line("[12:02:00] [Server thread/INFO]: .Steve_K was slain by Zombie", known)
    assert d and d.type == "death" and d.player == ".Steve_K"
    c = logparse.parse_line("[12:03:00] [Server thread/INFO]: <.Steve_K> hi", known)
    assert c and c.type == "chat" and c.player == ".Steve_K"
    assert logparse.parse_line("[12:00:00] [Server thread/INFO]: Tyler joined the game", known).player == "Tyler"


def test_whitelist_turned_away():
    lines = ["[18:00:01] [Server thread/INFO]: NewKid (/10.0.0.5:51234) lost connection: You are not white-listed on this server!",
             "[18:00:02] [Server thread/INFO]: Disconnecting .Bedrock_Kid (/10.0.0.6:51235): You are not white-listed on this server!",
             "[18:00:03] [Server thread/INFO]: com.mojang.authlib.GameProfile@1a2b[id=<null>,name=Old_Style,properties={}] (/10.0.0.7:1) lost connection: You are not white-listed on this server!",
             "[18:00:04] [Server thread/INFO]: GameProfile[id=0000, name=Newer, properties={}] (/10.0.0.8:1) lost connection: You are not white-listed on this server"]
    got = [logparse.parse_line(x, set()) for x in lines]
    assert [g.player for g in got] == ["NewKid", ".Bedrock_Kid", "Old_Style", "Newer"]
    assert all(g.type == "blocked" and "10.0.0" not in g.message and "isn't on the whitelist" in g.message for g in got)
