"""Tide, the fishing mod, on a server: its fish (read from the mod's jar), everyone's fishing
journal and fishing level (read from their save files), and the catches it writes to the log.

Solstone only reads here. Tide keeps each player's journal in their playerdata file under
TidePersistentData:
    TidePlayerData.fish_data: [{fish: "tide:bluegill", data: {stats: {amount_caught, largest_catch,
        smallest_catch, best_quality, heaviest_catch, quality_counts}}}]
    TideAngler: {xp, fair, ...}
and logs one line per caught fish:
    [Tide catch] {"player": "Tyler", "fish": "tide:bluegill", "quality": 2, "weight_g": 180.2, ...}
"""
from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

from . import db
from . import servers as S
from .nbtutil import load_dat

MOD_ID = "tide"
# Tide's catch qualities, best last; colours match the in-game tooltip (CSS classes fq-*)
QUALITIES = [("Poor", "gray"), ("Average", "white"), ("Fine", "green"), ("Prime", "aqua"), ("Trophy", "light_purple"), ("Mythic", "gold")]
QUALITY_ODDS = [30.0, 48.0, 17.0, 4.0, 0.9, 0.1]           # % at the baseline level, a normal hook
RARITIES = [("common", "Common", 1), ("uncommon", "Uncommon", 2), ("rare", "Rare", 3), ("very_rare", "Very rare", 4), ("legendary", "Legendary", 5)]
RARITY_XP = {"common": 10, "uncommon": 20, "rare": 40, "very_rare": 80, "legendary": 200}
POINTS_FACTOR = [0.5, 1.0, 1.5, 2.5, 4.0, 8.0]              # catch points: rarity XP x this, by quality
GROUPS = [("freshwater", "Lakes & rivers"), ("saltwater", "Oceans"), ("underground", "Underground"), ("lava", "Lava"),
          ("void", "The End & the Void"), ("misc", "Other")]
TITLES = ["Novice", "Apprentice", "Hobbyist", "Angler", "Skilled", "Seasoned", "Expert", "Veteran", "Master", "Grandmaster", "Legendary"]
_FISH_FILE = re.compile(r"^data/([^/]+)/fishing/fish/(?:.+/)?([^/]+)\.json$")
_LOG = re.compile(r"^\[(\d{2}):(\d{2}):(\d{2})[^\]]*\].*?\[Tide catch\] (\{.*\})\s*$")
G_PER_LB = 453.59237


# ------------------------------------------------------------------ the mod
def jar(srv) -> Path | None:
    """The Tide jar in the server's mods folder, if it's installed."""
    if not getattr(srv, "is_java", True) or getattr(srv, "dir", None) is None:
        return None
    for m in S.mods(srv):
        if m.get("id") == MOD_ID:
            return srv.dir / "mods" / m["file"]
    return None


def installed(srv) -> bool:
    return jar(srv) is not None


def _humanize(path: str) -> str:
    return path.replace("_", " ").title()


def _read_species(path: Path) -> list[dict]:
    out = []
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        try:
            lang = json.loads(z.read("assets/tide/lang/en_us.json").decode("utf-8", "replace"), strict=False)
        except KeyError:
            lang = {}
        for n in names:
            m = _FISH_FILE.match(n)
            if not m:
                continue
            try:
                j = json.loads(z.read(n).decode("utf-8", "replace"), strict=False)
            except ValueError:
                continue
            if not isinstance(j, dict) or not j.get("fish") or j.get("show_in_journal") is False:
                continue
            fid = str(j["fish"])
            ns, _, item = fid.partition(":")
            prof = j.get("journal_profile") or {}
            rarity = str(prof.get("rarity") or "common")
            size = j.get("size") or {}
            loc = prof.get("location")
            out.append({"id": fid, "name": lang.get(f"item.{ns}.{item}") or _humanize(item), "rarity": rarity,
                        "stars": next((s for k, _l, s in RARITIES if k == rarity), 1), "group": str(prof.get("group") or "misc"),
                        "where": lang.get(loc, "") if isinstance(loc, str) else "",
                        "typical_cm": [size.get("typical_low_cm"), size.get("typical_high_cm")] if size else None})
    order = {k: i for i, (k, _l) in enumerate(GROUPS)}
    rorder = {k: i for i, (k, _l, _s) in enumerate(RARITIES)}
    seen: dict[str, dict] = {}
    for s in out:                                          # a fish defined twice: keep one
        seen.setdefault(s["id"], s)
    return sorted(seen.values(), key=lambda s: (order.get(s["group"], 99), rorder.get(s["rarity"], 9), s["name"]))


