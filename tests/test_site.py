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


def test_guides_in_your_own_words_become_posts(client, anon):
    """Guides rewritten in the old Rules and guides tab move into Posts (once), as the post standing in for that guide."""
    from app import main
    try:
        client.put("/api/settings/site", json={"guide_join": "Join at **{java_address}** port {bedrock_port}. {ask}", "guide_account": ""})
        main.site._moved = False
        s = anon.get("/api/public/site").json()
        assert s["guide_join"] == "" and "join" in s["guide_posts"]
        p = anon.get(f"/api/public/posts/{s['guide_posts']['join']}").json()
        assert p["role"] == "join" and p["category"] == "guide" and p["body"].startswith("Join at **{java_address}**")   # filled in on the page
        assert anon.get("/api/public/site").json()["guide_posts"]["join"] == p["slug"]                                # only once
    finally:
        client.put("/api/settings/site", json={"guide_join": "", "guide_account": ""})
        for x in client.get("/api/posts").json()["posts"]:
            if x.get("role"):
                client.delete(f"/api/posts/{x['id']}")


def test_one_post_per_guide(client, anon):
    a = client.post("/api/posts", json={"title": "Our rules", "category": "guide", "body": "Be kind.", "role": "rules"}).json()
    b = client.post("/api/posts", json={"title": "New rules", "category": "guide", "body": "Be kinder.", "role": "rules"}).json()
    try:
        assert anon.get("/api/public/site").json()["guide_posts"]["rules"] == b["slug"]
        assert next(x for x in client.get("/api/posts").json()["posts"] if x["id"] == a["id"])["role"] is None   # taken over
        client.put(f"/api/posts/{b['id']}", json={"title": "New rules", "category": "guide", "body": "Be kinder.", "published": False, "role": "rules"})
        assert "rules" not in anon.get("/api/public/site").json()["guide_posts"]        # a draft doesn't stand in
        client.put(f"/api/posts/{b['id']}", json={"title": "New rules", "category": "guide", "body": "Be kinder."})       # role kept
        assert next(x for x in client.get("/api/posts").json()["posts"] if x["id"] == b["id"])["role"] == "rules"
    finally:
        client.delete(f"/api/posts/{a['id']}")
        client.delete(f"/api/posts/{b['id']}")


def test_ask_to_join(client, anon, monkeypatch):
    from app import main, notify, signup
    sent = []

    async def fake_send(title, message, tag="video_game", force=False, sid=None, click=None):
        sent.append((title, message, click))
        return []
    monkeypatch.setattr(notify, "send", fake_send)
    signup._sent.clear()
    assert anon.post("/api/public/join-request", json={"rules": True, "player": "NewKid"}).status_code == 404       # off to start
    client.put("/api/settings/site", json={"join_requests": True})
    try:
        r = anon.post("/api/public/join-request", json={"rules": True, "player": "NewKid", "name": "Sam", "note": "Tyler's cousin"})
        assert r.status_code == 200
        assert sent and "NewKid" in sent[-1][1] and "Sam" in sent[-1][1] and "Tyler's cousin" in sent[-1][1]
        assert sent[-1][2].endswith("/app#/manage/whitelist")                                   # tap → straight there
        assert anon.post("/api/public/join-request", json={"rules": True, "player": "Cool Kid 7", "edition": "bedrock"}).status_code == 200
        assert any(r["player"] == ".Cool_Kid_7" for r in main.site.join_requests())       # their name on the server
        assert anon.post("/api/public/join-request", json={"rules": True, "player": "Has Space"}).status_code == 400   # Java names have none
        assert anon.post("/api/public/join-request", json={"rules": True, "player": "x<script>"}).status_code == 400
        assert anon.post("/api/public/join-request", json={"rules": True, "player": "Third"}).status_code == 200
        assert anon.post("/api/public/join-request", json={"rules": True, "player": "Fourth"}).status_code == 429      # a few an hour
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
        r = anon.post("/api/public/join-request", json={"rules": True, "player": "Ticket_Kid"}).json()
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
        r = anon.post("/api/public/join-request", json={"rules": True, "player": "Picky_Kid", "servers": [sid, "not-a-server"]}).json()
        assert next(x for x in main.site.join_requests() if x["player"] == "Picky_Kid")["servers"] == [sid]
        assert [x["player"] for x in client.get(f"/api/servers/{sid}/control").json()["asked"]].count("Picky_Kid") == 1
        assert r["token"]
    finally:
        client.put("/api/settings/site", json={"join_requests": False})
        main.settings_store.save_section("join_requests", [])
        signup._sent.clear()


