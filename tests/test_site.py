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
