"""Accounts, sessions and the audit log.

- Passwords are hashed with scrypt (stdlib); session tokens are random and only
  their SHA-256 is stored, so a copy of the database can't be used to log in.
- Two roles: "viewer" sees everything read-only; "admin" can also run commands,
  change settings and manage users.
- On first start with no users, an admin account is created from
  ADMIN_USERNAME / ADMIN_PASSWORD, or with a generated password written to
  DATA_DIR/admin_credentials.txt and the container log.
- State-changing requests must carry an `X-Solstone: 1` header. Browsers won't
  send custom headers cross-site without CORS (which Solstone never allows), so
  together with SameSite=Lax cookies this blocks cross-site request forgery.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
import secrets
import threading
import time
from dataclasses import dataclass

from fastapi import HTTPException, Request

from . import db
from .config import config

log = logging.getLogger("solstone.auth")

ROLES = ("viewer", "admin")
COOKIE = "solstone_session"
SESSION_DAYS = int(os.getenv("SESSION_DAYS", "30"))
TRUST_PROXY = os.getenv("TRUST_PROXY_HEADERS", "").lower() in ("1", "true", "yes")
MAX_FAILS = int(os.getenv("LOGIN_MAX_ATTEMPTS", "8"))
FAIL_WINDOW = 15 * 60
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{2,32}$")
MIN_PASSWORD = 8

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL,
    created_ts REAL NOT NULL,
    last_login_ts REAL
);
CREATE TABLE IF NOT EXISTS sessions_auth (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_ts REAL NOT NULL,
    expires_ts REAL NOT NULL,
    ip TEXT,
    user_agent TEXT
);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY,
    ts REAL NOT NULL,
    username TEXT,
    server_id TEXT,
    action TEXT NOT NULL,
    detail TEXT,
    result TEXT
);
CREATE INDEX IF NOT EXISTS ix_audit ON audit(ts);
"""

_ready = False
_ready_lock = threading.Lock()
_fails: dict[str, list[float]] = {}


def _init() -> None:
    global _ready
    with _ready_lock:
        if _ready:
            return
        db.conn().executescript(SCHEMA)
        cols = {r["name"] for r in db.q("PRAGMA table_info(users)")}
        if "display_name" not in cols:                       # added later: the name shown in chat and on the site
            db.conn().execute("ALTER TABLE users ADD COLUMN display_name TEXT")
        _ready = True


# ---------------------------------------------------------------- passwords
def hash_password(pw: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt$16384$8$1${salt.hex()}${h.hex()}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        _algo, n, r, p, salt, h = stored.split("$")
        got = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p), dklen=len(h) // 2)
        return hmac.compare_digest(got.hex(), h)
    except Exception:
        return False


_DUMMY_HASH = hash_password(secrets.token_hex(8))  # equalises timing for unknown usernames


# ---------------------------------------------------------------- users
@dataclass
class User:
    id: int
    username: str
    role: str
    display_name: str | None = None

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def shown(self) -> str:
        """The name other people see (chat, the activity feed): the display name, else the login."""
        return self.display_name or self.username

    def public(self) -> dict:
        return {"id": self.id, "username": self.username, "role": self.role, "display_name": self.display_name, "shown": self.shown}


def _row_user(r) -> User:
    keys = r.keys() if hasattr(r, "keys") else []
    return User(id=r["id"], username=r["username"], role=r["role"], display_name=r["display_name"] if "display_name" in keys else None)


_DISPLAY_NAME = re.compile(r"^[A-Za-z0-9 _.'-]{1,24}$")


def set_display_name(uid: int, name: str | None) -> User:
    """Empty clears it (back to the login name). Letters, numbers, spaces and _ . ' -, up to 24, and not someone else's."""
    _init()
    name = " ".join((name or "").split())
    if name and not _DISPLAY_NAME.match(name):
        raise HTTPException(400, "Use up to 24 letters, numbers, spaces and _ . ' -")
    if name:
        taken = db.q("SELECT id FROM users WHERE id<>? AND (display_name=? COLLATE NOCASE OR username=? COLLATE NOCASE)", (uid, name, name))
        if taken:
            raise HTTPException(400, "Someone else already goes by that name")
    db.x("UPDATE users SET display_name=? WHERE id=?", (name or None, uid))
    u = get_user(uid)
    if not u:
        raise HTTPException(404, "User not found")
    return u


