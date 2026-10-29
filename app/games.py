"""Family games run by Solstone over RCON: hide and seek, treasure hunt, archery.

All three are vanilla Minecraft. Solstone reads positions once a second, says things in the
game (titles, chat, the line above the hotbar) and keeps score; archery also reads the shots
and target hits recorded by the Solstone data pack (see fishpack.py).

Hide and seek: an area (centre + radius) everyone must stay in (put back inside if they
leave; particles show the edge), optional Adventure mode so nobody digs or builds, hiders'
name tags hidden, the seeker blinded and held at the centre while everyone hides, found when a
seeker comes within a few blocks (found hiders join the seekers, or watch as spectators),
"marco" in chat tells the seeker roughly where each hider is. Seekers win if everyone's found;
whoever's still hidden at the end wins.

Treasure hunt: a chest of prizes hidden at a random spot in the area (or a chosen one), placed
on the ground; everyone's hotbar says how warm they are (and, later on, which way); whoever
takes the treasure first wins. The chest is removed afterwards if nobody found it.

Archery: one target block (an existing one, or one Solstone places). Longest bullseye, most
points (ring x distance) or HORSE: turn by turn, the setter shoots from anywhere; if they hit,
everyone else must make the same shot from that spot or take a letter; spell the word and
you're out; last one standing wins.
"""
from __future__ import annotations

import asyncio
import logging
import math
import re
import random
import secrets
import time

from . import bossbar, challenges, db, fwshow, hotzone, hud, settings_store
from . import servers as S
from .control import check_name, component
from .races import _direction, _fmt, _pos, _rcon

log = logging.getLogger("solstone.games")
SECTION = "games"
KINDS = {"hideseek": ("Hide and seek", "🙈"), "treasure": ("Treasure hunt", "💰"), "archery": ("Archery", "🎯"), "spleef": ("Spleef", "❄️")}
ACTIVE = ("countdown", "hiding", "running")


# ------------------------------------------------------------------ storage
def _load() -> dict:
    d = settings_store.load().get(SECTION) or {}
    return {"runs": list(d.get("runs") or []), "areas": list(d.get("areas") or [])}


def _save(d: dict) -> None:
    done = [r for r in d["runs"] if r["state"] not in ("scheduled", *ACTIVE)]
    keep = {r["id"] for r in sorted(done, key=lambda r: -r["start"])[:20]}
    d["runs"] = [r for r in d["runs"] if r["state"] in ("scheduled", *ACTIVE) or r["id"] in keep or r.get("owed")]
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
         # treasure and archery can gather everyone at a spot first (hide and seek always gathers at its area)
         "gather": gather.clean_spot(body.get("gather")) if kind in ("treasure", "archery") else None,
         "optin": bool(body.get("optin"))}          # players choose to join; off: everyone online plays
    if kind == "hideseek":
        r.update(area={**_point(body.get("center"), "middle of the area"), "r": round(_num(body.get("radius"), 10, 200, 40))},
                 hide_secs=int(_num(body.get("hide_secs"), 15, 300, 60)), minutes=int(_num(body.get("minutes"), 2, 30, 6)),
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
                 underwater=bool(body.get("underwater")))
        if not r["items"]:
            raise ValueError("Put something in the treasure chest")
    elif kind == "spleef":
        from . import spleef
        r.update(center=_point(body.get("center"), "spot for the arena"), **spleef.settings(body, _num))
        r["name"] = "Team spleef" if r["teams"] else "Spleef"
    else:
        mode = body.get("mode") if body.get("mode") in ("bullseye", "points", "horse") else "bullseye"
        word = "".join(c for c in str(body.get("word") or "HORSE").upper() if c.isalpha())[:10] or "HORSE"
        # timed modes run 30 seconds to 5 minutes (short rounds keep it lively); HORSE goes by turns
        minutes = (int(_num(body.get("minutes"), 2, 60, 30)) if mode == "horse"
                   else round(_num(body.get("seconds") or (float(body["minutes"]) * 60 if body.get("minutes") else None), 30, 300, 120)) / 60)
        r.update(target=_point(body.get("target"), "target"), place_target=bool(body.get("place_target")), mode=mode, word=word,
                 minutes=minutes, give_bow=bool(body.get("give_bow", True)),
                 spot_r=round(_num(body.get("spot_r"), 1, 5, 2), 1), min_ring=int(_num(body.get("min_ring"), 1, 15, 1)),
                 hot=bool(body.get("hot")) and mode == "points", **hotzone.settings(body),
                 hot_far=round(_num(body.get("hot_far"), HOT_NEAR + 4, 80, 40)),
                 name={"bullseye": "Archery: longest bullseye", "points": "Archery: most points", "horse": f"Archery: {word}"}[mode])
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
    if winners:
        fwshow.push(srv.id, srv.display_name, "challenge", winners[0], r["result"])


