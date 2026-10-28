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
from .config import config as app_config

CATEGORIES = ("news", "guide", "faq")
DEFAULTS = {"name": "Solstone", "tagline": "", "java_address": "", "bedrock_address": "", "bedrock_port": 19132,
            "discord": "", "about": "", "home_live": True, "signup": False,
            # the two built-in guides, in the admin's own words (empty: Solstone's wording); {java_address} and the
            # like are filled in from the details above, so the guides stay right when an address or port changes
            "guide_join": "", "guide_account": "", "guide_rules": "",
            "join_requests": False,       # an "Ask to join" form on the join guide, sent to the admins' notifications
            "main_server": ""}            # shown first everywhere (home page, Ask to join), starred; its addresses feed the join guide
GUIDE_MAX = 8000
_SLUG = re.compile(r"[^a-z0-9]+")


# ---------------------------------------------------------------- the logo
# An admin's own picture in place of Solstone's, everywhere the site shows its logo. Pictures only
# (PNG, JPEG, WebP, GIF), checked by their first bytes; never SVG, which can carry script.
LOGO_TYPES = {b"\x89PNG\r\n\x1a\n": ("png", "image/png"), b"\xff\xd8\xff": ("jpg", "image/jpeg"),
              b"GIF87a": ("gif", "image/gif"), b"GIF89a": ("gif", "image/gif")}
LOGO_MAX = 1024 * 1024
DEFAULT_LOGO = "/static/solstone.svg"


def _logo_kind(data: bytes) -> tuple[str, str] | None:
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp", "image/webp"
    return next((v for k, v in LOGO_TYPES.items() if data.startswith(k)), None)


def logo() -> dict | None:
    """{"file", "mime", "v"} when there's an uploaded logo."""
    saved = settings_store.load().get("site_logo") or {}
    path = app_config.data_dir / "site" / f"logo.{saved.get('ext', '')}"
    return {"file": path, "mime": saved["mime"], "v": saved["v"]} if saved.get("ext") and path.is_file() else None


def logo_url() -> str:
    lg = logo()
    return f"/api/public/logo?v={lg['v']}" if lg else DEFAULT_LOGO


def save_logo(data: bytes) -> str:
    """Store a new logo. Raises ValueError with a message for the admin if it isn't a picture we take."""
    if len(data) > LOGO_MAX:
        raise ValueError("Use a picture under 1 MB")
    kind = _logo_kind(data)
    if not kind:
        raise ValueError("Use a PNG, JPEG, WebP or GIF picture")
    folder = app_config.data_dir / "site"
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob("logo.*"):
        old.unlink(missing_ok=True)
    tmp = folder / f"logo.{kind[0]}.tmp"
    tmp.write_bytes(data)
    tmp.replace(folder / f"logo.{kind[0]}")
    settings_store.save_section("site_logo", {"ext": kind[0], "mime": kind[1], "v": int(time.time())})
    return logo_url()


def remove_logo() -> str:
    for old in (app_config.data_dir / "site").glob("logo.*"):
        old.unlink(missing_ok=True)
    settings_store.save_section("site_logo", {})
    return DEFAULT_LOGO


# ---------------------------------------------------------------- pictures in posts
# Uploaded by an admin, kept by a name made from their content, and only ever served as the picture type
# their first bytes say they are (same check as the logo), so nothing else can be passed off as one.
IMAGE_MAX = 4 * 1024 * 1024
IMAGE_NAME = re.compile(r"^[0-9a-f]{16}\.(png|jpg|gif|webp)$")
IMAGE_MD = re.compile(r"!\[[^\]]*\]\(/api/public/images/([0-9a-f]{16}\.(?:png|jpg|gif|webp))\)")
IMAGE_MIME = {"png": "image/png", "jpg": "image/jpeg", "gif": "image/gif", "webp": "image/webp"}


def save_image(data: bytes) -> str:
    import hashlib
    if len(data) > IMAGE_MAX:
        raise ValueError("Use a picture under 4 MB")
    kind = _logo_kind(data)
    if not kind:
        raise ValueError("Use a PNG, JPEG, WebP or GIF picture")
    folder = app_config.data_dir / "site" / "images"
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{hashlib.sha256(data).hexdigest()[:16]}.{kind[0]}"
    path = folder / name
    if not path.is_file():
        tmp = folder / f"{name}.tmp"
        tmp.write_bytes(data)
        tmp.replace(path)
    return f"/api/public/images/{name}"


