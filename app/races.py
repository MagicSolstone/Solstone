"""Waypoint races: a start, checkpoints in order, a finish. All vanilla.

Courses are laid out on Solstone's map (or at a player's spot) and saved. When a race runs:
- each point gets a tall glowing glass column (a block_display, so no blocks are placed) with a
  floating label (a text_display) and particles; glowing outlines show through hills;
- the chunks under the points are force-loaded for the race, so the markers can always be
  removed afterwards;
- everyone is optionally teleported to the start, then 10-second countdown and GO;
- once a second each racer's position is read over RCON; reaching the next point in order
  (within its radius) records a split, plays a ding and moves them on; a line above the hotbar
  shows the next point's name, distance and direction;
- it ends when everyone has finished or the time limit is up; places go by finish time, then by
  checkpoints reached; prizes for 1st/2nd/3rd reuse the challenge prizes (held for anyone
  who's logged off).
"""
from __future__ import annotations

import json
import logging
import math
import re
import secrets
import time

from . import bossbar, challenges, db, fwshow, settings_store
from . import servers as S
from .control import check_name, clean_text, component
from .rcon import RconError

log = logging.getLogger("solstone.races")
SECTION = "races"
COUNTDOWN = 10
MAX_POINTS = 16
_POS = re.compile(r"\[\s*(-?[\d.]+)d?,\s*(-?[\d.]+)d?,\s*(-?[\d.]+)d?\s*\]")
_DIRS = ["south", "south-west", "west", "north-west", "north", "north-east", "east", "south-east"]


# ------------------------------------------------------------------ storage
def _load() -> dict:
    d = settings_store.load().get(SECTION) or {}
    return {"courses": list(d.get("courses") or []), "runs": list(d.get("runs") or [])}


def _save(d: dict) -> None:
    done = [r for r in d["runs"] if r["state"] not in ("scheduled", "countdown", "running")]
    keep = {r["id"] for r in sorted(done, key=lambda r: -r["start"])[:20]}
    d["runs"] = [r for r in d["runs"] if r["state"] in ("scheduled", "countdown", "running") or r["id"] in keep]
    settings_store.save_section(SECTION, d)


def _num(v, lo: float, hi: float, default: float) -> float:
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return default


def clean_course(body: dict, server: str) -> dict:
    pts = []
    for p in (body.get("points") or [])[:MAX_POINTS]:
        if not isinstance(p, dict):
            continue
        pts.append({"x": round(_num(p.get("x"), -3e7, 3e7, 0), 1), "y": round(_num(p.get("y"), -64, 320, 64), 1),
                    "z": round(_num(p.get("z"), -3e7, 3e7, 0), 1), "radius": round(_num(p.get("radius"), 2, 16, 4), 1),
                    "name": clean_text(str(p.get("name") or ""), 32) if str(p.get("name") or "").strip() else ""})
    if len(pts) < 2:
        raise ValueError("A course needs at least a start and a finish")
    name = str(body.get("name") or "").strip()
    return {"server": server, "name": clean_text(name, 40) if name else "Race", "points": pts,
            "dim": str(body.get("dim") or "minecraft:overworld")[:64]}


def courses_for(server: str) -> list[dict]:
    return [c for c in _load()["courses"] if c["server"] == server]


def runs_for(server: str) -> list[dict]:
    order = {"running": 0, "countdown": 0, "scheduled": 1}
    return sorted([r for r in _load()["runs"] if r["server"] == server], key=lambda r: (order.get(r["state"], 2), -r["start"]))


def save_course(server: str, body: dict, cid: str | None = None) -> dict:
    d = _load()
    c = clean_course(body, server)
    if cid:
        cur = next((x for x in d["courses"] if x["id"] == cid and x["server"] == server), None)
        if not cur:
            raise KeyError(cid)
        cur.update(c)
        c = cur
    else:
        c["id"] = secrets.token_hex(4)
        d["courses"].append(c)
    _save(d)
    return c


def delete_course(server: str, cid: str) -> bool:
    d = _load()
    n = len(d["courses"])
    d["courses"] = [c for c in d["courses"] if not (c["id"] == cid and c["server"] == server)]
    _save(d)
    return len(d["courses"]) < n


