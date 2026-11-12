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
import threading
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
         "minecraft:iron_ore": "iron ore", "minecraft:deepslate_iron_ore": "iron ore",
         "minecraft:lapis_ore": "lapis ore", "minecraft:deepslate_lapis_ore": "lapis ore",
         "minecraft:redstone_ore": "redstone ore", "minecraft:deepslate_redstone_ore": "redstone ore",
         "minecraft:copper_ore": "copper ore", "minecraft:deepslate_copper_ore": "copper ore",
         "minecraft:coal_ore": "coal ore", "minecraft:deepslate_coal_ore": "coal ore", "minecraft:nether_quartz_ore": "quartz ore"}
_CROPS = {"minecraft:wheat", "minecraft:carrots", "minecraft:potatoes", "minecraft:beetroots", "minecraft:melon",
          "minecraft:pumpkin", "minecraft:sugar_cane", "minecraft:sweet_berry_bush", "minecraft:cocoa", "minecraft:nether_wart",
          "minecraft:bamboo", "minecraft:cactus"}
_CHESTS = ("minecraft:open_chest", "minecraft:open_barrel", "minecraft:open_shulker_box", "minecraft:open_enderchest")
_TRAVEL = ("minecraft:walk_one_cm", "minecraft:sprint_one_cm", "minecraft:swim_one_cm", "minecraft:walk_on_water_one_cm",
           "minecraft:walk_under_water_one_cm", "minecraft:crouch_one_cm", "minecraft:boat_one_cm", "minecraft:horse_one_cm",
           "minecraft:minecart_one_cm", "minecraft:aviate_one_cm", "minecraft:pig_one_cm", "minecraft:strider_one_cm",
           "minecraft:climb_one_cm", "minecraft:fly_one_cm", "minecraft:happy_ghast_one_cm", "minecraft:nautilus_one_cm")
# what a placed block looks like in "used" (tools, food and the like count there too)
_BUILD_WORDS = ("planks", "_log", "_wood", "stone", "brick", "glass", "wool", "slab", "stairs", "_wall", "fence", "door",
                "dirt", "sand", "gravel", "concrete", "terracotta", "_block", "torch", "lantern", "deepslate", "andesite",
                "diorite", "granite", "tuff", "calcite", "quartz", "prismarine", "carpet", "_bed", "chest", "furnace",
                "crafting_table", "ladder", "rail", "button", "pressure_plate", "sign", "copper", "mud", "clay", "snow",
                "leaves", "hay", "bookshelf", "scaffolding", "path", "farmland", "moss", "sapling", "flower", "tulip")


def _delta(before: dict, after: dict, group: str) -> dict[str, int]:
    b, a = before.get(group) or {}, after.get(group) or {}
    return {k: a[k] - b.get(k, 0) for k in a if a[k] > b.get(k, 0)}


def _is_log(key: str) -> bool:
    return key.endswith(("_log", "_stem", "_wood", "_hyphae")) and "stripped" not in key


# "used" counts every swing of a tool and every bite of food too: a stone pickaxe isn't stone being placed
_NOT_BLOCKS = ("_pickaxe", "_axe", "_shovel", "_hoe", "_sword", "_spear", "_helmet", "_chestplate", "_leggings", "_boots",
               "bow", "shears", "flint_and_steel", "fishing_rod", "shield", "trident", "mace", "bucket", "_boat", "_raft",
               "minecart", "brush", "spyglass", "_on_a_stick", "bundle", "_horse_armor", "elytra", "potion", "_stew", "_soup")