def image_file(name: str):
    if not IMAGE_NAME.match(name):
        return None
    path = app_config.data_dir / "site" / "images" / name
    return (path, IMAGE_MIME[name.rsplit(".", 1)[1]]) if path.is_file() else None


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
    for k in ("guide_join", "guide_account", "guide_rules"):
        if k in body:
            out[k] = str(body[k] or "").replace("\r", "")[:GUIDE_MAX].strip()
    if "discord" in body:
        d = _line(body["discord"], 200)
        out["discord"] = d if not d or d.startswith(("https://discord.gg/", "https://discord.com/")) else cur["discord"]
    if "bedrock_port" in body:
        try:
            out["bedrock_port"] = max(1, min(65535, int(body["bedrock_port"])))
        except (TypeError, ValueError):
            pass
    if "main_server" in body:
        out["main_server"] = re.sub(r"[^A-Za-z0-9_.\-]", "", str(body["main_server"] or ""))[:64]
    for k in ("home_live", "signup", "join_requests"):
        if k in body:
            out[k] = bool(body[k])
    out["name"] = out["name"] or DEFAULTS["name"]
    return out


# ---------------------------------------------------------------- asking to join
REQUESTS_KEPT = 40


def join_requests() -> list[dict]:
    return list(settings_store.load().get("join_requests") or [])


def add_join_request(player: str, name: str, note: str, token_hash: str = "", servers: list[str] | None = None) -> dict:
    """servers: the ones they'd like to play on (ids)."""
    req = {"ts": time.time(), "player": player, "name": name, "note": note, "token": token_hash,
           "servers": list(servers or []), "done": []}
    keep = [r for r in join_requests() if r.get("player", "").lower() != player.lower()][-(REQUESTS_KEPT - 1):]
    settings_store.save_section("join_requests", keep + [req])
    return req


def wants(r: dict, sid: str) -> bool:
    """Did this request ask for that server? (Older requests didn't say: any server.)"""
    return not r.get("servers") or sid in r["servers"]


def mark_let_in(player: str, sid: str) -> None:
    """Let in on one server from Control: their request knows, so their page can say so."""
    reqs = join_requests()
    for r in reqs:
        if r.get("player", "").lower() == player.lower() and sid not in r.setdefault("done", []):
            r["done"].append(sid)
    settings_store.save_section("join_requests", reqs)


def finish_join_request(token_hash: str) -> None:
    """In on everything they asked for: off the list, kept a while so their page still says "you're in"."""
    reqs = join_requests()
    done = [r for r in reqs if r.get("token") == token_hash]
    if not done:
        return
    settings_store.save_section("join_requests", [r for r in reqs if r.get("token") != token_hash])
    let_in = (settings_store.load().get("join_let_in") or [])[-(REQUESTS_KEPT - 1):]
    settings_store.save_section("join_let_in", let_in + [{**done[0], "ts_in": time.time()}])


def drop_join_request(player: str) -> None:
    """Done with this player's request altogether (every server)."""
    mine = [r for r in join_requests() if r.get("player", "").lower() == player.lower()]
    for r in mine:
        if r.get("token"):
            finish_join_request(r["token"])
    settings_store.save_section("join_requests", [r for r in join_requests() if r.get("player", "").lower() != player.lower()])


def deny_join_request(player: str) -> bool:
    """Not this time: off the list, kept a while (marked denied) so their page can tell them."""
    reqs = join_requests()
    mine = [r for r in reqs if r.get("player", "").lower() == player.lower()]
    if not mine:
        return False
    settings_store.save_section("join_requests", [r for r in reqs if r not in mine])
    answered = (settings_store.load().get("join_let_in") or [])[-(REQUESTS_KEPT - len(mine)):]
    settings_store.save_section("join_let_in", answered + [{**r, "ts_in": time.time(), "denied": True} for r in mine])
    return True


def request_for_token(token_hash: str) -> tuple[dict, bool] | None:
    """(the request, finished?) for someone checking their own request."""
    if not token_hash:
        return None
    for r in join_requests():
        if r.get("token") == token_hash:
            return r, False
    for r in settings_store.load().get("join_let_in") or []:
        if r.get("token") == token_hash:
            return r, True
    return None


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
        pic = IMAGE_MD.search(r["body"])
        out["image"] = f"/api/public/images/{pic.group(1)}" if pic else None   # the first picture, for the card
        text = IMAGE_MD.sub("", r["body"])
        text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)      # a link's text, not its address
        text = re.sub(r"[#*_`>\[\]()!-]", "", text)
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
