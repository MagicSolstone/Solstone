"""King of the Hill: hold the zone to score.

An admin sets the hill (a spot and a size on the map) and a spawn spot for each team (or a few spots for everyone
for themselves). Everyone's own things go safely into the vault (kits.py) and they get the kit. For the set time,
every second:
  - teams: the team with the most players standing on the hill scores a point (a tie scores nothing), so one player
    can't hold off four;
  - everyone for themselves: whoever stands on the hill alone scores (two or more there: nobody does).
Dying puts you in spectator over the hill for a few seconds' countdown, then back at your spawn, kit and all.
Highest score at the end wins. Everyone's things are given back exactly, and they're put back where they were.
"""
from __future__ import annotations

import time

from . import battle, hud, kits
from . import servers as S

TAG = "solkoth"


def settings(body: dict, num, point) -> dict:
    spawns = [point(p, "spawn spot") for p in (body.get("spawns") or [])[:8] if isinstance(p, dict)]
    if not spawns:
        raise ValueError("Set at least one spawn spot")
    teams = int(num(body.get("team_count"), 0, 4, 2))
    return {"zone": {**point(body.get("center"), "hill"), "r": round(num(body.get("radius"), 2, 30, 5), 1), "h": 6},
            "spawns": spawns, "team_count": 0 if teams < 2 else teams, "minutes": int(num(body.get("minutes"), 2, 30, 8)),
            "respawn_secs": int(num(body.get("respawn_secs"), 3, 15, 5)), "no_dig": bool(body.get("no_dig", True)),
            "kit": kits.clean_kit(body.get("kit") or {})}


async def start(srv, r: dict) -> None:
    from .games import _say
    names = r.get("entrants") or (await S.online_players(srv))[0]
    if len(names) < 2:
        r["state"], r["result"] = "skipped", "King of the Hill needs at least two players" + (" to join" if r.get("optin") else " online")
        return
    await battle.rules_on(srv, r)
    playing = await battle.ready(srv, r, names, TAG)
    if len(playing) < 2:
        await battle.finish(srv, r, TAG)
        r["state"], r["result"] = "skipped", "King of the Hill needs at least two players whose things could be kept safe"
        return
    if r["team_count"]:
        await battle.make_teams(srv, r, min(r["team_count"], len(playing)), TAG)
    for n in r["players"]:
        await battle.send_in(srv, r, n)
    r["state"], r["phase_ends"], r["ticks"] = "running", time.time() + r["minutes"] * 60, 0
    who = (" vs ".join(f"{t.title()}: " + ", ".join(n for n, p in r["players"].items() if p.get("team") == t) for t in r["teams"])
           if r.get("teams") else ", ".join(r["players"]))
    rule = "The team with the most players on the hill scores" if r.get("teams") else "Stand on the hill alone to score"
    await _say(srv, [("★ ", "gold"), ("King of the Hill! ", "yellow"), (f"{rule}, a point a second, for {r['minutes']} minutes. ", None), (who, "aqua")],
               "King of the Hill!", "Hold the hill!")


def _holder(r: dict, on_hill: list[str]) -> str | None:
    """Who scores this second: the team with the most players on the hill (no tie), or the one player alone there."""
    if r.get("teams"):
        counts = {}
        for n in on_hill:
            t = r["players"][n].get("team")
            counts[t] = counts.get(t, 0) + 1
        if not counts:
            return None
        best = max(counts.values())
        top = [t for t, c in counts.items() if c == best]
        return top[0] if len(top) == 1 else None
    return on_hill[0] if len(on_hill) == 1 else None


async def tick(srv, r: dict) -> None:
    from .adventures import _everyone
    now = time.time()
    r["ticks"] = r.get("ticks", 0) + 1
    where = {k.lower(): v for k, v in (await _everyone(srv)).items()}
    await battle.left_and_back(srv, r, where)
    await battle.deaths(srv, r, TAG, now)
    await battle.comebacks(srv, r, now)
    on_hill = [n for n, p in r["players"].items() if not p.get("out") and not p.get("back_at") and n.lower() in where
               and battle.inside(r, where[n.lower()])]
    who = _holder(r, on_hill)
    if who and r.get("teams"):
        r["teams"][who] += 1
    elif who:
        r["players"][who]["score"] += 1
    r["holder"] = who or ("contested" if on_hill else "")
    await battle.ring(srv, r)
    rows = {t.title(): s for t, s in r["teams"].items()} if r.get("teams") else {n: p["score"] for n, p in r["players"].items()}
    await hud.scores(srv, r, "👑 King of the Hill", rows)
    held = f"Held by {who.title() if r.get('teams') else who}" if who else ("Contested!" if on_hill else "Nobody on the hill")
    for n in on_hill:
        await hud.status(srv, r, r["players"][n]["uuid"], f"👑 {held}", "gold" if who else "red")
    if now >= r["phase_ends"]:
        await _end(srv, r)


async def _end(srv, r: dict, called_off: bool = False) -> None:
    from .games import _award, _finish, _say
    await hud.clear(srv, r)
    if called_off:
        winners, result = [], "King of the Hill was called off."
    elif r.get("teams"):
        best = max(r["teams"].values())
        top = [t for t, s in r["teams"].items() if s == best]
        winners = [n for n, p in r["players"].items() if p.get("team") in top] if best else []
        result = (f"{' & '.join(t.title() for t in top)} won King of the Hill with {best} points!" if best
                  else "King of the Hill: nobody held the hill.")
    else:
        best = max((p["score"] for p in r["players"].values()), default=0)
        winners = [n for n, p in r["players"].items() if p["score"] == best] if best else []
        result = f"{' & '.join(winners)} won King of the Hill with {best} points!" if winners else "King of the Hill: nobody held the hill."
    await _say(srv, [("★ ", "gold"), (result, "yellow")], "Game over" if not called_off else "", (" & ".join(winners))[:40] if winners else "")
    await battle.finish(srv, r, TAG)
    _finish(srv, r, result)
    if not called_off:
        await _award(srv, r, winners)


async def cancel(srv, r: dict) -> None:
    await _end(srv, r, called_off=True)


def live_rows(r: dict) -> tuple[list[dict], str]:
    if r.get("teams"):
        rows = [{"name": t.title(), "value": f"{s} pts"} for t, s in sorted(r["teams"].items(), key=lambda kv: -kv[1])]
    else:
        rows = [{"name": n, "value": f"{p['score']} pts"} for n, p in sorted(r["players"].items(), key=lambda kv: -kv[1]["score"])]
    h = r.get("holder")
    return rows, (f"Held by {h.title() if r.get('teams') else h}" if h and h != "contested" else "Contested!" if h else "Nobody on the hill")
