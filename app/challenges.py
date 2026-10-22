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

import json
import logging
import re
import secrets
import time
from datetime import datetime

from . import db, fwshow, settings_store
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
}
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
    return [{"key": k, "label": v[0], "emoji": v[1], "unit": v[2][1]} for k, v in KINDS.items()]


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
    if kind not in KINDS:
        raise ValueError("Pick what the challenge counts")
    try:
        start = float(body.get("start") or 0) or time.time()
        minutes = max(1, min(240, int(body.get("minutes") or 10)))
    except (TypeError, ValueError) as e:
        raise ValueError("Start time and length need to be numbers") from e
    if start < time.time() - 60:
        raise ValueError("That start time has already passed")
    first = _prize(body.get("prize"))
    if not first:
        raise ValueError("Choose a prize for the winner")
    return {"server": server, "kind": kind, "name": clean_text(str(body.get("name") or KINDS[kind][0]), 40),
            "start": start, "minutes": minutes, "prize": first, "second": _prize(body.get("second")),
            "say": bool(body.get("say", True))}


def list_for(server: str) -> list[dict]:
    items = [c for c in _load()["items"] if c["server"] == server]
    order = {"running": 0, "scheduled": 1}
    return sorted(items, key=lambda c: (order.get(c["state"], 2), c["start"] if c["state"] != "done" else -c["start"]))


def create(server: str, body: dict) -> dict:
    d = _load()
    c = {**clean(body, server), "id": secrets.token_hex(4), "state": "scheduled", "scores": {}, "players": [],
         "winners": [], "seconds": [], "objectives": []}
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
    c.update(clean({**c, **body}, server))
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
    return [f"sc{c['id'][:6]}{i}" for i in range(len(KINDS[c["kind"]][3]))]


def _total_obj(c: dict) -> str:
    return f"sc{c['id'][:6]}t"


async def _start(srv, c: dict) -> None:
    label, _emoji, unit, criteria, _div = KINDS[c["kind"]]
    made = []
    for obj, crit in zip(_objectives(c), criteria, strict=True):
        out = await _rcon(srv, f"scoreboard objectives add {obj} {crit}")
        if out and ("unknown" in out.lower() or "invalid" in out.lower() or "error" in out.lower()):
            continue                     # a block this version doesn't have (pale oak before 1.21.4, say)
        made.append(obj)
    await _rcon(srv, f"scoreboard objectives add {_total_obj(c)} dummy {json.dumps(c['name'])}")
    await _rcon(srv, f"scoreboard objectives setdisplay sidebar {_total_obj(c)}")
    c["objectives"] = made
    c["state"], c["started_at"] = "running", time.time()
    c["ends_at"] = c["started_at"] + c["minutes"] * 60
    if c["say"]:
        prize = f"{c['prize']['count']} × {c['prize'].get('name') or c['prize']['item'].split(':')[1].replace('_', ' ')}"
        rules = f" has started! Most {unit[1]} in {c['minutes']} minutes wins {prize}."
        await _rcon(srv, f"tellraw @a {component([('★ ', 'gold'), (c['name'], 'yellow'), (rules, None)])}")
        await _rcon(srv, "title @a times 10 60 20")
        await _rcon(srv, f"title @a title {component([('Go!', 'gold')])}")
        await _rcon(srv, f"title @a subtitle {component([(c['name'], 'yellow')])}")
    db.add_event(srv.id, time.time(), "challenge", f"{c['name']} started ({c['minutes']} minutes)")


async def _read_scores(srv, c: dict) -> None:
    names, _src = await S.online_players(srv)
    c["players"] = sorted({*c.get("players", []), *names}, key=str.lower)
    div = KINDS[c["kind"]][4]
    for p in c["players"]:
        total = 0
        for obj in c["objectives"]:
            m = _SCORE.search(await _rcon(srv, f"scoreboard players get {p} {obj}"))
            total += int(m.group(1)) if m else 0
        c["scores"][p] = total // div
        await _rcon(srv, f"scoreboard players set {p} {_total_obj(c)} {total // div}")


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
        c["result"] = f"{who} won {c['name']} with {n} {unit[0] if n == 1 else unit[1]}!"
    else:
        c["result"] = f"{c['name']} is over. Nobody scored this time."
    if c["say"]:
        await _rcon(srv, f"tellraw @a {component([('★ ', 'gold'), (c['result'], 'yellow')])}")
        if first:
            await _rcon(srv, "title @a times 10 80 20")
            await _rcon(srv, f"title @a title {component([(' & '.join(first)[:30], 'gold')])}")
            await _rcon(srv, f"title @a subtitle {component([('wins ' + c['name'], 'yellow')])}")
    for obj in [*c["objectives"], _total_obj(c)]:
        await _rcon(srv, f"scoreboard objectives remove {obj}")
    c["state"] = "done"
    db.add_event(srv.id, time.time(), "challenge", c["result"], first[0] if first else None)
    if first:
        fwshow.push(srv.id, srv.display_name, "challenge", first[0], c["result"])


async def cancel(srv, cid: str) -> bool:
    d = _load()
    c = next((x for x in d["items"] if x["id"] == cid and x["server"] == srv.id), None)
    if not c:
        return False
    if c["state"] == "running" and srv.rcon_conf():
        for obj in [*c.get("objectives", []), _total_obj(c)]:
            await _rcon(srv, f"scoreboard objectives remove {obj}")
        if c["say"]:
            await _rcon(srv, f"tellraw @a {component([('★ ', 'gold'), (c['name'] + ' was called off.', 'yellow')])}")
    if c["state"] in ("scheduled", "running"):
        c["state"] = "cancelled"
    else:
        d["items"] = [x for x in d["items"] if x["id"] != cid]      # deleting a finished one from the history
    _save(d)
    return True


async def tick(servers: list) -> None:
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
            elif srv and srv.rcon_conf() and c["say"] and 0 < c["start"] - now <= 60 and db.alert_once(f"ch-soon:{c['id']}"):
                await _rcon(srv, f"tellraw @a {component([('★ ', 'gold'), (c['name'] + ' starts in 1 minute!', 'yellow')])}")
        elif c["state"] == "running" and srv:
            if now >= c["ends_at"]:
                await _finish(srv, c, d)
            else:
                await _read_scores(srv, c)
                if c["say"] and 0 < c["ends_at"] - now <= 60 and db.alert_once(f"ch-1min:{c['id']}"):
                    await _rcon(srv, f"tellraw @a {component([('★ ', 'gold'), ('1 minute left in ' + c['name'] + '!', 'yellow')])}")
            changed = True
    if changed:
        _save(d)


async def on_join(srv, player: str) -> None:
    """Hand over prizes won while away."""
    d = _load()
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
            lead = f"{' & '.join(first)} {'leads' if len(first) == 1 else 'lead'} with {n} {unit[0] if n == 1 else unit[1]}" if first else "Nobody has scored yet"
            out.append({"id": f"ch-{c['id']}", "kind": "challenge", "emoji": emoji, "style": "party", "text": f"{c['name']}: {lead}",
                        "detail": "", "countdown": c["ends_at"], "done_text": "Time's up!", "scores": c.get("scores") or {}})
        elif c["state"] == "done" and c.get("winners") and now - (c.get("ends_at") or 0) < 1800:
            out.append({"id": f"chd-{c['id']}", "kind": "challenge", "emoji": "🏆", "style": "party", "text": c.get("result", ""),
                        "detail": "", "countdown": None})
    return out
