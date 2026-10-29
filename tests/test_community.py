"""Votes (polls and build contests), event sign-ups and messages between players and the admins."""
import asyncio
import time

from fastapi.testclient import TestClient

from app import auth, community, main, votegame


def _player(name, mc):
    u = auth.create_user(name, "player-pass-1", "player", check=False)
    auth.add_player(u.id, (f"00000000-0000-0000-0000-{abs(hash(mc)) % 10**12:012d}", mc))
    c = TestClient(main.app, headers={"X-Solstone": "1"})
    assert c.post("/api/auth/login", json={"username": name, "password": "player-pass-1"}).status_code == 200
    return u, c


def test_poll_votes_totals_only(client):
    a, ca = _player("cm_anna", "AnnaMC")
    b, cb = _player("cm_ben", "BenMC")
    try:
        assert ca.post("/api/community/admin/votes", json={"question": "Q", "options": ["x", "y"]}).status_code == 403
        assert client.post("/api/community/admin/votes", json={"question": "Next build?", "options": ["Castle"]}).status_code == 400
        p = client.post("/api/community/admin/votes", json={"question": "Next build?", "options": ["Castle", "Theme park"]}).json()
        castle, park = (o["id"] for o in p["options"])
        v = ca.get("/api/community/votes").json()["open"][0]
        assert v["question"] == "Next build?" and "counts" not in v                    # nothing shown before voting
        r = ca.post(f"/api/community/votes/{p['id']}", json={"option": castle}).json()
        assert r["counts"] == {castle: 1, park: 0} and r["mine"] == castle
        ca.post(f"/api/community/votes/{p['id']}", json={"option": park})                # changed their mind
        cb.post(f"/api/community/votes/{p['id']}", json={"option": park})
        r = cb.get("/api/community/votes").json()["open"][0]
        assert r["counts"] == {castle: 0, park: 2} and r["total"] == 2
        assert "voter" not in str(r) and "cm_anna" not in str(r)                         # never who voted for what
        assert ca.post(f"/api/community/votes/{p['id']}", json={"option": "nope"}).status_code == 400
        # closing: a result, and a notice to everyone who voted
        res = client.post(f"/api/community/admin/votes/{p['id']}/close").json()
        assert res["result"] == "Theme park won, with 2 votes."
        assert ca.post(f"/api/community/votes/{p['id']}", json={"option": castle}).status_code == 400
        threads = ca.get("/api/community/messages").json()["threads"]
        assert threads[0]["kind"] == "notice" and "Vote closed" in threads[0]["subject"]
        assert ca.get("/api/community/unread").json()["mine"] >= 1
        client.delete(f"/api/community/admin/votes/{p['id']}")
    finally:
        auth.delete_user(a.id)
        auth.delete_user(b.id)


def test_build_contest_no_voting_for_your_own(client):
    a, ca = _player("cm_cleo", "CleoMC")
    try:
        assert client.post("/api/community/admin/votes", json={"kind": "build", "question": "Best build",
                                                                "options": [{"text": "Castle"}, {"text": "Farm"}]}).status_code == 400
        p = client.post("/api/community/admin/votes", json={"kind": "build", "question": "Best build", "results": "closed",
                                                             "options": [{"text": "Castle", "builders": ["CleoMC", "Tyler"]},
                                                                         {"text": "Farm", "builders": ["Gimli_Jr"]}]}).json()
        castle, farm = (o["id"] for o in p["options"])
        v = ca.get("/api/community/votes").json()["open"][0]
        assert v["own"] == [castle]
        r = ca.post(f"/api/community/votes/{p['id']}", json={"option": castle})
        assert r.status_code == 400 and "you made" in r.json()["detail"]
        r = ca.post(f"/api/community/votes/{p['id']}", json={"option": farm}).json()
        assert "counts" not in r                                                          # results only when it closes
        # in the game: a builder can't either, by any of their names
        assert community.own_entries(community.get_poll(p["id"]), "p:tyler") == [castle]
        community.close_now(p["id"])
        assert "Farm (built by Gimli_Jr) won" in community.result_text(community.get_poll(p["id"]))
        client.delete(f"/api/community/admin/votes/{p['id']}")
    finally:
        auth.delete_user(a.id)


