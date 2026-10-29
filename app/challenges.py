"""Timed family challenges: "most fish in 10 minutes", with a prize for the winner.

Vanilla scoreboards do the counting. When a challenge starts, Solstone adds an objective for
each statistic it counts (minecraft.custom:minecraft.fish_caught, say). Those count from that
moment, live, for everyone, so there's no waiting on the game to save its stats files. A
"total" objective on the sidebar shows the race in the game, and Solstone keeps its own copy
of the scores for the web pages. At the end the winner (ties all win) gets the prize: right
away if they're on, otherwise the next time they join. Then the objectives are removed.

Everything runs on the recorder's 10-second guard tick.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import random
import re
import secrets
import time
from datetime import datetime

from . import bossbar, db, fwshow, hotzone, hud, settings_store
from . import servers as S
from .control import ITEM_RE, clean_text, component
from .rcon import RconError

log = logging.getLogger("solstone.challenges")

# key -> (label, emoji, unit (one, many), [criteria], divide-by for display)
KINDS: dict[str, tuple[str, str, tuple[str, str], list[str], int]] = {
    "fish": ("Fishing contest", "🎣", ("fish", "fish"), ["minecraft.custom:minecraft.fish_caught"], 1),
    "mobs": ("Monster hunt", "⚔️", ("monster", "monsters"), ["minecraft.custom:minecraft.mob_kills"], 1),
    "creepers": ("Creeper hunt", "💥", ("creeper", "creepers"), ["minecraft.killed:minecraft.creeper"], 1),
    "diamonds": ("Diamond rush", "💎", ("diamond ore", "diamond ores"),
                 ["minecraft.mined:minecraft.diamond_ore", "minecraft.mined:minecraft.deepslate_diamond_ore"], 1),
    "logs": ("Lumberjack", "🪓", ("log", "logs"), [f"minecraft.mined:minecraft.{w}_log" for w in
             ("oak", "birch", "spruce", "jungle", "acacia", "dark_oak", "mangrove", "cherry", "pale_oak")], 1),
    "stone": ("Mining marathon", "⛏️", ("block", "blocks"), [f"minecraft.mined:minecraft.{b}" for b in
              ("stone", "deepslate", "granite", "diorite", "andesite", "tuff", "netherrack")], 1),
    "breed": ("Farm fair", "🐑", ("animal bred", "animals bred"), ["minecraft.custom:minecraft.animals_bred"], 1),
    "jumps": ("Jump-a-thon", "🦘", ("jump", "jumps"), ["minecraft.custom:minecraft.jump"], 1),
    "walk": ("Explorer", "🧭", ("block walked", "blocks walked"),
             ["minecraft.custom:minecraft.walk_one_cm", "minecraft.custom:minecraft.sprint_one_cm"], 100),
    # These two need the Solstone Fishing pack (which keeps its own scoreboards) or the Tide
    # fishing mod (whose catches Solstone reads from the log and scores itself).
    "fish_points": ("Fishing tournament", "🏆", ("point", "points"), [], 1),
    "fish_heaviest": ("Biggest catch", "🐟", ("lb", "lb"), [], 1),
}
FISH_KINDS = {"fish_points": "solfish_cp", "fish_heaviest": "solfish_cb"}     # kind -> the pack's objective
ROD_KINDS = ("fish", "fish_points", "fish_heaviest")
# Kept so old contests still show properly, but no longer offered: not enough of a real race.
RETIRED = ("diamonds", "logs", "stone", "breed", "jumps", "walk")
SECTION = "challenges"
KEEP_DONE = 30                          # finished challenges kept for the history list
_SCORE = re.compile(r"has (-?\d+)")


# ------------------------------------------------------------------ storage
def _load() -> dict:
    d = settings_store.load().get(SECTION) or {}
    return {"items": list(d.get("items") or []), "gifts": list(d.get("gifts") or [])}


def _save(d: dict) -> None:
    done = [c for c in d["items"] if c["state"] in ("done", "skipped", "cancelled")]
    keep = {c["id"] for c in sorted(done, key=lambda c: -(c.get("ends_at") or c["start"]))[:KEEP_DONE]}
    d["items"] = [c for c in d["items"] if c["state"] in ("scheduled", "running") or c["id"] in keep]
    settings_store.save_section(SECTION, d)


def kinds() -> list[dict]:
    return [{"key": k, "label": v[0], "emoji": v[1], "unit": v[2][1], "pack": k in FISH_KINDS,
             "scale": 10 if k == "fish_heaviest" else 1, "retired": k in RETIRED} for k, v in KINDS.items()]


def _show(c: dict, n: int) -> str:
    """A score as people read it: '7 fish', '42 points', '16.2 lb'."""
    _l, _e, unit, _c, _d = KINDS[c["kind"]]
    if c["kind"] == "fish_heaviest":
        return f"{n / 10:g} lb"
    return f"{n} {unit[0] if n == 1 else unit[1]}"


def _prize(p) -> dict | None:
    if not isinstance(p, dict) or not str(p.get("item") or "").strip():
        return None
    item = str(p["item"]).strip().lower()
    if ":" not in item:
        item = f"minecraft:{item}"
    if not ITEM_RE.match(item):
        raise ValueError("That isn't a valid item id")
    try:
        count = max(1, min(6400, int(p.get("count") or 1)))
    except (TypeError, ValueError):
        count = 1
    label = str(p.get("name") or "").strip()
    return {"item": item, "count": count, "name": clean_text(label, 60) if label else ""}


def clean(body: dict, server: str) -> dict:
    kind = str(body.get("kind") or "")
    if kind not in KINDS or kind in RETIRED:
        raise ValueError("Pick what the challenge counts")
    try:
        start = float(body.get("start") or 0) or time.time()
        minutes = max(1, min(240, int(body.get("minutes") or 10)))
    except (TypeError, ValueError) as e:
        raise ValueError("Start time and length need to be numbers") from e
    if start < time.time() - 60:
        raise ValueError("That start time has already passed")
    from . import gather
    if start <= time.time() + 2:                         # "right now": a 10-second countdown first
        start = time.time() + gather.LEAD
    first = _prize(body.get("prize"))
    if not first:
        raise ValueError("Choose a prize for the winner")
    return {"server": server, "kind": kind, "name": clean_text(str(body.get("name") or KINDS[kind][0]), 40),
            "start": start, "minutes": minutes, "prize": first, "second": _prize(body.get("second")),
            "say": bool(body.get("say", True)),
            "gather": gather.clean_spot(body.get("gather")),
            "hot": bool(body.get("hot")) and kind == "fish_points", **hotzone.settings(body, 60, 30),
            "hot_far": int(max(16, min(96, float(body.get("hot_far") or 40)))),
            "lure": int(body.get("lure") or 0) if kind in ROD_KINDS and str(body.get("lure") or 0) in ("0", "3", "5") else 0,
            # Tide: everyone fishes at the same (baseline) level for the contest, whatever their own
            "fair": bool(body.get("fair", True)) and kind in ROD_KINDS,
            # "daily" / "weekly": when it's over, the same contest is put on again a day / a week after it started
            "repeat": body.get("repeat") if body.get("repeat") in REPEATS else ""}


REPEATS = {"daily": 86400, "weekly": 7 * 86400}


def _again(c: dict, d: dict, now: float) -> None:
    """A repeating contest is over (or was skipped): the same one again, a day or a week on from its start."""
    if not c.get("repeat") or c.get("repeated") or not c.get("config"):
        return
    c["repeated"] = True
    step = REPEATS[c["repeat"]]
    start = c["start"] + step
    while start <= now + 60:
        start += step
    d["items"].append({**c["config"], "start": start, "id": secrets.token_hex(4), "state": "scheduled", "scores": {}, "players": [],
                       "winners": [], "seconds": [], "objectives": [], "config": {**c["config"], "start": start}})


def list_for(server: str) -> list[dict]:
    items = [c for c in _load()["items"] if c["server"] == server]
    order = {"running": 0, "scheduled": 1}
    return sorted(items, key=lambda c: (order.get(c["state"], 2), c["start"] if c["state"] != "done" else -c["start"]))


def create(server: str, body: dict) -> dict:
    d = _load()
    conf = clean(body, server)
    c = {**conf, "id": secrets.token_hex(4), "state": "scheduled", "scores": {}, "players": [],
         "winners": [], "seconds": [], "objectives": [], "config": dict(conf)}
    d["items"].append(c)
    _save(d)
    return c


def update(server: str, cid: str, body: dict) -> dict:
    d = _load()
    c = next((x for x in d["items"] if x["id"] == cid and x["server"] == server), None)
    if not c:
        raise KeyError(cid)
    if c["state"] != "scheduled":
        raise ValueError("Only a challenge that hasn't started can be changed")
    conf = clean({**c.get("config", c), **body}, server)
    c.update(conf)
    c["config"] = dict(conf)
    _save(d)
    return c


def gifts_for(server: str) -> list[dict]:
    return [g for g in _load()["gifts"] if g["server"] == server]


# ------------------------------------------------------------------ the game side
async def _rcon(srv, cmd: str) -> str:
    try:
        return await srv.rcon(cmd) or ""
    except RconError as e:
        log.debug("challenge command failed on %s: %s", srv.id, e)
        return ""


def _objectives(c: dict) -> list[str]:
    if c["kind"] in FISH_KINDS:
        return [FISH_KINDS[c["kind"]]]
    return [f"sc{c['id'][:6]}{i}" for i in range(len(KINDS[c["kind"]][3]))]


def _total_obj(c: dict) -> str:
    return f"sc{c['id'][:6]}t"


def _rod(srv, lure: int) -> str:
    """The contest rod: Lure makes fish bite sooner (Lure V: within about 5 seconds; above V
    fish stop biting at all). Unbreakable, tagged so it can be taken back afterwards."""
    from .races import _new_text
    if _new_text(srv):
        return (f'minecraft:fishing_rod[minecraft:enchantments={{"minecraft:lure":{lure}}},minecraft:custom_data={{solrod:1b}},'
                f'minecraft:item_name="Contest Rod",minecraft:unbreakable={{}}]')
    return (f'minecraft:fishing_rod[minecraft:enchantments={{levels:{{"minecraft:lure":{lure}}}}},minecraft:custom_data={{solrod:1b}},'
            f"minecraft:item_name='\"Contest Rod\"',minecraft:unbreakable={{}}]")


ROD_MATCH = "minecraft:fishing_rod[minecraft:custom_data={solrod:1b}]"


async def _give_rod(srv, c: dict, player: str) -> None:
    if player.lower() in (c.setdefault("rodded", [])):
        return
    out = await _rcon(srv, f"give {player} {_rod(srv, c['lure'])}")
    if "gave" in out.lower() or not out:
        c["rodded"].append(player.lower())
        note = f"A Contest Rod (Lure {'III' if c['lure'] == 3 else 'V'}) for {c['name']}: the fish bite fast. It goes back when the contest ends."
        await _rcon(srv, f"tellraw {player} {component([('★ ', 'gold'), (note, 'yellow')])}")


async def _fair(srv, c: dict, who: str) -> None:
    """Tide's fair play for this contest: `who` (a name, or @a) fishes at the baseline level."""
    names = [n for n in (await S.online_players(srv))[0]] if who == "@a" else [who]
    for n in names:
        if n.lower() in {x.lower() for x in c.setdefault("faired", [])}:
            continue
        out = await _rcon(srv, f"fishinglevel fair {n} true")
        if "fair play on" in out.lower() or not out:
            c["faired"].append(n)


