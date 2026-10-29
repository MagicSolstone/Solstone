"""Events: a named group of challenges played one after another ("Fishing Fridays": three fishing contests,
then a race). The event holds the title, an optional description, the start, the break between challenges,
whether it repeats and whether players choose to join; its lineup is the challenges in order, each a contest,
race or game of its own (its own kind, length and prizes, and an optional note).

Each challenge in the lineup is made as an ordinary contest, race or game (tagged with the event), so it runs,
scores, alerts and is joined exactly as one on its own would be. The event keeps their times in step:

- contests have a set length, so their times are exact;
- races and games can end early or run long, so whatever comes after one starts a set break after it actually
  ends (the times shown until then are estimates), and never while it's still on.

A repeating event comes back as a whole once every challenge in it is over: a week (or a day) after it started.
"""
from __future__ import annotations

import logging
import re
import secrets
import time

from . import challenges, community, games, races, settings_store

log = logging.getLogger("solstone.eventgroups")

SECTION = "eventgroups"
TYPES = ("contest", "race", "game")
MAX_ITEMS = 20
FINISHED = ("done", "skipped", "cancelled")
KEEP_DONE = 20


def _load() -> dict:
    d = settings_store.load().get(SECTION) or {}
    return {"groups": list(d.get("groups") or [])}


def _save(d: dict) -> None:
    done = [g for g in d["groups"] if g["state"] in FINISHED]
    if len(done) > KEEP_DONE:                       # old finished events: only the latest are kept
        drop = {g["id"] for g in sorted(done, key=lambda g: g["start"])[:-KEEP_DONE]}
        d["groups"] = [g for g in d["groups"] if g["id"] not in drop]
    settings_store.save_section(SECTION, d)


def _text(v, n: int) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()[:n]


def _desc(v) -> str:
    lines = [ln.rstrip() for ln in str(v or "").replace("\r", "").split("\n")]
    return "\n".join(lines).strip()[:600]


# ------------------------------------------------------------------ the challenges themselves
def _store(kind: str):
    """(load, save, list key) for a kind of challenge."""
    return {"contest": (challenges._load, challenges._save, "items"), "race": (races._load, races._save, "runs"),
            "game": (games._load, games._save, "runs")}[kind]


def _find(kind: str, rid: str | None) -> dict | None:
    if not rid:
        return None
    load, _save_, key = _store(kind)
    return next((x for x in load()[key] if x["id"] == rid), None)


def _state(kind: str, it: dict | None) -> str:
    if it is None:
        return "missing"
    s = it["state"]
    if s in FINISHED:
        return "done"
    if kind == "contest":
        return "running" if s == "running" else "scheduled"
    return "scheduled" if s == "scheduled" else "running"


def length(kind: str, body: dict) -> float:
    """Minutes a challenge takes: exact for contests, an estimate for races and games."""
    def num(k, d):
        try:
            return float(body.get(k) or d)
        except (TypeError, ValueError):
            return d
    if kind == "contest":
        return max(1, min(240, int(num("minutes", 10))))
    if kind == "race":
        return num("minutes", 15)
    g = body.get("game")
    if g == "hideseek":
        return (num("hide_secs", 60) / 60 + num("minutes", 6)) * num("rounds", 1)
    if g == "treasure":
        return num("minutes", 15)
    if g == "archery":
        return 10 if body.get("mode") == "horse" else (num("seconds", 0) / 60 or num("minutes", 2))
    return 10                                         # spleef: rounds, not a clock


def title_of(kind: str, it: dict | None, body: dict) -> str:
    if it:
        return it["name"] + (" race" if kind == "race" else "")
    if kind == "contest":
        return _text(body.get("name"), 40) or challenges.KINDS.get(body.get("kind"), ("Contest",))[0]
    if kind == "race":
        c = next((x for x in races._load()["courses"] if x["id"] == body.get("course")), None)
        return f"{c['name'] if c else 'A'} race"
    return games.KINDS.get(body.get("game"), ("Game",))[0]


def emoji_of(kind: str, body: dict) -> str:
    if kind == "contest":
        return challenges.KINDS.get(body.get("kind"), ("", "🏆"))[1]
    if kind == "race":
        return "🏁"
    return games.KINDS.get(body.get("game"), ("", "🎲"))[1]


