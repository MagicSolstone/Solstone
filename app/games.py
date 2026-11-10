"""Family games run by Solstone over RCON: hide and seek and the treasure hunt.

Both are vanilla Minecraft, with nothing to install in the world. Solstone reads positions once a second, says things
in the game (titles, chat, the line above the hotbar) and keeps score.

Hide and seek: an area (centre + radius) everyone must stay in (put back inside if they
leave; particles show the edge), optional Adventure mode so nobody digs or builds, hiders'
name tags hidden, the seeker blinded and held at the centre while everyone hides, found when a
seeker comes within a few blocks (found hiders join the seekers, or watch as spectators),
"marco" in chat tells the seeker roughly where each hider is. Seekers win if everyone's found;
whoever's still hidden at the end wins.

Treasure hunt: a chest of prizes hidden at a random spot in the area (or a chosen one), placed
on the ground; everyone's hotbar says how warm they are (and, later on, which way); whoever
takes the treasure first wins. The chest is removed afterwards if nobody found it.

(Archery, spleef, King of the Hill and the mob arena were taken out in 1.16: GONE keeps their names for the games
already played, which stay in "Lately".)
"""
from __future__ import annotations

import asyncio
import logging
import math
import re
import random
import secrets
import time

from . import bossbar, challenges, db, hud, settings_store
from . import servers as S
from .control import check_name, component
from .races import _direction, _fmt, _pos, _rcon

log = logging.getLogger("solstone.games")
SECTION = "games"
KINDS = {"hideseek": ("Hide and seek", "🙈"), "treasure": ("Treasure hunt", "💰")}
GONE = {"archery": ("Archery", "🎯"), "spleef": ("Spleef", "❄️"), "koth": ("King of the Hill", "👑"), "arena": ("Mob arena", "⚔️")}
LABELS = KINDS | GONE                               # (name, emoji) for any game on record, played before or not
ACTIVE = ("countdown", "hiding", "running")


# ------------------------------------------------------------------ storage
def _load() -> dict:
    d = settings_store.load().get(SECTION) or {}
    runs = list(d.get("runs") or [])
    for r in runs:                                   # a game that's been taken out, still planned: it's off
        if r.get("game") not in KINDS and r.get("state") in ("scheduled", *ACTIVE):
            r["state"], r["result"] = "cancelled", "This game isn't part of Solstone any more"
    return {"runs": runs, "areas": list(d.get("areas") or [])}


def _save(d: dict) -> None:
    done = [r for r in d["runs"] if r["state"] not in ("scheduled", *ACTIVE)]
    keep = {r["id"] for r in sorted(done, key=lambda r: -r["start"])[:60]}     # (enough for a month of Lately)
    d["runs"] = [r for r in d["runs"] if r["state"] in ("scheduled", *ACTIVE) or r["id"] in keep]
    settings_store.save_section(SECTION, d)


def runs_for(server: str) -> list[dict]:
    order = {s: 0 for s in ACTIVE} | {"scheduled": 1}
    return sorted([r for r in _load()["runs"] if r["server"] == server], key=lambda r: (order.get(r["state"], 2), -r["start"]))


def _num(v, lo, hi, default):
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return default


def _point(p, what: str) -> dict:
    if not isinstance(p, dict):
        raise ValueError(f"Choose the {what}")
    return {"x": round(_num(p.get("x"), -3e7, 3e7, 0), 1), "y": round(_num(p.get("y"), -64, 320, 64), 1), "z": round(_num(p.get("z"), -3e7, 3e7, 0), 1)}


def create(server: str, body: dict) -> dict:
    kind = body.get("game")
    if kind not in KINDS:
        raise ValueError("Pick a game")
    start = _num(body.get("start"), 0, 1e11, 0) or time.time()
    if start < time.time() - 60:
        raise ValueError("That start time has already passed")
    from . import gather
    if start <= time.time() + 2:                         # "right now": a 10-second countdown first
        start = time.time() + gather.LEAD
    prizes = [challenges.clean_prize(p) for p in (body.get("prizes") or [])[:3]]
    r = {"id": secrets.token_hex(4), "server": server, "game": kind, "name": KINDS[kind][0], "start": start, "state": "scheduled",
         "dim": "minecraft:overworld", "prizes": prizes, "players": {}, "said": [], "result": "", "log": [],
         # the treasure hunt can gather everyone at a spot first (hide and seek always gathers at its area)
         "gather": gather.clean_spot(body.get("gather")) if kind == "treasure" else None,
         "optin": bool(body.get("optin"))}          # players choose to join; off: everyone online plays
    if kind == "hideseek":
        r.update(area={**_point(body.get("center"), "middle of the area"), "r": round(_num(body.get("radius"), 10, 200, 40))},
                 hide_secs=int(_num(body.get("hide_secs"), 15, 300, 60)), minutes=int(_num(body.get("minutes"), 1, 30, 6)),
                 no_dig=bool(body.get("no_dig", True)), marco=bool(body.get("marco", True)), infect=bool(body.get("infect", True)),
                 find=round(_num(body.get("find"), 2, 6, 3), 1), seeker=(check_name(body["seeker"]) if body.get("seeker") else ""),
                 rounds=int(_num(body.get("rounds"), 1, 5, 1)), peaceful=bool(body.get("peaceful", True)))
    elif kind == "treasure":
        if not any(prizes) and not body.get("items"):
            raise ValueError("Put something in the treasure chest")
        items = [challenges.clean_prize(p) for p in (body.get("items") or [])[:27]]
        r.update(area={**_point(body.get("center"), "middle of the area"), "r": round(_num(body.get("radius"), 20, 1000, 150))},
                 spot=_point(body["spot"], "spot") if body.get("spot") else None, items=[i for i in items if i],
                 minutes=int(_num(body.get("minutes"), 3, 60, 15)), hint_after=int(_num(body.get("hint_after"), 0, 60, 5)),
                 underwater=bool(body.get("underwater")), compass=bool(body.get("compass", True)), edge=bool(body.get("edge", True)))
        if not r["items"]:
            raise ValueError("Put something in the treasure chest")
    d = _load()
    d["runs"].append(r)
    _save(d)
    return r


