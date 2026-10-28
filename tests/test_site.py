"""The public website: site details and posts (news, guides, FAQ)."""


def test_site_details_public_and_admin_only_to_change(client, viewer, anon):
    r = client.put("/api/settings/site", json={"name": "Solstone SMP", "java_address": "play.example.net",
                                                "bedrock_address": "play.example.net", "bedrock_port": "19132",
                                                "discord": "https://evil.example/x"})
    assert r.status_code == 200 and r.json()["discord"] == ""           # only Discord invite links
    d = anon.get("/api/public/site").json()
    assert d["name"] == "Solstone SMP" and d["bedrock_port"] == 19132 and "servers" in d
    assert viewer.put("/api/settings/site", json={"name": "x"}).status_code == 403
    assert anon.put("/api/settings/site", json={"name": "x"}).status_code == 401


def test_posts_drafts_slugs_and_categories(client, viewer, anon):
    a = client.post("/api/posts", json={"title": "How to join", "body": "Use **Java** or Bedrock.", "category": "guide"}).json()
    b = client.post("/api/posts", json={"title": "How to join", "body": "Again", "category": "faq"}).json()
    draft = client.post("/api/posts", json={"title": "Secret plans", "body": "soon", "published": False}).json()
    assert a["slug"] == "how-to-join" and b["slug"] == "how-to-join-2"
    assert client.post("/api/posts", json={"title": "", "body": "x"}).status_code == 400
    guides = anon.get("/api/public/posts?category=guide").json()
    assert [p["slug"] for p in guides] == ["how-to-join"] and "excerpt" in guides[0] and "body" not in guides[0]
    assert anon.get("/api/public/posts/how-to-join").json()["body"].startswith("Use")
    assert anon.get(f"/api/public/posts/{draft['slug']}").status_code == 404     # drafts stay hidden
    assert all(p["slug"] != draft["slug"] for p in anon.get("/api/public/posts").json())
    assert viewer.post("/api/posts", json={"title": "x", "body": "y"}).status_code == 403
    r = client.put(f"/api/posts/{draft['id']}", json={"title": "Big plans", "body": "now", "published": True, "pinned": True})
    assert r.json()["slug"] == "big-plans"
    assert anon.get("/api/public/posts").json()[0]["slug"] == "big-plans"            # pinned first
    for p in (a, b, draft):
        assert client.delete(f"/api/posts/{p['id']}").status_code == 200
    assert client.delete(f"/api/posts/{a['id']}").status_code == 404


def test_site_logo(client, anon, viewer):
    import struct
    import zlib

    def png():
        raw = b"\x00\xff\x00\x00\xff"
        chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))  # noqa: E731
        return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")

    assert anon.get("/api/public/logo").status_code == 404
    assert '<link rel="icon" href="/static/solstone.svg">' in anon.get("/").text
    assert viewer.post("/api/settings/site/logo", content=png()).status_code == 403
    bad = client.post("/api/settings/site/logo", content=b"<svg onload=alert(1)></svg>")
    assert bad.status_code == 400                                          # pictures only, never SVG
    url = client.post("/api/settings/site/logo", content=png(), headers={"Content-Type": "image/png"}).json()["logo"]
    try:
        assert url.startswith("/api/public/logo?v=")
        r = anon.get("/api/public/logo")
        assert r.status_code == 200 and r.headers["content-type"] == "image/png" and r.headers["x-content-type-options"] == "nosniff"
        assert url in anon.get("/").text and url in anon.get("/app").text
    finally:
        assert client.delete("/api/settings/site/logo").json()["logo"] == "/static/solstone.svg"
    assert anon.get("/api/public/logo").status_code == 404


def test_guides_in_your_own_words(client, anon):
    try:
        client.put("/api/settings/site", json={"guide_join": "Join at **{java_address}** port {bedrock_port}. {ask}", "guide_account": ""})
        s = anon.get("/api/public/site").json()
        assert s["guide_join"].startswith("Join at **{java_address}**") and s["guide_account"] == ""   # filled in on the page
    finally:
        client.put("/api/settings/site", json={"guide_join": "", "guide_account": ""})


def test_ask_to_join(client, anon, monkeypatch):
    from app import main, notify, signup
    sent = []

    async def fake_send(title, message, tag="video_game", force=False, sid=None):
        sent.append((title, message))
        return []
    monkeypatch.setattr(notify, "send", fake_send)
    signup._sent.clear()
    assert anon.post("/api/public/join-request", json={"player": "NewKid"}).status_code == 404       # off to start
    client.put("/api/settings/site", json={"join_requests": True})
    try:
        r = anon.post("/api/public/join-request", json={"player": "NewKid", "name": "Sam", "note": "Tyler's cousin"})
        assert r.status_code == 200
        assert sent and "NewKid" in sent[-1][1] and "Sam" in sent[-1][1] and "Tyler's cousin" in sent[-1][1]
        assert anon.post("/api/public/join-request", json={"player": "Cool Kid 7", "edition": "bedrock"}).status_code == 200
        assert any(r["player"] == ".Cool_Kid_7" for r in main.site.join_requests())       # their name on the server
        assert anon.post("/api/public/join-request", json={"player": "Has Space"}).status_code == 400   # Java names have none
        assert anon.post("/api/public/join-request", json={"player": "x<script>"}).status_code == 400
        assert anon.post("/api/public/join-request", json={"player": "Third"}).status_code == 200
        assert anon.post("/api/public/join-request", json={"player": "Fourth"}).status_code == 429      # a few an hour
    finally:
        client.put("/api/settings/site", json={"join_requests": False})
        main.settings_store.save_section("join_requests", [])
        signup._sent.clear()


