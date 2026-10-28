"""Accounts, sessions and the audit log.

- Passwords are hashed with scrypt (stdlib); session tokens are random and only
  their SHA-256 is stored, so a copy of the database can't be used to log in.
- Three roles: "player" (usually a signed-up player, linked to their Minecraft account) sees the
  servers, who's on, leaderboards and their own page, nothing about anyone else's whereabouts or chat;
  "trusted" sees everything read-only and can chat; "admin" can also run commands, change settings
  and manage users. ("viewer" was the old name for trusted.)
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
import json
import logging
import os
import re
import secrets
import threading
import time
from dataclasses import dataclass, field

from fastapi import HTTPException, Request

from . import db
from .config import config

log = logging.getLogger("solstone.auth")

ROLES = ("player", "trusted", "admin")
ROLE_ALIASES = {"viewer": "trusted"}
COOKIE = "solstone_session"
SESSION_DAYS = int(os.getenv("SESSION_DAYS", "30"))
TRUST_PROXY = os.getenv("TRUST_PROXY_HEADERS", "").lower() in ("1", "true", "yes")
MAX_FAILS = int(os.getenv("LOGIN_MAX_ATTEMPTS", "8"))
USER_MAX_FAILS = 50          # one account from everywhere: high enough that a stranger can't lock someone out
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
-- the Minecraft accounts a login belongs to (a Java one and a Bedrock one, say); users.player_uuid is the first
CREATE TABLE IF NOT EXISTS user_players (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    uuid TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    added_ts REAL NOT NULL
);
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
        if "player_uuid" not in cols:                        # added with player sign-up: the linked Minecraft account
            db.conn().execute("ALTER TABLE users ADD COLUMN player_uuid TEXT")
            db.conn().execute("ALTER TABLE users ADD COLUMN player_name TEXT")
        if "servers" not in cols:                            # added later: the servers a login is limited to
            db.conn().execute("ALTER TABLE users ADD COLUMN servers TEXT")
        if "real_name" not in cols:                          # added later: their real name, for admins only
            db.conn().execute("ALTER TABLE users ADD COLUMN real_name TEXT")
        db.conn().execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_users_player ON users(player_uuid) WHERE player_uuid IS NOT NULL")
        db.conn().execute("UPDATE users SET role='trusted' WHERE role='viewer'")   # the old name
        db.conn().execute("INSERT OR IGNORE INTO user_players(user_id, uuid, name, added_ts) "        # from one linked player each
                          "SELECT id, player_uuid, player_name, created_ts FROM users WHERE player_uuid IS NOT NULL")
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
    player_uuid: str | None = None      # the Minecraft account this login belongs to (signed-up players)
    player_name: str | None = None
    servers: list[str] | None = None    # the only servers this login sees (None: all of them; admins always see all)
    real_name: str | None = None        # who they really are, so admins know; never shown to other players
    players: list[dict] = field(default_factory=list)   # every Minecraft account of theirs: [{"uuid", "name"}]

    @property
    def player_uuids(self) -> set[str]:
        return {p["uuid"] for p in self.players}

    def may_see(self, server_id: str) -> bool:
        return self.is_admin or self.servers is None or server_id in self.servers

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def is_player(self) -> bool:
        """The lowest level: no chat, no one else's position, inventory or history."""
        return self.role == "player"

    @property
    def shown(self) -> str:
        """The name other people see (chat, the activity feed): the display name, else the login."""
        return self.display_name or self.username

    def public(self) -> dict:
        return {"id": self.id, "username": self.username, "role": self.role, "display_name": self.display_name, "shown": self.shown,
                "player": {"uuid": self.player_uuid, "name": self.player_name} if self.player_uuid else None,
                "players": self.players,
                "servers": self.servers, "real_name": self.real_name}


def _row_user(r) -> User:
    keys = set(r.keys()) if hasattr(r, "keys") else set()
    g = lambda k: r[k] if k in keys else None  # noqa: E731
    return User(id=r["id"], username=r["username"], role=r["role"], display_name=g("display_name"),
                player_uuid=g("player_uuid"), player_name=g("player_name"), servers=_servers_of(g("servers")),
                real_name=g("real_name"), players=_players_of(r["id"]))


def _players_of(uid: int) -> list[dict]:
    try:
        return [{"uuid": p["uuid"], "name": p["name"]} for p in db.q("SELECT uuid, name FROM user_players WHERE user_id=? ORDER BY added_ts, rowid", (uid,))]
    except Exception:                       # before _init has made the table
        return []


def _servers_of(raw) -> list[str] | None:
    if not raw:
        return None
    try:
        v = json.loads(raw)
    except ValueError:
        return []                          # unreadable: see nothing rather than everything
    return [str(x) for x in v] if isinstance(v, list) else None


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


_REAL_NAME = re.compile(r"^[^\x00-\x1f<>]{1,40}$")


def set_real_name(uid: int, name: str | None) -> User:
    """Their real name (up to 40 characters; empty clears it). Only admins and the person themselves see it."""
    _init()
    name = " ".join((name or "").split())
    if name and not _REAL_NAME.match(name):
        raise HTTPException(400, "Use up to 40 characters for the name")
    db.x("UPDATE users SET real_name=? WHERE id=?", (name or None, uid))
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
        raise HTTPException(400, "Role must be player, trusted or admin")