async def _countdown(srv, r: dict) -> None:
    """The boss bar for whatever phase the game is in, plus 10/5/1 minute warnings."""
    if not r.get("phase_ends"):
        return
    if r["game"] == "hideseek" and r["state"] == "hiding":
        title, total, color = "Hide!", r["hide_secs"], "green"
    else:
        title, total, color = r["name"], r["minutes"] * 60, {"hideseek": "red", "treasure": "yellow", "archery": "blue"}[r["game"]]
    if r.get("bar_title") != title:                   # new phase: a fresh bar
        await bossbar.hide(srv, r)
        r["bar_title"] = title
    await bossbar.show(srv, r, f"g_{r['id']}", title, r["phase_ends"], total, color=color)
    mins = bossbar.due_warning(r, r["phase_ends"], total) if r["state"] == "running" else None
    if mins:
        await _say(srv, [("★ ", "gold"), (f"{mins} minute{'s' if mins > 1 else ''} left in {r['name']}!", "yellow")])


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
    await _say(srv, [("★ ", "gold"), ("Treasure hunt! ", "yellow"), (f"A chest of treasure is hidden within {a['r']} blocks{' (it could be underwater!)' if r.get('underwater') else ''}. Watch your hotbar: it says how warm you are.", None)],
               "Treasure hunt!", "Find the chest")


async def _th_tick(srv, r: dict) -> None:
    now, c = time.time(), r["chest"]
    online = await entrants(srv, r)
    hint = now - r["started"] >= r["hint_after"] * 60 if r.get("started") else False
    near = {}
    for n in online:
        q = await _pos(srv, n)
        if not q:
            continue
        d = math.dist(q, (c["x"] + 0.5, c["y"], c["z"] + 0.5))
        near[n] = d
        word, color = next((w, col) for lim, w, col in _BANDS if d < lim)
        extra = f" · {_direction(c['x'] - q[0], c['z'] - q[2])}" if hint and d > 10 else ""
        await _bar(srv, n, f"{word}{extra} · {_fmt(r['phase_ends'] - now)} left", color)
    r["warmest"] = min(near, key=near.get) if near else None
    out = await _rcon(srv, f"execute in {r['dim']} run data get block {c['x']} {c['y']} {c['z']} Items")
    low = out.lower()
    # an emptied chest has no Items at all ("found no elements"); a broken one is no block entity
    taken = "[]" in out or "found no elements" in low or "not a block entity" in low
    if taken:
        finder = min(near, key=near.get) if near else None
        result = f"{finder} found the treasure!" if finder else "Someone found the treasure!"
        await _say(srv, [("★ ", "gold"), (result, "yellow")], "Treasure found!", finder or "")
        await _rcon(srv, f"execute in {r['dim']} run setblock {c['x']} {c['y']} {c['z']} {'minecraft:water' if r.get('underwater_spot') else 'minecraft:air'}")
        await _rcon(srv, f"execute in {r['dim']} run forceload remove {c['x']} {c['z']}")
        _finish(srv, r, result)
        if finder:
            fwshow.push(srv.id, srv.display_name, "challenge", finder, result)
    elif now >= r["phase_ends"]:
        await _say(srv, [("★ ", "gold"), ("Time's up! Nobody found the treasure. It was at ", "yellow"), (f"{c['x']}, {c['y']}, {c['z']}", "white"), (".", "yellow")], "Time's up", "The treasure is gone")
        await _rcon(srv, f"execute in {r['dim']} run setblock {c['x']} {c['y']} {c['z']} {'minecraft:water' if r.get('underwater_spot') else 'minecraft:air'}")
        await _rcon(srv, f"execute in {r['dim']} run forceload remove {c['x']} {c['z']}")
        _finish(srv, r, "Nobody found the treasure in time.")


# ------------------------------------------------------------------ archery
BULLSEYE = 13                                 # rings 13-15: dead centre (15) is near impossible from far away


MIN_DIST = 15                                 # points mode: closer than this scores nothing
SAME_SPOT = 3                                 # shots from within this of an earlier hit are "the same spot"


def _multiplier(dist: float) -> float:
    """Distance bonus from the 15-block line, smooth and uncapped: x1 at 15 blocks, x2 at 25,
    x4 at 35, x6.8 at 45, x14.1 at 65. Closer than 15: nothing."""
    if dist < MIN_DIST:
        return 0.0
    return round(1 + ((dist - MIN_DIST) / 10) ** 1.6, 1)