def test_vote_in_the_game(client, sid, monkeypatch):
    from app import servers as S
    srv = S.registry.servers[sid]
    rcon = {"cmds": []}

    async def fake(cmd):
        rcon["cmds"].append(cmd)
        return ""
    monkeypatch.setattr(srv, "rcon", fake)
    monkeypatch.setattr(srv, "rcon_conf", lambda: {"port": 1})
    p = client.post("/api/community/admin/votes", json={"question": "Pets?", "options": ["Cats", "Dogs"]}).json()
    try:
        rcon["cmds"].clear()
        asyncio.run(votegame.on_chat(srv, "Gimli_Jr", "!vote 2"))
        assert community.tally(p["id"]) == {p["options"][1]["id"]: 1}
        assert any("You voted for Dogs" in c for c in rcon["cmds"])
        asyncio.run(votegame.on_chat(srv, "Gimli_Jr", "!vote 9"))
        assert any("from 1 to 2" in c for c in rcon["cmds"])
        asyncio.run(votegame.on_chat(srv, "Gimli_Jr", "hello"))                       # just chat
        assert community.tally(p["id"]) == {p["options"][1]["id"]: 1}
        # announced once, and closed when its time is up
        rcon["cmds"].clear()
        asyncio.run(votegame.tick([srv]))
        assert sum("New vote" in c for c in rcon["cmds"]) == 1
        community.update_poll(p["id"], {**p, "closes_ts": time.time() - 1})
        asyncio.run(votegame.tick([srv]))
        assert any("Vote closed" in c and "Dogs won" in c for c in rcon["cmds"])
    finally:
        client.delete(f"/api/community/admin/votes/{p['id']}")


def test_messages_only_between_a_player_and_admins(client):
    a, ca = _player("cm_dana", "DanaMC")
    b, cb = _player("cm_eli", "EliMC")
    try:
        assert ca.post("/api/community/messages", json={"kind": "idea", "subject": "A zoo", "body": ""}).status_code == 400
        tid = ca.post("/api/community/messages", json={"kind": "idea", "subject": "A zoo", "body": "Can we build a zoo?"}).json()["id"]
        assert cb.get(f"/api/community/messages/{tid}").status_code == 404                # someone else's
        assert cb.post(f"/api/community/messages/{tid}", json={"body": "hi"}).status_code == 404
        inbox = client.get("/api/community/admin/messages").json()
        t = next(x for x in inbox["threads"] if x["id"] == tid)
        assert t["with"] == "DanaMC" and t["unread_admin"] and t["subject"] == "💡 Idea: A zoo"
        assert client.get("/api/community/unread").json()["admin"] >= 1
        assert ca.get("/api/community/admin/messages").status_code == 403
        client.get(f"/api/community/messages/{tid}")                                      # the admin reads it
        client.post(f"/api/community/messages/{tid}", json={"body": "Great idea!"})
        assert ca.get("/api/community/unread").json()["mine"] == 1
        th = ca.get(f"/api/community/messages/{tid}").json()
        assert [m["from_admin"] for m in th["messages"]] == [False, True] and ca.get("/api/community/unread").json()["mine"] == 0
        # admins write first, to one or every player
        r = client.post("/api/community/admin/messages", json={"to": [b.id], "subject": "You won!", "body": "Well done."}).json()
        assert r["sent"] == 1 and cb.get("/api/community/messages").json()["threads"][0]["subject"] == "You won!"
        assert client.post("/api/community/admin/messages", json={"to": [], "subject": "x", "body": "y"}).status_code == 400
        # no flooding
        for _ in range(10):
            ca.post(f"/api/community/messages/{tid}", json={"body": "more"})
        assert ca.post(f"/api/community/messages/{tid}", json={"body": "more"}).status_code == 429
    finally:
        auth.delete_user(a.id)
        auth.delete_user(b.id)


def test_event_signups(client):
    a, ca = _player("cm_finn", "FinnMC")
    try:
        key = community.event_key("contest", "Fishing contest", 1800000000)
        assert ca.post("/api/community/signup", json={"event": key, "coming": True}).status_code == 200
        assert ca.post("/api/community/signup", json={"event": "nope", "coming": True}).status_code == 400
        assert community.signups([key]) == {key: [a.id]}
        ca.post("/api/community/signup", json={"event": key, "coming": False})
        assert community.signups([key]) == {}
    finally:
        auth.delete_user(a.id)