def species(srv) -> list[dict]:
    j = jar(srv)
    if not j:
        return []
    return S._cache.get(("tide-species", str(j)), j, _read_species) or []


_TACKLE_TAGS = ("fishing_rods", "lines", "hooks", "bobbers", "lures", "bait_items")
_GEAR = ("angler_hat", "fishing_vest", "waders", "wading_boots", "tackle_box", "fish_satchel")


def _read_tackle(path: Path) -> list[str]:
    """Every piece of tackle the journal's tackle section lists (by item path): the mod's tackle tags, plus gear."""
    out: set[str] = set()
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        for tag in _TACKLE_TAGS:
            f = f"data/tide/tags/item/{tag}.json"
            if f not in names:
                continue
            try:
                vals = json.loads(z.read(f).decode("utf-8", "replace")).get("values") or []
            except ValueError:
                continue
            for v in vals:
                v = v.get("id", "") if isinstance(v, dict) else str(v)
                if v.startswith("tide:"):
                    out.add(v[5:])
    if out:
        out.update(_GEAR)
    return sorted(out)


def tackle(srv) -> list[str]:
    """Every piece of tackle there is to find (empty for a Tide without the tackle journal)."""
    j = jar(srv)
    if not j:
        return []
    return S._cache.get(("tide-tackle", str(j)), j, _read_tackle) or []


# ------------------------------------------------------------------ levels (same maths as the mod)
def _config(srv) -> dict:
    raw = S._cache.get(("tide-config", srv.id), srv.dir / "config" / "tide.json", S._json) or {}
    lv = (raw.get("server") or {}).get("leveling") or {}
    return {"enabled": lv.get("enabled", True) is not False, "base": float(lv.get("xpPerLevel", 20.0)),
            "growth": float(lv.get("xpGrowth", 0.2)), "baseline": int(lv.get("baselineLevel", 40))}


def xp_for_level(level: int, cfg: dict) -> int:
    n = max(1, min(99, level)) - 1
    return round(max(1.0, cfg["base"]) * n + max(0.0, cfg["growth"]) * n * (n + 1) * (2 * n + 1) / 6)


def level_for_xp(xp: int, cfg: dict) -> int:
    lv = 1
    while lv < 99 and xp >= xp_for_level(lv + 1, cfg):
        lv += 1
    return lv