# ------------------------------------------------------------------ shared
def busy() -> bool:
    return any(r["state"] in ACTIVE or (r["state"] == "scheduled" and r["start"] - time.time() < 30) for r in _load()["runs"])


def hidden_from_map(sid: str) -> set[str]:
    """Players the status map mustn't show right now (hiders during hide and seek)."""
    out = set()
    for r in _load()["runs"]:
        if r["server"] == sid and r["game"] == "hideseek" and r["state"] in ACTIVE:
            out |= {n for n, p in r["players"].items() if p.get("role") == "hider"}
    return out


async def _say(srv, parts, title: str = "", sub: str = "", who: str = "@a") -> None:
    await _rcon(srv, f"tellraw {who} {component(parts)}")
    if title:
        await _rcon(srv, f"title {who} times 5 40 10")
        await _rcon(srv, f"title {who} subtitle {component([(sub, 'yellow')])}")
        await _rcon(srv, f"title {who} title {component([(title, 'gold')])}")


async def entrants(srv, r: dict) -> list[str]:
    """Who's playing, of those online: everyone, or those who joined (when players choose to)."""
    from . import optin
    online = (await S.online_players(srv))[0]
    if r.get("kept"):                                    # under way: just those whose things are kept safe
        return [n for n in online if n in r["kept"]]
    if not r.get("optin"):
        return online
    if r["state"] == "scheduled":
        return optin.players("game", r, online)
    return [n for n in online if n in (r.get("entrants") or [])]


async def _bar(srv, who: str, text: str, color: str = "yellow") -> None:
    await _rcon(srv, f"title {who} actionbar {component([(text, color)])}")


def _dist(a, b) -> float:
    return math.hypot(a[0] - b["x"], a[2] - b["z"])


async def _gamemode(srv, name: str) -> str:
    try:
        live = await S.live_player(srv, name)
        return (live or {}).get("gamemode") or "survival"
    except Exception:
        return "survival"


async def _award(srv, r: dict, winners: list[str]) -> None:
    prize = (r.get("prizes") or [None])[0]
    for w in winners:
        if prize:
            await challenges.award(srv, w, prize, f"won {r['name']}")


async def _countdown(srv, r: dict) -> None:
    """The boss bar for whatever phase the game is in, plus 10/5/1 minute warnings."""
    if not r.get("phase_ends"):
        return
    if r["game"] == "hideseek" and r["state"] == "hiding":
        title, total, color = "Hide!", r["hide_secs"], "green"
    else:
        title, total, color = r["name"], r["minutes"] * 60, {"hideseek": "red", "treasure": "yellow"}[r["game"]]
    if r.get("bar_title") != title:                   # new phase: a fresh bar
        await bossbar.hide(srv, r)
        r["bar_title"] = title
    await bossbar.show(srv, r, f"g_{r['id']}", title, r["phase_ends"], total, color=color)
    mins = bossbar.due_warning(r, r["phase_ends"], total) if r["state"] == "running" else None
    if mins:
        await _say(srv, [("★ ", "gold"), (f"{mins} minute{'s' if mins > 1 else ''} left in {r['name']}!", "yellow")])


def _go_home(srv, r: dict, secs: int | None = None) -> None:
    """Everyone back where they were with exactly their own things (kits.send_home), the game's things and anything
    picked up left behind. The treasure hunt's treasure is the finder's prize, given once they're home."""
    from . import kits
    r["sent_home"] = True
    r.pop("gathered", None)                              # (the trip home is where they were before the game)
    after = None
    if r["game"] == "treasure" and r.get("finder") and r.get("items"):
        finder, items, name = r["finder"], list(r["items"]), r["name"]

        async def after():
            for it in items:
                await challenges.award(srv, finder, it, f"found the treasure in {name}")
    kits.send_home(srv, r["kept"], r["id"], kits.HOME_SECS if secs is None else secs, after)


def _finish(srv, r: dict, result: str) -> None:
    r["state"], r["result"], r["ended"] = "done", result, time.time()
    db.add_event(srv.id, time.time(), "game", result)