def schedule(server: str, body: dict) -> dict:
    d = _load()
    course = next((c for c in d["courses"] if c["id"] == body.get("course") and c["server"] == server), None)
    if not course:
        raise ValueError("Pick a course")
    start = _num(body.get("start"), 0, 1e11, 0) or time.time()
    if start < time.time() - 60:
        raise ValueError("That start time has already passed")
    prizes = [challenges.clean_prize(p) for p in (body.get("prizes") or [])[:3]]
    r = {"id": secrets.token_hex(4), "server": server, "course": course["id"], "name": course["name"],
         "points": course["points"], "dim": course.get("dim", "minecraft:overworld"),
         "start": start, "minutes": int(_num(body.get("minutes"), 2, 60, 15)), "teleport": bool(body.get("teleport", True)),
         "prizes": prizes, "state": "scheduled", "racers": {}, "results": [], "said": []}
    d["runs"].append(r)
    _save(d)
    return r


# ------------------------------------------------------------------ the game side
def _new_text(srv) -> bool:
    """1.21.5+ (and 26.x) take text components in NBT as SNBT; older versions as JSON strings."""
    v = srv.mc_version or ""
    nums = [int(x) for x in re.findall(r"\d+", v)[:3]] + [0, 0, 0]
    return nums[0] >= 26 or (nums[0] == 1 and (nums[1], nums[2]) >= (21, 5))


def _text_nbt(srv, text: str, color: str) -> str:
    if _new_text(srv):
        return "{text:" + json.dumps(text) + ",color:\"" + color + "\",bold:1b}"
    return "'" + json.dumps({"text": text, "color": color, "bold": True}).replace("'", "\\'") + "'"


def _label(r: dict, i: int) -> str:
    p = r["points"][i]
    last = len(r["points"]) - 1
    base = "Start" if i == 0 else "Finish" if i == last else f"Checkpoint {i} of {last - 1}"
    return f"{base}: {p['name']}" if p.get("name") and 0 < i < last else (p.get("name") or base)


async def _rcon(srv, cmd: str) -> str:
    try:
        return await srv.rcon(cmd) or ""
    except RconError as e:
        log.debug("race command failed on %s: %s", srv.id, e)
        return ""


def _tag(r: dict) -> str:
    return f"solrace_{r['id']}"


async def _place_markers(srv, r: dict) -> None:
    last = len(r["points"]) - 1
    dim = r.get("dim") or "minecraft:overworld"
    errors = []
    for i, p in enumerate(r["points"]):
        cx, cz = int(math.floor(p["x"])) >> 4, int(math.floor(p["z"])) >> 4
        await _rcon(srv, f"execute in {dim} run forceload add {cx * 16} {cz * 16}")
        glass, glow, color = (("white_stained_glass", 0xFFFFFF, "white") if i == 0 else
                              ("yellow_stained_glass", 0xF2C14E, "gold") if i == last else
                              ("lime_stained_glass", 0x55FF55, "green"))
        x, y, z = p["x"], p["y"], p["z"]
        out = await _rcon(srv, f"execute in {dim} run summon minecraft:block_display {x} {y} {z} "
                               f"{{Tags:[\"solrace\",\"{_tag(r)}\"],block_state:{{Name:\"minecraft:{glass}\"}},Glowing:1b,glow_color_override:{glow},"
                               f"view_range:8f,brightness:{{sky:15,block:15}},transformation:{{left_rotation:[0f,0f,0f,1f],right_rotation:[0f,0f,0f,1f],"
                               f"translation:[-0.5f,0f,-0.5f],scale:[1f,32f,1f]}}}}")
        if out and "summoned" not in out.lower():
            errors.append(out[:160])
        if i > 0:                       # a dot on everyone's locator bar (1.21.6+): an armor stand buried under the point
            # (not Invisible: invisible entities are left off the locator bar)
            await _rcon(srv, f"execute in {dim} run summon minecraft:armor_stand {x} {y - 2} {z} "
                             f"{{Tags:[\"solrace\",\"{_tag(r)}\",\"{_tag(r)}_wp{i}\"],Small:1b,Marker:1b,NoGravity:1b,Invulnerable:1b,Silent:1b,"
                             f"attributes:[{{id:\"minecraft:waypoint_transmit_range\",base:60000000d}}]}}")
            await _rcon(srv, f"waypoint modify @e[tag={_tag(r)}_wp{i},limit=1] color {'gold' if i == last else 'green'}")
        await _rcon(srv, f"execute in {dim} run summon minecraft:text_display {x} {y + 33} {z} "
                         f"{{Tags:[\"solrace\",\"{_tag(r)}\"],billboard:\"center\",see_through:1b,view_range:8f,"
                         f"background:1073741824,transformation:{{left_rotation:[0f,0f,0f,1f],right_rotation:[0f,0f,0f,1f],"
                         f"translation:[0f,0f,0f],scale:[5f,5f,5f]}},text:{_text_nbt(srv, _label(r, i), color)}}}")
    r["marker_error"] = errors[0] if errors else ""