def _placed(used: dict[str, int]) -> int:
    return sum(n for k, n in used.items() if any(w in k for w in _BUILD_WORDS) and not k.endswith(_NOT_BLOCKS)
               and not any(w in k for w in ("bucket", "minecart", "_boat")))


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 or word.endswith('s') else 's'}"


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
    mined = _delta(before, after, "minecraft:mined")
    logs = sum(n for k, n in mined.items() if _is_log(k))
    if logs >= 3:
        parts.append(f"chopped {_plural(logs, 'log')}")
    crops = sum(n for k, n in mined.items() if k in _CROPS)
    if crops >= 3:
        parts.append(f"harvested {crops} crops")
    dug = sum(mined.values()) - logs - crops
    if dug >= 10:
        parts.append(f"dug {_plural(dug, 'block')}")
    placed = _placed(_delta(before, after, "minecraft:used"))
    if placed >= 10:
        parts.append(f"placed {_plural(placed, 'block')}")
    cb, ca = before.get("minecraft:custom") or {}, after.get("minecraft:custom") or {}
    gained = lambda k: ca.get(k, 0) - cb.get(k, 0)  # noqa: E731
    chests = sum(gained(k) for k in _CHESTS)
    if chests > 0:
        parts.append(f"opened {_plural(chests, 'chest')}")
    for key, say in (("minecraft:traded_with_villager", "traded with villagers {n}×"), ("minecraft:animals_bred", "bred {n} animals"),
                     ("minecraft:enchant_item", "enchanted {n} item{s}"), ("minecraft:sleep_in_bed", "slept in a bed")):
        n = gained(key)
        if n > 0:
            parts.append(say.format(n=n, s="" if n == 1 else "s"))
    travelled = sum(gained(k) for k in _TRAVEL) / 100
    if travelled >= 500:
        parts.append(f"travelled {travelled / 1000:.1f} km" if travelled >= 1000 else f"travelled {travelled:.0f} blocks")
    taken = (ca.get("minecraft:damage_taken", 0) - cb.get("minecraft:damage_taken", 0)) / 20   # tenths of a heart -> hearts
    if taken >= 5:
        parts.append(f"took {taken:.0f} ❤ of damage")
    died = gained("minecraft:deaths")                  # from the stats file: counted even when the log's line isn't
    if died > 0:
        parts.append(f"respawned {died}×")
    eaten = ca.get("minecraft:eat_cake_slice", 0) - cb.get("minecraft:eat_cake_slice", 0)
    if eaten > 0:
        parts.append(f"ate {eaten} slice{'s' if eaten > 1 else ''} of cake")
    return " · ".join(parts) or None


# ------------------------------------------------------------------ what each player has been up to lately
DOING_FOR = 12 * 60           # a label stays this long after the save that showed it
_doing: dict[tuple[str, str], tuple[float, str]] = {}


def doing(before: dict, after: dict) -> str | None:
    """One word or two for what a player did between two saves of their statistics, the busiest thing first."""
    mined = _delta(before, after, "minecraft:mined")
    cb, ca = before.get("minecraft:custom") or {}, after.get("minecraft:custom") or {}
    gained = lambda k: ca.get(k, 0) - cb.get(k, 0)  # noqa: E731
    logs = sum(n for k, n in mined.items() if _is_log(k))
    crops = sum(n for k, n in mined.items() if k in _CROPS)
    scores = {
        "🎣 Fishing": gained("minecraft:fish_caught") * 8,
        "⚔️ Fighting mobs": sum(_delta(before, after, "minecraft:killed").values()) * 4,
        "🪓 Chopping trees": logs * 2,
        "🌾 Farming": crops * 2,
        "⛏️ Mining": sum(mined.values()) - logs - crops,
        "🧱 Building": _placed(_delta(before, after, "minecraft:used")),
        "💰 Trading": gained("minecraft:traded_with_villager") * 6,
        "🧭 Exploring": sum(gained(k) for k in _TRAVEL) / 100 / 40,         # 40 blocks travelled ≈ one thing done
    }
    label, score = max(scores.items(), key=lambda i: i[1])
    return label if score >= 8 else None


def lately(server_id: str, name: str) -> str | None:
    hit = _doing.get((server_id, name.lower()))
    return hit[1] if hit and time.time() - hit[0] < DOING_FOR else None


_advs: dict[tuple[str, str], int] = {}       # (server, player) -> advancements done, at the last save looked at
TALLY_DAYS = 45                              # (the Stats page works out its last couple of days again from these)


def _tally_ensure() -> None:
    db.x("CREATE TABLE IF NOT EXISTS stat_tally (server_id TEXT NOT NULL, ts REAL NOT NULL, player TEXT, "
         "travelled REAL NOT NULL DEFAULT 0, advancements INTEGER NOT NULL DEFAULT 0, deaths INTEGER NOT NULL DEFAULT 0)")
    db.x("CREATE INDEX IF NOT EXISTS stat_tally_by_time ON stat_tally(server_id, ts)")


def _advancements_done(srv, uuid: str) -> int | None:
    try:
        adv = S.player_advancements(srv, uuid)
    except Exception:
        return None
    return sum(1 for k, a in adv.items() if a["done"] and "/recipes/" not in k and ":recipes/" not in k)