async def _start(srv, c: dict) -> None:
    from . import gather
    if c.get("gather"):                                  # everyone to the event's spot first (and home afterwards)
        c["gathered"] = await gather.send(srv, c["gather"])
    label, _emoji, unit, criteria, _div = KINDS[c["kind"]]
    made = []
    from . import tide
    c["tide"] = c["kind"] in ROD_KINDS and await asyncio.to_thread(tide.installed, srv)
    if c["kind"] in FISH_KINDS and c["tide"]:         # Tide: Solstone scores the catches it reads from the log
        c["best"], c["tscore"] = {}, {}
    elif c["kind"] in FISH_KINDS:                     # the pack's own objective, cleared for this contest
        made = _objectives(c)
        await _rcon(srv, f"scoreboard players reset * {made[0]}")
        c["best"] = {}
    if c["tide"] and c.get("fair"):
        await _fair(srv, c, "@a")
    for obj, crit in zip(_objectives(c) if c["kind"] not in FISH_KINDS else [], criteria, strict=True):
        out = await _rcon(srv, f"scoreboard objectives add {obj} {crit}")
        if out and ("unknown" in out.lower() or "invalid" in out.lower() or "error" in out.lower()):
            continue                     # a block this version doesn't have (pale oak before 1.21.4, say)
        made.append(obj)
    # One statistic counted as-is: the sidebar shows that objective itself, so the game keeps it
    # up to date instantly and Solstone doesn't have to send anything. Otherwise (several added
    # up, or shown as pounds) a total that Solstone writes when it changes.
    direct = made[0] if len(made) == 1 and KINDS[c["kind"]][4] == 1 and c["kind"] != "fish_heaviest" else None
    c["direct"] = direct
    if direct:
        await _rcon(srv, f"scoreboard objectives modify {direct} displayname {json.dumps(c['name'])}")
        await _rcon(srv, f"scoreboard objectives setdisplay sidebar {direct}")
    else:
        await _rcon(srv, f"scoreboard objectives add {_total_obj(c)} dummy {json.dumps(c['name'])}")
        await _rcon(srv, f"scoreboard objectives setdisplay sidebar {_total_obj(c)}")
    c["objectives"] = made
    c["shown"] = {}
    c["state"], c["started_at"] = "running", time.time()
    c["ends_at"] = c["started_at"] + c["minutes"] * 60
    if c.get("lure"):
        for n in (await S.online_players(srv))[0]:
            await _give_rod(srv, c, n)
    if c["say"]:
        prize = f"{c['prize']['count']} × {c['prize'].get('name') or c['prize']['item'].split(':')[1].replace('_', ' ')}"
        goal = {"fish_points": "Most fishing points", "fish_heaviest": "The heaviest fish"}.get(c["kind"], f"Most {unit[1]}")
        rules = f" has started! {goal} in {c['minutes']} minutes wins {prize}."
        if c["tide"] and c.get("fair"):
            rules += " Fair play: everyone fishes at the same level."
        await _rcon(srv, f"tellraw @a {component([('★ ', 'gold'), (c['name'], 'yellow'), (rules, None)])}")
        await _rcon(srv, "title @a times 10 60 20")
        await _rcon(srv, f"title @a title {component([('Go!', 'gold')])}")
        await _rcon(srv, f"title @a subtitle {component([(c['name'], 'yellow')])}")
    db.add_event(srv.id, time.time(), "challenge", f"{c['name']} started ({c['minutes']} minutes)")