def _accuracy(ring: int) -> float:
    """How much the ring counts: an edge hit (1) is a fifth of a middling one, a dead-centre
    bullseye (15) three times: x0.2 at ring 1, x0.9 at 8, x2.2 at 13, x3 at 15."""
    return round(0.2 + 2.8 * ((max(1, min(15, ring)) - 1) / 14) ** 2, 2)


def _spot_factor(r: dict, who: str, pos) -> tuple[float, int]:
    """Hitting again and again from one spot halves each time: x1, x0.5, x0.25…"""
    spots = r.setdefault("spots", {}).setdefault(who, [])
    n = sum(1 for q in spots if math.hypot(q[0] - pos[0], q[2] - pos[2]) <= SAME_SPOT)
    return 0.5 ** n, n


def _ring_points(ring: int, dist: float, extra: float = 1.0) -> int:
    return round(10 * _accuracy(ring) * _multiplier(dist) * extra)


# Bullseyes (rings 13-15) are announced by how far they came from: (from blocks, stars, words, colour, sound)
_TIERS = [(60, "★★★★ ", "LEGENDARY SHOT! ", "red!", "minecraft:ui.toast.challenge_complete"),
          (45, "★★★ ", "AMAZING SHOT! ", "light_purple!", "minecraft:entity.player.levelup"),
          (30, "★★ ", "Great shot! ", "gold!", "minecraft:entity.firework_rocket.twinkle"),
          (0, "★ ", "Bullseye! ", "green", "minecraft:entity.experience_orb.pickup")]
_PLAIN = (0, "≫ ", "", "aqua", "")


def _tier(ring: int, dist: float) -> tuple:
    if ring < BULLSEYE:
        return _PLAIN
    return next(t for t in _TIERS if dist >= t[0])


def _popup_parts(ring: int, d: float, pts: int, hot: float = 1, repeat: int = 0) -> list:
    """Above the shooter's hotbar: "+48  ring 12 · 31 m  x2.2 aim x3.1 distance"."""
    if d < MIN_DIST:
        return [(f"Ring {ring} from {d:.0f} m: too close (under {MIN_DIST} blocks), no points", "gray")]
    _f, stars, words, color, _snd = _tier(ring, d)
    parts = [(f"+{pts}", "yellow!"), (f"  {stars}{words}" if ring >= BULLSEYE else "  ", color), (f"ring {ring} · {d:.0f} m", "white"),
             (f"  ×{_accuracy(ring):g} aim ×{_multiplier(d):g} distance", "gray")]
    if hot > 1:
        parts.append((f" ×{hot:g} ♨", "red!"))
    if repeat:
        parts.append((f" ×{0.5 ** repeat:g} same spot: move!", "red"))
    return parts


def _hit_parts(who: str, ring: int, d: float, pts: int, total: int, hot: float = 1, repeat: int = 0) -> list:
    _f, stars, words, color, _snd = _tier(ring, d)
    parts = [(stars, color), (words, color), (who, "aqua"), (f": ring {ring} from {d:.0f} blocks", "white")]
    if d < MIN_DIST:
        return parts + [(f"  too close (under {MIN_DIST} blocks): no points", "gray")]
    parts.append((f"  ×{_accuracy(ring):g} aim ×{_multiplier(d):g} distance", "gray"))
    if hot > 1:
        parts.append((f" ×{hot:g} ♨", "red!"))
    if repeat:
        parts.append((f" ×{0.5 ** repeat:g} same spot", "red"))
    parts.append((f"  +{pts}", "yellow!" if ring >= BULLSEYE else "yellow"))
    parts.append((f" ({total})", "gray"))
    return parts


HOT_R = 3                                     # how big an archery hot zone is (blocks from its middle)
HOT_NEAR = MIN_DIST + HOT_R                   # hot zones open at least this far from the target (all of it scores)


def _hot_tag(r: dict) -> str:
    return hotzone.tag(r)


def _in_hot(r: dict, pos, now: float) -> bool:
    return hotzone.inside(r, pos, now, HOT_R)


async def _hot_tick(srv, r: dict, now: float) -> None:
    """Hot zones on the ground somewhere around the target."""
    tx, ty, tz = r["target_c"]

    async def pick():
        ang = random.uniform(0, 2 * math.pi)
        far = random.uniform(HOT_NEAR, max(HOT_NEAR + 2, r.get("hot_far", 40)))
        x, z = int(math.floor(tx + math.cos(ang) * far)), int(math.floor(tz + math.sin(ang) * far))
        top = await hotzone.surface(srv, r["dim"], x, z, hotzone.tag(r) + "_m")
        y = top[0] if top else int(ty)
        return x, y, z, r["dim"], f"{round(far)} blocks {_direction(x - tx, z - tz)} of the target"

    await hotzone.tick(srv, r, now, r["started"], r["phase_ends"], HOT_R, "Hits from inside", pick)