# ------------------------------------------------------------------ hide and seek
async def _hs_start(srv, r: dict) -> None:
    names = r["entrants"]
    if len(names) < 2:
        r["state"], r["result"] = "skipped", "Hide and seek needs at least two players" + (" to join" if r.get("optin") else " online")
        return
    seeker = r["seeker"] if r["seeker"] in names else random.choice(names)
    a, dim = r["area"], r["dim"]
    for n in names:
        r["players"][n] = {"role": "hider", "gm": await _gamemode(srv, n), "points": 0}
    r["round"], r["rounds"], r["sought"] = 1, r.get("rounds") or 1, []
    if r.get("peaceful"):                         # no monsters while people hide in the dark
        m = re.search(r"difficulty is (\w+)", await _rcon(srv, "difficulty"), re.I)
        r["difficulty"] = m.group(1).lower() if m else "normal"
        if r["difficulty"] != "peaceful":
            await _rcon(srv, "difficulty peaceful")
    await _rcon(srv, "team add solhs_h")
    await _rcon(srv, "team modify solhs_h nametagVisibility never")
    await _rcon(srv, "team modify solhs_h color green")
    await _rcon(srv, "team add solhs_s")
    await _rcon(srv, "team modify solhs_s color red")
    from . import gather
    r["gathered"] = await gather.send(srv, {"x": a["x"], "y": a["y"], "z": a["z"], "r": 3, "dim": dim}, list(r["players"]))
    await _hs_round(srv, r, seeker)


async def _hs_round(srv, r: dict, seeker: str) -> None:
    """A round: one seeker (counting, blind), everyone else hiding."""
    a = r["area"]
    r["sought"].append(seeker)
    for n, p in r["players"].items():
        p["role"] = "seeker" if n == seeker else "hider"
        p.pop("found_by", None)
        p.pop("found_at", None)
        await _rcon(srv, f"team join {'solhs_s' if p['role'] == 'seeker' else 'solhs_h'} {n}")
        if r["no_dig"]:
            await _rcon(srv, f"gamemode adventure {n}")
    await _rcon(srv, f"effect give {seeker} minecraft:blindness {r['hide_secs'] + 2} 0 true")
    await _rcon(srv, f"effect give {seeker} minecraft:slowness {r['hide_secs'] + 2} 255 true")
    r["state"], r["phase_ends"] = "hiding", time.time() + r["hide_secs"]
    hiders = [n for n, p in r["players"].items() if p["role"] == "hider"]
    which = f"Round {r['round']} of {r['rounds']}: " if r["rounds"] > 1 else "Hide and seek! "
    await _say(srv, [("★ ", "gold"), (which, "yellow"), (seeker, "red"), (f" is seeking. Hiders: {', '.join(hiders)}. Stay within {a['r']} blocks"
                     + (", no digging or building" if r["no_dig"] else "") + ".", None)], "Hide!", f"{r['hide_secs']} seconds")
    await _say(srv, [("You're the seeker. Count to ", None), (str(r["hide_secs"]), "gold"), ("...", None)]
               + ([("  Type ", "gray"), ("marco", "aqua"), (" in chat to hear where they are.", "gray")] if r["marco"] else []), "You're it!", "Count to " + str(r["hide_secs"]), who=seeker)
    await _hs_scores(srv, r)


async def _hs_scores(srv, r: dict) -> None:
    if r.get("rounds", 1) > 1:
        await hud.scores(srv, r, f"🙈 Round {r['round']} of {r['rounds']}", {n: p.get("points", 0) for n, p in r["players"].items()})


async def _hs_tick(srv, r: dict) -> None:
    now, a, dim = time.time(), r["area"], r["dim"]
    online, _src = await S.online_players(srv)
    pos = {}
    for n, p in r["players"].items():
        if n in online and p["role"] != "found":
            q = await _pos(srv, n)
            if q:
                pos[n] = q
    # stay inside the area
    for n, q in pos.items():
        d = _dist(q, a)
        if d > a["r"] + 1:
            back = r["players"][n].get("last_in")
            if back:                              # back to where they last stood inside (not onto a treetop)
                await _rcon(srv, f"execute in {dim} run tp {n} {back[0]} {back[1]} {back[2]}")
            else:
                k = (a["r"] - 3) / d
                bx, bz = a["x"] + (q[0] - a["x"]) * k, a["z"] + (q[2] - a["z"]) * k
                await _rcon(srv, f"execute in {dim} run spreadplayers {bx:.1f} {bz:.1f} 0 1 false {n}")
            await _bar(srv, n, "Stay inside the play area!", "red")
            continue
        if d <= a["r"] - 1:
            r["players"][n]["last_in"] = [round(q[0], 2), round(q[1], 2), round(q[2], 2)]
        if d > a["r"] - 5:
            await _bar(srv, n, f"The edge is {int(a['r'] - d) + 1} blocks away", "gold")
    if int(now) % 3 == 0:                        # the edge, as a ring of particles
        for k in range(32):
            ang = k * math.pi / 16
            await _rcon(srv, f"execute in {dim} run particle minecraft:end_rod {a['x'] + math.cos(ang) * a['r']:.1f} {a['y'] + 1} {a['z'] + math.sin(ang) * a['r']:.1f} 0.2 1.5 0.2 0 2 force")
    seekers = [n for n, p in r["players"].items() if p["role"] == "seeker"]
    hiders = [n for n, p in r["players"].items() if p["role"] == "hider"]
    if r["state"] == "hiding":
        for s in seekers:
            if s in pos and _dist(pos[s], a) > 2:
                await _rcon(srv, f"execute in {dim} run tp {s} {a['x']} {a['y'] + 0.5} {a['z']}")
        left = int(math.ceil(r["phase_ends"] - now))
        for n in hiders:
            await _bar(srv, n, f"Hide! {left} s")
        if left <= 0:
            r["state"], r["phase_ends"] = "running", now + r["minutes"] * 60
            for s in seekers:
                await _rcon(srv, f"effect clear {s}")
            await _say(srv, [("★ ", "gold"), ("Ready or not, here they come!", "yellow")], "Ready or not!", "here they come")
        return
    # seeking: anyone close enough to a seeker is found
    for h in list(hiders):
        if h not in pos:
            continue
        for s in seekers:
            if s in pos and _dist(pos[h], {"x": pos[s][0], "z": pos[s][2]}) <= r["find"] and abs(pos[h][1] - pos[s][1]) <= 3:
                await _found(srv, r, h, s)
                break
    hiders = [n for n, p in r["players"].items() if p["role"] == "hider"]
    left = r["phase_ends"] - now
    for s in [n for n, p in r["players"].items() if p["role"] == "seeker"]:
        await _bar(srv, s, f"Still hiding: {len(hiders)} · {_fmt(left)} left", "red")
    for h in hiders:
        near = min((_dist(pos[h], {"x": pos[s][0], "z": pos[s][2]}) for s in pos if r["players"][s]["role"] == "seeker"), default=999) if h in pos else 999
        await _bar(srv, h, "A seeker is close!" if near < 12 else f"Hidden · {_fmt(left)} left", "red" if near < 12 else "green")
    if not hiders:
        await _hs_end(srv, r, seekers_won=True)
    elif left <= 0:
        await _hs_end(srv, r, seekers_won=False)


