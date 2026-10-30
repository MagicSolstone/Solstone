"""Forgetting a player: everything Solstone keeps about one Minecraft player, across all servers, for when someone
has left for good (Manage → Whitelist → Removing a player).

Solstone keeps its own history, so deleting a player's files from the server doesn't take them off Solstone's
pages. This does: their play history (days played, play time), the activity feed and chat lines that are theirs,
their Adventures trail, their fishing catches, their name in daily recaps and in finished contests, races and
games ("a former player" instead), their play-time rules, join firework, prizes still owed, asks to join and
in-game votes (taken back from votes still open; kept in the count of finished ones, as nobody's).

Not touched: the game's own files (their inventory, stats, advancements, whitelist place and land claims: the
removal guide covers those), and a website account, which is deleted on its own (Manage → Users).

A Solstone backup is made just before, so a mistake can be undone (see selfbackup.py for restoring).
"""
from __future__ import annotations

import json
import logging
import re

from . import db, settings_store

log = logging.getLogger("solstone.forget")

FORMER = "a former player"


def _norm(uuid: str | None) -> str:
    return (uuid or "").lower().replace("-", "")


def who(name: str) -> dict | None:
    """The player by any name they've played under: their ID (when known) and every name it has used."""
    name = (name or "").strip()
    if not re.fullmatch(r"\.?[A-Za-z0-9_]{1,16}", name):
        return None
    rows = db.q("SELECT player, uuid FROM sessions WHERE player=? COLLATE NOCASE AND uuid IS NOT NULL ORDER BY start_ts DESC LIMIT 1", (name,))
    uuid = rows[0]["uuid"] if rows else None
    if not uuid:
        from . import servers as S
        for srv in S.registry.servers.values():
            uuid = next((u for u, p in S.known_players(srv).items() if p["name"].lower() == name.lower()), None)
            if uuid:
                break
    names = {name.lower()}
    if uuid:
        names |= {r["player"].lower() for r in db.q("SELECT DISTINCT player FROM sessions WHERE lower(replace(uuid, '-', ''))=?", (_norm(uuid),))}
    return {"name": name, "uuid": uuid, "names": sorted(names)}


def _where(p: dict, with_uuid: bool = True) -> tuple[str, tuple]:
    marks = ",".join("?" * len(p["names"]))
    if with_uuid and p["uuid"]:
        return f"(lower(player) IN ({marks}) OR lower(replace(uuid, '-', ''))=?)", (*p["names"], _norm(p["uuid"]))
    return f"lower(player) IN ({marks})", tuple(p["names"])


def _named(text: str, names: list[str]) -> bool:
    return any(re.search(rf"(?<![A-Za-z0-9_.]){re.escape(n)}(?![A-Za-z0-9_])", text, re.I) for n in names)