async def _read_scores(srv, c: dict) -> None:
    names, _src = await S.online_players(srv)
    c["players"] = sorted({*c.get("players", []), *names}, key=str.lower)
    div = KINDS[c["kind"]][4]
    tscore = c.get("tscore")
    if tscore is not None:                                       # Tide: scored from the catches themselves
        c["players"] = sorted({*c["players"], *tscore}, key=str.lower)
    for p in c["players"]:
        total = 0
        if tscore is not None:
            total = tscore.get(p, 0)
        for obj in c["objectives"]:
            m = _SCORE.search(await _rcon(srv, f"scoreboard players get {p} {obj}"))
            total += int(m.group(1)) if m else 0
        c["scores"][p] = total // div
        if c.get("direct") or c.setdefault("shown", {}).get(p) == total // div:
            continue                                            # nothing to send: shown by the game, or unchanged
        c["shown"][p] = total // div
        await _rcon(srv, f"scoreboard players set {p} {_total_obj(c)} {total // div}")
        if c["kind"] == "fish_heaviest" and total:               # the sidebar says "16.2 lb", not 162
            await _rcon(srv, f"scoreboard players display numberformat {p} {_total_obj(c)} fixed {json.dumps(_show(c, total))}")


def _places(scores: dict[str, int]) -> tuple[list[str], list[str]]:
    ranked = sorted({v for v in scores.values() if v > 0}, reverse=True)
    first = [p for p, v in scores.items() if ranked and v == ranked[0]]
    second = [p for p, v in scores.items() if len(ranked) > 1 and v == ranked[1]]
    return sorted(first, key=str.lower), sorted(second, key=str.lower)


