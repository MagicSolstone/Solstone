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

import logging
import math
import random
import secrets
import time

from . import challenges, db, fwshow, settings_store
from . import servers as S
from .control import check_name, component
from .races import _direction, _fmt, _pos, _rcon

log = logging.getLogger("solstone.games")
SECTION = "games"
KINDS = {"hideseek": ("Hide and seek", "🙈"), "treasure": ("Treasure hunt", "💰"), "archery": ("Archery", "🎯")}
ACTIVE = ("countdown", "hiding", "running")


# ------------------------------------------------------------------ storage
def _load() -> dict:
    d = settings_store.load().get(SECTION) or {}
    return {"runs": list(d.get("runs") or []), "areas": list(d.get("areas") or [])}


def _save(d: dict) -> None:
    done = [r for r in d["runs"] if r["state"] not in ("scheduled", *ACTIVE)]
    keep = {r["id"] for r in sorted(done, key=lambda r: -r["start"])[:20]}
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
    prizes = [challenges.clean_prize(p) for p in (body.get("prizes") or [])[:3]]
    r = {"id": secrets.token_hex(4), "server": server, "game": kind, "name": KINDS[kind][0], "start": start, "state": "scheduled",
         "dim": "minecraft:overworld", "prizes": prizes, "players": {}, "said": [], "result": "", "log": []}
    if kind == "hideseek":
        r.update(area={**_point(body.get("center"), "middle of the area"), "r": round(_num(body.get("radius"), 10, 200, 40))},
                 hide_secs=int(_num(body.get("hide_secs"), 15, 300, 60)), minutes=int(_num(body.get("minutes"), 2, 30, 6)),
                 no_dig=bool(body.get("no_dig", True)), marco=bool(body.get("marco", True)), infect=bool(body.get("infect", True)),
                 find=round(_num(body.get("find"), 2, 6, 3), 1), seeker=(check_name(body["seeker"]) if body.get("seeker") else ""))
    elif kind == "treasure":
        if not any(prizes) and not body.get("items"):
            raise ValueError("Put something in the treasure chest")
        items = [challenges.clean_prize(p) for p in (body.get("items") or [])[:27]]
        r.update(area={**_point(body.get("center"), "middle of the area"), "r": round(_num(body.get("radius"), 20, 1000, 150))},
                 spot=_point(body["spot"], "spot") if body.get("spot") else None, items=[i for i in items if i],
                 minutes=int(_num(body.get("minutes"), 3, 60, 15)), hint_after=int(_num(body.get("hint_after"), 0, 60, 5)))
        if not r["items"]:
            raise ValueError("Put something in the treasure chest")
    else:
        mode = body.get("mode") if body.get("mode") in ("bullseye", "points", "horse") else "bullseye"
        word = "".join(c for c in str(body.get("word") or "HORSE").upper() if c.isalpha())[:10] or "HORSE"
        r.update(target=_point(body.get("target"), "target"), place_target=bool(body.get("place_target")), mode=mode, word=word,
                 minutes=int(_num(body.get("minutes"), 2, 60, 10 if mode != "horse" else 30)), give_bow=bool(body.get("give_bow", True)),
                 spot_r=round(_num(body.get("spot_r"), 1, 5, 2), 1), min_ring=int(_num(body.get("min_ring"), 1, 15, 1)),
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


def _finish(srv, r: dict, result: str) -> None:
    r["state"], r["result"], r["ended"] = "done", result, time.time()
    db.add_event(srv.id, time.time(), "game", result)


# ------------------------------------------------------------------ hide and seek
async def _hs_start(srv, r: dict) -> None:
    names, _src = await S.online_players(srv)
    if len(names) < 2:
        r["state"], r["result"] = "skipped", "Hide and seek needs at least two players online"
        return
    seeker = r["seeker"] if r["seeker"] in names else random.choice(names)
    a, dim = r["area"], r["dim"]
    for n in names:
        r["players"][n] = {"role": "seeker" if n == seeker else "hider", "gm": await _gamemode(srv, n)}
    await _rcon(srv, "team add solhs_h")
    await _rcon(srv, "team modify solhs_h nametagVisibility never")
    await _rcon(srv, "team modify solhs_h color green")
    await _rcon(srv, "team add solhs_s")
    await _rcon(srv, "team modify solhs_s color red")
    for n, p in r["players"].items():
        await _rcon(srv, f"team join {'solhs_s' if p['role'] == 'seeker' else 'solhs_h'} {n}")
        await _rcon(srv, f"execute in {dim} run tp {n} {a['x']} {a['y'] + 0.5} {a['z']}")
        if r["no_dig"]:
            await _rcon(srv, f"gamemode adventure {n}")
    await _rcon(srv, f"effect give {seeker} minecraft:blindness {r['hide_secs'] + 2} 0 true")
    await _rcon(srv, f"effect give {seeker} minecraft:slowness {r['hide_secs'] + 2} 255 true")
    r["state"], r["phase_ends"] = "hiding", time.time() + r["hide_secs"]
    hiders = [n for n, p in r["players"].items() if p["role"] == "hider"]
    await _say(srv, [("★ ", "gold"), ("Hide and seek! ", "yellow"), (seeker, "red"), (f" is seeking. Hiders: {', '.join(hiders)}. Stay within {a['r']} blocks"
                     + (", no digging or building" if r["no_dig"] else "") + ".", None)], "Hide!", f"{r['hide_secs']} seconds")
    await _say(srv, [("You're the seeker. Count to ", None), (str(r["hide_secs"]), "gold"), ("...", None)]
               + ([("  Type ", "gray"), ("marco", "aqua"), (" in chat to hear where they are.", "gray")] if r["marco"] else []), "You're it!", "Count to " + str(r["hide_secs"]), who=seeker)


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
            k = (a["r"] - 3) / d
            bx, bz = a["x"] + (q[0] - a["x"]) * k, a["z"] + (q[2] - a["z"]) * k
            await _rcon(srv, f"execute in {dim} run spreadplayers {bx:.1f} {bz:.1f} 0 1 false {n}")
            await _bar(srv, n, "Stay inside the play area!", "red")
        elif d > a["r"] - 5:
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


async def _hs_cleanup(srv, r: dict) -> None:
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


async def _th_start(srv, r: dict) -> None:
    a, dim = r["area"], r["dim"]
    if r.get("spot"):
        x, z = r["spot"]["x"], r["spot"]["z"]
    else:
        ang, rad = random.uniform(0, 2 * math.pi), a["r"] * math.sqrt(random.uniform(0.15, 1))
        x, z = a["x"] + math.cos(ang) * rad, a["z"] + math.sin(ang) * rad
    x, z = int(math.floor(x)), int(math.floor(z))
    await _rcon(srv, f"execute in {dim} run forceload add {x} {z}")
    tag = f"solth_{r['id']}"
    # a marker on the ground there tells us the height
    await _rcon(srv, f"execute in {dim} positioned {x} 320 {z} positioned over motion_blocking_no_leaves run summon minecraft:marker ~ ~ ~ {{Tags:[\"{tag}\"]}}")
    from .races import _POS
    m = _POS.search(await _rcon(srv, f"data get entity @e[tag={tag},limit=1] Pos"))
    await _rcon(srv, f"kill @e[tag={tag}]")
    y = int(float(m.group(2))) if m else int(r["area"]["y"])
    items = ",".join(f'{{Slot:{i}b,id:"{it["item"]}",count:{it["count"]}}}' for i, it in enumerate(r["items"][:27]))
    out = await _rcon(srv, f"execute in {dim} run setblock {x} {y} {z} minecraft:chest{{Items:[{items}]}} replace")
    if out and "changed" not in out.lower():
        r["chest_error"] = out[:160]
    r["chest"] = {"x": x, "y": y, "z": z}
    r["state"], r["phase_ends"] = "running", time.time() + r["minutes"] * 60
    await _say(srv, [("★ ", "gold"), ("Treasure hunt! ", "yellow"), (f"A chest of treasure is hidden within {a['r']} blocks. Watch your hotbar: it says how warm you are.", None)],
               "Treasure hunt!", "Find the chest")


async def _th_tick(srv, r: dict) -> None:
    now, c = time.time(), r["chest"]
    online, _src = await S.online_players(srv)
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
    out = await _rcon(srv, f"execute in {r['dim']} run data get block {c['x']} {c['y']} {c['z']} Items")
    low = out.lower()
    # an emptied chest has no Items at all ("found no elements"); a broken one is no block entity
    taken = "[]" in out or "found no elements" in low or "not a block entity" in low
    if taken:
        finder = min(near, key=near.get) if near else None
        result = f"{finder} found the treasure!" if finder else "Someone found the treasure!"
        await _say(srv, [("★ ", "gold"), (result, "yellow")], "Treasure found!", finder or "")
        await _rcon(srv, f"execute in {r['dim']} run setblock {c['x']} {c['y']} {c['z']} minecraft:air")
        await _rcon(srv, f"execute in {r['dim']} run forceload remove {c['x']} {c['z']}")
        _finish(srv, r, result)
        if finder:
            fwshow.push(srv.id, srv.display_name, "challenge", finder, result)
    elif now >= r["phase_ends"]:
        await _say(srv, [("★ ", "gold"), ("Time's up! Nobody found the treasure. It was at ", "yellow"), (f"{c['x']}, {c['y']}, {c['z']}", "white"), (".", "yellow")], "Time's up", "The treasure is gone")
        await _rcon(srv, f"execute in {r['dim']} run setblock {c['x']} {c['y']} {c['z']} minecraft:air")
        await _rcon(srv, f"execute in {r['dim']} run forceload remove {c['x']} {c['z']}")
        _finish(srv, r, "Nobody found the treasure in time.")


# ------------------------------------------------------------------ archery
def _ring_points(ring: int, dist: float) -> int:
    return round(ring * (1 + dist / 10))


async def _ar_start(srv, r: dict) -> None:
    t, dim = r["target"], r["dim"]
    tx, ty, tz = int(math.floor(t["x"])), int(math.floor(t["y"])), int(math.floor(t["z"]))
    if r["place_target"]:
        await _rcon(srv, f"execute in {dim} run setblock {tx} {ty} {tz} minecraft:target")
    names, _src = await S.online_players(srv)
    r["players"] = {n: {"letters": "", "best": 0.0, "points": 0, "hits": 0, "shots": 0} for n in names}
    r["target_c"] = [tx + 0.5, ty + 0.5, tz + 0.5]
    if r["give_bow"]:
        await _rcon(srv, "give @a minecraft:bow 1")
        await _rcon(srv, "give @a minecraft:arrow 64")
    log_ = await _rcon(srv, "data get storage solstone:games log")
    from .fishpack import parse_game_log
    seen = parse_game_log(log_)
    r["seq"] = max((e["i"] for e in seen), default=0)
    r["pending"] = {}
    r["state"], r["phase_ends"] = "running", time.time() + r["minutes"] * 60
    goal = {"bullseye": "Longest bullseye wins.", "points": "Points: the ring (1-15) times a bonus for distance. Most points wins.",
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
        st = r["players"].setdefault(who, {"letters": "", "best": 0.0, "points": 0, "hits": 0, "shots": 0})
        if r["mode"] == "horse":
            await _horse_shot(srv, r, who, pos, ring, d)
            continue
        st["shots"] += 1
        if ring:
            st["hits"] += 1
            if r["mode"] == "points":
                pts = _ring_points(ring, d)
                st["points"] += pts
                await _say(srv, [("≫ ", "aqua"), (who, "aqua"), (f": ring {ring} from {d:.0f} blocks", None), (f" +{pts} ({st['points']})", "yellow")])
            elif ring == 15:
                if d > st["best"]:
                    st["best"] = round(d, 1)
                await _say(srv, [("≫ ", "aqua"), (who, "aqua"), (": BULLSEYE", "gold"), (f" from {d:.1f} blocks!", None)])
            else:
                await _bar(srv, who, f"Ring {ring} of 15 from {d:.0f} blocks", "white")
    if r["mode"] == "horse":
        await _horse_tick(srv, r)
        return
    left = r["phase_ends"] - now
    board = sorted(r["players"].items(), key=lambda kv: -(kv[1]["points"] if r["mode"] == "points" else kv[1]["best"]))
    lead = board[0] if board and (board[0][1]["points"] or board[0][1]["best"]) else None
    for n in r["players"]:
        mine = r["players"][n]
        s = f"{mine['points']} points" if r["mode"] == "points" else f"best bullseye {mine['best']:.1f} m" if mine["best"] else "no bullseye yet"
        await _bar(srv, n, f"{s} · {_fmt(left)} left" + (f" · leader {lead[0]}" if lead and lead[0] != n else ""), "yellow")
    if left <= 0:
        key = "points" if r["mode"] == "points" else "best"
        top = max((p[key] for p in r["players"].values()), default=0)
        winners = [n for n, p in r["players"].items() if top and p[key] == top]
        result = (f"{' & '.join(winners)} won {r['name']} with " + (f"{top} points!" if key == "points" else f"a bullseye from {top:.1f} blocks!")) if winners else f"{r['name']} is over. No winner this time."
        await _ar_end(srv, r, result, winners)


async def _ar_end(srv, r: dict, result: str, winners: list[str]) -> None:
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
async def tick(servers: list) -> None:
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
                await {"hideseek": _hs_start, "treasure": _th_start, "archery": _ar_start}[r["game"]](srv, r)
            else:
                continue
            changed = True
        elif srv:
            try:
                await {"hideseek": _hs_tick, "treasure": _th_tick, "archery": _ar_tick}[r["game"]](srv, r)
            except Exception:
                log.exception("game %s failed", r["id"])
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
    d = _load()
    r = next((x for x in d["runs"] if x["id"] == rid and x["server"] == srv.id), None)
    if not r:
        return False
    if r["state"] in ACTIVE:
        if r["game"] == "hideseek":
            await _hs_cleanup(srv, r)
        elif r["game"] == "treasure" and r.get("chest"):
            c = r["chest"]
            await _rcon(srv, f"execute in {r['dim']} run setblock {c['x']} {c['y']} {c['z']} minecraft:air")
            await _rcon(srv, f"execute in {r['dim']} run forceload remove {c['x']} {c['z']}")
        elif r["game"] == "archery" and r.get("place_target"):
            t = r["target"]
            await _rcon(srv, f"execute in {r['dim']} run setblock {int(math.floor(t['x']))} {int(math.floor(t['y']))} {int(math.floor(t['z']))} minecraft:air")
        await _say(srv, [("★ ", "gold"), (f"{r['name']} was called off.", "yellow")])
    if r["state"] in ("scheduled", *ACTIVE):
        r["state"] = "cancelled"
    else:
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
            elif r["game"] == "archery" and r.get("mode") == "horse":
                txt = f"{r['name']}: " + " · ".join(f"{n} {p['letters'] or '-'}" for n, p in r["players"].items())
            else:
                txt = f"{r['name']} is on!"
            out.append({"id": f"g-{r['id']}", "kind": "challenge", "emoji": emoji, "style": "party", "text": txt, "detail": "",
                        "countdown": r.get("phase_ends"), "done_text": "Time's up!"})
        elif r["state"] == "done" and time.time() - (r.get("ended") or 0) < 1800 and r.get("result"):
            out.append({"id": f"gd-{r['id']}", "kind": "challenge", "emoji": "🏆", "style": "party", "text": r["result"], "detail": "", "countdown": None})
    return out