def _make(g: dict, item: dict, start: float) -> str:
    """Make one challenge of the lineup; returns its id."""
    body = {**item["body"], "start": start, "optin": g["optin"]}
    if item["type"] == "contest":
        made = challenges.create(g["server"], {**body, "repeat": "", "rounds": 1})
    elif item["type"] == "race":
        made = races.schedule(g["server"], body)
    else:
        made = games.create(g["server"], body)
    load, save, key = _store(item["type"])
    d = load()
    x = next(x for x in d[key] if x["id"] == made["id"])
    x.update(group=g["id"], gitem=item["id"], signup=signup_key(g, item["id"]))
    if item["type"] == "contest":
        x["config"] = {**x.get("config", {}), "repeat": ""}
    save(d)
    return made["id"]


def _drop(kind: str, rid: str) -> None:
    """Take a challenge that hasn't started off the list altogether."""
    load, save, key = _store(kind)
    d = load()
    d[key] = [x for x in d[key] if not (x["id"] == rid and x["state"] == "scheduled")]
    save(d)


def _set_start(kind: str, rid: str, start: float) -> None:
    load, save, key = _store(kind)
    d = load()
    x = next((x for x in d[key] if x["id"] == rid and x["state"] == "scheduled"), None)
    if x and abs(x["start"] - start) >= 1:
        x["start"] = start
        if kind == "contest" and x.get("config"):
            x["config"]["start"] = start
        save(d)


# ------------------------------------------------------------------ timing
def plan(g: dict, now: float | None = None) -> list[dict]:
    """Each challenge in order: when it starts and ends (actual, or planned), whether that's exact, and its state."""
    now = now or time.time()
    out, t, exact = [], g["start"], True
    for item in g["items"]:
        rid = (g.get("refs") or {}).get(item["id"])
        it = _find(item["type"], rid)
        st = _state(item["type"], it) if rid else "planned"
        mins = length(item["type"], item["body"])
        if st == "done":
            start = (it or {}).get("started_at") or (it or {}).get("started") or (it or {}).get("start") or t
            end = (g.get("ended") or {}).get(item["id"]) or (it or {}).get("ends_at") or now
        elif st == "running":
            start = (it.get("started_at") or it.get("started") or it["start"])
            end = it.get("ends_at") if item["type"] == "contest" else max(now, start + mins * 60)
            if item["type"] != "contest":
                exact = False
        else:
            start = t
            end = start + mins * 60
        out.append({"item": item, "ref": it, "rid": rid, "state": st, "start": start, "end": end, "exact": exact,
                    "minutes": mins})
        if st in ("planned", "scheduled") and item["type"] != "contest":
            exact = False                             # after a race or game the times are estimates
        t = end + g["gap"] * 60
    return out


# ------------------------------------------------------------------ the event
def clean(body: dict, server: str, cur: dict | None = None) -> dict:
    cur = cur or {}
    title = _text(body.get("title", cur.get("title")), 60)
    if not title:
        raise ValueError("Give the event a name")
    try:
        start = float(body.get("start") or cur.get("start") or 0) or time.time()
        gap = max(0, min(60, int(body.get("gap", cur.get("gap", 2)))))
    except (TypeError, ValueError) as e:
        raise ValueError("The start and the break need to be numbers") from e
    if start < time.time() - 60 and start != cur.get("start"):
        raise ValueError("That start time has already passed")
    rep = body.get("repeat", cur.get("repeat", ""))
    return {"server": server, "title": title, "desc": _desc(body.get("desc", cur.get("desc", ""))), "start": start, "gap": gap,
            "repeat": rep if rep in challenges.REPEATS else "", "optin": bool(body.get("optin", cur.get("optin", True)))}


def _get(d: dict, server: str, gid: str) -> dict:
    g = next((x for x in d["groups"] if x["id"] == gid and x["server"] == server), None)
    if not g:
        raise KeyError(gid)
    return g


def _started(g: dict) -> bool:
    return any(p["state"] in ("running", "done") for p in plan(g))


def _rebuild(g: dict) -> None:
    """Make (again) every challenge of the lineup that hasn't started, at its planned time; drop any no longer in it."""
    refs = g.setdefault("refs", {})
    keep = {i["id"] for i in g["items"]}
    for iid, rid in list(refs.items()):
        kind = next((i["type"] for i in g["items"] if i["id"] == iid), None) or g.get("kinds", {}).get(iid)
        it = _find(kind, rid) if kind else None
        if it is None or it["state"] == "scheduled":
            if it is not None:
                _drop(kind, rid)
            del refs[iid]
        elif iid not in keep:
            del refs[iid]                              # over (or on): leaves the lineup but stays in the history
    g["kinds"] = {i["id"]: i["type"] for i in g["items"]}
    for p in plan(g):
        if p["state"] == "planned":
            refs[p["item"]["id"]] = _make(g, p["item"], max(p["start"], time.time() + 2))