def record_save(srv, name: str, uuid: str, prev: dict, st: dict) -> None:
    """Exactly what a save added, for the Stats page: every block travelled (the feed only mentions trips of 500 or
    more), every advancement (from the player's own file: the log's line isn't always there to read) and every death.
    Kept apart from the feed, which it would only clutter."""
    cb, ca = prev.get("minecraft:custom") or {}, st.get("minecraft:custom") or {}
    travelled = max(0.0, sum(ca.get(k, 0) - cb.get(k, 0) for k in _TRAVEL) / 100)
    deaths = max(0, ca.get("minecraft:deaths", 0) - cb.get("minecraft:deaths", 0))
    now_adv, key = _advancements_done(srv, uuid), (srv.id, name.lower())
    before = _advs.get(key)
    if now_adv is not None:
        _advs[key] = now_adv
    advs = max(0, now_adv - before) if now_adv is not None and before is not None else 0
    if travelled or advs or deaths:
        _tally_ensure()
        db.x("INSERT INTO stat_tally(server_id, ts, player, travelled, advancements, deaths) VALUES (?,?,?,?,?,?)",
             (srv.id, time.time(), name, round(travelled, 1), advs, deaths))


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
        if prev is None:                                  # (first look since Solstone started: what's done so far)
            done = _advancements_done(srv, uuid)
            if done is not None:
                _advs[(srv.id, name.lower())] = done
            continue
        if prev == st:
            continue
        record_save(srv, name, uuid, prev, st)
        label = doing(prev, st)
        if label:
            _doing[(srv.id, name.lower())] = (time.time(), label)
        line = progress_line(prev, st)
        if line:
            db.add_event(srv.id, time.time(), "progress", f"{name} {line}", name, uuid)
            n += 1
    return n


def prune() -> None:
    _tally_ensure()
    try:
        tally_travels()                     # (counted for all time before any old positions go)
    except Exception:
        log.exception("Couldn't count travels before clearing old positions: keeping them for now")
        return
    db.x("DELETE FROM stat_tally WHERE ts < ?", (time.time() - TALLY_DAYS * 86400,))
    cutoff = time.time() - POSITIONS_DAYS * 86400
    db.x("DELETE FROM adventures_hidden WHERE end_ts < ?", (cutoff,))
    db.x("DELETE FROM events WHERE type='progress' AND ts < ? AND NOT EXISTS (SELECT 1 FROM adventures a "
         "WHERE a.server_id = events.server_id AND events.ts BETWEEN a.start_ts AND a.end_ts)", (cutoff,))
    db.x("""DELETE FROM positions WHERE ts < ? AND NOT EXISTS (
            SELECT 1 FROM adventures a WHERE a.server_id = positions.server_id AND positions.ts BETWEEN a.start_ts AND a.end_ts)""", (cutoff,))


# ------------------------------------------------------------------ reading
def sessions(server_id: str, days: int = 30) -> list[dict]:
    """Play sessions (anyone on), newest first, with who played and any saved adventure in them."""
    # unsaved sessions only as far back as their trail is kept: past that they're gone from the list too
    since = time.time() - min(days, POSITIONS_DAYS) * 86400
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
    hidden = db.q("SELECT start_ts, end_ts FROM adventures_hidden WHERE server_id=?", (server_id,))
    result = []
    for s in reversed(out):
        if s["end"] - s["start"] < 60:
            continue
        mine = [a for a in saved if a["start_ts"] < s["end"] and a["end_ts"] > s["start"]]
        result.append({"start": s["start"], "end": s["end"], "players": sorted(s["players"], key=str.lower),
                       "saved": [_public(a) for a in mine],
                       "hidden": not mine and any(h["start_ts"] < s["end"] and h["end_ts"] > s["start"] for h in hidden)})
    # saved adventures older than the list still show
    shown = {a["id"] for s in result for a in s["saved"]}
    for a in saved:
        if a["id"] not in shown:
            result.append({"start": a["start_ts"], "end": a["end_ts"], "players": _players_between(server_id, a["start_ts"], a["end_ts"]),
                           "saved": [_public(a)], "hidden": False})
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
    return {"start": start, "end": end, "trails": trails, "events": events, "summary": summary(events, start, end)}


