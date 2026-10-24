"""Adventures: replays of play sessions on the world map.

While anyone is on, where each player is gets written down every few seconds (RCON `data get entity`), and the
game's statistics are compared between saves so what happened between them becomes feed lines ("defeated 3 zombies,
mined 2 diamond ore"). A play session is a stretch of time with anyone on (gaps under ten minutes joined up). The
Adventures page replays one: trails on the map, a scrubbable timeline, and the feed (joins, chat, deaths,
advancements, fish, and those statistics). A session can be saved with a title and a note; saved ones keep their
trail when older positions are cleared out.
"""
from __future__ import annotations

import logging
import re
import time

from . import db
from . import servers as S
from .rcon import RconError

log = logging.getLogger("solstone.adventures")

TRACK_INTERVAL = 5            # seconds between position checks while someone is on
KEEP_STILL = 60               # a player standing still is written down at most this often
POSITIONS_DAYS = 45           # positions older than this go, unless they're part of a saved adventure
SESSION_GAP = 600             # online stretches closer than this are one session

# the positions and adventures tables are in db.SCHEMA


# the statistics worth a feed line, and how to say them
_ORES = {"minecraft:diamond_ore": "diamond ore", "minecraft:deepslate_diamond_ore": "diamond ore",
         "minecraft:ancient_debris": "ancient debris", "minecraft:emerald_ore": "emerald ore",
         "minecraft:deepslate_emerald_ore": "emerald ore", "minecraft:gold_ore": "gold ore",
         "minecraft:deepslate_gold_ore": "gold ore", "minecraft:nether_gold_ore": "nether gold ore",
         "minecraft:iron_ore": "iron ore", "minecraft:deepslate_iron_ore": "iron ore"}


# ------------------------------------------------------------------ recording
_last: dict[tuple[str, str], tuple[float, str, float, float, float]] = {}   # (server, player) -> last written
_stats: dict[tuple[str, str], dict] = {}                                     # (server, player) -> last stats seen


_POS_OF = re.compile(r"(\S+) has the following entity data: \[\s*(-?[\d.]+)d?,\s*(-?[\d.]+)d?,\s*(-?[\d.]+)d?\s*\]")
_DIM_OF = re.compile(r'(\S+) has the following entity data: "([a-z0-9_.-]+:[a-z0-9_/.-]+)"')


async def _everyone(srv) -> dict[str, tuple[str, float, float, float]]:
    """Where every online player is: two commands however many are on (fewer "[Rcon: ...]" lines for ops)."""
    try:
        pos = await srv.rcon("execute as @a run data get entity @s Pos") or ""
        dims = await srv.rcon("execute as @a run data get entity @s Dimension") or ""
    except RconError:
        return {}
    dim_of = {m.group(1): m.group(2) for m in _DIM_OF.finditer(dims)}
    return {m.group(1): (dim_of.get(m.group(1), "minecraft:overworld"), float(m.group(2)), float(m.group(3)), float(m.group(4)))
            for m in _POS_OF.finditer(pos)}


async def track(srv, names: list[str]) -> int:
    """Write down where everyone online is (moved a block or more, or a minute since the last). Returns rows written."""
    if not names or not srv.rcon_conf():
        return 0
    now, rows = time.time(), []
    for n, (dim, x, y, z) in (await _everyone(srv)).items():
        prev = _last.get((srv.id, n))
        if prev and prev[1] == dim and abs(prev[2] - x) + abs(prev[3] - y) + abs(prev[4] - z) < 1 and now - prev[0] < KEEP_STILL:
            continue
        _last[(srv.id, n)] = (now, dim, x, y, z)
        rows.append((srv.id, now, n, dim, round(x, 1), round(y, 1), round(z, 1)))
    if rows:
        with db._lock:
            db.conn().executemany("INSERT INTO positions(server_id, ts, player, dim, x, y, z) VALUES (?,?,?,?,?,?,?)", rows)
    return len(rows)


def _short(key: str) -> str:
    return key.split(":", 1)[-1].replace("_", " ")


def progress_line(before: dict, after: dict) -> str | None:
    """What changed between two saves of a player's statistics, in a line ("defeated 3 zombies · mined 2 diamond ore")."""
    parts = []
    kb, ka = before.get("minecraft:killed") or {}, after.get("minecraft:killed") or {}
    kills = sorted(((ka[k] - kb.get(k, 0), k) for k in ka if ka[k] > kb.get(k, 0)), reverse=True)
    if kills:
        parts.append("defeated " + ", ".join(f"{n} {_short(k)}{'s' if n > 1 and not _short(k).endswith('s') else ''}" for n, k in kills[:4])
                     + (f" and {len(kills) - 4} more kinds" if len(kills) > 4 else ""))
    mb, ma = before.get("minecraft:mined") or {}, after.get("minecraft:mined") or {}
    ores: dict[str, int] = {}
    for k, label in _ORES.items():
        d = ma.get(k, 0) - mb.get(k, 0)
        if d > 0:
            ores[label] = ores.get(label, 0) + d
    if ores:
        parts.append("mined " + ", ".join(f"{n} {o}" for o, n in sorted(ores.items(), key=lambda i: -i[1])))
    cb, ca = before.get("minecraft:custom") or {}, after.get("minecraft:custom") or {}
    taken = (ca.get("minecraft:damage_taken", 0) - cb.get("minecraft:damage_taken", 0)) / 20   # tenths of a heart -> hearts
    if taken >= 5:
        parts.append(f"took {taken:.0f} ❤ of damage")
    eaten = ca.get("minecraft:eat_cake_slice", 0) - cb.get("minecraft:eat_cake_slice", 0)
    if eaten > 0:
        parts.append(f"ate {eaten} slice{'s' if eaten > 1 else ''} of cake")
    return " · ".join(parts) or None