def create(server: str, body: dict) -> dict:
    d = _load()
    gid = secrets.token_hex(4)
    g = {**clean(body, server), "id": gid, "series": gid, "items": [], "refs": {}, "ended": {}, "state": "scheduled",
         "created": time.time()}
    for it in body.get("items") or []:
        g["items"].append(_item(it))
    d["groups"].append(g)
    if g["items"]:
        _rebuild(g)
    _save(d)
    return view(g)


def update(server: str, gid: str, body: dict) -> dict:
    d = _load()
    g = _get(d, server, gid)
    if g["state"] in FINISHED:
        raise ValueError("That event is over")
    conf = clean(body, server, g)
    if _started(g) and conf["start"] != g["start"]:
        raise ValueError("It has already started, so its start can't change")
    g.update(conf)
    _rebuild(g)
    _save(d)
    return view(g)


def _item(body: dict) -> dict:
    kind = body.get("type")
    if kind not in TYPES:
        raise ValueError("Pick a contest, race or game")
    inner = body.get("body") if isinstance(body.get("body"), dict) else {}
    inner = {k: v for k, v in inner.items() if k not in ("start", "optin", "repeat", "rounds", "gap")}
    # check it now, so a mistake shows up when it's added rather than when it's due
    if kind == "contest":
        challenges.clean({**inner, "start": time.time() + 3600}, "check")
    elif kind == "race" and not any(c["id"] == inner.get("course") for c in races._load()["courses"]):
        raise ValueError("Pick a course")
    elif kind == "game" and inner.get("game") not in games.KINDS:
        raise ValueError("Pick a game")
    return {"id": secrets.token_hex(4), "type": kind, "body": inner, "note": _text(body.get("note"), 160)}


def add_items(server: str, gid: str, body: dict) -> dict:
    """Add a challenge to the lineup (at the end, or after one), `count` times over (5 fishing contests in a row)."""
    d = _load()
    g = _get(d, server, gid)
    if g["state"] in FINISHED:
        raise ValueError("That event is over")
    try:
        count = max(1, min(MAX_ITEMS, int(body.get("count") or 1)))
    except (TypeError, ValueError):
        count = 1
    if len(g["items"]) + count > MAX_ITEMS:
        raise ValueError(f"An event can have up to {MAX_ITEMS} challenges")
    new = [_item(body) for _ in range(count)]
    at = next((i + 1 for i, x in enumerate(g["items"]) if x["id"] == body.get("after")), len(g["items"]))
    g["items"][at:at] = new
    _rebuild(g)
    _save(d)
    return view(g)


def change_item(server: str, gid: str, iid: str, body: dict) -> dict:
    """Change a challenge still to come (its settings, prizes or note), move it (step: -1 up, 1 down), copy or remove it."""
    d = _load()
    g = _get(d, server, gid)
    i = next((n for n, x in enumerate(g["items"]) if x["id"] == iid), None)
    if i is None:
        raise KeyError(iid)
    p = {x["item"]["id"]: x for x in plan(g)}
    if p[iid]["state"] in ("running", "done") and (body.get("remove") or body.get("body") or body.get("step")):
        raise ValueError("That one has already started")
    if body.get("remove"):
        g["items"].pop(i)
    elif body.get("copy"):
        if len(g["items"]) >= MAX_ITEMS:
            raise ValueError(f"An event can have up to {MAX_ITEMS} challenges")
        g["items"].insert(i + 1, {**g["items"][i], "id": secrets.token_hex(4)})
    elif body.get("step"):
        j = i + (1 if int(body["step"]) > 0 else -1)
        if 0 <= j < len(g["items"]) and p[g["items"][j]["id"]]["state"] in ("planned", "scheduled"):
            g["items"][i], g["items"][j] = g["items"][j], g["items"][i]
    else:
        cur = g["items"][i]
        if isinstance(body.get("body"), dict):
            cur["body"] = _item({"type": cur["type"], "body": {**cur["body"], **body["body"]}})["body"]
            rid = g["refs"].pop(iid, None)            # made again with the new settings
            if rid:
                _drop(cur["type"], rid)
        if "note" in body:
            cur["note"] = _text(body.get("note"), 160)
    _rebuild(g)
    _save(d)
    return view(g)