async def _give(srv, d: dict, player: str, prize: dict, why: str, online: set[str]) -> None:
    if player.lower() in online:
        out = await _rcon(srv, f"give {player} {prize['item']} {prize['count']}")
        if out and "gave" in out.lower():
            return
    d["gifts"].append({"server": srv.id, "player": player, "item": prize["item"], "count": prize["count"], "why": why, "at": time.time()})


async def award(srv, player: str, prize: dict, why: str) -> bool:
    """Give a prize now if they're on, otherwise hold it for their next join. True if given now."""
    d = _load()
    online = {n.lower() for n in (await S.online_players(srv))[0]}
    before = len(d["gifts"])
    await _give(srv, d, player, prize, why, online)
    _save(d)
    return len(d["gifts"]) == before


def clean_prize(p) -> dict | None:
    return _prize(p)


async def _finish(srv, c: dict, d: dict) -> None:
    await _read_scores(srv, c)
    label, _emoji, unit, _crit, _div = KINDS[c["kind"]]
    first, second = _places(c["scores"])
    c["winners"], c["seconds"] = first, (second if c.get("second") else [])
    online = {n.lower() for n in (await S.online_players(srv))[0]}
    for p in first:
        await _give(srv, d, p, c["prize"], f"won {c['name']}", online)
    for p in c["seconds"]:
        await _give(srv, d, p, c["second"], f"came second in {c['name']}", online)
    if first:
        n = c["scores"][first[0]]
        who = " and ".join(first)
        best = (c.get("best") or {}).get(first[0])
        weight = _lb_oz(best["lb"]) if best and c.get("tide") else f"{best['lb']} lb" if best else ""
        what = f"a {weight} {best['name']}" if c["kind"] == "fish_heaviest" and best else _show(c, n)
        c["result"] = f"{who} won {c['name']} with {what}!"
    else:
        c["result"] = f"{c['name']} is over. Nobody scored this time."
    if c["say"]:
        await _rcon(srv, f"tellraw @a {component([('★ ', 'gold'), (c['result'], 'yellow')])}")
        if first:
            await _rcon(srv, "title @a times 10 80 20")
            await _rcon(srv, f"title @a title {component([(' & '.join(first)[:30], 'gold')])}")
            await _rcon(srv, f"title @a subtitle {component([('wins ' + c['name'], 'yellow')])}")
    await _tidy(srv, c)
    c["state"] = "done"
    db.add_event(srv.id, time.time(), "challenge", c["result"], first[0] if first else None)
    if first:
        fwshow.push(srv.id, srv.display_name, "challenge", first[0], c["result"])


