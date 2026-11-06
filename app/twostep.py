"""Two-step sign-in for admins (and Trusted, if they like): a six-digit code from an authenticator app (Google
Authenticator, Microsoft Authenticator, 1Password…) after the password, so a stolen or guessed password alone isn't
enough.

- Turning it on: a new secret is shown as a QR code (and as text, to type in); the app's first code confirms it. Then
  ten one-time backup codes are shown once, for when the phone's lost (only their hashes are kept).
- Signing in: password, then a code (or a backup code). "Trust this device for 30 days" sets a cookie so that
  browser isn't asked again for a while; changing the password or turning two-step off forgets every trusted device.
- Codes are the standard kind (TOTP, RFC 6238: 30 seconds, six digits, SHA-1), checked one step either side for a
  clock that's a little off, and never accepted twice.
- Locked out (phone and backup codes gone)? Another admin can turn it off for you (Manage → Users), or on the Unraid
  server: docker exec -it solstone python -m app.cli two-step-off <login>  (see cli.py).

Stdlib only, apart from drawing the QR code (segno).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import secrets
import struct
import threading
import time
from urllib.parse import quote

from fastapi import HTTPException

from . import auth, db

STEP = 30
DIGITS = 6
TRUST_DAYS = 30
TRUST_COOKIE = "solstone_trust"
TICKET_SECS = 300
TICKET_TRIES = 5
BACKUP_CODES = 10
ROLES = ("admin", "trusted")           # who can turn it on (players: a lost phone would lock a child out)

_tickets: dict[str, dict] = {}         # sha256(ticket) -> {uid, expires, tries, ip}
_lock = threading.Lock()
_ready = False


def _init() -> None:
    global _ready
    if _ready:
        return
    auth._init()
    cols = {r["name"] for r in db.q("PRAGMA table_info(users)")}
    for col, kind in (("totp_secret", "TEXT"), ("totp_pending", "TEXT"), ("totp_last", "INTEGER"), ("totp_backup", "TEXT")):
        if col not in cols:
            db.conn().execute(f"ALTER TABLE users ADD COLUMN {col} {kind}")
    db.conn().execute("CREATE TABLE IF NOT EXISTS trusted_devices (token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL "
                      "REFERENCES users(id) ON DELETE CASCADE, expires_ts REAL NOT NULL)")
    _ready = True


# ---------------------------------------------------------------- the codes themselves
def _code_at(secret: str, counter: int) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    mac = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    off = mac[-1] & 0x0F
    n = (struct.unpack(">I", mac[off:off + 4])[0] & 0x7FFFFFFF) % 10 ** DIGITS
    return f"{n:0{DIGITS}d}"


def code_now(secret: str, now: float | None = None) -> str:
    return _code_at(secret, int((now or time.time()) // STEP))


def _match(secret: str, code: str, now: float | None = None, after: int | None = None) -> int | None:
    """The time step a code belongs to (this one, or one either side), or None. Steps at or before `after` don't
    count: a code is good once."""
    step = int((now or time.time()) // STEP)
    for s in (step, step - 1, step + 1):
        if (after is None or s > after) and hmac.compare_digest(_code_at(secret, s), code):
            return s
    return None


def _clean(code: str) -> str:
    return "".join(ch for ch in str(code or "") if ch.isalnum()).lower()


def _h(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


# ---------------------------------------------------------------- on, off, backup codes
def _row(uid: int):
    _init()
    rows = db.q("SELECT * FROM users WHERE id=?", (uid,))
    if not rows:
        raise HTTPException(404, "No such login")
    return rows[0]


def is_on(uid: int) -> bool:
    _init()
    rows = db.q("SELECT totp_secret FROM users WHERE id=?", (uid,))
    return bool(rows and rows[0]["totp_secret"])


def status(uid: int) -> dict:
    r = _row(uid)
    left = len(json.loads(r["totp_backup"] or "[]")) if r["totp_secret"] else 0
    return {"on": bool(r["totp_secret"]), "backup_left": left, "may": r["role"] in ROLES}


def begin(user: auth.User, site_name: str) -> dict:
    """A new secret, waiting to be confirmed with the app's first code: the QR code (an SVG) and the text of it."""
    if user.role not in ROLES:
        raise HTTPException(403, "Two-step sign-in is for admins and Trusted accounts")
    secret = base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")
    db.x("UPDATE users SET totp_pending=? WHERE id=?", (secret, user.id))
    label = quote(f"{site_name}:{user.username}")
    uri = f"otpauth://totp/{label}?secret={secret}&issuer={quote(site_name)}&digits={DIGITS}&period={STEP}"
    import segno
    out = io.BytesIO()
    segno.make(uri, micro=False, error="m").save(out, kind="svg", scale=5, border=2, dark="#000", light="#fff",
                                                 xmldecl=False, svgns=True, title="Scan with your authenticator app")
    return {"svg": out.getvalue().decode(), "secret": " ".join(secret[i:i + 4] for i in range(0, len(secret), 4)), "uri": uri}


