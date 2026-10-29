"""Reminders in the game about what's waiting on the website: only when something is, and not too often."""
import asyncio
import json
import time

from app import auth, community, nudge


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


def test_join_new_message_and_reminders(client, sid, monkeypatch):
    from app import servers as S
    srv = S.registry.servers[sid]
    sent = []

    async def fake_send(srv, cmds, delay=0):
        sent.append(cmds[0])
    monkeypatch.setattr(nudge.welcome, "send", fake_send)
    monkeypatch.setattr(srv, "rcon_conf", lambda: {"port": 1})
    online = []

    async def players(_s):
        return list(online), "rcon"
    monkeypatch.setattr(S, "online_players", players)
    u = auth.create_user("ng_two", "kid-pass-123", "player", check=False)
    auth.add_player(u.id, ("00000000-0000-0000-0000-0000000000n2", "NudgeTwo"))
    nudge._seen.clear()

    async def join():
        nudge.on_join(srv, "NudgeTwo")
        await asyncio.sleep(0)

    def tick(later=0):
        nudge._checked = 0
        monkeypatch.setattr(nudge.time, "time", lambda: real() + later)
        asyncio.run(nudge.tick([srv]))
    real = time.time
    try:
        asyncio.run(join())
        assert sent == []                                                  # nothing waiting: nothing said
        online.append("NudgeTwo")
        tick()
        assert sent == []
        community.start(u.id, "message", "Hi", "There's a contest on Saturday", True, "admin")
        tick()
        assert len(sent) == 1 and "new message on the website" in sent[0]  # a new message while playing: straight away
        tick(60)
        assert len(sent) == 1                                              # still waiting, but not yet an hour
        tick(3700)
        assert len(sent) == 2 and "1 new message" in sent[1]               # an hour on: reminded once
        tick(3800)
        assert len(sent) == 2
        # leaving and joining again: told at once, every time (but not twice for a dropped connection)
        online.clear()
        monkeypatch.setattr(nudge.time, "time", real)
        nudge._seen.clear()
        asyncio.run(join())
        asyncio.run(join())
        assert len(sent) == 3 and "1 new message" in sent[2]
        nudge.save({"join": False})
        nudge._seen.clear()
        asyncio.run(join())
        assert len(sent) == 3                                              # switched off
    finally:
        monkeypatch.setattr(nudge.time, "time", real)
        nudge.save({"join": True})
        nudge._seen.clear()
        auth.delete_user(u.id)


def test_settings(client, viewer):
    assert viewer.get("/api/settings/nudge").status_code == 403
    r = client.put("/api/settings/nudge", json={"repeat_minutes": 99999, "join_text": "", "live": False}).json()
    assert r["repeat_minutes"] == 1440 and r["join_text"] == nudge.DEFAULTS["join_text"] and r["live"] is False
    assert client.put("/api/settings/nudge", json={"repeat_minutes": 0}).json()["repeat_minutes"] == 0
    client.put("/api/settings/nudge", json={"repeat_minutes": 60, "live": True})


def test_invitation_to_make_an_account(client, sid, monkeypatch):
    """Only players without an account, only while sign-up is open, as often as set (once a day to start)."""
    from app import db, site
    from app import servers as S
    srv = S.registry.servers[sid]
    sent = []

    async def fake_send(srv, cmds, delay=0):
        sent.append(cmds[0])
    monkeypatch.setattr(nudge.welcome, "send", fake_send)
    signup = {"on": True}
    real_cfg = site.config
    monkeypatch.setattr(site, "config", lambda: {**real_cfg(), "signup": signup["on"]})
    u = auth.create_user("ng_three", "kid-pass-123", "player", check=False)
    auth.add_player(u.id, ("00000000-0000-0000-0000-0000000000n3", "HasAccount"))
    db.x("DELETE FROM alerts WHERE key LIKE 'nudge-signup:%'")

    def join(name):
        nudge._seen.clear()

        async def go():
            nudge.on_join(srv, name)
            await asyncio.sleep(0)
        asyncio.run(go())
    try:
        assert nudge.config()["signup"] == "day"
        join("NoAccount")
        assert len(sent) == 1 and "Make a free account" in sent[0] and sent[0].startswith("tellraw NoAccount ")
        join("NoAccount")
        assert len(sent) == 1                                   # once a day
        join("HasAccount")
        assert len(sent) == 1                                   # already has one: never
        nudge.save({"signup": "every", "signup_text": "&aSign up at {site}!"})
        join("NoAccount")
        assert len(sent) == 2 and "Sign up at" in sent[1]
        signup["on"] = False
        join("NoAccount")
        assert len(sent) == 2                                   # sign-up closed: nothing to invite them to
        signup["on"] = True
        nudge.save({"signup": "off"})
        join("NoAccount")
        assert len(sent) == 2
        assert client.put("/api/settings/nudge", json={"signup": "first", "signup_text": ""}).json()["signup_text"] == nudge.DEFAULTS["signup_text"]
    finally:
        nudge.save({"signup": "day", "signup_text": nudge.DEFAULTS["signup_text"]})
        nudge._seen.clear()
        auth.delete_user(u.id)