async def _ar_start(srv, r: dict) -> None:
    t, dim = r["target"], r["dim"]
    tx, ty, tz = int(math.floor(t["x"])), int(math.floor(t["y"])), int(math.floor(t["z"]))
    if r["place_target"]:
        await _rcon(srv, f"execute in {dim} run setblock {tx} {ty} {tz} minecraft:target")
    names = r["entrants"]
    r["players"] = {n: {"letters": "", "best": 0.0, "points": 0, "hits": 0, "shots": 0} for n in names}
    r["target_c"] = [tx + 0.5, ty + 0.5, tz + 0.5]
    if r["give_bow"]:
        # a match bow with Infinity and one arrow: endless shots, nothing to pick up, and both
        # (tagged) are taken back at the end without touching anyone's own bows and arrows
        for n in (names if r.get("optin") else ["@a"]):
            await _rcon(srv, f"give {n} {_match_item(srv, 'bow')}")
            await _rcon(srv, f"give {n} {_match_item(srv, 'arrow')}")
    log_ = await _rcon(srv, "data get storage solstone:games log")
    from .fishpack import parse_game_log
    seen = parse_game_log(log_)
    r["seq"] = max((e["i"] for e in seen), default=0)
    r["pending"] = {}
    r["state"], r["phase_ends"] = "running", time.time() + r["minutes"] * 60
    goal = {"bullseye": f"Longest bullseye (ring {BULLSEYE}-15) wins.", "points": f"Points: aim (an edge hit x0.2, a dead-centre bullseye x3) times distance (x1 at {MIN_DIST} blocks, x2 at 25, x4 at 35, x14 at 65; closer than {MIN_DIST} scores nothing). Hits from the same spot count half each time: keep moving. Most points wins.",
            "horse": f"{r['word']}: make the setter's shot or take a letter."}[r["mode"]]
    await _say(srv, [("★ ", "gold"), (r["name"], "yellow"), (f" at the target at {tx}, {ty}, {tz}. {goal}", None)], "Archery!", goal[:40])
    if r["mode"] == "horse":
        r["order"] = sorted(names, key=str.lower)
        r["setter"], r["turn"], r["queue"], r["spot"] = 0, None, [], None
        await _horse_next_setter(srv, r, first=True)


async def _ar_events(srv, r: dict, names: dict[str, str]) -> list[tuple]:
    """New shots and hits, paired: (player, shot position, ring or 0 for a miss, distance)."""
    from .fishpack import parse_game_log
    log_ = parse_game_log(await _rcon(srv, "data get storage solstone:games log"))
    now = time.time()
    for e in sorted((e for e in log_ if e["i"] > r["seq"]), key=lambda e: e["i"]):
        r["seq"] = e["i"]
        who = names.get(e["uuid"].lower())
        if not who:
            continue
        p = r["pending"].setdefault(who, [])
        if e["k"] == "shot" and e["pos"]:
            p.append({"pos": list(e["pos"]), "at": now, "ring": 0})
        elif e["k"] == "hit":
            open_ = [s for s in p if not s["ring"]]
            if open_:
                open_[0]["ring"] = e["s"]
            else:                                   # a hit with no recorded shot: count it from where they are now
                p.append({"pos": list(e["pos"] or r["target_c"]), "at": now, "ring": e["s"]})
    done = []
    for who, shots in r["pending"].items():
        keep = []
        for s in shots:
            if s["ring"] or now - s["at"] > 4:         # an arrow lands within a few seconds
                d = math.dist(s["pos"], r["target_c"])
                done.append((who, s["pos"], s["ring"], d))
            else:
                keep.append(s)
        r["pending"][who] = keep
    return done


