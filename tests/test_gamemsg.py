"""Messages an admin sends into the game: now, at everyone's next join, or to one player when they're next on."""
import asyncio

from app import gamemsg, settings_store


class FakeServer:
    id = "gm-test"
    display_name = "Test"


def test_send_now_queue_for_everyone_and_for_one_player(monkeypatch):
    said = []

    async def run(srv, cmd):
        said.append(cmd)
    from app import control
    monkeypatch.setattr(control, "run", run)
    srv = FakeServer()
    settings_store.save_section(gamemsg.SECTION, [])
    try:
        now = asyncio.run(gamemsg.create(srv, "&6Hello {player}", "online", "", "admin", ["Alex", "Sam"]))
        assert now["done"] and set(now["sent"]) == {"Alex", "Sam"} and any("Hello Alex" in c for c in said)
        later = asyncio.run(gamemsg.create(srv, "Movie night!", "next", "", "admin", ["Alex"]))
        assert not later["done"] and list(later["sent"]) == ["Alex"]                # the one on now gets it straight away
        one = asyncio.run(gamemsg.create(srv, "Your prize is here", "player", "Kid", "admin", ["Alex"]))
        assert not one["done"] and not one["sent"]                                  # not on: waiting
        assert [x["text"] for x in gamemsg.due("gm-test", "kid")] == ["Movie night!", "Your prize is here"]
        assert not gamemsg.due("gm-test", "alex")                                   # already had it
        said.clear()
        assert asyncio.run(gamemsg.deliver(srv, "Kid", delay=0)) == 2 and len(said) == 2
        assert not gamemsg.due("gm-test", "Kid")                                     # once each
        mine = {x["id"]: x for x in gamemsg.listing("gm-test")}
        assert mine[one["id"]]["done"] and "Kid" in mine[later["id"]]["sent"] and not mine[later["id"]]["done"]
        assert gamemsg.remove("gm-test", later["id"]) and not gamemsg.due("gm-test", "Newbie")
    finally:
        settings_store.save_section(gamemsg.SECTION, [])


def test_game_messages_api_is_admin_only(client, viewer, sid):
    assert viewer.get(f"/api/servers/{sid}/game-messages").status_code == 403
    assert client.get(f"/api/servers/{sid}/game-messages").json() == {"messages": []}
    r = client.post(f"/api/servers/{sid}/game-messages", json={"text": "Hi", "to": "online"})
    assert r.status_code == 400 and "Nobody" in r.json()["detail"]                   # nobody on in the tests
    m = client.post(f"/api/servers/{sid}/game-messages", json={"text": "Hi", "to": "player", "player": "Tyler"}).json()
    assert m["player"] == "Tyler" and not m["done"]
    assert client.delete(f"/api/servers/{sid}/game-messages/{m['id']}").json() == {"ok": True}
