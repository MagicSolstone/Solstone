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