async def _tidy(srv, c: dict) -> None:
    """Remove this contest's objectives and countdown; the fishing pack's own objectives get
    their sidebar and name back."""
    await bossbar.hide(srv, c)
    if c.get("faired"):                                  # back to their own fishing level (whoever's away: on joining)
        online = {n.lower() for n in (await S.online_players(srv))[0]}
        for n in c["faired"]:
            if n.lower() in online:
                await _rcon(srv, f"fishinglevel fair {n} false")
        c["fair_owed"] = [n.lower() for n in c["faired"] if n.lower() not in online]
        c["faired"] = []
    if c.get("gathered"):                                # prizes are out: a countdown, then everyone goes home
        from . import gather
        gather.come_home(srv, c.pop("gathered"), c["name"])
    if c.get("hot"):
        await hotzone.clear(srv, c)
    if c.get("rodded"):                              # the contest rods go back; whoever's away hands theirs in on joining
        online = {n.lower() for n in (await S.online_players(srv))[0]}
        for n in c["rodded"]:
            if n in online:
                await _rcon(srv, f"clear {n} {ROD_MATCH}")
        c["rod_owed"] = [n for n in c["rodded"] if n not in online]
    for obj in [*c.get("objectives", []), _total_obj(c)]:
        if obj in FISH_KINDS.values():
            await _rcon(srv, "scoreboard objectives setdisplay sidebar")
            await _rcon(srv, f"scoreboard objectives modify {obj} displayname {json.dumps({'solfish_cp': 'Challenge points', 'solfish_cb': 'Heaviest catch'}[obj])}")
        else:
            await _rcon(srv, f"scoreboard objectives remove {obj}")


