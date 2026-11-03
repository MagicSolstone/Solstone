"""One person, one line: an account with more than one Minecraft name linked (a Java and a Bedrock account, say)
counts as one player on the leaderboards, the time-played chart and the daily recap, under the account's main name
with a "+" (and the other names in "also"). Everywhere a name is acted on (giving items, teleporting, adventures on
the map, a player's own page) each Minecraft account stays its own.
"""
from __future__ import annotations

from . import auth, db

# boards where the best of the accounts counts (a level, a record), not the sum
BEST_OF = {"xp_level", "advancements", "fishing_level", "heaviest_fish", "time_since_death"}


def stacks() -> dict[str, dict]:
    """Each linked name (lowercased) -> {"name": the account's main name, "uuid": its, "names": every name},
    for accounts with two or more Minecraft names only."""
    auth._init()
    out: dict[str, dict] = {}
    by_user: dict[int, list] = {}
    for r in db.q("SELECT user_id, uuid, name, main FROM user_players ORDER BY added_ts, rowid"):
        by_user.setdefault(r["user_id"], []).append(r)
    for rows in by_user.values():
        if len(rows) < 2:
            continue
        main = next((r for r in rows if r["main"]), rows[0])
        info = {"name": main["name"], "uuid": main["uuid"], "names": [r["name"] for r in rows]}
        for r in rows:
            out[r["name"].lower()] = info
    return out


def _also(info: dict) -> list[str]:
    return [n for n in info["names"] if n.lower() != info["name"].lower()]


def leaderboard(data: dict) -> dict:
    """The leaderboard's players with each account's names as one row (counts added up, levels and records the best)."""
    st = stacks()
    if not st:
        return data
    keys = [b["key"] for b in data.get("boards", [])]
    rows: dict[str, dict] = {}
    order: list[str] = []
    for r in data.get("players", []):
        info = st.get(r["name"].lower())
        key = info["name"].lower() if info else r["name"].lower()
        if key not in rows:
            rows[key] = {**r, **({"name": info["name"], "uuid": info["uuid"] or r["uuid"], "also": _also(info)} if info else {})}
            order.append(key)
            continue
        row = rows[key]
        for k in keys:
            a, b = row.get(k) or 0, r.get(k) or 0
            row[k] = max(a, b) if k in BEST_OF else a + b
    return {**data, "players": [rows[k] for k in order]}


def daily(days: list[dict]) -> list[dict]:
    """The time-played chart's days with each account's names as one (their time added up)."""
    st = stacks()
    if not st:
        return days
    out = []
    for d in days:
        players: dict[str, float] = {}
        for n, v in d["players"].items():
            name = st[n.lower()]["name"] if n.lower() in st else n
            players[name] = players.get(name, 0) + v
        out.append({**d, "players": players})
    return out


def recap(r: dict | None) -> dict | None:
    """A daily recap's players with each account's names as one (time added up, the earliest start)."""
    st = stacks()
    if not r or not st or not r.get("players"):
        return r
    merged: dict[str, dict] = {}
    for p in r["players"]:
        info = st.get(p["name"].lower())
        key = info["name"].lower() if info else p["name"].lower()
        if key not in merged:
            merged[key] = {**p, **({"name": info["name"], "uuid": info["uuid"] or p.get("uuid"), "also": _also(info)} if info else {})}
            continue
        m = merged[key]
        m["seconds"] = (m.get("seconds") or 0) + (p.get("seconds") or 0)
        if p.get("first") and (not m.get("first") or p["first"] < m["first"]):
            m["first"] = p["first"]
    players = sorted(merged.values(), key=lambda p: -(p.get("seconds") or 0))
    return {**r, "players": players}


def together(srv, name: str) -> dict | None:
    """For a player page: the person's Minecraft accounts on this server (main first) and their progress added up
    (time played, mobs, blocks mined, distance...). What belongs to one character (level, health, inventory) isn't
    added: that stays on each account's own page. None for someone with one account here."""
    from . import servers as S
    info = stacks().get(name.lower())
    if not info:
        return None
    known = {p["name"].lower(): u for u, p in S.known_players(srv).items()}
    names = [n for n in sorted(info["names"], key=lambda n: n.lower() != info["name"].lower()) if n.lower() in known]
    if len(names) < 2:
        return None
    total: dict[str, int] = {}
    for n in names:
        for k, v in S.headline_stats(S.player_stats(srv, known[n.lower()])).items():
            total[k] = max(total.get(k, 0), v) if k in BEST_OF else total.get(k, 0) + v
    return {"main": info["name"], "accounts": [{"name": n, "uuid": known[n.lower()]} for n in names], "headline": total}