def title(level: int) -> str:
    """The mod's titles: a new one every 10 levels, and Legendary only at 99."""
    if level >= 99:
        return "Legendary Angler"
    name = TITLES[min(level // 10, len(TITLES) - 2)]
    return "Angler" if name == "Angler" else f"{name} Angler"


# ------------------------------------------------------------------ players
def _player_tide(srv, uuid: str) -> dict:
    """The Tide part of a player's save file: {"fish": {id: stats}, "xp": int, "fair": bool}."""
    p = S._player_files(srv, uuid)["playerdata"]
    raw = S._cache.get(("pd", srv.id, uuid), p, load_dat)
    tide = (raw or {}).get("TidePersistentData") or {}
    fish = {}
    for e in ((tide.get("TidePlayerData") or {}).get("fish_data") or []):
        if not isinstance(e, dict) or not e.get("fish"):
            continue
        st = ((e.get("data") or {}).get("stats")) or {}
        if not st or int(st.get("amount_caught", 0)) <= 0:
            continue
        smallest = float(st.get("smallest_catch", 0) or 0)
        fish[str(e["fish"])] = {
            "count": int(st.get("amount_caught", 0)),
            "longest_cm": float(st.get("largest_catch", 0) or 0),
            "shortest_cm": smallest if 0 < smallest < 1e9 else 0.0,
            "heaviest_g": float(st.get("heaviest_catch", 0) or 0),
            "heaviest_quality": int(st.get("heaviest_quality", -1)),   # quality of that heaviest fish (newer Tide+ only)
            "best_quality": int(st.get("best_quality", -1)),
            "qualities": [int(x) for x in (st.get("quality_counts") or [])][:len(QUALITIES)],
        }
    ang = tide.get("TideAngler") or {}
    found = str((tide.get("TideTackle") or {}).get("found") or "")
    return {"fish": fish, "xp": int(ang.get("xp", 0) or 0), "fair": bool(ang.get("fair", False)),
            "tackle": {t for t in found.split(",") if t}}


def _level_info(xp: int, cfg: dict) -> dict:
    lv = level_for_xp(xp, cfg)
    lo, hi = xp_for_level(lv, cfg), xp_for_level(lv + 1, cfg) if lv < 99 else xp_for_level(99, cfg)
    return {"level": lv, "title": title(lv), "xp": xp, "next": None if lv >= 99 else hi - xp,
            "progress": 1.0 if lv >= 99 else round((xp - lo) / max(1, hi - lo), 3)}


def player_summary(srv, uuid: str) -> dict | None:
    """For the player page: level, title, XP, and how much of the journal they've filled."""
    if not installed(srv):
        return None
    cfg = _config(srv)
    t = _player_tide(srv, uuid)
    sp = {s["id"]: s for s in species(srv)}
    biggest = max(((fid, f) for fid, f in t["fish"].items() if f["heaviest_g"] > 0), key=lambda x: x[1]["heaviest_g"], default=None)
    return {**_level_info(t["xp"], cfg), "fair": t["fair"], "levels_on": cfg["enabled"],
            "species": sum(1 for fid in t["fish"] if fid in sp), "species_total": len(sp),
            "caught": sum(f["count"] for f in t["fish"].values()),
            "biggest": {"id": biggest[0], "name": sp.get(biggest[0], {}).get("name") or _humanize(biggest[0].split(":")[-1]),
                        "weight_g": biggest[1]["heaviest_g"]} if biggest else None}


def leaderboard_values(srv, uuid: str) -> dict:
    """fishing_level and heaviest_fish (grams) for the leaderboards; zeros without Tide."""
    if not installed(srv):
        return {"fishing_level": 0, "heaviest_fish": 0}
    t = _player_tide(srv, uuid)
    has_any = t["xp"] > 0 or t["fish"]
    return {"fishing_level": level_for_xp(t["xp"], _config(srv)) if has_any else 0,
            "heaviest_fish": round(max((f["heaviest_g"] for f in t["fish"].values()), default=0))}


# ------------------------------------------------------------------ the family journal
def journal(srv) -> dict:
    """Everything the Fishing tab shows when Tide is installed."""
    cfg = _config(srv)
    sp = species(srv)
    ids = {s["id"] for s in sp}
    known = S.known_players(srv)
    players, entries = [], {s["id"]: [] for s in sp}
    all_tackle = set(tackle(srv))
    for uuid, p in known.items():
        t = _player_tide(srv, uuid)
        if not t["fish"] and not t["xp"]:
            continue
        quals = [0] * len(QUALITIES)
        for fid, f in t["fish"].items():
            for i, n in enumerate(f["qualities"]):
                quals[i] += n
            if fid in entries:
                entries[fid].append({"player": p["name"], "uuid": uuid, **f})
        players.append({"uuid": uuid, "name": p["name"], **_level_info(t["xp"], cfg), "fair": t["fair"],
                        "species": {fid: f for fid, f in t["fish"].items() if fid in ids},
                        "caught": sum(f["count"] for f in t["fish"].values()), "qualities": quals,
                        "tackle": len(t["tackle"] & all_tackle)})
    # catches seen in the log since the last save: count toward records too (save files lag a few minutes)
    uuids = {p["name"]: u for u, p in known.items()}
    for r in db.fish_catches(srv.id):
        if r["species"] not in entries:
            continue
        grams = r["weight"] * G_PER_LB
        row = next((e for e in entries[r["species"]] if e["player"] == r["player"]), None)
        if row is None:                                    # caught since their last save
            row = {"player": r["player"], "uuid": uuids.get(r["player"]), "count": 0, "longest_cm": 0.0, "shortest_cm": 0.0,
                   "heaviest_g": 0.0, "heaviest_quality": -1, "best_quality": -1, "qualities": [], "logged": 0}
            entries[r["species"]].append(row)
        if "logged" in row:
            row["logged"] += 1
            row["count"] = max(row["count"], row["logged"])
        if grams > row["heaviest_g"]:
            row["heaviest_g"] = grams
            row["heaviest_quality"] = r["quality"]
        row["best_quality"] = max(row["best_quality"], r["quality"])

    records, top = {}, {}
    for fid, rows in entries.items():
        if not rows:
            continue
        ranked = sorted(rows, key=lambda e: (e["heaviest_g"], e["longest_cm"]), reverse=True)
        top[fid] = [{"player": e["player"], "uuid": e["uuid"], "weight_g": round(e["heaviest_g"], 1), "length_cm": round(e["longest_cm"], 1),
                     "quality": e["best_quality"], "fish_quality": e.get("heaviest_quality", -1), "count": e["count"]} for e in ranked[:3]]
        records[fid] = top[fid][0]

    family = {fid for fid, rows in entries.items() if rows}
    tiers = []
    for key, label, stars in RARITIES:
        of_tier = [s["id"] for s in sp if s["rarity"] == key]
        if not of_tier:
            continue
        tiers.append({"key": key, "label": label, "stars": stars, "total": len(of_tier), "family": sum(1 for f in of_tier if f in family),
                      "players": {p["name"]: sum(1 for f in of_tier if f in p["species"]) for p in players}})
    recent = [{"player": r["player"], "species": r["species"], "name": r["name"], "quality": r["quality"], "quality_name": r["quality_name"],
               "weight_g": round(r["weight"] * G_PER_LB, 1), "points": r["points"], "ts": r["ts"]}
              for r in db.fish_catches(srv.id)[-25:] if r["species"] in ids][::-1]
    players.sort(key=lambda p: (-p["xp"], -len(p["species"])))
    return {"source": "tide", "species": sp, "groups": [{"key": k, "label": lbl} for k, lbl in GROUPS],
            "qualities": [{"name": n, "color": c, "chance": QUALITY_ODDS[i]} for i, (n, c) in enumerate(QUALITIES)],
            "players": players, "records": records, "top": top, "tiers": tiers, "family_species": len(family),
            "recent": recent, "levels_on": cfg["enabled"], "baseline": cfg["baseline"], "tackle_total": len(all_tackle)}


# ------------------------------------------------------------------ catches from the log
def parse_log_line(line: str) -> tuple[int, int, int, dict] | None:
    """`[12:34:56] [Server thread/INFO]: [Tide catch] {...}` -> (h, m, s, catch)."""
    if "[Tide catch]" not in line:
        return None
    m = _LOG.match(line.rstrip("\r\n"))
    if not m:
        return None
    try:
        c = json.loads(m.group(4))
    except ValueError:
        return None
    if not isinstance(c, dict) or not c.get("player") or not c.get("fish"):
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3)), c


