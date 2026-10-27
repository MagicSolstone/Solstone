"""The public website around Solstone: the site's own details and its posts.

The home page at / shows what a visitor needs without signing in: how to join (the Java and
Bedrock addresses), the public servers' live status, announcements, and posts. Posts are
news, guides or FAQ entries an admin writes in the app; their text is a small, safe subset
of Markdown, turned into HTML in the browser (home.js), never stored as HTML.
"""
from __future__ import annotations

import re
import time

from . import db, settings_store

CATEGORIES = ("news", "guide", "faq")
DEFAULTS = {"name": "Solstone", "tagline": "", "java_address": "", "bedrock_address": "", "bedrock_port": 19132,
            "discord": "", "about": "", "home_live": True}
_SLUG = re.compile(r"[^a-z0-9]+")


def _line(v, n: int) -> str:
    return " ".join(str(v or "").split())[:n]


def config() -> dict:
    saved = settings_store.load().get("site") or {}
    return {**DEFAULTS, **{k: v for k, v in saved.items() if k in DEFAULTS}}


def clean_config(body: dict) -> dict:
    cur = config()
    out = dict(cur)
    for k in ("name", "tagline", "java_address", "bedrock_address"):
        if k in body:
            out[k] = _line(body[k], 80 if k != "tagline" else 160)
    if "about" in body:
        out["about"] = str(body["about"] or "")[:4000]
    if "discord" in body:
        d = _line(body["discord"], 200)
        out["discord"] = d if not d or d.startswith(("https://discord.gg/", "https://discord.com/")) else cur["discord"]
    if "bedrock_port" in body:
        try:
            out["bedrock_port"] = max(1, min(65535, int(body["bedrock_port"])))
        except (TypeError, ValueError):
            pass
    if "home_live" in body:
        out["home_live"] = bool(body["home_live"])
    out["name"] = out["name"] or DEFAULTS["name"]
    return out


def save_config(body: dict) -> dict:
    cfg = clean_config(body)
    settings_store.save_section("site", cfg)
    return cfg


# ---------------------------------------------------------------- posts
def _row(r, full: bool = True) -> dict:
    out = {"id": r["id"], "slug": r["slug"], "title": r["title"], "category": r["category"],
           "published": bool(r["published"]), "pinned": bool(r["pinned"]), "author": r["author"],
           "created": r["created_ts"], "updated": r["updated_ts"]}
    if full:
        out["body"] = r["body"]
    else:
        text = re.sub(r"[#*_`>\[\]()!-]", "", r["body"])
        out["excerpt"] = _line(text, 220)
    return out


def posts(category: str | None = None, drafts: bool = False, limit: int = 50) -> list[dict]:
    where, args = [], []
    if category:
        where.append("category=?")
        args.append(category)
    if not drafts:
        where.append("published=1")
    sql = "SELECT * FROM posts" + (" WHERE " + " AND ".join(where) if where else "") + \
          " ORDER BY pinned DESC, created_ts DESC LIMIT ?"
    return [_row(r, full=drafts) for r in db.q(sql, (*args, max(1, min(200, limit))))]


def post(slug: str, drafts: bool = False) -> dict | None:
    rows = db.q("SELECT * FROM posts WHERE slug=?" + ("" if drafts else " AND published=1"), (slug,))
    return _row(rows[0]) if rows else None


def _slug_for(title: str, own_id: int | None = None) -> str:
    base = _SLUG.sub("-", title.lower()).strip("-")[:60] or "post"
    slug, n = base, 2
    while True:
        rows = db.q("SELECT id FROM posts WHERE slug=?", (slug,))
        if not rows or rows[0]["id"] == own_id:
            return slug
        slug, n = f"{base}-{n}", n + 1


def save(body: dict, author: str, pid: int | None = None) -> dict:
    """Create a post (no pid) or change one. Raises ValueError with a message for the admin."""
    title = _line(body.get("title"), 120)
    text = str(body.get("body") or "").strip()[:20000]
    category = body.get("category") if body.get("category") in CATEGORIES else "news"
    if not title:
        raise ValueError("A post needs a title")
    if not text:
        raise ValueError("A post needs some text")
    now = time.time()
    published, pinned = int(bool(body.get("published", True))), int(bool(body.get("pinned", False)))
    if pid is None:
        pid = db.x("INSERT INTO posts(slug, title, body, category, published, pinned, author, created_ts, updated_ts) "
                   "VALUES (?,?,?,?,?,?,?,?,?)", (_slug_for(title), title, text, category, published, pinned, author, now, now))
    else:
        if not db.q("SELECT id FROM posts WHERE id=?", (pid,)):
            raise LookupError("No such post")
        db.x("UPDATE posts SET slug=?, title=?, body=?, category=?, published=?, pinned=?, updated_ts=? WHERE id=?",
             (_slug_for(title, pid), title, text, category, published, pinned, now, pid))
    return _row(db.q("SELECT * FROM posts WHERE id=?", (pid,))[0])


def delete(pid: int) -> bool:
    if not db.q("SELECT id FROM posts WHERE id=?", (pid,)):
        return False
    db.x("DELETE FROM posts WHERE id=?", (pid,))
    return True