async def _ar_tick(srv, r: dict) -> None:
    names = {u.lower(): p["name"] for u, p in S.known_players(srv).items()}
    now = time.time()
    for who, pos, ring, d in await _ar_events(srv, r, names):
        if r.get("optin") and who not in r["players"]:      # didn't join: their arrows don't count
            continue
        st = r["players"].setdefault(who, {"letters": "", "best": 0.0, "points": 0, "hits": 0, "shots": 0})
        if r["mode"] == "horse":
            await _horse_shot(srv, r, who, pos, ring, d)
            continue
        st["shots"] += 1
        if ring:
            st["hits"] += 1
            if r["mode"] == "points":
                hot = r["hot_bonus"] if r.get("hot") and _in_hot(r, pos, now) else 1
                same, repeat = _spot_factor(r, who, pos) if d >= MIN_DIST else (1.0, 0)
                pts = _ring_points(ring, d, hot * same)
                st["points"] += pts
                if pts:
                    r["spots"][who].append([round(pos[0], 1), round(pos[1], 1), round(pos[2], 1)])
                _f, stars, words, _c, snd = _tier(ring, d)
                await hud.popup(srv, r, who, _popup_parts(ring, d, pts, hot, repeat))
                if ring >= BULLSEYE and d >= 30:              # great shots and up: everyone hears about it
                    await _say(srv, _hit_parts(who, ring, d, pts, st["points"], hot, repeat))
                if snd and d >= MIN_DIST:
                    await _rcon(srv, f"execute as @a at @s run playsound {snd} master @s ~ ~ ~ 1 1")
                if ring >= BULLSEYE and d >= 45:              # the big ones go in the activity feed
                    db.add_event(srv.id, now, "game", f"{who}: {words.strip().lower().rstrip('!')}, a bullseye from {d:.0f} blocks for {pts} points", who)
            elif ring >= BULLSEYE:
                best = d > st["best"]
                if best:
                    st["best"] = round(d, 1)
                await hud.popup(srv, r, who, [("BULLSEYE", "gold!"), (f" from {d:.1f} blocks" + ("  new best!" if best else ""), "white")])
                if best and st["best"] >= max(p["best"] for p in r["players"].values()):
                    await _say(srv, [("≫ ", "aqua"), (who, "aqua"), (" leads: BULLSEYE", "gold"), (f" from {d:.1f} blocks!", None)])
            else:
                await hud.popup(srv, r, who, f"Ring {ring} of 15 from {d:.0f} blocks (bullseye is {BULLSEYE}+)", "white")
        elif r["mode"] != "horse":
            await hud.popup(srv, r, who, "Miss", "gray")
    if r["mode"] == "horse":
        await _horse_tick(srv, r)
        return
    left = r["phase_ends"] - now
    if r.get("hot"):
        await _hot_tick(srv, r, now)
    hz = r.get("hot_zone") if r.get("hot") else None
    # the scores on the right; time on the boss bar; above the hotbar only the hot zone (and popups)
    if r["mode"] == "points":
        await hud.scores(srv, r, "🎯 Points", {n: p["points"] for n, p in r["players"].items()})
    else:
        await hud.scores(srv, r, "🎯 Longest bullseye", {n: int(p["best"] * 10) for n, p in r["players"].items()},
                         {n: (f"{p['best']:.1f} m" if p["best"] else "—") for n, p in r["players"].items()})
    for n in r["players"]:
        if hz and hz["on"]:
            hot_txt, in_it = hotzone.bar(r, await _pos(srv, n), HOT_R)
            await hud.status(srv, r, n, hot_txt.rstrip(" ·"), "red" if in_it else "gold")
    if left <= 0:
        key = "points" if r["mode"] == "points" else "best"
        top = max((p[key] for p in r["players"].values()), default=0)
        winners = [n for n, p in r["players"].items() if top and p[key] == top]
        result = (f"{' & '.join(winners)} won {r['name']} with " + (f"{top} points!" if key == "points" else f"a bullseye from {top:.1f} blocks!")) if winners else f"{r['name']} is over. No winner this time."
        await _ar_end(srv, r, result, winners)


def _match_item(srv, what: str) -> str:
    from .races import _new_text
    name = {"bow": "Match Bow", "arrow": "Match Arrow"}[what]
    label = f'"{name}"' if _new_text(srv) else f"'\"{name}\"'"
    if what == "bow":
        ench = '{"minecraft:infinity":1}' if _new_text(srv) else '{levels:{"minecraft:infinity":1}}'
        return (f"minecraft:bow[minecraft:custom_data={{solmatch:1b}},minecraft:unbreakable={{}},"
                f"minecraft:enchantments={ench},minecraft:item_name={label}] 1")
    return f"minecraft:arrow[minecraft:custom_data={{solmatch:1b}},minecraft:item_name={label}] 1"


async def _take_back_match_gear(srv) -> None:
    for item in ("minecraft:bow", "minecraft:arrow"):
        await _rcon(srv, f"clear @a {item}[minecraft:custom_data={{solmatch:1b}}]")


async def _ar_end(srv, r: dict, result: str, winners: list[str]) -> None:
    await hud.clear(srv, r)
    if r.get("give_bow"):
        await _take_back_match_gear(srv)
    if r.get("hot"):
        await _rcon(srv, f"kill @e[tag={_hot_tag(r)}]")
    await _say(srv, [("★ ", "gold"), (result, "yellow")], "Game over", (" & ".join(winners) + " won")[:40] if winners else "")
    if r["place_target"]:
        t = r["target"]
        await _rcon(srv, f"execute in {r['dim']} run setblock {int(math.floor(t['x']))} {int(math.floor(t['y']))} {int(math.floor(t['z']))} minecraft:air")
    _finish(srv, r, result)
    await _award(srv, r, winners)