def create_user(username: str, password: str, role: str, check: bool = True,
                player: tuple[str, str] | None = None, servers: list[str] | None = None) -> User:
    _init()
    role = ROLE_ALIASES.get(role, role)
    if check:
        validate_new(username, password, role)
    if db.q("SELECT 1 FROM users WHERE username=? COLLATE NOCASE", (username,)):
        raise HTTPException(409, f"There's already a user called {username}")
    if player and user_for_player(player[0]):
        raise HTTPException(409, f"{player[1]} already has an account")
    uid = db.x("INSERT INTO users(username, password_hash, role, created_ts, servers) VALUES (?,?,?,?,?)",
               (username, hash_password(password), role, time.time(), json.dumps(servers) if servers is not None else None))
    if player:
        add_player(uid, player)
    return get_user(uid)


def user_for_player(uuid: str) -> str | None:
    """The login already linked to this Minecraft player, if any."""
    _init()
    rows = db.q("SELECT u.username FROM user_players p JOIN users u ON u.id = p.user_id WHERE p.uuid=?", (uuid,))
    return rows[0]["username"] if rows else None


def _sync_first(uid: int) -> None:
    """users.player_uuid/player_name follow the first linked account (older code and the unique index use them)."""
    first = db.q("SELECT uuid, name FROM user_players WHERE user_id=? ORDER BY added_ts, rowid LIMIT 1", (uid,))
    db.x("UPDATE users SET player_uuid=?, player_name=? WHERE id=?", (first[0]["uuid"], first[0]["name"], uid) if first else (None, None, uid))


def add_player(uid: int, player: tuple[str, str]) -> User:
    """Link one more Minecraft account (Java or Bedrock) to a login."""
    _init()
    other = db.q("SELECT user_id FROM user_players WHERE uuid=?", (player[0],))
    if other and other[0]["user_id"] != uid:
        raise HTTPException(409, f"{player[1]} is already linked to another account")
    if other:
        db.x("UPDATE user_players SET name=? WHERE uuid=?", (player[1], player[0]))
    else:
        db.x("INSERT INTO user_players(user_id, uuid, name, added_ts) VALUES (?,?,?,?)", (uid, player[0], player[1], time.time()))
    _sync_first(uid)
    u = get_user(uid)
    if not u:
        raise HTTPException(404, "User not found")
    return u


def remove_player(uid: int, uuid: str) -> User:
    _init()
    db.x("DELETE FROM user_players WHERE user_id=? AND uuid=?", (uid, uuid))
    _sync_first(uid)
    u = get_user(uid)
    if not u:
        raise HTTPException(404, "User not found")
    return u


def link_player(uid: int, player: tuple[str, str] | None) -> User:
    """Link a login to just this Minecraft player (None unlinks every one)."""
    _init()
    if player and (owner := user_for_player(player[0])) and owner.lower() != (get_user(uid) or User(0, "", "")).username.lower():
        raise HTTPException(409, f"{player[1]} is already linked to another account")
    db.x("DELETE FROM user_players WHERE user_id=?", (uid,))
    return add_player(uid, player) if player else remove_player(uid, "")


def set_servers(uid: int, servers: list[str] | None) -> User:
    """Limit a login to these servers (None: every server)."""
    _init()
    db.x("UPDATE users SET servers=? WHERE id=?", (json.dumps(sorted(set(servers))) if servers is not None else None, uid))
    u = get_user(uid)
    if not u:
        raise HTTPException(404, "User not found")
    return u


def list_users() -> list[dict]:
    _init()
    return [{"id": r["id"], "username": r["username"], "display_name": r["display_name"], "role": r["role"], "created": r["created_ts"],
             "last_login": r["last_login_ts"], "player_name": r["player_name"], "real_name": r["real_name"],
             "players": _players_of(r["id"]),
             "servers": _servers_of(r["servers"])} for r in db.q("SELECT * FROM users ORDER BY username COLLATE NOCASE")]


def get_user(uid: int) -> User | None:
    rows = db.q("SELECT * FROM users WHERE id=?", (uid,))
    return _row_user(rows[0]) if rows else None


def update_user(uid: int, role: str | None = None, password: str | None = None) -> User:
    _init()
    u = get_user(uid)
    if not u:
        raise HTTPException(404, "User not found")
    role = ROLE_ALIASES.get(role, role) if role else role
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
    db.x("DELETE FROM user_players WHERE user_id=?", (uid,))
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


def _limited(key: str, limit: int = MAX_FAILS) -> bool:
    now = time.time()
    hits = [t for t in _fails.get(key, []) if now - t < FAIL_WINDOW]
    if hits:
        _fails[key] = hits
    else:
        _fails.pop(key, None)
    if len(_fails) > 5000:                     # old entries from many addresses: drop the stale ones
        for k in [k for k, v in _fails.items() if not v or now - v[-1] > FAIL_WINDOW]:
            _fails.pop(k, None)
    return len(hits) >= limit


def login(request: Request, username: str, password: str) -> tuple[User, str]:
    _init()
    ip = client_ip(request)
    name = (username or "").lower()
    # Per address, per account from that address, and a high cap per account from everywhere: wrong passwords
    # from someone else's machine never lock you out, and nobody gets unlimited guesses at one account.
    keys = (f"ip:{ip}", f"user:{name}@{ip}", f"user:{name}")
    limits = (MAX_FAILS, MAX_FAILS, USER_MAX_FAILS)
    if any(_limited(k, n) for k, n in zip(keys, limits, strict=True)):
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