def _scrub(obj, names: set[str]):
    """Their name out of a saved contest, race or game: score lists without them, results with "a former player"."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if isinstance(k, str) and k.lower() in names:
                continue                                   # {name: score}
            if isinstance(v, dict) and str(v.get("name") or v.get("player") or "").lower() in names:
                continue
            out[k] = _scrub(v, names)
        return out
    if isinstance(obj, list):
        keep = []
        for v in obj:
            if isinstance(v, str) and v.lower() in names:
                continue
            if isinstance(v, dict) and str(v.get("name") or v.get("player") or "").lower() in names:
                continue
            keep.append(_scrub(v, names))
        return keep
    if isinstance(obj, str) and any(n in obj.lower() for n in names):
        for n in names:
            obj = re.sub(rf"(?<![A-Za-z0-9_.]){re.escape(n)}(?![A-Za-z0-9_])", FORMER, obj, flags=re.I)
        return obj
    return obj


def _played(p: dict) -> list[tuple[str, str, list]]:
    """(settings section, list key, items) of contests, races and games that mention them."""
    names = set(p["names"])
    out = []
    for section, key in (("challenges", "items"), ("races", "runs"), ("games", "runs")):
        items = (settings_store.load().get(section) or {}).get(key) or []
        hits = [it for it in items if any(n in json.dumps(it).lower() for n in names)]
        out.append((section, key, hits))
    return out


def plan(name: str) -> dict | None:
    """What forgetting them would remove: counts of each kind (nothing is changed)."""
    p = who(name)
    if not p:
        return None
    where, args = _where(p)
    pw, pargs = _where(p, with_uuid=False)
    recaps = [r for r in db.q("SELECT data FROM recaps") if _named(r["data"], p["names"])]
    cfg = settings_store.load()
    pt = (cfg.get("playtime") or {}).get("people") or {}
    counts = {
        "sessions": db.q(f"SELECT COUNT(*) AS n FROM sessions WHERE {where}", args)[0]["n"],
        "events": db.q(f"SELECT COUNT(*) AS n FROM events WHERE {where}", args)[0]["n"],
        "positions": db.q(f"SELECT COUNT(*) AS n FROM positions WHERE {pw}", pargs)[0]["n"],
        "fish": db.q(f"SELECT COUNT(*) AS n FROM fish_catches WHERE {pw}", pargs)[0]["n"],
        "recaps": len(recaps),
        "challenges": sum(len(h) for _s, _k, h in _played(p)),
        "playtime": sum(1 for n in p["names"] if f"p:{n}" in pt),
        "join_firework": sum(1 for n in p["names"] if n in (cfg.get("fw_signatures") or {})),
        "prizes_owed": sum(1 for g in (cfg.get("challenges") or {}).get("gifts") or [] if g.get("player", "").lower() in p["names"]),
        "join_requests": sum(1 for r in cfg.get("join_requests") or [] if r.get("player", "").lower() in p["names"]),
        "votes": db.q(f"SELECT COUNT(*) AS n FROM poll_votes WHERE voter IN ({','.join('?' * len(p['names']))})",
                      tuple(f"p:{n}" for n in p["names"]))[0]["n"] if _has("poll_votes") else 0,
    }
    from . import auth
    acct = next((u for u in auth.list_users() if any(x["name"].lower() in p["names"] for x in u["players"])), None)
    return {**p, "counts": counts, "total": sum(counts.values()), "account": acct["username"] if acct else None}


def _has(table: str) -> bool:
    return bool(db.q("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)))


def wipe(name: str) -> dict:
    """Forget them. Returns what was removed (the same counts as plan())."""
    from . import playtime, selfbackup
    before = plan(name)
    if not before:
        raise ValueError("That isn't a Minecraft name")
    selfbackup.make()                                     # undo, if this was a mistake
    p = before
    names = set(p["names"])
    where, args = _where(p)
    pw, pargs = _where(p, with_uuid=False)
    db.x(f"DELETE FROM sessions WHERE {where}", args)
    db.x(f"DELETE FROM events WHERE {where}", args)
    db.x(f"DELETE FROM positions WHERE {pw}", pargs)
    db.x(f"DELETE FROM fish_catches WHERE {pw}", pargs)
    for r in db.q("SELECT server_id, day, data FROM recaps"):
        if _named(r["data"], p["names"]):
            d = _scrub(json.loads(r["data"]), names)
            d["total_seconds"] = sum(x.get("seconds", 0) for x in d.get("players") or [])
            db.x("UPDATE recaps SET data=? WHERE server_id=? AND day=?", (json.dumps(d, separators=(",", ":")), r["server_id"], r["day"]))
    for section, key, hits in _played(p):
        if hits:
            cfg = settings_store.load().get(section) or {}
            cfg[key] = [_scrub(it, names) if it in hits else it for it in cfg.get(key) or []]
            settings_store.save_section(section, cfg)
    cfg = settings_store.load()
    pt = cfg.get(playtime.SECTION)
    if isinstance(pt, dict) and any(f"p:{n}" in (pt.get("people") or {}) for n in names):
        pt["people"] = {k: v for k, v in pt["people"].items() if k not in {f"p:{n}" for n in names}}
        playtime.save(pt)
    sigs = cfg.get("fw_signatures") or {}
    if any(n in sigs for n in names):
        settings_store.save_section("fw_signatures", {k: v for k, v in sigs.items() if k not in names})
    ch = cfg.get("challenges") or {}
    if any(g.get("player", "").lower() in names for g in ch.get("gifts") or []):
        ch["gifts"] = [g for g in ch["gifts"] if g.get("player", "").lower() not in names]
        settings_store.save_section("challenges", ch)
    if any(r.get("player", "").lower() in names for r in cfg.get("join_requests") or []):
        settings_store.save_section("join_requests", [r for r in cfg["join_requests"] if r.get("player", "").lower() not in names])
    if _has("poll_votes"):
        voters = tuple(f"p:{n}" for n in names)
        marks = ",".join("?" * len(voters))
        db.x(f"DELETE FROM poll_votes WHERE voter IN ({marks}) AND poll_id IN (SELECT id FROM polls WHERE closed_ts IS NULL)", voters)
        import secrets
        for r in db.q(f"SELECT poll_id, voter FROM poll_votes WHERE voter IN ({marks})", voters):
            db.x("UPDATE poll_votes SET voter=? WHERE poll_id=? AND voter=?", (f"gone:{secrets.token_hex(6)}", r["poll_id"], r["voter"]))
    log.info("forgot %s (%s)", p["name"], ", ".join(p["names"]))
    return before