def count_users() -> int:
    _init()
    return db.q("SELECT COUNT(*) AS n FROM users")[0]["n"]


def count_admins() -> int:
    _init()
    return db.q("SELECT COUNT(*) AS n FROM users WHERE role='admin'")[0]["n"]


def validate_new(username: str | None, password: str | None, role: str | None) -> None:
    if username is not None and not USERNAME_RE.match(username):
        raise HTTPException(400, "Usernames are 2–32 letters, numbers, dots, dashes or underscores")
    if password is not None and len(password) < MIN_PASSWORD:
        raise HTTPException(400, f"Passwords need at least {MIN_PASSWORD} characters")
    if role is not None and role not in ROLES:
        raise HTTPException(400, "Role must be viewer or admin")


def create_user(username: str, password: str, role: str, check: bool = True) -> User:
    _init()
    if check:
        validate_new(username, password, role)
    if db.q("SELECT 1 FROM users WHERE username=? COLLATE NOCASE", (username,)):
        raise HTTPException(409, f"There's already a user called {username}")
    uid = db.x("INSERT INTO users(username, password_hash, role, created_ts) VALUES (?,?,?,?)",
               (username, hash_password(password), role, time.time()))
    return User(uid, username, role)


def list_users() -> list[dict]:
    _init()
    return [{"id": r["id"], "username": r["username"], "display_name": r["display_name"], "role": r["role"], "created": r["created_ts"],
             "last_login": r["last_login_ts"]} for r in db.q("SELECT * FROM users ORDER BY username COLLATE NOCASE")]


def get_user(uid: int) -> User | None:
    rows = db.q("SELECT * FROM users WHERE id=?", (uid,))
    return _row_user(rows[0]) if rows else None


def update_user(uid: int, role: str | None = None, password: str | None = None) -> User:
    _init()
    u = get_user(uid)
    if not u:
        raise HTTPException(404, "User not found")
    validate_new(None, password, role)
    if role and role != u.role:
        if u.role == "admin" and count_admins() <= 1:
            raise HTTPException(400, "Solstone needs at least one admin")
        db.x("UPDATE users SET role=? WHERE id=?", (role, uid))
    if password:
        db.x("UPDATE users SET password_hash=? WHERE id=?", (hash_password(password), uid))
        db.x("DELETE FROM sessions_auth WHERE user_id=?", (uid,))  # sign out everywhere
    return get_user(uid)


def delete_user(uid: int) -> None:
    _init()
    u = get_user(uid)
    if not u:
        raise HTTPException(404, "User not found")
    if u.role == "admin" and count_admins() <= 1:
        raise HTTPException(400, "Solstone needs at least one admin")
    db.x("DELETE FROM sessions_auth WHERE user_id=?", (uid,))
    db.x("DELETE FROM users WHERE id=?", (uid,))


def bootstrap() -> None:
    """Create the first admin if there are no users."""
    if count_users():
        return
    username = os.getenv("ADMIN_USERNAME", "admin")
    password = os.getenv("ADMIN_PASSWORD") or config.admin_token  # ADMIN_TOKEN from older setups still works
    generated = not password
    if generated:
        password = secrets.token_urlsafe(12)
    create_user(username, password, "admin", check=False)  # a short ADMIN_PASSWORD is the operator's call
    if generated:
        path = config.data_dir / "admin_credentials.txt"
        path.write_text(f"Solstone first admin account\nusername: {username}\npassword: {password}\n"
                        "Change this password after signing in (account menu), then delete this file.\n")
        try:
            path.chmod(0o600)
        except OSError:
            pass
        log.warning("Created admin account %r with password %s (also saved to %s)", username, password, path)
    else:
        log.info("Created admin account %r", username)


# ---------------------------------------------------------------- sessions
def client_ip(request: Request) -> str:
    if TRUST_PROXY:
        for h in ("cf-connecting-ip", "x-real-ip"):
            if request.headers.get(h):
                return request.headers[h].strip()
        xff = request.headers.get("x-forwarded-for")
        if xff:
            return xff.split(",")[0].strip()
    return request.client.host if request.client else "?"