def test_one_join_card_per_server(client, anon, sid):
    client.put("/api/settings/site", json={"java_address": "play.example.net", "bedrock_address": "play.example.net"})
    try:
        j = next(x for x in anon.get("/api/public/site").json()["joins"] if x["id"] == sid)
        assert j["java"] == "play.example.net" and j["bedrock"] == "play.example.net"      # the main address, for the main server
        assert "status" in j
        client.put(f"/api/servers/{sid}/settings", json={"join_address": "mods.example.net"})
        j = next(x for x in anon.get("/api/public/site").json()["joins"] if x["id"] == sid)
        assert j["java"] == "mods.example.net" and j["bedrock"] == ""                      # its own wins
    finally:
        client.put(f"/api/servers/{sid}/settings", json={"join_address": ""})
        client.put("/api/settings/site", json={"java_address": "", "bedrock_address": ""})


def test_the_join_guide_uses_the_first_servers_addresses(client, anon, sid):
    try:
        client.put(f"/api/servers/{sid}/settings", json={"join_address": "play.family.net", "join_bedrock_address": "play.family.net", "join_bedrock_port": 19133})
        s = anon.get("/api/public/site").json()
        assert s["java_address"] == "play.family.net" and s["bedrock_port"] == 19133
    finally:
        client.put(f"/api/servers/{sid}/settings", json={"join_address": "", "join_bedrock_address": "", "join_bedrock_port": ""})


def test_main_server_first_with_its_colour(client, anon, sid):
    try:
        client.put(f"/api/servers/{sid}/settings", json={"join_address": "play.family.net", "join_color": "#FF8800"})
        assert client.put(f"/api/servers/{sid}/settings", json={"join_color": "red; background:url(x)"}).json().get("join_color") is None
        client.put(f"/api/servers/{sid}/settings", json={"join_color": "#ff8800"})
        client.put("/api/settings/site", json={"main_server": sid, "join_requests": True})
        s = anon.get("/api/public/site").json()
        assert s["joins"][0]["id"] == sid and s["joins"][0]["main"] is True and s["joins"][0]["color"] == "#ff8800"
        assert s["ask_servers"][0]["id"] == sid and s["ask_servers"][0]["main"] is True
    finally:
        client.put(f"/api/servers/{sid}/settings", json={"join_address": "", "join_color": ""})
        client.put("/api/settings/site", json={"main_server": "", "join_requests": False})


def test_whitelist_page_across_servers(client, anon, viewer, monkeypatch, sid):
    from app import main, notify, signup

    async def fake_send(*a, **k):
        return []
    monkeypatch.setattr(notify, "send", fake_send)
    signup._sent.clear()
    client.put("/api/settings/site", json={"join_requests": True})
    try:
        anon.post("/api/public/join-request", json={"rules": True, "player": "Both_Kid", "servers": [sid]})
        assert anon.get("/api/whitelist").status_code in (401, 403)
        assert viewer.get("/api/whitelist").status_code == 403                  # admins only
        d = client.get("/api/whitelist").json()
        assert any(s["id"] == sid for s in d["servers"]) and all("whitelist" in s for s in d["servers"])
        r = next(x for x in d["requests"] if x["player"] == "Both_Kid")
        assert [(x["id"], x["in"]) for x in r["servers"]] == [(sid, False)]
        main.site.mark_let_in("Both_Kid", sid)
        assert not any(x["player"] == "Both_Kid" for x in client.get("/api/whitelist").json()["requests"])   # done everywhere
    finally:
        client.put("/api/settings/site", json={"join_requests": False})
        main.settings_store.save_section("join_requests", [])
        main.settings_store.save_section("join_let_in", [])
        signup._sent.clear()


def test_saying_no_to_a_request(client, anon, viewer, monkeypatch, sid):
    from app import main, notify, signup

    async def fake_send(*a, **k):
        return []
    monkeypatch.setattr(notify, "send", fake_send)
    signup._sent.clear()
    client.put("/api/settings/site", json={"join_requests": True})
    try:
        t = anon.post("/api/public/join-request", json={"rules": True, "player": "No_Kid"}).json()["token"]
        assert viewer.post("/api/whitelist/deny", json={"player": "No_Kid"}).status_code == 403
        assert client.post("/api/whitelist/deny", json={"player": "No_Kid"}).status_code == 200
        assert not any(r["player"] == "No_Kid" for r in client.get("/api/whitelist").json()["requests"])
        assert not any(r["player"] == "No_Kid" for r in client.get(f"/api/servers/{sid}/control").json()["asked"])
        st = anon.post("/api/public/join-request/status", json={"token": t}).json()
        assert st["state"] == "denied" and st["player"] == "No_Kid"                  # their page tells them
        assert client.post("/api/whitelist/deny", json={"player": "No_Kid"}).status_code == 404
    finally:
        client.put("/api/settings/site", json={"join_requests": False})
        main.settings_store.save_section("join_requests", [])
        main.settings_store.save_section("join_let_in", [])
        signup._sent.clear()