def test_asking_shows_only_you_when_youre_in(client, anon, monkeypatch, sid):
    from app import main, notify, signup

    async def fake_send(*a, **k):
        return []
    monkeypatch.setattr(notify, "send", fake_send)
    signup._sent.clear()
    client.put("/api/settings/site", json={"join_requests": True})
    try:
        r = anon.post("/api/public/join-request", json={"player": "Ticket_Kid"}).json()
        st = lambda t: anon.post("/api/public/join-request/status", json={"token": t}).json()   # noqa: E731
        w = st(r["token"])
        assert w["state"] == "waiting" and w["player"] == "Ticket_Kid" and [s["in"] for s in w["servers"]] == [False]
        assert st("not-their-ticket")["state"] == "unknown" and st("")["state"] == "unknown"    # nobody else can look
        main.site.mark_let_in("Ticket_Kid", sid)                                                # what Let them in does
        done = st(r["token"])
        assert done["state"] == "in" and done["servers"][0]["in"] is True
        assert st(r["token"])["state"] == "in"                                                  # and it stays that way
    finally:
        client.put("/api/settings/site", json={"join_requests": False})
        main.settings_store.save_section("join_requests", [])
        main.settings_store.save_section("join_let_in", [])
        signup._sent.clear()


def test_pictures_in_posts(client, anon):
    import io

    from PIL import Image
    buf = io.BytesIO(); Image.new("RGB", (8, 8), (200, 40, 40)).save(buf, "PNG")
    up = client.post("/api/posts/images", content=buf.getvalue(), headers={"Content-Type": "image/png"})
    assert up.status_code == 200 and up.json()["url"].startswith("/api/public/images/")
    url = up.json()["url"]
    got = anon.get(url)
    assert got.status_code == 200 and got.headers["content-type"] == "image/png" and "immutable" in got.headers["cache-control"]
    assert client.post("/api/posts/images", content=b"<svg onload=alert(1)>", headers={"Content-Type": "image/svg+xml"}).status_code == 400
    assert anon.post("/api/posts/images", content=buf.getvalue()).status_code in (401, 403)
    assert anon.get("/api/public/images/../../secret.png").status_code in (401, 404)
    assert anon.get("/api/public/images/settings.json").status_code == 404
    p = client.post("/api/posts", json={"title": "Look at this", "category": "news", "body": f"Our build:\n\n![tower picture]({url})\n\nNice!"}).json()
    try:
        card = next(x for x in anon.get("/api/public/posts?category=news").json() if x["id"] == p["id"])
        assert card["image"] == url and "tower" not in card["excerpt"] and "Our build" in card["excerpt"]
    finally:
        client.delete(f"/api/posts/{p['id']}")


def test_a_second_server_with_its_own_way_in(client, anon, sid):
    try:
        r = client.put(f"/api/servers/{sid}/settings", json={"join_address": "mods.example.net:25566", "join_note": "Needs the modpack"})
        assert r.status_code == 200
        j = next(x for x in anon.get("/api/public/site").json()["joins"] if x["id"] == sid)
        assert j["java"] == "mods.example.net:25566" and j["bedrock"] == "" and j["note"] == "Needs the modpack"
        assert client.put(f"/api/servers/{sid}/settings", json={"join_bedrock_port": "lots"}).status_code == 400
        client.put(f"/api/servers/{sid}/settings", json={"private": True})
        assert not [x for x in anon.get("/api/public/site").json()["joins"] if x["id"] == sid]     # private: never public
    finally:
        client.put(f"/api/servers/{sid}/settings", json={"join_address": "", "join_note": "", "private": ""})


def test_join_box_mods_and_status(client, anon, sid):
    try:
        client.put(f"/api/servers/{sid}/settings", json={"join_address": "mods.example.net", "join_mods": True})
        s = anon.get("/api/public/site").json()
        j = next(x for x in s["joins"] if x["id"] == sid)
        assert j["mods"] is not None and "loader" in j["mods"] and isinstance(j["mods"]["list"], list)
        client.put(f"/api/servers/{sid}/settings", json={"join_mods": False})
        assert next(x for x in anon.get("/api/public/site").json()["joins"] if x["id"] == sid)["mods"] is None
        if s["servers"]:
            assert {"started", "tps", "running", "online", "max"} <= set(s["servers"][0])
    finally:
        client.put(f"/api/servers/{sid}/settings", json={"join_address": "", "join_mods": False})


def test_asking_for_some_servers(client, anon, monkeypatch, sid):
    from app import main, notify, signup

    async def fake_send(*a, **k):
        return []
    monkeypatch.setattr(notify, "send", fake_send)
    signup._sent.clear()
    client.put("/api/settings/site", json={"join_requests": True})
    try:
        assert anon.get("/api/public/site").json()["ask_servers"][0]["id"] == sid
        r = anon.post("/api/public/join-request", json={"player": "Picky_Kid", "servers": [sid, "not-a-server"]}).json()
        assert next(x for x in main.site.join_requests() if x["player"] == "Picky_Kid")["servers"] == [sid]
        assert [x["player"] for x in client.get(f"/api/servers/{sid}/control").json()["asked"]].count("Picky_Kid") == 1
        assert r["token"]
    finally:
        client.put("/api/settings/site", json={"join_requests": False})
        main.settings_store.save_section("join_requests", [])
        signup._sent.clear()