async def _found(srv, r: dict, hider: str, seeker: str) -> None:
    p = r["players"][hider]
    p["found_by"], p["found_at"] = seeker, time.time()
    r["players"][seeker]["points"] = r["players"][seeker].get("points", 0) + 1
    if r["infect"]:
        p["role"] = "seeker"
        await _rcon(srv, f"team join solhs_s {hider}")
        await _say(srv, [("★ ", "gold"), (seeker, "red"), (" found ", None), (hider, "green"), ("! They're seeking now.", None)])
    else:
        p["role"] = "found"
        await _rcon(srv, f"gamemode spectator {hider}")
        await _say(srv, [("★ ", "gold"), (seeker, "red"), (" found ", None), (hider, "green"), ("!", None)])
    await _rcon(srv, f"execute as {hider} at @s run playsound minecraft:entity.experience_orb.pickup master @a ~ ~ ~ 1 0.6")


async def _hs_end(srv, r: dict, seekers_won: bool) -> None:
    hiders = [n for n, p in r["players"].items() if p["role"] == "hider"]
    if r.get("rounds", 1) > 1:
        await _hs_round_over(srv, r, hiders)
        return
    if seekers_won:
        first = [n for n, p in r["players"].items() if p.get("found_by") is None and p["role"] == "seeker"]
        winners = first
        result = f"{' & '.join(first)} found everyone! Hide and seek is over."
    else:
        winners = hiders
        result = f"{' & '.join(hiders)} stayed hidden and {'win' if len(hiders) > 1 else 'wins'} hide and seek!"
    await _say(srv, [("★ ", "gold"), (result, "yellow")], "Game over", ", ".join(winners)[:40] + " won")
    await _hs_cleanup(srv, r)
    _finish(srv, r, result)
    await _award(srv, r, winners)


async def _hs_round_over(srv, r: dict, hiders: list[str]) -> None:
    """Best of several rounds: hiders still hidden score 2, each find scored 1 for the finder.
    Then a new seeker (nobody seeks twice until everyone has had a turn), or the final result."""
    for h in hiders:
        r["players"][h]["points"] = r["players"][h].get("points", 0) + 2
    standings = sorted(r["players"].items(), key=lambda kv: -kv[1].get("points", 0))
    table = " · ".join(f"{n} {p.get('points', 0)}" for n, p in standings)
    what = f"{' & '.join(hiders)} stayed hidden (+2)" if hiders else "Everyone was found"
    await _hs_scores(srv, r)
    online = set((await S.online_players(srv))[0])
    players = [n for n in r["players"] if n in online]
    if r["round"] < r["rounds"] and len(players) >= 2:
        await _say(srv, [("★ ", "gold"), (f"Round {r['round']} over: {what}. ", "yellow"), (table, "gray")], f"Round {r['round']} over", table[:40])
        for n, p in r["players"].items():                    # found players come back from watching
            if p["role"] == "found" or not r["no_dig"]:
                await _rcon(srv, f"gamemode {'adventure' if r['no_dig'] else p.get('gm') or 'survival'} {n}")
            await _rcon(srv, f"effect clear {n}")
        fresh = [n for n in players if n not in r["sought"]]
        seeker = random.choice(fresh or [n for n in players if n != r["sought"][-1]] or players)
        a = r["area"]
        await _rcon(srv, f"execute in {r['dim']} run spreadplayers {a['x']} {a['z']} 1 3 false {' '.join(players)}")
        for n in players:
            r["players"][n].pop("last_in", None)
        r["round"] += 1
        await _hs_round(srv, r, seeker)
        return
    top = max((p.get("points", 0) for p in r["players"].values()), default=0)
    winners = [n for n, p in r["players"].items() if p.get("points", 0) == top and top > 0]
    result = (f"{' & '.join(winners)} won hide and seek with {top} points! " if winners else "Hide and seek is over. ") + f"({table})"
    await _say(srv, [("★ ", "gold"), (result, "yellow")], "Game over", (", ".join(winners) + " won")[:40] if winners else "")
    await _hs_cleanup(srv, r)
    _finish(srv, r, result)
    await _award(srv, r, winners)