def _new_backups() -> tuple[list[str], list[str]]:
    codes = [f"{secrets.token_hex(2)}-{secrets.token_hex(2)}" for _ in range(BACKUP_CODES)]
    return codes, [_h(_clean(c)) for c in codes]


def confirm(user: auth.User, code: str) -> list[str]:
    """The app's first code proves it's set up: two-step is on. Returns the backup codes (shown this once)."""
    r = _row(user.id)
    secret = r["totp_pending"]
    if not secret:
        raise HTTPException(400, "Start again: press Turn on")
    step = _match(secret, _clean(code))
    if step is None:
        raise HTTPException(400, "That code isn't right. Check the app shows this site, and your phone's clock is right")
    codes, hashes = _new_backups()
    db.x("UPDATE users SET totp_secret=?, totp_pending=NULL, totp_last=?, totp_backup=? WHERE id=?",
         (secret, step, json.dumps(hashes), user.id))
    forget_devices(user.id)
    return codes


def new_backups(user: auth.User, code: str) -> list[str]:
    if not check(user.id, code):
        raise HTTPException(400, "That code isn't right")
    codes, hashes = _new_backups()
    db.x("UPDATE users SET totp_backup=? WHERE id=?", (json.dumps(hashes), user.id))
    return codes


def turn_off(uid: int) -> None:
    _init()
    db.x("UPDATE users SET totp_secret=NULL, totp_pending=NULL, totp_last=NULL, totp_backup=NULL WHERE id=?", (uid,))
    forget_devices(uid)


def check(uid: int, code: str) -> bool:
    """A code from the app (each good once), or one of the backup codes (used up)."""
    r = _row(uid)
    secret, typed = r["totp_secret"], _clean(code)
    if not secret or not typed:
        return False
    if typed.isdigit() and len(typed) == DIGITS:
        with _lock:
            step = _match(secret, typed, after=r["totp_last"])
            if step is None:
                return False
            db.x("UPDATE users SET totp_last=? WHERE id=?", (step, uid))
            return True
    hashes = json.loads(r["totp_backup"] or "[]")
    h = _h(typed)
    with _lock:
        if h not in hashes:
            return False
        hashes.remove(h)
        db.x("UPDATE users SET totp_backup=? WHERE id=?", (json.dumps(hashes), uid))
    return True


# ---------------------------------------------------------------- signing in: the step between password and session
def ticket_for(uid: int, ip: str) -> str:
    t = secrets.token_urlsafe(24)
    now = time.time()
    with _lock:
        for k in [k for k, v in _tickets.items() if v["expires"] < now]:
            _tickets.pop(k, None)
        _tickets[_h(t)] = {"uid": uid, "expires": now + TICKET_SECS, "tries": 0, "ip": ip}
    return t


def use_ticket(ticket: str, code: str) -> int:
    """The login the ticket is for, once the code checks out. Five tries, five minutes."""
    k = _h(str(ticket or ""))
    with _lock:
        t = _tickets.get(k)
        if not t or t["expires"] < time.time():
            _tickets.pop(k, None)
            raise HTTPException(400, "That took too long. Sign in again")
        t["tries"] += 1
        tries = t["tries"]
    if check(t["uid"], code):
        _tickets.pop(k, None)
        return t["uid"]
    if tries >= TICKET_TRIES:
        _tickets.pop(k, None)
        raise HTTPException(400, "Wrong code too many times. Sign in again")
    raise HTTPException(400, "That code isn't right")


def trust_device(uid: int) -> str:
    _init()
    token = secrets.token_urlsafe(32)
    db.x("INSERT INTO trusted_devices VALUES (?,?,?)", (_h(token), uid, time.time() + TRUST_DAYS * 86400))
    db.x("DELETE FROM trusted_devices WHERE expires_ts < ?", (time.time(),))
    return token


def is_trusted(uid: int, token: str | None) -> bool:
    _init()
    if not token:
        return False
    rows = db.q("SELECT expires_ts FROM trusted_devices WHERE token_hash=? AND user_id=?", (_h(token), uid))
    return bool(rows and rows[0]["expires_ts"] > time.time())


def forget_devices(uid: int) -> None:
    _init()
    db.x("DELETE FROM trusted_devices WHERE user_id=?", (uid,))