def remove(server: str, gid: str) -> bool:
    """Cancel an event still to come (its challenges that haven't started go); a finished one leaves the list."""
    d = _load()
    g = next((x for x in d["groups"] if x["id"] == gid and x["server"] == server), None)
    if not g:
        return False
    if g["state"] in FINISHED:
        d["groups"].remove(g)
    else:
        for item in g["items"]:
            rid = g["refs"].get(item["id"])
            it = _find(item["type"], rid)
            if it and it["state"] == "scheduled":
                _drop(item["type"], rid)
        g["state"] = "cancelled"
    _save(d)
    return True


def running_refs(server: str, gid: str) -> list[tuple[str, str]]:
    """Challenges of an event that are on now (to stop them when the event is called off)."""
    g = _get(_load(), server, gid)
    return [(p["item"]["type"], p["rid"]) for p in plan(g) if p["state"] == "running"]


# ------------------------------------------------------------------ keeping time
def busy() -> bool:
    """Something of an event on now (whatever follows it has to wait for it to end)."""
    return any(g["state"] == "running" for g in _load()["groups"])


def tick(now: float | None = None) -> None:
    """Keep the lineup's times in step with what has actually happened, and bring repeating events back."""
    now = now or time.time()
    d = _load()
    changed = False
    for g in d["groups"]:
        if g["state"] in FINISHED or not g["items"]:
            continue
        ps = plan(g, now)
        for p in ps:
            if p["state"] == "done" and p["item"]["id"] not in g.setdefault("ended", {}):
                it = p["ref"] or {}
                g["ended"][p["item"]["id"]] = it.get("ends_at") if p["item"]["type"] == "contest" and it.get("state") == "done" else now
                changed = True
        ps = plan(g, now)
        prev_on = False
        for p in ps:
            if p["state"] == "scheduled":
                want = max(p["start"], now + g["gap"] * 60) if prev_on else p["start"]
                _set_start(p["item"]["type"], p["rid"], want)
            prev_on = p["state"] == "running"
        state = ("done" if all(p["state"] in ("done", "missing") for p in ps)
                 else "running" if any(p["state"] in ("running", "done") for p in ps) else "scheduled")
        if state != g["state"]:
            g["state"], changed = state, True
        if state == "done" and g["repeat"]:
            nxt = {**g, "id": secrets.token_hex(4), "refs": {}, "ended": {}, "state": "scheduled",
                   "items": [{**i} for i in g["items"]]}
            step = challenges.REPEATS[g["repeat"]]
            nxt["start"] = g["start"] + step
            while nxt["start"] <= now + 60:
                nxt["start"] += step
            g["repeat"] = ""                          # this one's over; the next one carries on repeating
            d["groups"].append(nxt)
            try:
                _rebuild(nxt)
            except Exception:
                log.exception("couldn't set up the next %s", nxt["title"])
    if changed or any(g["state"] == "running" for g in d["groups"]):
        _save(d)


# ------------------------------------------------------------------ pages
def signup_key(g: dict, item_id: str) -> str:
    """"I'm coming!" for one challenge of one time the event is on (it doesn't move when the times shift)."""
    return community.event_key("group", f"{g.get('series') or g['id']}:{item_id}", g["start"])


def view(g: dict, now: float | None = None) -> dict:
    now = now or time.time()
    parts = []
    for p in plan(g, now):
        it, item = p["ref"], p["item"]
        parts.append({"id": item["id"], "type": item["type"], "title": title_of(item["type"], it, item["body"]),
                      "emoji": emoji_of(item["type"], item["body"]), "note": item["note"], "start": p["start"], "end": p["end"],
                      "minutes": round(p["minutes"], 1), "exact": p["exact"], "state": p["state"], "ref": p["rid"],
                      "result": (it or {}).get("result") or "", "key": signup_key(g, item["id"]), "body": item["body"],
                      "joined": None})
    end = max((x["end"] for x in parts), default=g["start"])
    return {**{k: g[k] for k in ("id", "server", "title", "desc", "start", "gap", "repeat", "optin", "state")},
            "end": end, "parts": parts}


def list_for(server: str) -> list[dict]:
    order = {"running": 0, "scheduled": 1}
    gs = [view(g) for g in _load()["groups"] if g["server"] == server]
    return sorted(gs, key=lambda g: (order.get(g["state"], 2), g["start"] if g["state"] in order else -g["start"]))


def tag(items: list[dict]) -> list[dict]:
    """For the Contests, Races and Games pages: the name of the event each one is part of."""
    titles = {g["id"]: g["title"] for g in _load()["groups"]}
    for it in items:
        if it.get("group") in titles:
            it["group_title"] = titles[it["group"]]
    return items