def is_https(request: Request) -> bool:
    if request.url.scheme == "https":
        return True
    return TRUST_PROXY and request.headers.get("x-forwarded-proto", "").lower() == "https"


def _limited(key: str) -> bool:
    now = time.time()
    hits = [t for t in _fails.get(key, []) if now - t < FAIL_WINDOW]
    _fails[key] = hits
    return len(hits) >= MAX_FAILS


def login(request: Request, username: str, password: str) -> tuple[User, str]:
    _init()
    ip = client_ip(request)
    keys = (f"ip:{ip}", f"user:{(username or '').lower()}")
    if any(_limited(k) for k in keys):
        raise HTTPException(429, "Too many failed sign-ins. Wait 15 minutes and try again")
    rows = db.q("SELECT * FROM users WHERE username=? COLLATE NOCASE", (username or "",))
    ok = verify_password(password or "", rows[0]["password_hash"] if rows else _DUMMY_HASH) and bool(rows)
    if not ok:
        for k in keys:
            _fails.setdefault(k, []).append(time.time())
        audit(None, None, "login_failed", f"{username} from {ip}", "denied")
        raise HTTPException(401, "Wrong username or password")
    for k in keys:
        _fails.pop(k, None)
    user = _row_user(rows[0])
    token = secrets.token_urlsafe(32)
    now = time.time()
    db.x("INSERT INTO sessions_auth VALUES (?,?,?,?,?,?)",
         (_th(token), user.id, now, now + SESSION_DAYS * 86400, ip, (request.headers.get("user-agent") or "")[:200]))
    db.x("UPDATE users SET last_login_ts=? WHERE id=?", (now, user.id))
    db.x("DELETE FROM sessions_auth WHERE expires_ts < ?", (now,))
    return user, token


def logout(token: str | None) -> None:
    if token:
        db.x("DELETE FROM sessions_auth WHERE token_hash=?", (_th(token),))


def _th(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def user_from_request(request: Request) -> User | None:
    _init()
    token = request.cookies.get(COOKIE)
    if not token:
        return None
    rows = db.q("SELECT u.*, s.expires_ts FROM sessions_auth s JOIN users u ON u.id = s.user_id WHERE s.token_hash=?",
                (_th(token),))
    if not rows or rows[0]["expires_ts"] < time.time():
        return None
    # Sliding expiry: extend at most once a day.
    if rows[0]["expires_ts"] - time.time() < (SESSION_DAYS - 1) * 86400:
        db.x("UPDATE sessions_auth SET expires_ts=? WHERE token_hash=?", (time.time() + SESSION_DAYS * 86400, _th(token)))
    return _row_user(rows[0])


def set_cookie(response, request: Request, token: str) -> None:
    response.set_cookie(COOKIE, token, max_age=SESSION_DAYS * 86400, httponly=True, samesite="lax",
                        secure=is_https(request), path="/")


def require_user(request: Request) -> User:
    u = getattr(request.state, "user", None)
    if u is None:
        raise HTTPException(401, "Sign in to continue")
    return u


def require_admin(request: Request) -> User:
    u = require_user(request)
    if not u.is_admin:
        raise HTTPException(403, "Only admins can do that")
    return u


# ---------------------------------------------------------------- audit
def audit(user: User | str | None, server_id: str | None, action: str, detail: str = "", result: str = "") -> None:
    """Record who did what. `user` may be a User or a label like "Bedtime" for automatic actions."""
    _init()
    who = user.username if isinstance(user, User) else user
    db.x("INSERT INTO audit(ts, username, server_id, action, detail, result) VALUES (?,?,?,?,?,?)",
         (time.time(), who, server_id, action, (detail or "")[:500], (result or "")[:500]))


def audit_log(server_id: str | None = None, limit: int = 100) -> list[dict]:
    _init()
    if server_id:
        rows = db.q("SELECT * FROM audit WHERE server_id=? OR server_id IS NULL ORDER BY ts DESC LIMIT ?", (server_id, limit))
    else:
        rows = db.q("SELECT * FROM audit ORDER BY ts DESC LIMIT ?", (limit,))
    return [dict(r) for r in rows]