def _alive(r: dict) -> list[str]:
    return [n for n in r["order"] if len(r["players"].get(n, {}).get("letters", "")) < len(r["word"])]


async def _horse_next_setter(srv, r: dict, first: bool = False) -> None:
    alive = _alive(r)
    if not first:
        r["setter"] = (r["setter"] + 1) % len(r["order"])
    while r["order"][r["setter"]] not in alive:
        r["setter"] = (r["setter"] + 1) % len(r["order"])
    setter = r["order"][r["setter"]]
    r["turn"], r["queue"], r["spot"], r["deadline"] = setter, [], None, time.time() + 60
    await _say(srv, [("★ ", "gold"), (setter, "aqua"), (" sets the shot: shoot from anywhere. Hit it and everyone has to match it!", None)], f"{setter}'s shot", "Set the shot")


async def _horse_shot(srv, r: dict, who: str, pos, ring: int, d: float) -> None:
    if who != r["turn"]:
        await _bar(srv, who, f"Wait your turn: it's {r['turn']}'s shot", "gray")
        return
    hit = ring >= r["min_ring"]
    if r["spot"] is None:                           # the setter
        if hit:
            r["spot"] = {"x": pos[0], "y": pos[1], "z": pos[2], "d": round(d, 1)}
            r["queue"] = [n for n in _alive(r) if n != who]
            await _say(srv, [("★ ", "gold"), (who, "aqua"), (f" made it from {d:.0f} blocks! Everyone else: same shot, same spot (follow the sparkles).", None)])
            await _horse_next_matcher(srv, r)
        else:
            await _say(srv, [("★ ", "gold"), (who, "aqua"), (" missed. Next setter...", None)])
            await _horse_next_setter(srv, r)
        return
    if math.hypot(pos[0] - r["spot"]["x"], pos[2] - r["spot"]["z"]) > r["spot_r"] + 0.5:
        await _bar(srv, who, "That wasn't from the spot. Go to the sparkles and shoot again", "red")
        return
    if hit:
        await _say(srv, [("✔ ", "green"), (who, "aqua"), (" made the shot!", None)])
    else:
        await _letter(srv, r, who)
    await _horse_next_matcher(srv, r)


async def _letter(srv, r: dict, who: str) -> None:
    st = r["players"][who]
    st["letters"] = r["word"][: len(st["letters"]) + 1]
    out = len(st["letters"]) >= len(r["word"])
    await _say(srv, [("✘ ", "red"), (who, "aqua"), (" missed: ", None), (st["letters"], "red")] + ([(" and they're out!", "red")] if out else []))


async def _horse_next_matcher(srv, r: dict) -> None:
    alive = _alive(r)
    if len(alive) <= 1:
        winners = alive
        await _ar_end(srv, r, f"{winners[0]} won {r['name']}!" if winners else f"{r['name']} is over.", winners)
        return
    r["queue"] = [n for n in r["queue"] if n in alive]
    if not r["queue"]:                                  # everyone's had a go: the setter sets again
        r["turn"], r["spot"], r["deadline"] = r["order"][r["setter"]], None, time.time() + 60
        if r["turn"] not in alive:
            await _horse_next_setter(srv, r)
        else:
            await _say(srv, [("★ ", "gold"), (r["turn"], "aqua"), (" sets the next shot.", None)])
        return
    r["turn"], r["deadline"] = r["queue"].pop(0), time.time() + 45
    await _say(srv, [("★ ", "gold"), (r["turn"], "aqua"), (f": your turn. Shoot from the spot ({r['spot']['d']:.0f} blocks).", None)], f"{r['turn']}'s turn", "Match the shot")


