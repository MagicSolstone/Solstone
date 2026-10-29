"""Things players do on the website once signed in: votes (polls and build contests), signing up for events, and
messages with the admins.

Made for kids: players pick, they don't write to each other. Votes show totals only, never who voted for what (not
even to admins). Messages are only ever between one player and the admins: a suggestion box, the admins' answers,
and notices Solstone sends by itself (a vote closed, your build won).

A build contest is a vote where each entry says who built it; nobody can vote for an entry they built, under any of
their Minecraft names. Votes can be made in the game too: "!vote 2" in chat counts for the newest open vote.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import threading
import time

from . import auth, db, mcname

SCHEMA = """
CREATE TABLE IF NOT EXISTS polls (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL DEFAULT 'poll',          -- 'poll' or 'build'
  question TEXT NOT NULL,
  detail TEXT NOT NULL DEFAULT '',
  options TEXT NOT NULL,                      -- [{"id", "text", "image", "builders": [names]}]
  results TEXT NOT NULL DEFAULT 'voted',      -- 'voted': shown once you've voted; 'closed': only when it closes
  created_ts REAL NOT NULL,
  closes_ts REAL,
  closed_ts REAL,
  announced INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS poll_votes (
  poll_id INTEGER NOT NULL,
  voter TEXT NOT NULL,                        -- 'u<id>' for an account, 'p:<name>' for a player voting in the game
  option TEXT NOT NULL,
  ts REAL NOT NULL,
  PRIMARY KEY (poll_id, voter)
);
CREATE TABLE IF NOT EXISTS signups (
  event TEXT NOT NULL,
  user_id INTEGER NOT NULL,
  ts REAL NOT NULL,
  PRIMARY KEY (event, user_id)
);
CREATE TABLE IF NOT EXISTS threads (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,                   -- the player it's with
  kind TEXT NOT NULL,                         -- 'suggestion' (they wrote first), 'message' (an admin did), 'notice'
  subject TEXT NOT NULL,
  created_ts REAL NOT NULL,
  updated_ts REAL NOT NULL,
  user_read_ts REAL NOT NULL DEFAULT 0,
  admin_read_ts REAL NOT NULL DEFAULT 0,
  closed INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_threads_user ON threads(user_id, updated_ts);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  thread_id INTEGER NOT NULL,
  from_admin INTEGER NOT NULL,
  author TEXT NOT NULL,
  body TEXT NOT NULL,
  ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_messages_thread ON messages(thread_id, ts);
"""
_ready = False
_lock = threading.Lock()
SUBJECT_MAX, BODY_MAX, OPTIONS_MAX = 80, 1000, 12
KINDS = {"idea": "💡 Idea", "problem": "🛠️ Something's wrong", "question": "❓ Question", "other": "✉️ Something else"}


def _init() -> None:
    global _ready
    with _lock:
        if not _ready:
            db.conn().executescript(SCHEMA)
            if "user_hidden" not in {r["name"] for r in db.q("PRAGMA table_info(threads)")}:    # added later
                db.conn().execute("ALTER TABLE threads ADD COLUMN user_hidden INTEGER NOT NULL DEFAULT 0")
            _ready = True


def _line(v, n: int) -> str:
    return " ".join(str(v or "").split())[:n]


def _text(v, n: int) -> str:
    return re.sub(r"\n{3,}", "\n\n", str(v or "").replace("\r", "")).strip()[:n]


def voter_key(user: auth.User) -> str:
    return f"u{user.id}"


def _names_of(voter: str) -> set[str]:
    """Every Minecraft name (lowercase) a voter plays as."""
    if voter.startswith("p:"):
        return {voter[2:]}
    u = auth.get_user(int(voter[1:])) if voter[1:].isdigit() else None
    return {p["name"].lower() for p in (u.players if u else [])}


# ---------------------------------------------------------------- votes
def clean_poll(body: dict) -> dict:
    kind = body.get("kind") if body.get("kind") in ("poll", "build") else "poll"
    question = _line(body.get("question"), 120)
    if not question:
        raise ValueError("Write the question")
    opts, seen = [], set()
    for o in (body.get("options") or [])[:OPTIONS_MAX]:
        o = o if isinstance(o, dict) else {"text": o}
        text = _line(o.get("text"), 80)
        if not text:
            continue
        oid = re.sub(r"[^a-z0-9]", "", str(o.get("id") or ""))[:12] or secrets.token_hex(3)
        while oid in seen:
            oid = secrets.token_hex(3)
        seen.add(oid)
        from .site import IMAGE_NAME
        img = str(o.get("image") or "").rsplit("/", 1)[-1]
        builders = sorted({str(b).strip() for b in (o.get("builders") or []) if mcname.is_name(str(b).strip())}, key=str.lower)
        opts.append({"id": oid, "text": text, "image": img if IMAGE_NAME.match(img) else "",
                     "builders": builders if kind == "build" else []})
    if len(opts) < 2:
        raise ValueError("Give it at least two choices")
    if kind == "build" and any(not o["builders"] for o in opts):
        raise ValueError("Say who built each entry, so nobody can vote for their own")
    closes = body.get("closes_ts")
    try:
        closes = float(closes) if closes else None
    except (TypeError, ValueError):
        closes = None
    return {"kind": kind, "question": question, "detail": _text(body.get("detail"), 400), "options": opts,
            "results": body.get("results") if body.get("results") in ("voted", "closed") else "voted", "closes_ts": closes}


def _row(r) -> dict:
    return {"id": r["id"], "kind": r["kind"], "question": r["question"], "detail": r["detail"], "options": json.loads(r["options"]),
            "results": r["results"], "created": r["created_ts"], "closes": r["closes_ts"], "closed": r["closed_ts"]}


def create_poll(body: dict) -> dict:
    _init()
    p = clean_poll(body)
    pid = db.x("INSERT INTO polls(kind, question, detail, options, results, created_ts, closes_ts) VALUES (?,?,?,?,?,?,?)",
               (p["kind"], p["question"], p["detail"], json.dumps(p["options"]), p["results"], time.time(), p["closes_ts"]))
    return get_poll(pid)


def update_poll(pid: int, body: dict) -> dict:
    """Changing a vote people already voted in keeps their votes for the choices still there."""
    _init()
    if not get_poll(pid):
        raise KeyError(pid)
    p = clean_poll(body)
    db.x("UPDATE polls SET kind=?, question=?, detail=?, options=?, results=?, closes_ts=? WHERE id=?",
         (p["kind"], p["question"], p["detail"], json.dumps(p["options"]), p["results"], p["closes_ts"], pid))
    db.x(f"DELETE FROM poll_votes WHERE poll_id=? AND option NOT IN ({','.join('?' * len(p['options']))})",
         (pid, *[o["id"] for o in p["options"]]))
    return get_poll(pid)


def delete_poll(pid: int) -> None:
    _init()
    db.x("DELETE FROM poll_votes WHERE poll_id=?", (pid,))
    db.x("DELETE FROM polls WHERE id=?", (pid,))


def get_poll(pid: int) -> dict | None:
    _init()
    rows = db.q("SELECT * FROM polls WHERE id=?", (pid,))
    return _row(rows[0]) if rows else None


def is_open(p: dict, now: float | None = None) -> bool:
    now = now or time.time()
    return not p["closed"] and not (p["closes"] and p["closes"] <= now)


def polls(limit: int = 30) -> list[dict]:
    _init()
    return [_row(r) for r in db.q("SELECT * FROM polls ORDER BY created_ts DESC LIMIT ?", (limit,))]


def open_polls() -> list[dict]:
    return [p for p in polls() if is_open(p)]


def tally(pid: int) -> dict[str, int]:
    _init()
    return {r["option"]: r["n"] for r in db.q("SELECT option, COUNT(*) n FROM poll_votes WHERE poll_id=? GROUP BY option", (pid,))}


def my_vote(pid: int, voter: str) -> str | None:
    _init()
    r = db.q("SELECT option FROM poll_votes WHERE poll_id=? AND voter=?", (pid, voter))
    return r[0]["option"] if r else None


def own_entries(p: dict, voter: str) -> list[str]:
    """The entries of a build contest this voter built (they can't vote for those)."""
    names = _names_of(voter)
    return [o["id"] for o in p["options"] if names & {b.lower() for b in o.get("builders") or []}]


def vote(pid: int, voter: str, option: str) -> dict:
    p = get_poll(pid)
    if not p:
        raise KeyError(pid)
    if not is_open(p):
        raise ValueError("This vote has closed")
    if option not in {o["id"] for o in p["options"]}:
        raise ValueError("That isn't one of the choices")
    if option in own_entries(p, voter):
        raise ValueError("You can't vote for a build you made. Pick someone else's!")
    db.x("INSERT INTO poll_votes(poll_id, voter, option, ts) VALUES (?,?,?,?) "
         "ON CONFLICT(poll_id, voter) DO UPDATE SET option=excluded.option, ts=excluded.ts", (pid, voter, option, time.time()))
    return p


def view(p: dict, voter: str | None, admin: bool = False) -> dict:
    """A vote as someone sees it: totals only when they may see them, never who voted for what."""
    mine = my_vote(p["id"], voter) if voter else None
    open_ = is_open(p)
    show = admin or not open_ or (p["results"] == "voted" and mine is not None)
    out = {**p, "open": open_, "mine": mine, "own": own_entries(p, voter) if voter and p["kind"] == "build" else [],
           "show_results": show}
    out["options"] = [{**o, "image": f"/api/public/images/{o['image']}" if o.get("image") else ""} for o in p["options"]]
    if show:
        t = tally(p["id"])
        out["counts"] = {o["id"]: t.get(o["id"], 0) for o in p["options"]}
        out["total"] = sum(out["counts"].values())
    return out


def winners(p: dict) -> list[dict]:
    t = tally(p["id"])
    best = max(t.values(), default=0)
    return [o for o in p["options"] if best and t.get(o["id"], 0) == best]


def close_due(now: float | None = None) -> list[dict]:
    """Votes whose time is up and haven't been closed yet: closes them and hands them back, for the notices."""
    _init()
    now = now or time.time()
    out = []
    for r in db.q("SELECT * FROM polls WHERE closed_ts IS NULL AND closes_ts IS NOT NULL AND closes_ts <= ?", (now,)):
        if db.x("UPDATE polls SET closed_ts=? WHERE id=? AND closed_ts IS NULL", (now, r["id"])):
            out.append(get_poll(r["id"]))
    return out


def close_now(pid: int) -> dict | None:
    _init()
    if db.x("UPDATE polls SET closed_ts=? WHERE id=? AND closed_ts IS NULL", (time.time(), pid)):
        return get_poll(pid)
    return None


def to_announce() -> list[dict]:
    _init()
    out = []
    for r in db.q("SELECT * FROM polls WHERE announced=0 AND closed_ts IS NULL"):
        db.x("UPDATE polls SET announced=1 WHERE id=?", (r["id"],))
        p = _row(r)
        if is_open(p):
            out.append(p)
    return out


def result_text(p: dict) -> str:
    w = winners(p)
    t = tally(p["id"])
    if not w:
        return "Nobody voted."
    n = t.get(w[0]["id"], 0)
    votes = f"{n} vote{'s' if n != 1 else ''}"
    if len(w) > 1:
        return f"It's a tie: {' and '.join(o['text'] for o in w)}, with {votes} each."
    who = f" (built by {', '.join(w[0]['builders'])})" if w[0].get("builders") else ""
    return f"{w[0]['text']}{who} won, with {votes}."


def closed_notices(p: dict) -> None:
    """Messages to everyone with an account who voted, and to the builders who won."""
    _init()
    text = result_text(p)
    voters = {int(r["voter"][1:]) for r in db.q("SELECT voter FROM poll_votes WHERE poll_id=? AND voter LIKE 'u%'", (p["id"],))
              if r["voter"][1:].isdigit()}
    won_by = {b.lower() for o in winners(p) for b in o.get("builders") or []}
    builders = {u["id"] for u in auth.list_users() if won_by & {pl["name"].lower() for pl in u["players"]}}
    for uid in voters - builders:
        notice(uid, f"🗳️ Vote closed: {p['question']}", f"{text}\nThanks for voting!")
    for uid in builders:
        notice(uid, f"🏆 Your build won: {p['question']}", f"{text}\nCongratulations!")


# ---------------------------------------------------------------- event sign-ups
def event_key(kind: str, title: str, at: float) -> str:
    return hashlib.sha1(f"{kind}|{title}|{int(at)}".encode()).hexdigest()[:12]


def signups(keys: list[str]) -> dict[str, list[int]]:
    _init()
    if not keys:
        return {}
    out: dict[str, list[int]] = {}
    for r in db.q(f"SELECT event, user_id FROM signups WHERE event IN ({','.join('?' * len(keys))})", tuple(keys)):
        out.setdefault(r["event"], []).append(r["user_id"])
    return out


def sign_up(event: str, uid: int, coming: bool) -> None:
    _init()
    if not re.fullmatch(r"[0-9a-f]{12}", event):
        raise ValueError("Unknown event")
    if coming:
        db.x("INSERT OR IGNORE INTO signups(event, user_id, ts) VALUES (?,?,?)", (event, uid, time.time()))
    else:
        db.x("DELETE FROM signups WHERE event=? AND user_id=?", (event, uid))


# ---------------------------------------------------------------- messages
def _thread(r) -> dict:
    return {"id": r["id"], "user_id": r["user_id"], "kind": r["kind"], "subject": r["subject"], "created": r["created_ts"],
            "updated": r["updated_ts"], "closed": bool(r["closed"]), "archived": bool(r["closed"]),
            "unread_user": r["updated_ts"] > r["user_read_ts"], "unread_admin": r["updated_ts"] > r["admin_read_ts"]}


def _add(tid: int, from_admin: bool, author: str, body: str) -> None:
    now = time.time()
    db.x("INSERT INTO messages(thread_id, from_admin, author, body, ts) VALUES (?,?,?,?,?)", (tid, int(from_admin), author, body, now))
    who = "admin_read_ts" if from_admin else "user_read_ts"       # the writer has read their own
    # something new: back out of the archive, and back in the player's list if they'd removed it
    db.x(f"UPDATE threads SET updated_ts=?, {who}=?, closed=0, user_hidden=0 WHERE id=?", (now, now, tid))


def start(user_id: int, kind: str, subject: str, body: str, from_admin: bool, author: str) -> int:
    _init()
    subject, body = _line(subject, SUBJECT_MAX), _text(body, BODY_MAX)
    if not body:
        raise ValueError("Write your message")
    tid = db.x("INSERT INTO threads(user_id, kind, subject, created_ts, updated_ts) VALUES (?,?,?,?,?)",
               (user_id, kind, subject or "(no subject)", time.time(), time.time()))
    _add(tid, from_admin, author, body)
    if kind == "notice":                       # nothing to answer
        db.x("UPDATE threads SET admin_read_ts=updated_ts WHERE id=?", (tid,))
    return tid


def notice(user_id: int, subject: str, body: str) -> int:
    return start(user_id, "notice", subject, body, True, "Solstone")


def reply(tid: int, body: str, from_admin: bool, author: str) -> None:
    _init()
    body = _text(body, BODY_MAX)
    if not body:
        raise ValueError("Write your message")
    t = thread(tid)
    if not t:
        raise KeyError(tid)
    if t["kind"] == "notice" and not from_admin:
        raise ValueError("This is a notice: there's nothing to answer. Send a new message instead.")
    _add(tid, from_admin, author, body)


def thread(tid: int) -> dict | None:
    _init()
    r = db.q("SELECT * FROM threads WHERE id=?", (tid,))
    return _thread(r[0]) if r else None


def thread_messages(tid: int) -> list[dict]:
    _init()
    return [{"id": r["id"], "from_admin": bool(r["from_admin"]), "author": r["author"], "body": r["body"], "ts": r["ts"]}
            for r in db.q("SELECT * FROM messages WHERE thread_id=? ORDER BY ts, id", (tid,))]


def mark_read(tid: int, admin: bool) -> None:
    db.x(f"UPDATE threads SET {'admin_read_ts' if admin else 'user_read_ts'}=? WHERE id=?", (time.time(), tid))


def threads_for(user_id: int) -> list[dict]:
    _init()
    return [_thread(r) for r in db.q("SELECT * FROM threads WHERE user_id=? AND user_hidden=0 ORDER BY updated_ts DESC LIMIT 100",
                                     (user_id,))]


def hide_for_user(tid: int) -> None:
    """A player removes a conversation from their list. The admins keep it; a new message brings it back."""
    _init()
    db.x("UPDATE threads SET user_hidden=1, user_read_ts=updated_ts WHERE id=?", (tid,))


def set_archived(tid: int, archived: bool) -> None:
    _init()
    db.x("UPDATE threads SET closed=?, admin_read_ts=MAX(admin_read_ts, updated_ts) WHERE id=?", (int(archived), tid))


def delete_thread(tid: int) -> None:
    _init()
    db.x("DELETE FROM messages WHERE thread_id=?", (tid,))
    db.x("DELETE FROM threads WHERE id=?", (tid,))


NOTICE_DAYS = 30
_tidied = 0.0


def tidy(now: float | None = None) -> int:
    """Notices (a vote closed, you won) go by themselves after a month; conversations stay until an admin deletes them.
    At most once an hour."""
    global _tidied
    now = now or time.time()
    if now - _tidied < 3600:
        return 0
    _tidied = now
    _init()
    old = [r["id"] for r in db.q("SELECT id FROM threads WHERE kind='notice' AND updated_ts < ?", (now - NOTICE_DAYS * 86400,))]
    for tid in old:
        delete_thread(tid)
    return len(old)


def all_threads(limit: int = 200) -> list[dict]:
    _init()
    return [_thread(r) for r in db.q("SELECT * FROM threads WHERE kind != 'notice' ORDER BY updated_ts DESC LIMIT ?", (limit,))]


def unread(user_id: int) -> int:
    _init()
    return db.q("SELECT COUNT(*) n FROM threads WHERE user_id=? AND user_hidden=0 AND updated_ts > user_read_ts", (user_id,))[0]["n"]


def unread_admin() -> int:
    _init()
    return db.q("SELECT COUNT(*) n FROM threads WHERE kind != 'notice' AND updated_ts > admin_read_ts")[0]["n"]


def recent_from(user_id: int, seconds: int = 3600) -> int:
    """How many messages a player has written lately (so nobody can flood the admins)."""
    _init()
    return db.q("SELECT COUNT(*) n FROM messages m JOIN threads t ON t.id = m.thread_id "
                "WHERE t.user_id=? AND m.from_admin=0 AND m.ts > ?", (user_id, time.time() - seconds))[0]["n"]


def forget_user(uid: int) -> None:
    """An account removed: its messages, votes and sign-ups go too (a new account never inherits them)."""
    _init()
    for (tid,) in [(r["id"],) for r in db.q("SELECT id FROM threads WHERE user_id=?", (uid,))]:
        db.x("DELETE FROM messages WHERE thread_id=?", (tid,))
    db.x("DELETE FROM threads WHERE user_id=?", (uid,))
    db.x("DELETE FROM poll_votes WHERE voter=?", (f"u{uid}",))
    db.x("DELETE FROM signups WHERE user_id=?", (uid,))