def _lb_oz(lb: float) -> str:
    from .tide import fmt_lb
    return fmt_lb(lb)


def busy() -> bool:
    """Something to look at every couple of seconds: a contest on, or about to start."""
    now = time.time()
    return any(c["state"] == "running" or (c["state"] == "scheduled" and c["start"] - now < 75) for c in _load()["items"])


async def cancel(srv, cid: str) -> bool:
    d = _load()
    c = next((x for x in d["items"] if x["id"] == cid and x["server"] == srv.id), None)
    if not c:
        return False
    if c["state"] == "running" and srv.rcon_conf():
        await _tidy(srv, c)
        if c["say"]:
            await _rcon(srv, f"tellraw @a {component([('★ ', 'gold'), (c['name'] + ' was called off.', 'yellow')])}")
    if c["state"] in ("scheduled", "running"):
        c["state"] = "cancelled"
    else:
        d["items"] = [x for x in d["items"] if x["id"] != cid]      # deleting a finished one from the history
    _save(d)
    return True


LEAD_SECS = 10                         # the countdown on screen before a contest starts (gather.LEAD)
FISH_HOT_R = 5                         # a fishing hot zone: cast into water within this many blocks of its middle
_lock = asyncio.Lock()                 # tick and on_catch both change the contest list


async def _fish_hot(srv, c: dict, now: float) -> None:
    """Fishing tournament hot zones: always on open water, somewhere near someone."""
    from .races import _pos

    async def pick():
        names = (await S.online_players(srv))[0]
        random.shuffle(names)
        for n in names[:2]:
            q = await _pos(srv, n)
            if not q:
                continue
            m = re.search(r'"([a-z0-9_.-]+:[a-z0-9_/.-]+)"', await _rcon(srv, f"data get entity {n} Dimension"))
            dim = m.group(1) if m else "minecraft:overworld"
            for _ in range(3):
                ang, far = random.uniform(0, 2 * math.pi), random.uniform(8, c.get("hot_far", 40))
                x, z = int(math.floor(q[0] + math.cos(ang) * far)), int(math.floor(q[2] + math.sin(ang) * far))
                top = await hotzone.surface(srv, dim, x, z, hotzone.tag(c) + "_m")
                if not top or top[1] != "water":
                    continue
                # enough water around it to fish in, not a puddle
                y = top[0] - 1
                around = [await _rcon(srv, f"execute in {dim} if block {x + dx} {y} {z + dz} minecraft:water") for dx, dz in ((3, 0), (-3, 0), (0, 3), (0, -3))]
                if sum(1 for a in around if "passed" in a.lower()) >= 3:
                    from .races import _direction
                    return x, top[0], z, dim, f"On the water {round(far)} blocks {_direction(x - q[0], z - q[2])} of {n}"
        return None

    await hotzone.tick(srv, c, now, c["started_at"], c["ends_at"], FISH_HOT_R, "Fish hooked inside", pick)
    if c.get("hot_zone", {}).get("on"):
        for n in (await S.online_players(srv))[0]:
            text, in_it = hotzone.bar(c, await _pos(srv, n), FISH_HOT_R)
            await _rcon(srv, f"title {n} actionbar {component([(text.rstrip(' ·') + ' (cast into it)' if not in_it else text.rstrip(' ·'), 'red' if in_it else 'gold')])}")


async def tick(servers: list) -> None:
    async with _lock:
        await _tick(servers)