async def _horse_tick(srv, r: dict) -> None:
    now = time.time()
    if r["state"] != "running":
        return
    turn = r["turn"]
    if r["spot"]:
        sp = r["spot"]
        await _rcon(srv, f"execute in {r['dim']} run particle minecraft:happy_villager {sp['x']:.1f} {sp['y'] + 0.3:.1f} {sp['z']:.1f} 0.6 0.2 0.6 0 12 force")
        q = await _pos(srv, turn)
        if q:
            d = math.hypot(q[0] - sp["x"], q[2] - sp["z"])
            await _bar(srv, turn, "You're on the spot. Shoot!" if d <= r["spot_r"] else f"Go to the spot: {d:.0f} m {_direction(sp['x'] - q[0], sp['z'] - q[2])}", "green" if d <= r["spot_r"] else "yellow")
    else:
        await _bar(srv, turn, f"Set the shot · {int(r['deadline'] - now)} s", "yellow")
    standing = " · ".join(f"{n}: {r['players'][n]['letters'] or '-'}" for n in r["order"])
    for n in r["order"]:
        if n != turn:
            await _bar(srv, n, standing, "white")
    if now > r["deadline"]:                              # took too long: a miss
        if r["spot"] is None:
            await _say(srv, [("★ ", "gold"), (turn, "aqua"), (" ran out of time.", None)])
            await _horse_next_setter(srv, r)
        else:
            await _letter(srv, r, turn)
            await _horse_next_matcher(srv, r)
    if now >= r["phase_ends"] and r["state"] == "running":
        fewest = min(len(r["players"][n]["letters"]) for n in _alive(r))
        winners = [n for n in _alive(r) if len(r["players"][n]["letters"]) == fewest]
        await _ar_end(srv, r, f"Time's up! {' & '.join(winners)} won {r['name']} with the fewest letters.", winners)


# ------------------------------------------------------------------ the loop
_lock = asyncio.Lock()                  # tick and on_join both change the saved games


async def tick(servers: list) -> None:
    async with _lock:
        await _tick(servers)


async def on_join(srv, player: str) -> None:
    """Someone who was in a game when it ended (offline at the time): put them back now."""
    from . import spleef
    async with _lock:
        d = _load()
        for r in d["runs"]:
            p = (r.get("owed") or {}).get(player) if r["server"] == srv.id else None
            if p and await spleef.send_back(srv, player, p):
                del r["owed"][player]
                await _say(srv, [("★ ", "gold"), (f"{r['name']} ended while you were away, so you're back where you were.", "yellow")], who=player)
                _save(d)


async def _tick(servers: list) -> None:
    from . import gather, spleef
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
                if r.get("gather"):
                    r["gathered"] = await gather.send(srv, r["gather"], r["entrants"])
                await {"hideseek": _hs_start, "treasure": _th_start, "archery": _ar_start, "spleef": spleef.start}[r["game"]](srv, r)
            elif srv and srv.rcon_conf() and 0 < r["start"] - now <= gather.LEAD:
                moved = r.get("gather") or r["game"] in ("hideseek", "spleef")
                who = await entrants(srv, r) if r.get("optin") else None
                await gather.lead_in(srv, r, now, r["name"], "you'll be teleported there" if moved else "", who)
            else:
                continue
            changed = True
        elif srv:
            try:
                await {"hideseek": _hs_tick, "treasure": _th_tick, "archery": _ar_tick, "spleef": spleef.tick}[r["game"]](srv, r)
                if r["game"] == "spleef":
                    pass                             # rounds, not a clock: no countdown bar
                elif r["state"] in ACTIVE:
                    await _countdown(srv, r)
                else:
                    await bossbar.hide(srv, r)
            except Exception:
                log.exception("game %s failed", r["id"])
            changed = True
        if srv and r["state"] not in ACTIVE and r.get("gathered"):
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
    if r["state"] in ACTIVE and r["game"] == "spleef":
        from . import spleef
        await spleef.cancel(srv, r)
    elif r["state"] in ACTIVE:
        await bossbar.hide(srv, r)
        if r["game"] == "hideseek":
            await _hs_cleanup(srv, r)
        elif r["game"] == "treasure" and r.get("chest"):
            c = r["chest"]
            await _rcon(srv, f"execute in {r['dim']} run setblock {c['x']} {c['y']} {c['z']} {'minecraft:water' if r.get('underwater_spot') else 'minecraft:air'}")
            await _rcon(srv, f"execute in {r['dim']} run forceload remove {c['x']} {c['z']}")
        elif r["game"] == "archery":
            await hud.clear(srv, r)
            if r.get("give_bow"):
                await _take_back_match_gear(srv)
            if r.get("hot"):
                await _rcon(srv, f"kill @e[tag={_hot_tag(r)}]")
            if r.get("place_target"):
                t = r["target"]
                await _rcon(srv, f"execute in {r['dim']} run setblock {int(math.floor(t['x']))} {int(math.floor(t['y']))} {int(math.floor(t['z']))} minecraft:air")
        await _say(srv, [("★ ", "gold"), (f"{r['name']} was called off.", "yellow")])
    if was_live:
        r["state"] = "cancelled"
        if r.get("gathered"):
            from . import gather
            gather.come_home(srv, r.pop("gathered"), r["name"])
    elif not r.get("owed"):                          # removing a finished one (kept while it still owes someone a trip back)
        d["runs"] = [x for x in d["runs"] if x["id"] != rid]
    _save(d)
    return True


