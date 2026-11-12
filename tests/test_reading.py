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


def test_timeline_by_the_hour():
    import time
    from app import db, reading
    reading._ensure()
    db.x("DELETE FROM reading_hours WHERE page LIKE '/guides/rdt-%'")
    now = time.time()
    two_ago = (now // 3600 - 2) * 3600 + 60                 # (early in its hour: the view a minute later is the same hour)
    reading.note("/guides/rdt-a", "A", "view", "t1", None, "5.5.5.5", now=two_ago)
    reading.note("/guides/rdt-a", "A", "view", "t2", None, "5.5.5.5", now=two_ago + 60)   # the same hour
    reading.note("/guides/rdt-b", "B", "view", "t3", None, "5.5.5.6", now=now)
    reading.note("/guides/rdt-b", "B", "read", "t3", None, "5.5.5.6", now=now)            # only views go on the timeline
    t = reading.timeline(1, now)
    assert t["slot_secs"] == 3600
    def at(ts):
        return next(s for s in t["slots"] if s["t"] <= ts < s["t"] + 3600)["pages"]
    if time.localtime(two_ago).tm_yday == time.localtime(now).tm_yday:              # (just after midnight: before "today")
        assert at(two_ago).get("/guides/rdt-a") == 2
    assert at(now).get("/guides/rdt-b") == 1
    week = reading.timeline(7, now)
    assert week["slot_secs"] == 6 * 3600 and sum(s["pages"].get("/guides/rdt-b", 0) for s in week["slots"]) == 1
    year = reading.timeline(365, now)
    assert year["slot_secs"] == 7 * 86400 and len(year["slots"]) >= 52
    reading.prune(now + 40 * 86400)                                                    # the hours go after a month
    assert not db.q("SELECT 1 FROM reading_hours WHERE page LIKE '/guides/rdt-%'")
    db.x("DELETE FROM reading WHERE page LIKE '/guides/rdt-%'")
