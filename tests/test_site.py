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