def to_catch(srv, c: dict) -> dict:
    """A Tide catch in the shape Solstone's fishing journal and contests use."""
    names = {s["id"]: s["name"] for s in species(srv)}
    q = max(0, min(len(QUALITIES) - 1, int(c.get("quality", 1))))
    rarity = str(c.get("rarity") or "common")
    grams = float(c.get("weight_g") or 0)
    lb = round(grams / G_PER_LB, 2)
    return {"species": c["fish"], "name": names.get(c["fish"]) or _humanize(str(c["fish"]).split(":")[-1]),
            "quality": q, "quality_name": QUALITIES[q][0], "weight": lb, "lb": lb, "length_cm": c.get("length_cm"),
            "points": max(1, round(RARITY_XP.get(rarity, 10) * POINTS_FACTOR[q])), "rarity": rarity,
            "pos": [c.get("x"), c.get("y"), c.get("z")] if c.get("x") is not None else None, "fair": bool(c.get("fair"))}


def describe(c: dict, who: str) -> str:
    fish = c["name"] if c["quality"] == 1 else f"{c['quality_name']} {c['name']}"
    article = "an" if fish[0].upper() in "AEIOU" else "a"
    weight = f" · {fmt_lb(c['weight'])}" if c["weight"] else ""
    return f"{who} caught {article} {fish}{weight} · {c['points']} points"


def fmt_lb(lb: float) -> str:
    """Same as the mod: "0.38 lb", "3.4 lb", "1,298 lb"."""
    if lb < 1:
        return f"{max(lb, 0.01):.2f} lb"
    return f"{lb:.1f} lb" if lb < 100 else f"{round(lb):,} lb"


def record_catch(srv, ts: float, c: dict) -> tuple[str, str] | None:
    """Into the catch table and the activity feed (once). Returns (event type, message)."""
    who = c["player"]
    catch = to_catch(srv, c)
    dupe = db.q("SELECT 1 FROM fish_catches WHERE server_id=? AND player=? AND species=? AND ABS(ts-?)<2 AND ABS(weight-?)<0.005 LIMIT 1",
                (srv.id, who, catch["species"], ts, catch["weight"]))
    if dupe:
        return None
    db.add_catch(srv.id, ts, who, catch)
    etype = "bigfish" if catch["quality"] >= 4 else "fish"            # Trophy and Mythic are news
    msg = describe(catch, who)
    db.add_event(srv.id, ts, etype, msg, who)
    return etype, msg