# ------------------------------------------------------------------ the feed, summed up every ten minutes
SUMMARY_STEP = 600
# what each kind of thing in a statistics line adds up to: (pattern, what it counts)
_TALLY = [(re.compile(r"defeated (.+?)(?: and (\d+) more kinds)?$"), "mobs"), (re.compile(r"^dug (\d+) blocks?$"), "mined"),
          (re.compile(r"^mined (.+)$"), "ores"), (re.compile(r"^chopped (\d+) logs?$"), "logs"),
          (re.compile(r"^harvested (\d+) crops$"), "crops"), (re.compile(r"^placed (\d+) blocks?$"), "placed"),
          (re.compile(r"^opened (\d+) chests?$"), "chests"), (re.compile(r"^traded with villagers (\d+)×$"), "trades"),
          (re.compile(r"^bred (\d+) animals$"), "bred"), (re.compile(r"^took (\d+) ❤ of damage$"), "damage"),
          (re.compile(r"^travelled ([\d.]+) (km|blocks)$"), "travelled"), (re.compile(r"^respawned (\d+)×$"), "respawns")]
# kept as lines of their own in the summary: the moments worth seeing
NOTABLE = {"join", "leave", "death", "advancement", "challenge", "race", "bigfish", "game"}


def tally(line: str) -> dict[str, float]:
    """A statistics line ("defeated 3 zombies · chopped 12 logs") as counts by kind ({"mobs": 3, "logs": 12})."""
    out: dict[str, float] = {}
    parts = (line or "").split(" · ")
    if parts and " " in parts[0] and not any(rx.search(parts[0]) for rx, _k in _TALLY):
        parts[0] = parts[0].split(" ", 1)[1]        # the saved line starts with their name ("Sam dug 40 blocks")
    for part in parts:
        for rx, kind in _TALLY:
            m = rx.search(part)
            if not m:
                continue
            if kind in ("mobs", "ores"):
                n = sum(int(x) for x in re.findall(r"(?:^|, )(\d+) ", m.group(1)))
            elif kind == "travelled":
                n = float(m.group(1)) * (1000 if m.group(2) == "km" else 1)
            else:
                n = int(m.group(1))
            out[kind] = out.get(kind, 0) + n
            break
    return out