async def _hs_cleanup(srv, r: dict) -> None:
    await hud.clear(srv, r)
    if r.get("difficulty") and r["difficulty"] != "peaceful":
        await _rcon(srv, f"difficulty {r['difficulty']}")
    for n, p in r["players"].items():
        await _rcon(srv, f"team leave {n}")
        await _rcon(srv, f"effect clear {n}")
        if r["no_dig"] or p["role"] == "found":
            await _rcon(srv, f"gamemode {p.get('gm') or 'survival'} {n}")
    await _rcon(srv, "team remove solhs_h")
    await _rcon(srv, "team remove solhs_s")


async def _marco(srv, r: dict, player: str) -> None:
    if r["players"].get(player, {}).get("role") != "seeker" or r["state"] != "running":
        return
    now = time.time()
    if now - r.get("marco_at", 0) < 20:
        await _bar(srv, player, f"Marco again in {int(20 - (now - r['marco_at']))} s", "gray")
        return
    r["marco_at"] = now
    me = await _pos(srv, player)
    if not me:
        return
    parts = [("Polo! ", "aqua")]
    hiders = [n for n, p in r["players"].items() if p["role"] == "hider"]
    for h in hiders:
        q = await _pos(srv, h)
        if not q:
            continue
        d = math.hypot(q[0] - me[0], q[2] - me[2])
        band = "very close" if d < 10 else "close" if d < 25 else "not far" if d < 50 else "far away"
        parts.append((f"Someone {band}, {_direction(q[0] - me[0], q[2] - me[2])}. ", "white"))
    if len(parts) == 1:
        parts.append(("Nobody left to find.", "white"))
    await _rcon(srv, f"tellraw {player} {component(parts)}")
    await _say(srv, [("★ ", "gold"), (player, "red"), (" called ", None), ("Marco!", "aqua")], who="@a[team=solhs_h]")


# ------------------------------------------------------------------ treasure hunt
_BANDS = [(10, "Burning hot!", "red"), (20, "Hot", "gold"), (40, "Warm", "yellow"), (80, "Cool", "aqua"), (150, "Cold", "blue"), (1e9, "Freezing", "dark_aqua")]


def _bands(radius: float) -> list[tuple[float, str, str]]:
    """How warm, by distance. Burning hot and Hot stay close (that's where the chest is); Warm, Cool and Cold stretch
    with a big area, so a 500-block hunt isn't "Freezing" nearly everywhere."""
    r = max(0.0, float(radius or 0))
    return [(10, "Burning hot!", "red"), (20, "Hot", "gold"), (max(40, r * 0.2), "Warm", "yellow"),
            (max(80, r * 0.45), "Cool", "aqua"), (max(150, r * 0.9), "Cold", "blue"), (1e9, "Freezing", "dark_aqua")]


_ROT = re.compile(r"\[\s*(-?[\d.]+)f?\s*,")


def _relative(yaw: float, dx: float, dz: float) -> str:
    """Which way the chest is from where someone's looking: no compass needed, the same on Java and Bedrock.
    (Minecraft's yaw: 0 is south, and it grows turning right.)"""
    want = math.degrees(math.atan2(-dx, dz))
    rel = (want - yaw + 180) % 360 - 180                  # -180..180: negative is to the left
    a = abs(rel)
    side = "right" if rel > 0 else "left"
    if a <= 22.5:
        return "⬆ straight ahead"
    if a <= 67.5:
        return f"{'↗' if rel > 0 else '↖'} ahead, to your {side}"
    if a <= 112.5:
        return f"{'➡' if rel > 0 else '⬅'} to your {side}"
    if a <= 157.5:
        return f"{'↘' if rel > 0 else '↙'} behind you, to the {side}"
    return "⬇ behind you"


async def _yaw(srv, name: str) -> float | None:
    m = _ROT.search(await _rcon(srv, f"data get entity {name} Rotation"))
    return float(m.group(1)) if m else None


def _treasure_compass(srv, r: dict) -> str:
    """A compass that points at the chest (a lodestone compass with no lodestone), marked as the game's: it goes when
    they're home with their things."""
    from .kits import KIT_TAG
    from .races import _new_text
    c = r["chest"]
    name = '"Treasure compass"' if _new_text(srv) else "'\"Treasure compass\"'"
    return (f'minecraft:compass[minecraft:lodestone_tracker={{target:{{dimension:"{r["dim"]}",pos:[I;{c["x"]},{c["y"]},{c["z"]}]}},tracked:false}},'
            f"minecraft:custom_data={{{KIT_TAG}:1b}},minecraft:item_name={name}]")