async def _tick(servers: list) -> None:
    now = time.time()
    d = _load()
    if not d["items"]:
        return
    by_id = {s.id: s for s in servers}
    changed = False
    for c in d["items"]:
        srv = by_id.get(c["server"])
        if c["state"] == "scheduled":
            if now >= c["start"] + 300 or (srv is None and now >= c["start"]):
                c["state"], c["result"] = "skipped", "The server wasn't running with RCON at the start time"
                changed = True
            elif srv and srv.rcon_conf() and now >= c["start"]:
                await _start(srv, c)
                changed = True
            elif srv and srv.rcon_conf() and 0 < c["start"] - now <= LEAD_SECS:
                from . import gather
                await gather.lead_in(srv, c, now, c["name"], "you'll be teleported there" if c.get("gather") else "")
                changed = True
            elif srv and srv.rcon_conf() and c["say"] and 0 < c["start"] - now <= 60 and db.alert_once(f"ch-soon:{c['id']}"):
                await _rcon(srv, f"tellraw @a {component([('★ ', 'gold'), (c['name'] + ' starts in 1 minute!', 'yellow')])}")
        elif c["state"] == "running" and srv:
            if now >= c["ends_at"]:
                await _finish(srv, c, d)
            elif now - c.get("read_at", 0) >= 2:
                c["read_at"] = now
                await _read_scores(srv, c)
                await bossbar.show(srv, c, f"c_{c['id']}", c["name"], c["ends_at"], c["minutes"] * 60)
                mins = bossbar.due_warning(c, c["ends_at"], c["minutes"] * 60)
                if c["say"] and mins:
                    left = f"{mins} minute{'s' if mins > 1 else ''} left in {c['name']}!"
                    await _rcon(srv, f"tellraw @a {component([('★ ', 'gold'), (left, 'yellow')])}")
            if c.get("hot") and now < c["ends_at"]:
                try:
                    await _fish_hot(srv, c, now)
                except Exception:
                    log.exception("fishing hot zone failed")
            changed = True
        if c["state"] in ("done", "skipped") and c.get("repeat") and not c.get("repeated"):
            _again(c, d, now)                                # the next one (weekly fishing night, say)
            changed = True
    if changed:
        _save(d)


async def on_catch(srv, player: str, catch: dict) -> bool:
    """A fish from the fishing pack. During a fishing contest everyone hears about it (with
    where it puts them), and the biggest fish per player is kept for the result. True if a
    fishing contest is on."""
    async with _lock:
        return await _on_catch(srv, player, catch)


async def _on_catch(srv, player: str, catch: dict) -> bool:
    d = _load()
    c = next((x for x in d["items"] if x["server"] == srv.id and x["state"] == "running" and x["kind"] in FISH_KINDS), None)
    if not c:
        return False
    best = c.setdefault("best", {})
    if player not in best or catch["weight"] > best[player]["weight"]:
        best[player] = {k: catch[k] for k in ("name", "lb", "weight", "quality_name", "points")}
    hot = c.get("hot") and catch.get("pos") and hotzone.inside(c, catch["pos"], time.time(), FISH_HOT_R)
    tscore = c.get("tscore")
    if tscore is not None:                     # Tide: Solstone keeps the score (tenths of a pound for the heaviest)
        if c["kind"] == "fish_points":
            tscore[player] = tscore.get(player, 0) + round(catch["points"] * (c["hot_bonus"] if hot else 1))
        else:
            tscore[player] = max(tscore.get(player, 0), round(catch["weight"] * 10))
    _save(d)
    from .fishing import QUALITY_COLOR
    colour = QUALITY_COLOR.get(catch["quality"], "white")
    fish = catch["name"] if catch["quality"] == 1 else f"{catch['quality_name']} {catch['name']}"
    if c["kind"] == "fish_points" and hot:
        more = round(catch["points"] * (c["hot_bonus"] - 1))
        if tscore is None:
            await _rcon(srv, f"scoreboard players add {player} {FISH_KINDS['fish_points']} {more}")
        extra = f" · ♨ ×{c['hot_bonus']:g} hot zone · +{catch['points'] + more} points"
    elif c["kind"] == "fish_points":
        extra = f" · +{catch['points']} points"
    else:
        extra = " · new best!" if best[player]["weight"] == catch["weight"] else ""
    size = f" · {catch['lb']} lb" if tscore is None else f" · {_lb_oz(catch['lb'])}"
    # the catcher sees it above their hotbar; everyone hears about the good ones (the scores are on the sidebar)
    await hud.popup(srv, c, player, [(fish, colour), (size, "white"), (extra, "yellow")])
    if catch["quality"] >= 3 or catch.get("basic"):    # vanilla fish (the pack's weights): every catch in chat
        await _rcon(srv, f"tellraw @a {component([('≫ ', 'aqua'), (player, 'aqua'), (' caught ', None), (fish, colour), (size, None), (extra, 'yellow')])}")
    return True


