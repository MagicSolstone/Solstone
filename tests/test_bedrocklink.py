"""A Bedrock account linked to a Java one (Floodgate's global linking), read from GeyserMC (faked here)."""
import asyncio

from app import bedrocklink
from app import servers as S

BEDROCK = "00000000-0000-0000-0009-01234abcdef0"          # Floodgate's id for an Xbox account


def test_link_lookup_and_memory(monkeypatch):
    calls = []

    async def fake(xuid):
        calls.append(xuid)
        return {"java_uuid": "069a79f4-44e9-4726-a5be-fca90e38aaf5", "java_name": "Tyler"}
    monkeypatch.setattr(bedrocklink, "_fetch", fake)
    bedrocklink._cache.clear()
    link = asyncio.run(bedrocklink.linked_java(BEDROCK))
    assert link["java_name"] == "Tyler" and calls == [int("901234abcdef0", 16)]
    asyncio.run(bedrocklink.linked_java(BEDROCK))
    assert len(calls) == 1                                                      # remembered
    assert asyncio.run(bedrocklink.linked_java("069a79f4-44e9-4726-a5be-fca90e38aaf5")) is None   # a Java player: no lookup
    assert asyncio.run(bedrocklink.bedrock_for("069a79f4-44e9-4726-a5be-fca90e38aaf5", [BEDROCK])) == [BEDROCK]
    bedrocklink._cache.clear()


def test_link_on_the_player_pages(client, sid, tyler, monkeypatch):
    real = S.known_players

    def with_bedrock(srv):
        out = dict(real(srv))
        out[S.norm_uuid(BEDROCK)] = {"uuid": BEDROCK, "name": ".TylerPhone"}
        return out
    monkeypatch.setattr(S, "known_players", with_bedrock)

    async def fake(xuid):
        return {"java_uuid": tyler, "java_name": "Tyler"}
    monkeypatch.setattr(bedrocklink, "_fetch", fake)
    bedrocklink._cache.clear()
    try:
        r = client.get(f"/api/servers/{sid}/players/{BEDROCK}/link").json()
        assert r["bedrock"] and r["plays_as"]["name"] == "Tyler" and r["plays_as"]["here"]
        r = client.get(f"/api/servers/{sid}/players/{tyler}/link").json()
        assert not r["bedrock"] and [x["name"] for x in r["linked_bedrock"]] == [".TylerPhone"]

        async def none(xuid):
            return None
        monkeypatch.setattr(bedrocklink, "_fetch", none)
        bedrocklink._cache.clear()
        assert client.get(f"/api/servers/{sid}/players/{BEDROCK}/link").json()["plays_as"] is None

        async def down(xuid):
            import httpx
            raise httpx.ConnectError("no network")
        monkeypatch.setattr(bedrocklink, "_fetch", down)
        bedrocklink._cache.clear()
        assert "GeyserMC" in client.get(f"/api/servers/{sid}/players/{BEDROCK}/link").json()["error"]
    finally:
        bedrocklink._cache.clear()