async def _th_edge(srv, r: dict) -> None:
    """The area's edge in sparkles on the ground, a stretch at a time all the way round, and a column of them in the
    middle: somewhere to start (or to stay away from)."""
    a = r["area"]
    n = max(24, min(360, round(2 * math.pi * a["r"] / 4)))       # about every 4 blocks
    i0 = r.get("edge_i", 0)
    for k in range(i0, i0 + 30):
        ang = 2 * math.pi * (k % n) / n
        x, z = a["x"] + a["r"] * math.cos(ang), a["z"] + a["r"] * math.sin(ang)
        await _rcon(srv, f"execute in {r['dim']} positioned {x:.1f} 320 {z:.1f} positioned over motion_blocking_no_leaves "
                         f"run particle minecraft:end_rod ~ ~1.2 ~ 0.1 0.8 0.1 0 6 force")
    r["edge_i"] = (i0 + 30) % n
    if r.get("ticks_th", 0) % 3 == 0:
        await _rcon(srv, f"execute in {r['dim']} positioned {a['x']} 320 {a['z']} positioned over motion_blocking_no_leaves "
                         f"run particle minecraft:end_rod ~ ~6 ~ 0.15 5 0.15 0 40 force")


async def _height(srv, dim: str, x: int, z: int, tag: str, heightmap: str) -> int | None:
    from .races import _POS
    await _rcon(srv, f"execute in {dim} positioned {x} 320 {z} positioned over {heightmap} run summon minecraft:marker ~ ~ ~ {{Tags:[\"{tag}\"]}}")
    m = _POS.search(await _rcon(srv, f"data get entity @e[tag={tag},limit=1] Pos"))
    await _rcon(srv, f"kill @e[tag={tag}]")
    return int(float(m.group(2))) if m else None


async def _treasure_spot(srv, r: dict, x: int, z: int, tag: str) -> tuple[int, bool] | None:
    """Where a chest can go at x, z: (y, underwater) on solid ground, or on the bottom of the water
    when that's allowed. None for no good: lava, the top of a tree, water when it isn't allowed."""
    dim = r["dim"]
    y = await _height(srv, dim, x, z, tag, "motion_blocking_no_leaves")
    if y is None:
        return None

    async def is_(block: str) -> bool:
        return "passed" in (await _rcon(srv, f"execute in {dim} if block {x} {y - 1} {z} {block}")).lower()
    if await is_("minecraft:water"):
        if not r.get("underwater"):
            return None
        floor = await _height(srv, dim, x, z, tag, "ocean_floor")
        return (floor, True) if floor is not None and floor < y else None
    if await is_("minecraft:lava") or await is_("#minecraft:logs") or await is_("#minecraft:leaves"):
        return None
    return y, False


async def _th_start(srv, r: dict) -> None:
    a, dim = r["area"], r["dim"]
    tag = f"solth_{r['id']}"
    found = None
    for attempt in range(16):
        if r.get("spot") and attempt == 0:
            x, z = r["spot"]["x"], r["spot"]["z"]
        elif r.get("spot") and attempt < 6:                  # the chosen spot won't do: somewhere close by
            x, z = r["spot"]["x"] + random.uniform(-8, 8), r["spot"]["z"] + random.uniform(-8, 8)
        else:
            ang, rad = random.uniform(0, 2 * math.pi), a["r"] * math.sqrt(random.uniform(0.15, 1))
            x, z = a["x"] + math.cos(ang) * rad, a["z"] + math.sin(ang) * rad
        x, z = int(math.floor(x)), int(math.floor(z))
        await _rcon(srv, f"execute in {dim} run forceload add {x} {z}")
        found = await _treasure_spot(srv, r, x, z, tag)
        if found:
            break
        await _rcon(srv, f"execute in {dim} run forceload remove {x} {z}")
    if found:
        y, wet = found
    else:                                                    # nowhere good after all that: the last spot's surface
        y, wet = (await _height(srv, dim, x, z, tag, "motion_blocking_no_leaves") or int(r["area"]["y"])), False
        await _rcon(srv, f"execute in {dim} run forceload add {x} {z}")
    r["underwater_spot"] = wet
    items = ",".join(f'{{Slot:{i}b,id:"{it["item"]}",count:{it["count"]}}}' for i, it in enumerate(r["items"][:27]))
    chest = "minecraft:chest[waterlogged=true]" if wet else "minecraft:chest"
    out = await _rcon(srv, f"execute in {dim} run setblock {x} {y} {z} {chest}{{Items:[{items}]}} replace")
    if out and "changed" not in out.lower():
        r["chest_error"] = out[:160]
    r["chest"] = {"x": x, "y": y, "z": z}
    r["state"], r["phase_ends"] = "running", time.time() + r["minutes"] * 60
    await _say(srv, [("★ ", "gold"), ("Treasure hunt! ", "yellow"), (f"A chest of treasure is hidden within {a['r']} blocks{' (it could be underwater!)' if r.get('underwater') else ''}"
                     f"{' of the sparkling column (the sparkles on the ground mark the edge)' if r.get('edge', True) else ''}. Watch your hotbar: it says how warm you are.", None)],
               "Treasure hunt!", "Find the chest")