def summary(events: list[dict], start: float, end: float, step: int = SUMMARY_STEP) -> list[dict]:
    """The feed in ten-minute blocks: what each player did in each (mobs, mining, logs, fish, chat...), and the
    moments worth their own line (joins, deaths, advancements, big fish). Empty blocks are left out."""
    blocks: dict[int, dict] = {}
    for e in events:
        i = int((e["ts"] - start) // step)
        b = blocks.setdefault(i, {"start": start + i * step, "end": min(end, start + (i + 1) * step), "players": {}, "moments": []})
        if e["type"] in NOTABLE:
            b["moments"].append(e)
        if not e.get("player"):
            continue
        who = b["players"].setdefault(e["player"], {})
        add = tally(e["message"]) if e["type"] == "progress" else \
            {"fish": 1} if e["type"] in ("fish", "bigfish") else {"chat": 1} if e["type"] in ("chat", "webchat") else {}
        for k, v in add.items():
            who[k] = who.get(k, 0) + v
    out = []
    for i in sorted(blocks):
        b = blocks[i]
        b["players"] = {p: {k: round(v, 1) for k, v in t.items()} for p, t in b["players"].items() if t}
        if b["players"] or b["moments"]:
            out.append(b)
    return out


def save(server_id: str, start: float, end: float, title: str, note: str, who: str, aid: int | None = None) -> dict:
    title, note = " ".join(title.split())[:80], note.strip()[:2000]
    if not title:
        raise ValueError("Give it a title")
    if end <= start:
        raise ValueError("The end has to be after the start")
    hide(server_id, start, end, who, False)                   # a saved one is never hidden
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


def hide(server_id: str, start: float, end: float, who: str, hidden: bool = True) -> None:
    """Hide a session from the Adventures list (or show it again). Saving one shows it again too."""
    db.x("DELETE FROM adventures_hidden WHERE server_id=? AND start_ts < ? AND end_ts > ?", (server_id, end, start))
    if hidden:
        db.x("INSERT INTO adventures_hidden(server_id, start_ts, end_ts, hidden_by, hidden_ts) VALUES (?,?,?,?,?)",
             (server_id, start, end, who, time.time()))


def erase(server_id: str, start: float, end: float) -> dict:
    """Delete a stretch of play's trail, its statistics lines and any saved adventure over it. The play time,
    joins, chat and the rest of the history stay (other pages use them)."""
    n = db.x("DELETE FROM positions WHERE server_id=? AND ts BETWEEN ? AND ?", (server_id, start, end))
    e = db.x("DELETE FROM events WHERE server_id=? AND type='progress' AND ts BETWEEN ? AND ?", (server_id, start, end))
    db.x("DELETE FROM adventures WHERE server_id=? AND start_ts < ? AND end_ts > ?", (server_id, end, start))
    hide(server_id, start, end, "", True)
    return {"positions": n, "lines": e}


# ------------------------------------------------------------------ a player's travels (their page → Travels)
CELL = 16                     # one square on the travels map: a chunk


# For all time: a tally of each chunk each player has been in (how often, first and last time), and their records
# (deepest, highest, farthest), kept for good: a few MB for years of play, where the positions themselves (every few
# seconds) are kept POSITIONS_DAYS days. It's brought up to date from the positions not counted yet (by their rowid),
# before the travels are read and before old positions are cleared, so nothing is missed.
_tally_lock = threading.Lock()


def travel_ensure() -> None:
    db.x("CREATE TABLE IF NOT EXISTS travel_cells (server_id TEXT NOT NULL, player TEXT NOT NULL, dim TEXT NOT NULL, "
         "cx INTEGER NOT NULL, cz INTEGER NOT NULL, n INTEGER NOT NULL, first_ts REAL NOT NULL, last_ts REAL NOT NULL, "
         "PRIMARY KEY (server_id, player, dim, cx, cz))")
    db.x("CREATE TABLE IF NOT EXISTS travel_records (server_id TEXT NOT NULL, player TEXT NOT NULL, dim TEXT NOT NULL, "
         "kind TEXT NOT NULL, v REAL NOT NULL, x REAL, y REAL, z REAL, ts REAL, PRIMARY KEY (server_id, player, dim, kind))")
    db.x("CREATE TABLE IF NOT EXISTS travel_meta (k TEXT PRIMARY KEY, v REAL NOT NULL)")


def tally_travels(batch: int = 200_000) -> int:
    """Count the positions not counted yet into the all-time tally. Returns how many were counted."""
    import math
    travel_ensure()
    done = 0
    with _tally_lock:
        while True:
            mark = db.q("SELECT v FROM travel_meta WHERE k='positions_rowid'")
            seen = int(mark[0]["v"]) if mark else 0
            top = db.q("SELECT MAX(rowid) AS m FROM positions")[0]["m"] or 0
            seen = min(seen, top)               # (the newest rows were deleted: rowids from there are new ones)
            rows = db.q("SELECT rowid, server_id, ts, player, dim, x, y, z FROM positions WHERE rowid > ? ORDER BY rowid LIMIT ?",
                        (seen, batch))
            if not rows:
                db.x("INSERT OR REPLACE INTO travel_meta(k, v) VALUES ('positions_rowid', ?)", (seen,))
                return done
            cells: dict[tuple, list] = {}
            recs: dict[tuple, dict] = {}
            for r in rows:
                who = (r["server_id"], r["player"].lower(), r["dim"])
                key = (*who, math.floor(r["x"] / CELL), math.floor(r["z"] / CELL))
                c = cells.get(key)
                if c is None:
                    cells[key] = [1, r["ts"], r["ts"]]
                else:
                    c[0] += 1
                    c[1] = min(c[1], r["ts"])
                    c[2] = max(c[2], r["ts"])
                rec = recs.setdefault(who, {})
                here = (r["x"], r["y"], r["z"], r["ts"])
                for kind, v, better in (("deepest", r["y"], lambda a, b: a < b), ("highest", r["y"], lambda a, b: a > b),
                                        ("farthest", math.hypot(r["x"], r["z"]), lambda a, b: a > b)):
                    if kind not in rec or better(v, rec[kind][0]):
                        rec[kind] = (v, *here)
            with db._lock:
                c = db.conn()
                c.execute("BEGIN IMMEDIATE")
                try:
                    c.executemany("INSERT INTO travel_cells(server_id, player, dim, cx, cz, n, first_ts, last_ts) VALUES (?,?,?,?,?,?,?,?) "
                                  "ON CONFLICT(server_id, player, dim, cx, cz) DO UPDATE SET n = n + excluded.n, "
                                  "first_ts = MIN(first_ts, excluded.first_ts), last_ts = MAX(last_ts, excluded.last_ts)",
                                  [(*k, *v) for k, v in cells.items()])
                    c.executemany("INSERT INTO travel_records(server_id, player, dim, kind, v, x, y, z, ts) VALUES (?,?,?,?,?,?,?,?,?) "
                                  "ON CONFLICT(server_id, player, dim, kind) DO UPDATE SET v=excluded.v, x=excluded.x, y=excluded.y, "
                                  "z=excluded.z, ts=excluded.ts WHERE (excluded.kind = 'deepest' AND excluded.v < travel_records.v) "
                                  "OR (excluded.kind <> 'deepest' AND excluded.v > travel_records.v)",
                                  [(*who, kind, *vals) for who, rec in recs.items() for kind, vals in rec.items()])
                    c.execute("INSERT OR REPLACE INTO travel_meta(k, v) VALUES ('positions_rowid', ?)", (rows[-1]["rowid"],))
                    c.execute("COMMIT")
                except Exception:
                    c.execute("ROLLBACK")
                    raise
            done += len(rows)
            if len(rows) < batch:
                return done


def travels_all(server_id: str, names: list[str]) -> dict:
    """Where these names (one person's accounts) have ever been, from the all-time tally: like travels(), for all time."""
    low = [n.lower() for n in names if n]
    if not low:
        return {"dims": {}, "since": None}
    tally_travels()
    marks = ",".join("?" * len(low))
    out: dict[str, dict] = {}
    first = None
    for r in db.q(f"SELECT dim, cx, cz, SUM(n) AS n, MIN(first_ts) AS f FROM travel_cells WHERE server_id=? AND player IN ({marks}) "
                  "GROUP BY dim, cx, cz ORDER BY n DESC", (server_id, *low)):
        d = out.setdefault(r["dim"], {"cells": [], "chunks": 0, "points": 0, "deepest": None, "highest": None, "farthest": None})
        if len(d["cells"]) < 50000:
            d["cells"].append([r["cx"], r["cz"], r["n"]])
        d["chunks"] += 1
        d["points"] += r["n"]
        first = r["f"] if first is None else min(first, r["f"])
    for r in db.q(f"SELECT dim, kind, v, x, y, z, ts FROM travel_records WHERE server_id=? AND player IN ({marks})", (server_id, *low)):
        d = out.get(r["dim"])
        if d is None:
            continue
        cur = d.get(r["kind"])
        better = (r["v"] < cur["v"]) if cur and r["kind"] == "deepest" else (r["v"] > cur["v"]) if cur else True
        if better:
            d[r["kind"]] = {"x": round(r["x"]), "y": round(r["y"]), "z": round(r["z"]), "ts": r["ts"], "v": r["v"],
                            **({"dist": round(r["v"])} if r["kind"] == "farthest" else {})}
    return {"dims": out, "since": first, "cell": CELL, "keep_days": POSITIONS_DAYS}


def travels(server_id: str, names: list[str]) -> dict:
    """Where these names (one person's accounts) have been, from the positions kept (the last POSITIONS_DAYS days, and
    saved adventures): each dimension's chunks with how often they were seen there, and their records (deepest,
    highest, farthest from 0, 0)."""
    import math
    low = [n.lower() for n in names if n]
    if not low:
        return {"dims": {}, "since": None}
    marks = ",".join("?" * len(low))
    dims: dict[str, dict] = {}
    first = None
    for r in db.q(f"SELECT ts, dim, x, y, z FROM positions WHERE server_id=? AND lower(player) IN ({marks})", (server_id, *low)):
        d = dims.get(r["dim"])
        if d is None:
            d = dims[r["dim"]] = {"cells": {}, "points": 0, "deepest": None, "highest": None, "farthest": None}
        first = r["ts"] if first is None else min(first, r["ts"])
        key = (math.floor(r["x"] / CELL), math.floor(r["z"] / CELL))
        d["cells"][key] = d["cells"].get(key, 0) + 1
        d["points"] += 1
        here = {"x": round(r["x"]), "y": round(r["y"]), "z": round(r["z"]), "ts": r["ts"]}
        if d["deepest"] is None or r["y"] < d["deepest"]["y"]:
            d["deepest"] = here
        if d["highest"] is None or r["y"] > d["highest"]["y"]:
            d["highest"] = here
        far = math.hypot(r["x"], r["z"])
        if d["farthest"] is None or far > d["farthest"]["dist"]:
            d["farthest"] = {**here, "dist": round(far)}
    out = {}
    for dim, d in dims.items():
        cells = sorted(d["cells"].items(), key=lambda kv: -kv[1])[:20000]
        out[dim] = {"cells": [[cx, cz, n] for (cx, cz), n in cells], "chunks": len(d["cells"]), "points": d["points"],
                    "deepest": d["deepest"], "highest": d["highest"], "farthest": d["farthest"]}
    return {"dims": out, "since": first, "cell": CELL, "keep_days": POSITIONS_DAYS}