async def on_join(srv, player: str) -> None:
    """Hand over prizes won while away; a contest rod for a contest that's on, or back if one ended while away."""
    d = _load()
    for c in d["items"]:
        if c["server"] != srv.id:
            continue
        if c["state"] == "running" and c.get("tide") and c.get("fair"):
            await _fair(srv, c, player)
            _save(d)
        elif player.lower() in (c.get("fair_owed") or []):
            await _rcon(srv, f"fishinglevel fair {player} false")
            c["fair_owed"].remove(player.lower())
            _save(d)
        if c["state"] == "running" and c.get("lure"):
            await _give_rod(srv, c, player)
            _save(d)
        elif player.lower() in (c.get("rod_owed") or []):
            await _rcon(srv, f"clear {player} {ROD_MATCH}")
            c["rod_owed"].remove(player.lower())
            _save(d)
    mine = [g for g in d["gifts"] if g["server"] == srv.id and g["player"].lower() == player.lower()]
    if not mine or not srv.rcon_conf():
        return
    for g in mine:
        out = await _rcon(srv, f"give {player} {g['item']} {g['count']}")
        if out and "gave" in out.lower():
            d["gifts"].remove(g)
            note = f"A prize for you: you {g['why']}!"
            await _rcon(srv, f"tellraw {player} {component([('★ ', 'gold'), (note, 'yellow')])}")
    _save(d)


# ------------------------------------------------------------------ pages
def live(sid: str) -> list[dict]:
    """Running contests for the status page and TV: the full scoreboard and when it ends."""
    out = []
    for c in _load()["items"]:
        if c["server"] != sid or c["state"] != "running":
            continue
        _label, emoji, unit, _crit, _div = KINDS.get(c["kind"], ("", "🏆", ("", ""), [], 1))
        ranked = sorted(((n, v) for n, v in (c.get("scores") or {}).items()), key=lambda kv: (-kv[1], kv[0].lower()))
        out.append({"id": f"ch-{c['id']}", "emoji": emoji, "title": c["name"], "sub": f"Most {unit[1]} wins" + (f" · 🔥 hot zone open ×{c['hot_bonus']:g}" if (c.get("hot_zone") or {}).get("on") else ""), "ends_at": c["ends_at"],
                    "rows": [{"name": n, "value": _show(c, v)} for n, v in ranked[:10]], "empty": "Nobody has scored yet"})
    return out


def banners(sid: str | None, now: float | None = None) -> list[dict]:
    """Status page and app banners: coming up within the hour, running (with the leader), just finished."""
    now = now or time.time()
    out = []
    for c in _load()["items"]:
        if sid and c["server"] != sid:
            continue
        label, emoji, unit, _crit, _div = KINDS.get(c["kind"], ("", "🏆", ("", ""), [], 1))
        if c["state"] == "scheduled" and 0 < c["start"] - now <= 3600:
            clock = datetime.fromtimestamp(c["start"], db.tz()).strftime("%I:%M %p").lstrip("0")
            out.append({"id": f"ch-{c['id']}", "kind": "challenge", "emoji": emoji, "style": "info", "text": f"{c['name']} at {clock}",
                        "detail": f"Most {unit[1]} in {c['minutes']} minutes wins", "countdown": c["start"], "done_text": "It's on!"})
        elif c["state"] == "running":
            first, _ = _places(c.get("scores") or {})
            n = c["scores"].get(first[0], 0) if first else 0
            lead = f"{' & '.join(first)} {'leads' if len(first) == 1 else 'lead'} with {_show(c, n)}" if first else "Nobody has scored yet"
            out.append({"id": f"ch-{c['id']}", "kind": "challenge", "emoji": emoji, "style": "party", "text": f"{c['name']}: {lead}",
                        "detail": "", "countdown": c["ends_at"], "done_text": "Time's up!", "scores": c.get("scores") or {}})
        elif c["state"] == "done" and c.get("winners") and now - (c.get("ends_at") or 0) < 1800:
            out.append({"id": f"chd-{c['id']}", "kind": "challenge", "emoji": "🏆", "style": "party", "text": c.get("result", ""),
                        "detail": "", "countdown": None})
    return out