async def target_under(srv, player: str) -> dict:
    """The block a player is standing on, if it's a target (to use an archery range you built)."""
    q = await _pos(srv, check_name(player))
    if not q:
        raise ValueError(f"Couldn't find {player}. Are they online?")
    x, y, z = int(math.floor(q[0])), int(math.floor(q[1] - 0.5)), int(math.floor(q[2]))
    out = await _rcon(srv, f"execute if block {x} {y} {z} minecraft:target")
    return {"x": x, "y": y, "z": z, "is_target": "passed" in out.lower()}


def live(sid: str) -> list[dict]:
    """Running games for the status page and TV."""
    out = []
    for r in _load()["runs"]:
        if r["server"] != sid or r["state"] not in ACTIVE:
            continue
        name, emoji = KINDS[r["game"]]
        rows, sub = [], ""
        if r["game"] == "hideseek":
            order = {"seeker": 0, "hider": 1, "found": 2}
            label = {"seeker": "seeking", "hider": "hidden" if r["state"] != "hiding" else "hiding", "found": "found"}
            rows = [{"name": n, "value": label.get(p["role"], p["role"])} for n, p in sorted(r["players"].items(), key=lambda kv: (order.get(kv[1]["role"], 3), kv[0].lower()))]
            hidden = sum(1 for p in r["players"].values() if p["role"] == "hider")
            sub = "Hiders are hiding..." if r["state"] == "hiding" else f"{hidden} still hidden"
        elif r["game"] == "spleef":
            from . import spleef
            rows, sub = spleef.live_rows(r)
            if r["state"] == "countdown":
                sub = f"Round {r.get('round', 1)} starting... · best of {r['best_of']}"
        elif r["game"] == "treasure":
            sub = "Find the hidden chest"
            if r.get("warmest"):
                rows = [{"name": r["warmest"], "value": "closest"}]
        elif r["game"] == "archery":
            mode = r.get("mode")
            if mode == "horse":
                rows = [{"name": n, "value": p["letters"] or "-", "note": "out" if len(p["letters"]) >= len(r["word"]) else ""} for n, p in r["players"].items()]
                sub = f"Spell {r['word']} and you're out"
            else:
                key = "points" if mode == "points" else "best"
                ranked = sorted(r["players"].items(), key=lambda kv: (-kv[1][key], kv[0].lower()))
                rows = [{"name": n, "value": f"{p['points']} pts" if key == "points" else (f"{p['best']:.1f} m" if p["best"] else "-"),
                         "note": f"{p['hits']}/{p['shots']} hits"} for n, p in ranked]
                sub = "Most points" if key == "points" else "Longest bullseye"
                hz = r.get("hot_zone") if r.get("hot") else None
                if hz and hz["on"]:
                    sub += f" · 🔥 hot zone open ×{r['hot_bonus']:g}"
        out.append({"id": f"g-{r['id']}", "emoji": emoji, "title": r["name"] or name, "sub": sub, "ends_at": r.get("phase_ends"),
                    "rows": rows[:10], "empty": ""})
    return out


def banners(sid: str | None) -> list[dict]:
    out = []
    for r in _load()["runs"]:
        if sid and r["server"] != sid:
            continue
        emoji = KINDS[r["game"]][1]
        if r["state"] == "scheduled" and 0 < r["start"] - time.time() <= 3600:
            out.append({"id": f"g-{r['id']}", "kind": "challenge", "emoji": emoji, "style": "info", "text": r["name"], "detail": "Starting soon",
                        "countdown": r["start"], "done_text": "Starting!"})
        elif r["state"] in ACTIVE:
            if r["game"] == "hideseek":
                hiders = sum(1 for p in r["players"].values() if p["role"] == "hider")
                txt = f"Hide and seek: {'hiding...' if r['state'] == 'hiding' else f'{hiders} still hidden'}"
            elif r["game"] == "spleef":
                left = [n for n, p in r["players"].items() if p.get("alive")]
                txt = f"{r['name']}: round {r.get('round', 1)}, {len(left)} still standing"
            elif r["game"] == "archery" and r.get("mode") == "horse":
                txt = f"{r['name']}: " + " · ".join(f"{n} {p['letters'] or '-'}" for n, p in r["players"].items())
            else:
                txt = f"{r['name']} is on!"
            out.append({"id": f"g-{r['id']}", "kind": "challenge", "emoji": emoji, "style": "party", "text": txt, "detail": "",
                        "countdown": r.get("phase_ends"), "done_text": "Time's up!"})
        elif r["state"] == "done" and time.time() - (r.get("ended") or 0) < 1800 and r.get("result"):
            out.append({"id": f"gd-{r['id']}", "kind": "challenge", "emoji": "🏆", "style": "party", "text": r["result"], "detail": "", "countdown": None})
    return out

