"""What people read: views, people, read to the end, time on it. Admins aren't counted; nobody's named."""
from types import SimpleNamespace


def test_counts_views_people_reads_and_time():
    from app import db, reading
    reading._ensure()
    db.x("DELETE FROM reading WHERE page LIKE '/guides/rd-%'")
    page = "/guides/rd-rules"
    kid = SimpleNamespace(id=7, role="player")
    admin = SimpleNamespace(id=1, role="admin")
    assert reading.note(page, "Rules", "view", "v1", None, "1.2.3.4")
    assert reading.note(page, "Rules", "view", "v2", None, "1.2.3.4")          # the same visitor again: a view, not a new person
    assert reading.note(page, "Rules", "view", "v3", kid, "1.2.3.4")           # a signed-in player
    assert not reading.note(page, "Rules", "view", "v4", admin, "9.9.9.9")     # admins don't count
    assert reading.note(page, "Rules", "read", "v1", None, "1.2.3.4")
    assert not reading.note(page, "Rules", "read", "v1", None, "1.2.3.4")      # once per view
    assert reading.note(page, "Rules", "time", "v1", None, "1.2.3.4", 40)
    assert reading.note(page, "Rules", "time", "v1", None, "1.2.3.4", 60)      # came back to it: 20 s more, same visit
    assert reading.note(page, "Rules", "time", "v3", kid, "1.2.3.4", 30)
    assert not reading.note("/admin/secret", "x", "view", "v5", None, "1.2.3.4")
    p = next(x for x in reading.report(30)["pages"] if x["page"] == page)
    assert (p["views"], p["people"], p["visitors"], p["players"], p["reads"]) == (3, 2, 1, 1, 1)
    assert p["avg_secs"] == 45 and p["title"] == "Rules" and p["article"]
    db.x("DELETE FROM reading WHERE page LIKE '/guides/rd-%'")


def test_the_page_reports_itself_and_only_admins_see_it(client, anon):
    pid = client.post("/api/posts", json={"title": "Read me please", "body": "News!", "category": "news"}).json()
    slug = pid.get("slug") or pid.get("post", {}).get("slug")
    page = f"/post/{slug}"
    assert anon.post("/api/public/read", json={"page": page, "event": "view", "id": "a1", "title": "fake title"}).json()["counted"]
    assert not client.post("/api/public/read", json={"page": page, "event": "view", "id": "a2"}).json()["counted"]   # the admin
    assert not anon.post("/api/public/read", json={"page": "/post/not-a-post", "event": "view", "id": "a3"}).json()["counted"]
    assert not anon.post("/api/public/read", json={"page": page, "event": "view", "id": "a4"}, headers={"User-Agent": "Googlebot/2.1"}).json()["counted"]
    assert anon.get("/api/reading").status_code == 401
    rows = client.get("/api/reading", params={"days": 7}).json()["pages"]
    p = next(x for x in rows if x["page"] == page)
    assert p["views"] == 1 and p["title"] == "Read me please"           # the post's own title, not what the page said