def test_colours_and_sizes_stay_out_of_excerpts(client, anon):
    p = client.post("/api/posts", json={"title": "Colourful", "category": "news", "body": "{red}Big news{/red} and {big}more{/big} here.\n\n---\n\n## Part two"}).json()
    try:
        card = next(x for x in anon.get("/api/public/posts?category=news").json() if x["slug"] == p["slug"])
        assert card["excerpt"].startswith("Big news and more here") and "{" not in card["excerpt"]
    finally:
        client.delete(f"/api/posts/{p['id']}")


def test_join_cards_say_the_minecraft_version(client, anon, sid):
    try:
        client.put(f"/api/servers/{sid}/settings", json={"join_address": "play.example.net"})
        s = anon.get("/api/public/site").json()
        card = next(j for j in s["joins"] if j["id"] == sid)
        assert card["version"] and s["java_version"] == card["version"]           # from the world's save
    finally:
        client.put(f"/api/servers/{sid}/settings", json={"join_address": ""})


def test_contact_email(client, anon):
    try:
        assert client.put("/api/settings/site", json={"contact": "contact@fbc.example"}).status_code == 200
        assert anon.get("/api/public/site").json()["contact"] == "contact@fbc.example"
        client.put("/api/settings/site", json={"contact": "not an email <script>"})       # refused: the old one stays
        assert anon.get("/api/public/site").json()["contact"] == "contact@fbc.example"
        from app import welcome
        assert "contact@fbc.example" in welcome.fill("Questions? {contact}", "Steve", "Survival")
    finally:
        client.put("/api/settings/site", json={"contact": ""})
    assert anon.get("/api/public/site").json()["contact"] == ""


def test_offline_worker(client, viewer, anon):
    import json
    import re
    import shutil
    import subprocess
    assert anon.get("/api/settings/site/offline-worker").status_code == 401
    assert viewer.get("/api/settings/site/offline-worker").status_code == 403
    try:
        client.put("/api/settings/site", json={"contact": "help@fbc.example"})
        r = client.get("/api/settings/site/offline-worker")
        assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
        code = r.text
        assert "__SITE__" not in code and "export default" in code
        cfg = json.loads(re.search(r"const SITE = (\{.*?\n\});", code, re.S).group(1))
        assert cfg["contact"] == "help@fbc.example" and isinstance(cfg["servers"], list)
        assert set(cfg) == {"name", "contact", "discord", "servers", "key"}   # what the home page shows, and its maintenance key
        if shutil.which("node"):
            import tempfile
            from pathlib import Path
            f = Path(tempfile.mkdtemp()) / "worker.mjs"
            f.write_text(code)
            assert subprocess.run(["node", "--check", str(f)], capture_output=True).returncode == 0
    finally:
        client.put("/api/settings/site", json={"contact": ""})


def test_post_card_description(client, anon):
    p = client.post("/api/posts", json={"title": "Card words", "body": "The long text of the post starts here.", "category": "news",
                                        "summary": "  A short line for the card.  "}).json()
    try:
        card = next(x for x in anon.get("/api/public/posts?category=news&limit=100").json() if x["id"] == p["id"])
        assert card["excerpt"] == "A short line for the card."
        # changed without the field (an older page): the description stays
        client.put(f"/api/posts/{p['id']}", json={"title": "Card words", "body": "New text.", "category": "news"})
        card = next(x for x in anon.get("/api/public/posts?category=news&limit=100").json() if x["id"] == p["id"])
        assert card["excerpt"] == "A short line for the card."
        # emptied: the start of the post again
        client.put(f"/api/posts/{p['id']}", json={"title": "Card words", "body": "New text.", "category": "news", "summary": ""})
        card = next(x for x in anon.get("/api/public/posts?category=news&limit=100").json() if x["id"] == p["id"])
        assert card["excerpt"] == "New text."
    finally:
        client.delete(f"/api/posts/{p['id']}")


def test_top_bar_ready_for_who_is_signed_in(client, viewer, anon):
    """The bar comes from the server already right, so Events, Servers and Manage don't pop in a moment later."""
    for path in ("/", "/app"):
        a = anon.get(path).text
        assert 'data-nav="events" data-signed-in hidden' in a and 'data-nav="manage" data-admin hidden' in a
        v = viewer.get(path).text
        assert 'data-nav="events" data-signed-in>' in v and 'data-nav="manage" data-admin hidden' in v
        c = client.get(path).text
        assert 'data-nav="events" data-signed-in>' in c and 'data-nav="manage" data-admin aria-label' in c
    assert 'id="hp-signin">Sign in</a>' in anon.get("/").text and 'id="hp-signin">Sign in</a>' not in client.get("/").text