def progress(srv, online: dict[str, str | None]) -> int:
    """Feed lines from statistics that changed since the last save (the game writes them every few minutes)."""
    n = 0
    for name, uuid in online.items():
        if not uuid:
            continue
        st = S.player_stats(srv, uuid)
        if not st:
            continue
        prev = _stats.get((srv.id, name))
        _stats[(srv.id, name)] = st
        if prev is None or prev == st:
            continue
        line = progress_line(prev, st)
        if line:
            db.add_event(srv.id, time.time(), "progress", f"{name} {line}", name, uuid)
            n += 1
    return n


def prune() -> None:
    cutoff = time.time() - POSITIONS_DAYS * 86400
    db.x("""DELETE FROM positions WHERE ts < ? AND NOT EXISTS (
            SELECT 1 FROM adventures a WHERE a.server_id = positions.server_id AND positions.ts BETWEEN a.start_ts AND a.end_ts)""", (cutoff,))


# ------------------------------------------------------------------ reading
def sessions(server_id: str, days: int = 30) -> list[dict]:
    """Play sessions (anyone on), newest first, with who played and any saved adventure in them."""
    since = time.time() - days * 86400
    rows = db.q("SELECT player, start_ts, COALESCE(end_ts, last_seen_ts) AS end_ts FROM sessions "
                "WHERE server_id=? AND COALESCE(end_ts, last_seen_ts) >= ? ORDER BY start_ts", (server_id, since))
    out: list[dict] = []
    for r in rows:
        if out and r["start_ts"] <= out[-1]["end"] + SESSION_GAP:
            out[-1]["end"] = max(out[-1]["end"], r["end_ts"])
            out[-1]["players"].add(r["player"])
        else:
            out.append({"start": r["start_ts"], "end": r["end_ts"], "players": {r["player"]}})
    saved = [dict(a) for a in db.q("SELECT * FROM adventures WHERE server_id=? ORDER BY start_ts DESC", (server_id,))]
    result = []
    for s in reversed(out):
        if s["end"] - s["start"] < 60:
            continue
        mine = [a for a in saved if a["start_ts"] < s["end"] and a["end_ts"] > s["start"]]
        result.append({"start": s["start"], "end": s["end"], "players": sorted(s["players"], key=str.lower),
                       "saved": [_public(a) for a in mine]})
    # saved adventures older than the list still show
    shown = {a["id"] for s in result for a in s["saved"]}
    for a in saved:
        if a["id"] not in shown:
            result.append({"start": a["start_ts"], "end": a["end_ts"], "players": _players_between(server_id, a["start_ts"], a["end_ts"]),
                           "saved": [_public(a)]})
    result.sort(key=lambda s: -s["start"])
    return result


def _players_between(server_id: str, start: float, end: float) -> list[str]:
    # from the play sessions (a few rows a day), not the positions (thousands): the list stays quick with many saved
    rows = db.q("SELECT DISTINCT player FROM sessions WHERE server_id=? AND start_ts <= ? AND COALESCE(end_ts, last_seen_ts) >= ?",
                (server_id, end, start))
    return sorted((r["player"] for r in rows), key=str.lower)


def _public(a) -> dict:
    return {"id": a["id"], "start": a["start_ts"], "end": a["end_ts"], "title": a["title"], "note": a["note"],
            "created_by": a["created_by"]}


TIMELINE_TYPES = ["join", "leave", "chat", "webchat", "death", "advancement", "challenge", "race", "fish", "bigfish", "game", "progress"]


def timeline(server_id: str, start: float, end: float) -> dict:
    """Everyone's trail and the feed between two times (at most a day)."""
    end = min(end, start + 86400)
    trails: dict[str, list] = {}
    for r in db.q("SELECT ts, player, dim, x, y, z FROM positions WHERE server_id=? AND ts BETWEEN ? AND ? ORDER BY ts",
                  (server_id, start, end)):
        trails.setdefault(r["player"], []).append([round(r["ts"], 1), r["dim"], r["x"], r["y"], r["z"]])
    marks = ",".join("?" * len(TIMELINE_TYPES))
    events = [{"ts": e["ts"], "type": e["type"], "player": e["player"], "message": e["message"]}
              for e in db.q(f"SELECT ts, type, player, message FROM events WHERE server_id=? AND ts BETWEEN ? AND ? "
                            f"AND type IN ({marks}) ORDER BY ts", (server_id, start, end, *TIMELINE_TYPES))]
    return {"start": start, "end": end, "trails": trails, "events": events}


def save(server_id: str, start: float, end: float, title: str, note: str, who: str, aid: int | None = None) -> dict:
    title, note = " ".join(title.split())[:80], note.strip()[:2000]
    if not title:
        raise ValueError("Give it a title")
    if end <= start:
        raise ValueError("The end has to be after the start")
    if aid:
        db.x("UPDATE adventures SET title=?, note=?, start_ts=?, end_ts=? WHERE id=? AND server_id=?", (title, note, start, end, aid, server_id))
    else:
        aid = db.x("INSERT INTO adventures(server_id, start_ts, end_ts, title, note, created_by, created_ts) VALUES (?,?,?,?,?,?,?)",
                   (server_id, start, end, title, note, who, time.time()))
    return _public(db.q("SELECT * FROM adventures WHERE id=?", (aid,))[0])


def get(aid: int) -> dict | None:
    rows = db.q("SELECT * FROM adventures WHERE id=?", (aid,))
    return dict(rows[0]) if rows else None


def delete(aid: int) -> None:
    db.x("DELETE FROM adventures WHERE id=?", (aid,))