async def _th_tick(srv, r: dict) -> None:
    now, c = time.time(), r["chest"]
    online = await entrants(srv, r)
    hint = now - r["started"] >= r["hint_after"] * 60 if r.get("started") else False
    r["ticks_th"] = r.get("ticks_th", 0) + 1
    if r.get("edge", True):
        await _th_edge(srv, r)
    if hint and r.get("compass", True) and not r.get("compass_given"):
        r["compass_given"] = True                         # once: everyone playing gets one (taken back when they're home)
        for n in online:
            from . import kits
            await kits.hand_out(srv, n, [], [(_treasure_compass(srv, r), 1)])     # given, then checked
            await _say(srv, [("★ ", "gold"), ("Hint! ", "yellow"), ("Here's a treasure compass: it points straight at the chest.", None)], who=n)
    bands = _bands(r["area"]["r"])
    near = {}
    for n in online:
        q = await _pos(srv, n)
        if not q:
            continue
        d = math.dist(q, (c["x"] + 0.5, c["y"], c["z"] + 0.5))
        near[n] = d
        word, color = next((w, col) for lim, w, col in bands if d < lim)
        extra = ""
        if hint and d > 10:
            yaw = await _yaw(srv, n)
            extra = f" · {_relative(yaw, c['x'] + 0.5 - q[0], c['z'] + 0.5 - q[2]) if yaw is not None else _direction(c['x'] - q[0], c['z'] - q[2])}"
        await _bar(srv, n, f"{word}{extra} · {_fmt(r['phase_ends'] - now)} left", color)
    r["warmest"] = min(near, key=near.get) if near else None
    out = await _rcon(srv, f"execute in {r['dim']} run data get block {c['x']} {c['y']} {c['z']} Items")
    low = out.lower()
    # an emptied chest has no Items at all ("found no elements"); a broken one is no block entity
    taken = "[]" in out or "found no elements" in low or "not a block entity" in low
    if taken:
        finder = min(near, key=near.get) if near else None
        r["finder"] = finder
        result = (f"{finder} found the treasure! It's theirs once they're home." if finder and r.get("kept")
                  else f"{finder} found the treasure!" if finder else "Someone found the treasure!")
        await _say(srv, [("★ ", "gold"), (result, "yellow")], "Treasure found!", finder or "")
        await _rcon(srv, f"execute in {r['dim']} run setblock {c['x']} {c['y']} {c['z']} {'minecraft:water' if r.get('underwater_spot') else 'minecraft:air'}")
        await _rcon(srv, f"execute in {r['dim']} run forceload remove {c['x']} {c['z']}")
        _finish(srv, r, result)
    elif now >= r["phase_ends"]:
        await _say(srv, [("★ ", "gold"), ("Time's up! Nobody found the treasure. It was at ", "yellow"), (f"{c['x']}, {c['y']}, {c['z']}", "white"), (".", "yellow")], "Time's up", "The treasure is gone")
        await _rcon(srv, f"execute in {r['dim']} run setblock {c['x']} {c['y']} {c['z']} {'minecraft:water' if r.get('underwater_spot') else 'minecraft:air'}")
        await _rcon(srv, f"execute in {r['dim']} run forceload remove {c['x']} {c['z']}")
        _finish(srv, r, "Nobody found the treasure in time.")


# ------------------------------------------------------------------ the loop
_lock = asyncio.Lock()                  # the tick and a cancel both change the saved games


async def tick(servers: list) -> None:
    async with _lock:
        await _tick(servers)


async def _tick(servers: list) -> None:
    from . import gather
    d = _load()
    live = [r for r in d["runs"] if r["state"] in ("scheduled", *ACTIVE)]
    if not live:
        return
    by_id = {s.id: s for s in servers}
    now = time.time()
    changed = False
    for r in live:
        srv = by_id.get(r["server"])
        if r["state"] == "scheduled":
            if now >= r["start"] + 300 or (srv is None and now >= r["start"]):
                r["state"], r["result"] = "skipped", "The server wasn't running with RCON at the start time"
            elif srv and srv.rcon_conf() and now >= r["start"]:
                r["started"] = now
                r["entrants"] = await entrants(srv, r)
                if r.get("optin") and not r["entrants"]:
                    r["state"], r["result"] = "skipped", "Nobody joined"
                    await _say(srv, [("★ ", "gold"), (f"Nobody joined {r['name']}, so it's off this time.", "yellow")])
                    changed = True
                    continue
                from . import kits                      # everyone's own things are kept safe for the game
                r["kept"] = await kits.keep_safe(srv, r["entrants"], r["id"])
                r["entrants"] = list(r["kept"])
                if not r["entrants"]:
                    r["state"], r["result"] = "skipped", "Nobody's things could be kept safe, so it didn't start"
                    changed = True
                    continue
                if r.get("gather"):
                    r["gathered"] = await gather.send(srv, r["gather"], r["entrants"])
                await {"hideseek": _hs_start, "treasure": _th_start}[r["game"]](srv, r)
            elif srv and srv.rcon_conf() and 0 < r["start"] - now <= gather.LEAD:
                moved = r.get("gather") or r["game"] == "hideseek"
                who = await entrants(srv, r) if r.get("optin") else None
                await gather.lead_in(srv, r, now, r["name"], "you'll be teleported there" if moved else "", who)
            else:
                continue
            changed = True
        elif srv:
            try:
                await {"hideseek": _hs_tick, "treasure": _th_tick}[r["game"]](srv, r)
                if r.get("state") == "running":
                    from . import kits
                    await kits.hand_back_dropped(srv, 16)        # the treasure compass dropped: straight back
                    for n, u in list((r.get("kept") or {}).items()):
                        if kits.wants_out(srv.id, n):            # /trigger leave: out, and home with their things
                            del r["kept"][n]
                            await kits.give_back(srv, u, move=True)
                            await _say(srv, [("★ ", "gold"), (n, "aqua"), (" left the game. Their things are on the way back.", "yellow")])
                            changed = True
                if r["state"] in ACTIVE:
                    await _countdown(srv, r)
                else:
                    await bossbar.hide(srv, r)
            except Exception:
                log.exception("game %s failed", r["id"])
            changed = True
        if srv and r["state"] not in ACTIVE and r.get("kept") and not r.get("sent_home"):
            _go_home(srv, r)                                             # winners announced: everyone home, with their things
            changed = True
        elif srv and r["state"] not in ACTIVE and r.get("gathered"):
            gather.come_home(srv, r.pop("gathered"), r["name"])         # winners announced: everyone home after a countdown
            changed = True
    if changed:
        _save(d)