def test_post_card_picture(client, anon):
    pic = "/api/public/images/0123456789abcdef.png"
    body = f"Look at this ![Our castle|small]({pic}) build."
    p = client.post("/api/posts", json={"title": "Card picture", "body": body, "category": "news"}).json()

    def card():
        return next(x for x in anon.get("/api/public/posts?category=news&limit=100").json() if x["id"] == p["id"])
    try:
        assert card()["image"] == pic                                   # the first picture in the post, sized or not
        assert "small" not in card()["excerpt"] and "castle" not in card()["excerpt"]
        client.put(f"/api/posts/{p['id']}", json={"title": "Card picture", "body": body, "category": "news", "card_image": "fedcba9876543210.jpg"})
        assert card()["image"] == "/api/public/images/fedcba9876543210.jpg"   # one just for the card
        client.put(f"/api/posts/{p['id']}", json={"title": "Card picture", "body": body, "category": "news"})
        assert card()["image"] == "/api/public/images/fedcba9876543210.jpg"   # kept when the field isn't sent
        client.put(f"/api/posts/{p['id']}", json={"title": "Card picture", "body": body, "category": "news", "card_image": "none"})
        assert card()["image"] is None                                   # no picture on the card
        client.put(f"/api/posts/{p['id']}", json={"title": "Card picture", "body": body, "category": "news", "card_image": "../../etc/passwd"})
        assert card()["image"] == pic                                   # anything else: back to the first picture
    finally:
        client.delete(f"/api/posts/{p['id']}")


def test_home_counts_and_version_at_the_bottom(client, anon):
    from app.main import VERSION
    r = client.put("/api/settings/site", json={"home_news": 50, "home_guides": 0}).json()
    try:
        cfg = anon.get("/api/public/site").json()
        assert cfg["home_news"] == 12 and cfg["home_guides"] == 0                      # 12 at most; 0 leaves it off
        assert f"Made with Solstone {VERSION}" in anon.get("/").text
        assert f"Solstone {VERSION}" in client.get("/app").text
    finally:
        client.put("/api/settings/site", json={"home_news": 3, "home_guides": 4})
    assert r is not None


def test_post_dates_and_order(client, anon):
    made = []
    try:
        for title in ("Guide A", "Guide B", "Guide C"):
            made.append(client.post("/api/posts", json={"title": title, "body": "x", "category": "guide"}).json())
        order = lambda: [p["title"] for p in anon.get("/api/public/posts?category=guide&limit=50").json() if p["title"].startswith("Guide ")]  # noqa: E731
        assert order() == ["Guide A", "Guide B", "Guide C"]                     # new ones go last, in the order written
        client.post(f"/api/posts/{made[2]['id']}/move", json={"up": True})
        assert order() == ["Guide A", "Guide C", "Guide B"]
        client.post(f"/api/posts/{made[0]['id']}/move", json={"up": False})
        assert order() == ["Guide C", "Guide A", "Guide B"]
        client.post(f"/api/posts/{made[0]['id']}/move", json={"up": True})
        client.post(f"/api/posts/{made[0]['id']}/move", json={"up": True})        # already first: stays
        assert order() == ["Guide A", "Guide C", "Guide B"]
        # news: by its date, which can be set
        old = client.post("/api/posts", json={"title": "Old news", "body": "x", "category": "news", "date": "2020-05-01"}).json()
        made.append(old)
        new = client.post("/api/posts", json={"title": "Fresh news", "body": "x", "category": "news"}).json()
        made.append(new)
        titles = [p["title"] for p in anon.get("/api/public/posts?category=news&limit=50").json()]
        assert titles.index("Fresh news") < titles.index("Old news")
        client.put(f"/api/posts/{old['id']}", json={"title": "Old news", "body": "x", "category": "news", "date": "2099-01-01"})
        titles = [p["title"] for p in anon.get("/api/public/posts?category=news&limit=50").json()]
        assert titles[0] == "Old news" or titles.index("Old news") < titles.index("Fresh news")
        assert client.post(f"/api/posts/{new['id']}/move", json={"up": True}).status_code == 400     # news goes by date
        assert client.post("/api/posts", json={"title": "Bad", "body": "x", "date": "someday"}).status_code == 400
    finally:
        for p in made:
            client.delete(f"/api/posts/{p['id']}")
