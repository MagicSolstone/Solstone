"""Reminders in the game about what's waiting on the website: only when something is, and not too often."""
import asyncio
import json

from app import auth, community, db, nudge


def test_what_is_waiting(client):
    u = auth.create_user("ng_kid", "kid-pass-123", "player", check=False)
    auth.add_player(u.id, ("00000000-0000-0000-0000-0000000000n1", "NudgeKid"))
    p = community.create_poll({"question": "Snacks?", "options": ["Cake", "Pie"]})
    try:
        assert nudge.waiting("NudgeKid") == (0, 1)
        community.start(u.id, "message", "Hello", "Welcome!", True, "admin")
        assert nudge.waiting("nudgekid") == (1, 1)
        community.vote(p["id"], f"u{u.id}", p["options"][0]["id"])
        assert nudge.waiting("NudgeKid") == (1, 0)
        assert nudge.describe(2, 1) == "2 new messages and a vote" and nudge.describe(1, 0) == "1 new message"
        cmd = nudge.lines("&6✉ Waiting for you:&r {waiting}. {site}", "NudgeKid", "Family", 2, 1)[0]
        assert cmd.startswith("tellraw NudgeKid ") and "2 new messages and a vote" in cmd
        json.loads(cmd.split(" ", 2)[2])
    finally:
        community.delete_poll(p["id"])
        auth.delete_user(u.id)


def test_on_join_only_when_something_waits_and_not_too_often(client, sid, monkeypatch):
    from app import servers as S
    srv = S.registry.servers[sid]
    sent = []

    async def fake_send(srv, cmds, delay=0):
        sent.append(cmds)
    monkeypatch.setattr(nudge.welcome, "send", fake_send)
    u = auth.create_user("ng_two", "kid-pass-123", "player", check=False)
    auth.add_player(u.id, ("00000000-0000-0000-0000-0000000000n2", "NudgeTwo"))
    db.x("DELETE FROM alerts WHERE key LIKE 'nudge%'")

    async def join():
        nudge.on_join(srv, "NudgeTwo")
        await asyncio.sleep(0)
    try:
        asyncio.run(join())
        assert sent == []                                                  # nothing waiting: nothing said
        community.start(u.id, "message", "Hi", "There's a contest on Saturday", True, "admin")
        asyncio.run(join())
        asyncio.run(join())                                                # joining again soon: not again
        assert len(sent) == 1 and "1 new message" in sent[0][0]
        nudge.on_join(srv, "NudgeTwo")                                    # no event loop (the log reader's thread)
        db.x("DELETE FROM alerts WHERE key LIKE 'nudge%'")
        nudge.save({"join": False})
        asyncio.run(join())
        assert len(sent) == 1                                              # switched off
    finally:
        nudge.save({"join": True})
        auth.delete_user(u.id)


def test_settings(client, viewer):
    assert viewer.get("/api/settings/nudge").status_code == 403
    r = client.put("/api/settings/nudge", json={"hours": 500, "join_text": "", "live": False}).json()
    assert r["hours"] == 72 and r["join_text"] == nudge.DEFAULTS["join_text"] and r["live"] is False
    client.put("/api/settings/nudge", json={"hours": 12, "live": True})