async def on_chat(srv, player: str, text: str) -> None:
    if text.strip().lower().rstrip("!?.").startswith("marco"):
        d = _load()
        for r in d["runs"]:
            if r["server"] == srv.id and r["game"] == "hideseek" and r["state"] == "running" and r.get("marco"):
                await _marco(srv, r, player)
                _save(d)


async def cancel(srv, rid: str) -> bool:
    async with _lock:
        return await _cancel(srv, rid)


async def _cancel(srv, rid: str) -> bool:
    d = _load()
    r = next((x for x in d["runs"] if x["id"] == rid and x["server"] == srv.id), None)
    if not r:
        return False
    was_live = r["state"] in ("scheduled", *ACTIVE)
    if r["state"] in ACTIVE:
        await bossbar.hide(srv, r)
        if r["game"] == "hideseek":
            await _hs_cleanup(srv, r)
        elif r["game"] == "treasure" and r.get("chest"):
            c = r["chest"]
            await _rcon(srv, f"execute in {r['dim']} run setblock {c['x']} {c['y']} {c['z']} {'minecraft:water' if r.get('underwater_spot') else 'minecraft:air'}")
            await _rcon(srv, f"execute in {r['dim']} run forceload remove {c['x']} {c['z']}")
        await _say(srv, [("★ ", "gold"), (f"{r['name']} was called off.", "yellow")])
    if was_live:
        r["state"] = "cancelled"
        if r.get("kept") and not r.get("sent_home"):
            _go_home(srv, r, secs=3)
        elif r.get("gathered"):
            from . import gather
            gather.come_home(srv, r.pop("gathered"), r["name"])
    else:                                            # removing a finished one
        d["runs"] = [x for x in d["runs"] if x["id"] != rid]
    _save(d)
    return True


def live(sid: str) -> list[dict]:
    """Running games for the status page and TV."""
    out = []
    for r in _load()["runs"]:
        if r["server"] != sid or r["state"] not in ACTIVE:
            continue
        name, emoji = LABELS[r["game"]]
        rows, sub = [], ""
        if r["game"] == "hideseek":
            order = {"seeker": 0, "hider": 1, "found": 2}
            label = {"seeker": "seeking", "hider": "hidden" if r["state"] != "hiding" else "hiding", "found": "found"}
            rows = [{"name": n, "value": label.get(p["role"], p["role"])} for n, p in sorted(r["players"].items(), key=lambda kv: (order.get(kv[1]["role"], 3), kv[0].lower()))]
            hidden = sum(1 for p in r["players"].values() if p["role"] == "hider")
            sub = "Hiders are hiding..." if r["state"] == "hiding" else f"{hidden} still hidden"
        elif r["game"] == "treasure":
            sub = "Find the hidden chest"
            if r.get("warmest"):
                rows = [{"name": r["warmest"], "value": "closest"}]
        out.append({"id": f"g-{r['id']}", "emoji": emoji, "title": r["name"] or name, "sub": sub, "ends_at": r.get("phase_ends"),
                    "rows": rows[:10], "empty": ""})
    return out


def banners(sid: str | None) -> list[dict]:
    out = []
    for r in _load()["runs"]:
        if sid and r["server"] != sid:
            continue
        emoji = LABELS.get(r["game"], ("", "🎲"))[1]
        if r["state"] == "scheduled" and 0 < r["start"] - time.time() <= 3600:
            out.append({"id": f"g-{r['id']}", "kind": "challenge", "emoji": emoji, "style": "info", "text": r["name"], "detail": "Starting soon",
                        "countdown": r["start"], "done_text": "Starting!"})
        elif r["state"] in ACTIVE:
            if r["game"] == "hideseek":
                hiders = sum(1 for p in r["players"].values() if p["role"] == "hider")
                txt = f"Hide and seek: {'hiding...' if r['state'] == 'hiding' else f'{hiders} still hidden'}"
            else:
                txt = f"{r['name']} is on!"
            out.append({"id": f"g-{r['id']}", "kind": "challenge", "emoji": emoji, "style": "party", "text": txt, "detail": "",
                        "countdown": r.get("phase_ends"), "done_text": "Time's up!"})
        elif r["state"] == "done" and time.time() - (r.get("ended") or 0) < 1800 and r.get("result"):
            out.append({"id": f"gd-{r['id']}", "kind": "challenge", "emoji": "🏆", "style": "party", "text": r["result"], "detail": "", "countdown": None})
    return out