def test_reading_removing_archiving_and_old_notices(client):
    a, ca = _player("cm_gwen", "GwenMC")
    try:
        assert client.post("/api/community/messages", json={"body": "to myself"}).status_code == 400   # admins: Manage → Messages
        tid = ca.post("/api/community/messages", json={"kind": "question", "body": "When is the contest?"}).json()["id"]
        client.get(f"/api/community/messages/{tid}")
        assert not next(t for t in client.get("/api/community/admin/messages").json()["threads"] if t["id"] == tid)["unread_admin"]
        client.post(f"/api/community/messages/{tid}", json={"body": "Saturday!"})
        ca.delete(f"/api/community/messages/{tid}")                                   # removed from their list...
        assert ca.get("/api/community/messages").json()["threads"] == [] and ca.get("/api/community/unread").json()["mine"] == 0
        assert any(t["id"] == tid for t in client.get("/api/community/admin/messages").json()["threads"])   # ...the admins keep it
        client.post(f"/api/community/admin/messages/{tid}/archive", json={"archived": True})
        assert next(t for t in client.get("/api/community/admin/messages").json()["threads"] if t["id"] == tid)["archived"]
        client.post(f"/api/community/messages/{tid}", json={"body": "See you there"})            # written again: back for both
        assert ca.get("/api/community/messages").json()["threads"][0]["id"] == tid
        assert not next(t for t in client.get("/api/community/admin/messages").json()["threads"] if t["id"] == tid)["archived"]
        client.delete(f"/api/community/messages/{tid}")                                # an admin deletes it for everyone
        assert ca.get(f"/api/community/messages/{tid}").status_code == 404
        # notices go after a month
        n = community.notice(a.id, "Vote closed", "Cats won")
        community.db.x("UPDATE threads SET updated_ts=? WHERE id=?", (time.time() - 31 * 86400, n))
        community._tidied = 0
        assert community.tidy() >= 1 and community.thread(n) is None
    finally:
        auth.delete_user(a.id)


def test_events_public_without_names_and_who_is_coming(client, anon, sid):
    import datetime as dt

    from app import board, challenges, db
    a, ca = _player("cm_hank", "HankMC")
    soon = time.time() + 3600
    c = challenges.create(sid, {"kind": "fish", "name": "Fishing night", "start": soon, "minutes": 30, "prize": {"item": "diamond", "count": 1},
                                "repeat": "weekly"})
    today = dt.date.fromtimestamp(time.time())
    keep = board.config()
    client.put("/api/board", json={"birthdays": [{"player": "HankMC", "month": today.month, "day": today.day}]})
    try:
        pub = anon.get("/api/public/upcoming").json()["items"]
        nights = [i for i in pub if i["title"] == "Fishing night"]
        assert len(nights) >= 4 and "every week" in nights[0]["detail"]                    # the next few Tuesdays, say
        assert all(i["kind"] != "birthday" for i in pub) and "HankMC" not in str(pub)    # no names in public
        assert all("key" not in i and "who" not in i for i in pub)
        key = next(i for i in ca.get("/api/upcoming").json()["items"] if i["title"] == "Fishing night")["key"]
        ca.post("/api/community/signup", json={"event": key, "coming": True})
        mine = next(i for i in ca.get("/api/upcoming").json()["items"] if i["key"] == key)
        assert mine["who"] == ["HankMC"] and mine["me"]                                  # players see who's coming
        assert "Events" in anon.get("/").text and 'href="/events" data-nav="events" data-signed-out>' in anon.get("/").text
        assert 'data-signed-out hidden>' in client.get("/").text
        assert anon.get("/events").status_code == 200
        # when it's over, the same one again a week on
        d = challenges._load()
        x = next(i for i in d["items"] if i["id"] == c["id"])
        x["state"] = "done"
        challenges._save(d)
        asyncio.run(challenges.tick([]))
        nxt = [i for i in challenges._load()["items"] if i["name"] == "Fishing night" and i["state"] == "scheduled"]
        assert len(nxt) == 1 and abs(nxt[0]["start"] - (soon + 7 * 86400)) < 1 and nxt[0]["repeat"] == "weekly"
        assert nxt[0]["prize"]["item"] == "minecraft:diamond" and db is not None
    finally:
        client.put("/api/board", json={"birthdays": keep["birthdays"]})
        d = challenges._load()
        d["items"] = [i for i in d["items"] if i["name"] != "Fishing night"]
        challenges._save(d)
        auth.delete_user(a.id)
