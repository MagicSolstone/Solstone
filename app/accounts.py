"""What else belongs to an account, for renaming it and for deleting it.

Most things are kept by the account's id and need nothing (its Minecraft names, messages, votes, sign-ups). Some
are kept by its login name: fireworks and saved sounds, a maker's weight in the show, posts, Adventures saved or
hidden, and the activity log. Renaming carries those over to the new login.

Deleting an account takes with it what was only theirs: their fireworks and sounds, their join firework and their
weight in the show (messages, votes and sign-ups go in community.forget_user). Kept: posts on the website (the
site's own pages), Adventures saved for a server, and the activity log. A player's bedtime and play-time limits
move onto their Minecraft names, so they still apply in the game without an account.
"""
from __future__ import annotations

import logging

from . import db, fireworks, settings_store

log = logging.getLogger("solstone.accounts")


def rename(old: str, new: str) -> None:
    """Everything kept under the login `old` now goes by `new`."""
    if not old or old == new:
        return
    with fireworks._lock:
        items = fireworks._load()
        for d in items:
            if d.get("author") == old:
                d["author"] = new
        fireworks._save(items)
        sounds = fireworks.sounds()
        for s in sounds:
            if s.get("author") == old:
                s["author"] = new
        settings_store.save_section("sounds", sounds)
    cw = settings_store.load().get("fw_creators") or {}
    if old in cw:
        cw[new] = cw.pop(old)
        settings_store.save_section("fw_creators", cw)
    for sql in ("UPDATE posts SET author=? WHERE author=?", "UPDATE adventures SET created_by=? WHERE created_by=?",
                "UPDATE adventures_hidden SET hidden_by=? WHERE hidden_by=?", "UPDATE audit SET username=? WHERE username=?"):
        try:
            db.x(sql, (new, old))
        except Exception:                          # a table that isn't made yet
            log.debug("rename skipped: %s", sql)


def forget(uid: int, username: str, players: list[str]) -> dict:
    """An account is being deleted: what was only theirs goes. Returns how much (for the activity log)."""
    from . import playtime
    gone = {"fireworks": 0, "sounds": 0}
    with fireworks._lock:
        items = fireworks._load()
        keep = [d for d in items if d.get("author") != username]
        gone["fireworks"] = len(items) - len(keep)
        fireworks._save(keep)
        sounds = fireworks.sounds()
        keep_s = [s for s in sounds if s.get("author") != username]
        gone["sounds"] = len(sounds) - len(keep_s)
        settings_store.save_section("sounds", keep_s)
    cw = settings_store.load().get("fw_creators") or {}
    if username in cw:
        del cw[username]
        settings_store.save_section("fw_creators", cw)
    names = {p.lower() for p in players}
    sigs = settings_store.load().get("fw_signatures") or {}
    if any(k.lower() in names for k in sigs):
        settings_store.save_section("fw_signatures", {k: v for k, v in sigs.items() if k.lower() not in names})
    # bedtime and play-time limits: from the account onto its Minecraft names (they still play)
    pt = settings_store.load().get(playtime.SECTION)
    if isinstance(pt, dict) and f"u{uid}" in (pt.get("people") or {}):
        row = pt["people"].pop(f"u{uid}")
        for n in names:
            pt["people"].setdefault(f"p:{n}", dict(row))
        playtime.save(pt)
    return gone


def follow_name(uuid: str, name: str) -> str | None:
    """A player joined under a new name (a Java name change, a new Xbox gamertag): the game knows them by their
    UUID, which stays the same, so their stats, whitelist place and history carry on. What Solstone keeps under the
    name follows: the name linked to their account (and their login, if it was that name), their play-time limits,
    their join firework and their votes. Returns the old name if it changed."""
    from . import auth, playtime
    if not uuid or not name:
        return None
    auth._init()
    row = next((r for r in db.q("SELECT user_id, name FROM user_players WHERE lower(replace(uuid, '-', ''))=?",
                                (uuid.lower().replace("-", ""),))), None)
    old = row["name"] if row and row["name"] != name else None
    if old:
        db.x("UPDATE user_players SET name=? WHERE lower(replace(uuid, '-', ''))=?", (name, uuid.lower().replace("-", "")))
        auth._sync_first(row["user_id"])
        u = auth.get_user(row["user_id"])
        if u and u.username.lower() == old.lower() and not db.q(
                "SELECT 1 FROM users WHERE id<>? AND username=? COLLATE NOCASE", (u.id, name)):
            db.x("UPDATE users SET username=? WHERE id=?", (name, u.id))      # they sign in with their Minecraft name
            rename(u.username, name)
        auth.audit(name, None, "name_changed", f"{old} → {name}")
    if not old:                                     # not on an account: name-kept things may still need to follow
        old = _previous_name(uuid, name)
    if not old:
        return None
    o, n = old.lower(), name.lower()
    pt = settings_store.load().get(playtime.SECTION)
    if isinstance(pt, dict) and f"p:{o}" in (pt.get("people") or {}):
        pt["people"].setdefault(f"p:{n}", pt["people"].pop(f"p:{o}"))
        playtime.save(pt)
    sigs = settings_store.load().get("fw_signatures") or {}
    if o in sigs:
        sigs.setdefault(n, sigs.pop(o))
        settings_store.save_section("fw_signatures", sigs)
    try:
        db.x("UPDATE OR IGNORE poll_votes SET voter=? WHERE voter=?", (f"p:{n}", f"p:{o}"))
    except Exception:
        pass
    return old


def _previous_name(uuid: str, name: str) -> str | None:
    """The name this UUID last joined under, if it was a different one (from the play history)."""
    try:
        r = db.q("SELECT player FROM sessions WHERE lower(replace(uuid, '-', ''))=? AND player<>? ORDER BY start_ts DESC LIMIT 1",
                 (uuid.lower().replace("-", ""), name))
    except Exception:
        return None
    return r[0]["player"] if r else None