async def _remove_markers(srv, r: dict) -> None:
    dim = r.get("dim") or "minecraft:overworld"
    await _rcon(srv, f"kill @e[tag={_tag(r)}]")
    for p in r["points"]:
        cx, cz = int(math.floor(p["x"])) >> 4, int(math.floor(p["z"])) >> 4
        await _rcon(srv, f"execute in {dim} run forceload remove {cx * 16} {cz * 16}")


async def _pos(srv, name: str) -> tuple[float, float, float] | None:
    m = _POS.search(await _rcon(srv, f"data get entity {name} Pos"))
    return (float(m.group(1)), float(m.group(2)), float(m.group(3))) if m else None


def _direction(dx: float, dz: float) -> str:
    # Minecraft: +z is south, +x is east
    ang = math.degrees(math.atan2(-dx, dz)) % 360
    return _DIRS[int((ang + 22.5) // 45) % 8]


def _fmt(sec: float) -> str:
    sec = max(0, int(sec))
    return f"{sec // 60}:{sec % 60:02d}"


async def _say(srv, r: dict, parts, title: str = "", sub: str = "") -> None:
    await _rcon(srv, f"tellraw @a {component(parts)}")
    if title:
        await _rcon(srv, "title @a times 5 30 10")
        if sub:
            await _rcon(srv, f"title @a subtitle {component([(sub, 'yellow')])}")
        await _rcon(srv, f"title @a title {component([(title, 'gold')])}")


async def _begin_countdown(srv, r: dict) -> None:
    await _place_markers(srv, r)
    s = r["points"][0]
    if r["teleport"]:
        await _rcon(srv, f"execute in {r.get('dim') or 'minecraft:overworld'} run tp @a {s['x']} {s['y'] + 0.5} {s['z']}")
    r["state"], r["go_at"] = "countdown", time.time() + COUNTDOWN
    await _say(srv, r, [("★ ", "gold"), (r["name"], "yellow"), (f" starts in {COUNTDOWN} seconds! Reach the checkpoints in order, then the finish.", None)],
               "Get ready", r["name"])


async def _go(srv, r: dict) -> None:
    names, _src = await S.online_players(srv)
    r["state"], r["started_at"] = "running", time.time()
    r["ends_at"] = r["started_at"] + r["minutes"] * 60
    r["racers"] = {n: {"next": 1, "splits": [], "finished": None} for n in names}
    await _say(srv, r, [("★ ", "gold"), ("GO!", "gold")], "GO!")
    await _rcon(srv, "execute as @a at @s run playsound minecraft:block.note_block.bell master @s ~ ~ ~ 1 1.4")
    db.add_event(srv.id, time.time(), "race", f"{r['name']} started")


async def _track(srv, r: dict) -> None:
    pts, last = r["points"], len(r["points"]) - 1
    online, _src = await S.online_players(srv)
    for n in online:                                   # joined mid-race: in, from the start
        r["racers"].setdefault(n, {"next": 1, "splits": [], "finished": None})
    now = time.time()
    for n, st in r["racers"].items():
        if st["finished"] or n not in online:
            continue
        pos = await _pos(srv, n)
        if not pos:
            continue
        st["at"] = [round(pos[0], 1), round(pos[2], 1)]
        tgt = pts[st["next"]]
        dx, dz, dy = tgt["x"] - pos[0], tgt["z"] - pos[2], tgt["y"] - pos[1]
        dist = math.hypot(dx, dz)
        if dist <= tgt["radius"] and abs(dy) <= 10:
            st["splits"].append(round(now - r["started_at"], 1))
            if st["next"] == last:
                st["finished"] = st["splits"][-1]
                place = sum(1 for o in r["racers"].values() if o["finished"] is not None)
                await _say(srv, r, [("★ ", "gold"), (n, "aqua"), (f" finished {_ordinal(place)} in {_fmt(st['finished'])}!", "yellow")])
                await _rcon(srv, f"execute as {n} at @s run playsound minecraft:ui.toast.challenge_complete master @s")
                done = f"Finished {_ordinal(place)}! {_fmt(st['finished'])}"
                await _rcon(srv, f"title {n} actionbar {component([(done, 'gold')])}")
                if place == 1:
                    fwshow.push(srv.id, srv.display_name, "challenge", n, f"{n} won {r['name']}")
                continue
            await _rcon(srv, f"execute as {n} at @s run playsound minecraft:entity.experience_orb.pickup master @s ~ ~ ~ 1 1.2")
            await _say(srv, r, [("✔ ", "green"), (n, "aqua"), (f" reached {_label(r, st['next'])} ({_fmt(st['splits'][-1])})", None)])
            st["next"] += 1
            tgt = pts[st["next"]]
            dx, dz = tgt["x"] - pos[0], tgt["z"] - pos[2]
            dist = math.hypot(dx, dz)
        nxt = f"Next: {_label(r, st['next'])} · {int(dist)} m {_direction(dx, dz)} · {_fmt(r['ends_at'] - now)} left"
        await _rcon(srv, f"title {n} actionbar {component([(nxt, 'yellow')])}")
    # checkpoints everyone has passed leave the locator bar, so the nearest dot is the next one
    todo = {st["next"] for st in r["racers"].values() if not st["finished"]}
    lowest = min(todo, default=last + 1)
    for i in range(1, lowest):
        if i not in r.setdefault("wp_gone", []):
            r["wp_gone"].append(i)
            await _rcon(srv, f"kill @e[tag={_tag(r)}_wp{i}]")
    # a tall beam of particles on every point still to be reached by someone, every other second
    if int(now) % 2 == 0:
        dim = r.get("dim") or "minecraft:overworld"
        for i in sorted(todo):
            p = pts[i]
            await _rcon(srv, f"execute in {dim} run particle minecraft:end_rod {p['x']} {p['y'] + 8} {p['z']} {p['radius'] / 3} 8 {p['radius'] / 3} 0.02 90 force")
            await _rcon(srv, f"execute in {dim} run particle minecraft:glow {p['x']} {p['y'] + 1} {p['z']} {p['radius'] / 2} 0.5 {p['radius'] / 2} 0 30 force")


def _ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def standings(r: dict) -> list[dict]:
    rows = []
    for n, st in (r.get("racers") or {}).items():
        rows.append({"name": n, "finished": st.get("finished"), "reached": st["next"] - 1 if not st.get("finished") else len(r["points"]) - 1,
                     "last_split": st["splits"][-1] if st.get("splits") else None, "at": st.get("at")})
    rows.sort(key=lambda x: (x["finished"] is None, x["finished"] or 0, -x["reached"], x["last_split"] or 1e9))
    return rows


async def _end(srv, r: dict) -> None:
    rows = standings(r)
    finished = [x for x in rows if x["finished"] is not None]
    r["results"] = rows
    r["state"] = "done"
    if finished:
        top = ", ".join(f"{_ordinal(i + 1)} {x['name']} ({_fmt(x['finished'])})" for i, x in enumerate(finished[:3]))
        r["result"] = f"{r['name']}: {top}"
    else:
        r["result"] = f"{r['name']} is over. Nobody reached the finish."
    await _say(srv, r, [("★ ", "gold"), (r["result"], "yellow")], finished[0]["name"] if finished else "Time's up", "wins " + r["name"] if finished else r["name"])
    for i, x in enumerate(finished[:3]):
        prize = (r.get("prizes") or [None, None, None])[i] if i < len(r.get("prizes") or []) else None
        if prize:
            await challenges.award(srv, x["name"], prize, f"came {_ordinal(i + 1)} in {r['name']}")
    await _remove_markers(srv, r)
    await bossbar.hide(srv, r)
    db.add_event(srv.id, time.time(), "race", r["result"], finished[0]["name"] if finished else None)


async def cancel(srv, rid: str) -> bool:
    d = _load()
    r = next((x for x in d["runs"] if x["id"] == rid and x["server"] == srv.id), None)
    if not r:
        return False
    if r["state"] in ("countdown", "running"):
        await _remove_markers(srv, r)
        await bossbar.hide(srv, r)
        await _say(srv, r, [("★ ", "gold"), (f"{r['name']} was called off.", "yellow")])
    if r["state"] in ("scheduled", "countdown", "running"):
        r["state"] = "cancelled"
    else:
        d["runs"] = [x for x in d["runs"] if x["id"] != rid]
    _save(d)
    return True


def busy() -> bool:
    return any(r["state"] in ("countdown", "running") or (r["state"] == "scheduled" and r["start"] - time.time() < 30)
               for r in _load()["runs"])


async def tick(servers: list) -> None:
    """Every second while a race is near or on; otherwise returns straight away."""
    d = _load()
    live = [r for r in d["runs"] if r["state"] in ("scheduled", "countdown", "running")]
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
                changed = True
            elif srv and srv.rcon_conf() and now >= r["start"]:
                await _begin_countdown(srv, r)
                changed = True
            elif srv and srv.rcon_conf() and 0 < r["start"] - now <= 60 and "1min" not in r["said"]:
                r["said"].append("1min")
                await _say(srv, r, [("★ ", "gold"), (f"{r['name']} starts in 1 minute!", "yellow")])
                changed = True
        elif r["state"] == "countdown" and srv:
            left = int(math.ceil(r["go_at"] - now))
            if left <= 0:
                await _go(srv, r)
            elif left <= 3 and f"cd{left}" not in r["said"]:
                r["said"].append(f"cd{left}")
                await _rcon(srv, "title @a times 0 20 0")
                await _rcon(srv, f"title @a title {component([(str(left), 'gold')])}")
                await _rcon(srv, "execute as @a at @s run playsound minecraft:block.note_block.hat master @s")
            changed = True
        elif r["state"] == "running" and srv:
            await _track(srv, r)
            await bossbar.show(srv, r, f"r_{r['id']}", r["name"], r["ends_at"], r["minutes"] * 60, color="green")
            mins = bossbar.due_warning(r, r["ends_at"], r["minutes"] * 60)
            if mins:
                await _say(srv, r, [("★ ", "gold"), (f"{mins} minute{'s' if mins > 1 else ''} left in {r['name']}!", "yellow")])
            if now >= r["ends_at"] or (r["racers"] and all(st["finished"] is not None for st in r["racers"].values())):
                await _end(srv, r)
            changed = True
    if changed:
        _save(d)


# ------------------------------------------------------------------ pages
def banners(sid: str | None, now: float | None = None) -> list[dict]:
    now = now or time.time()
    out = []
    for r in _load()["runs"]:
        if sid and r["server"] != sid:
            continue
        if r["state"] == "scheduled" and 0 < r["start"] - now <= 3600:
            out.append({"id": f"race-{r['id']}", "kind": "challenge", "emoji": "🏁", "style": "info", "text": f"{r['name']} race",
                        "detail": f"{len(r['points']) - 2} checkpoints · {r['minutes']} minutes", "countdown": r["start"], "done_text": "Get to the start!"})
        elif r["state"] in ("countdown", "running"):
            rows = standings(r)
            lead = rows[0] if rows else None
            last = len(r["points"]) - 1
            if lead and (lead["reached"] or lead["finished"] is not None):
                where = "finished" if lead["finished"] is not None else f"{lead['reached']}/{last}"
                txt = f"{r['name']}: {lead['name']} leads ({where})"
            else:
                txt = f"{r['name']}: racing now"
            out.append({"id": f"race-{r['id']}", "kind": "challenge", "emoji": "🏁", "style": "party", "text": txt, "detail": "",
                        "countdown": r.get("ends_at") or r.get("go_at"), "done_text": "Time's up!"})
        elif r["state"] == "done" and now - r["start"] < 1800 and r.get("results"):
            out.append({"id": f"raced-{r['id']}", "kind": "challenge", "emoji": "🏆", "style": "party", "text": r.get("result", ""), "detail": "", "countdown": None})
    return out


def live(sid: str) -> list[dict]:
    """The running race for the status page and TV: everyone's place and how far along they are."""
    out = []
    for r in _load()["runs"]:
        if r["server"] != sid or r["state"] not in ("countdown", "running"):
            continue
        last = len(r["points"]) - 1
        rows = [{"name": x["name"], "value": _fmt(x["finished"]) if x["finished"] is not None else f"{x['reached']}/{last}",
                 "note": "finished" if x["finished"] is not None else "checkpoints"} for x in standings(r)]
        sub = "Starting..." if r["state"] == "countdown" else f"{last - 1} checkpoints, then the finish"
        out.append({"id": f"race-{r['id']}", "emoji": "🏁", "title": f"{r['name']} race", "sub": sub,
                    "ends_at": r.get("ends_at") or r.get("go_at"), "rows": rows[:10], "empty": "Waiting for racers"})
    return out


def live_for_map(sid: str) -> dict | None:
    """The running race for the status map: points, and where each racer is up to."""
    for r in _load()["runs"]:
        if r["server"] == sid and r["state"] in ("countdown", "running"):
            return {"name": r["name"], "dim": r.get("dim"), "points": [{"x": p["x"], "z": p["z"], "label": _label(r, i)} for i, p in enumerate(r["points"])],
                    "racers": {n: {"next": st["next"], "finished": st["finished"]} for n, st in (r.get("racers") or {}).items()}}
    return None


async def player_spot(srv, name: str) -> dict:
    name = check_name(name)
    pos = await _pos(srv, name)
    if not pos:
        raise ValueError(f"Couldn't find {name}. Are they online?")
    return {"x": round(pos[0], 1), "y": round(pos[1], 1), "z": round(pos[2], 1)}
