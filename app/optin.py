"""Choosing to take part: contests, races and games where players join in, instead of everyone online being in.

- Each event has a switch: players choose to join (new events), or everyone online takes part (as before).
- Joining: /trigger join in the game (any player can, no operator needed, nobody else sees it; it works from
  Bedrock too, typed). On Java the "/trigger join" in a message can be clicked. /trigger leave to change your mind.
  "I'm coming!" on the website counts too, once they're on the server.
- Joining opens a while before the start (an hour, to start) and closes when it starts, except contests, which
  can be joined until they end (their score counts from joining).
- Each event takes its own joining, so a night of back-to-back contests can be joined one at a time: /trigger join
  joins the next one you're not in yet.
- Countdown alerts in everyone's chat before each event (10, 5, 2, 1 minutes and 30 seconds, to start), and the
  next event when someone joins the server.

Only those who joined are teleported, get the contest rod, fish at the fair level, are scored, win prizes and
see the start on their screen. Admins write every message (Play → Contests → Messages), with the welcome
message's & colour codes and fill-ins, plus {event}, {left} ("5 minutes"), {time}, {count}, {join} and {leave}.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime

from . import community, db, settings_store, welcome

log = logging.getLogger("solstone.optin")

SECTION = "optin"
STATE = "optin_state"
JOIN, LEAVE = "join", "leave"                 # the trigger objectives: /trigger join, /trigger leave
ALERT_CHOICES = (1800, 900, 600, 300, 180, 120, 60, 30, 15)
TEXTS = {
    "alert_text": "&6★ &e{event}&r starts in {left}! Want to play? Click or type {join}",
    "alert_in_text": "&6★ &e{event}&r starts in {left}. You're in!",
    "alert_all_text": "&6★ &e{event}&r starts in {left}!",
    "joined_text": "&a✔ You're in {event}!&r It starts in {left}. Changed your mind? {leave}",
    "joined_late_text": "&a✔ You're in {event}!&r It's on now. Good luck!",
    "signed_text": "&a✔ You said you're coming to {event} on the website, so you're in!&r It starts in {left}. Changed your mind? {leave}",
    "left_text": "&7You've left {event}. To get back in: {join}",
    "already_text": "&7You're already in {event}.",
    "closed_text": "&7{event} has already started, so it's too late to join this one.",
    "none_text": "&7There's nothing to join right now.",
    "started_text": "&6★ &e{event}&r has started! There's still time to join: {join}",
}
LABELS = {
    "alert_text": "Countdown alert (to players who haven't joined)",
    "alert_in_text": "Countdown alert (to players who have joined)",
    "alert_all_text": "Countdown alert (events everyone takes part in)",
    "joined_text": "After joining",
    "joined_late_text": "After joining a contest that's already on",
    "signed_text": "Joined by saying \"I'm coming!\" on the website",
    "left_text": "After leaving (/trigger leave)",
    "already_text": "Joining again when already in",
    "closed_text": "Too late: it has started",
    "none_text": "Nothing to join",
    "started_text": "A contest has started (to players who haven't joined)",
}
DEFAULTS = {"alerts": [600, 300, 120, 60, 30], "open_minutes": 60, "on_join": True, **TEXTS}
POLL = 2.0                                     # seconds between looks for /trigger use


# ------------------------------------------------------------------ settings
def config() -> dict:
    saved = settings_store.load().get(SECTION) or {}
    out = {**DEFAULTS, **{k: v for k, v in saved.items() if k in DEFAULTS}}
    out["alerts"] = sorted({int(a) for a in out["alerts"] if int(a) in ALERT_CHOICES}, reverse=True)
    out["open_minutes"] = max(5, min(24 * 60, int(out["open_minutes"] or 60)))
    return out


def save(body: dict) -> dict:
    cur = config()
    for k in TEXTS:
        if k in body:
            cur[k] = welcome.clean(body[k])[:400] or TEXTS[k]
    if "alerts" in body and isinstance(body["alerts"], list):
        cur["alerts"] = sorted({int(a) for a in body["alerts"] if str(a).isdigit() and int(a) in ALERT_CHOICES}, reverse=True)
    if "open_minutes" in body:
        try:
            cur["open_minutes"] = max(5, min(24 * 60, int(body["open_minutes"])))
        except (TypeError, ValueError):
            pass
    if "on_join" in body:
        cur["on_join"] = bool(body["on_join"])
    settings_store.save_section(SECTION, cur)
    return cur


def _state() -> dict:
    d = settings_store.load().get(STATE) or {}
    return {k: dict(d.get(k) or {}) for k in ("joined", "left", "said")}


def _save_state(d: dict) -> None:
    settings_store.save_section(STATE, d)


# ------------------------------------------------------------------ events
def key(kind: str, item: dict) -> str:
    return f"{kind}:{item['id']}"


def _event(kind: str, item: dict, title: str, state: str, late: bool, say: bool = True) -> dict:
    return {"key": key(kind, item), "kind": kind, "server": item["server"], "title": title, "start": item["start"], "state": state,
            "optin": bool(item.get("optin")), "late": late, "say": say, "item": item,
            "signup": community.event_key(kind, title, item["start"])}


def events(sid: str | None = None) -> list[dict]:
    """Contests, races and games that haven't happened yet or are on now."""
    from . import challenges, games, races
    out = []
    for c in challenges._load()["items"]:
        if c["state"] in ("scheduled", "running"):
            out.append(_event("contest", c, c["name"], c["state"], True, c.get("say", True)))
    for r in races._load()["runs"]:
        if r["state"] in ("scheduled", "countdown", "running"):
            out.append(_event("race", r, f"{r['name']} race", "scheduled" if r["state"] == "scheduled" else "running", False))
    for r in games._load()["runs"]:
        if r["state"] == "scheduled" or r["state"] in games.ACTIVE:
            out.append(_event("game", r, r["name"] or games.KINDS.get(r["game"], ("Game",))[0], r["state"] if r["state"] == "scheduled" else "running", False))
    return [e for e in out if sid is None or e["server"] == sid]


def joined(k: str, st: dict | None = None) -> list[str]:
    return list(((st or _state())["joined"]).get(k) or [])


def _accounts_signed(e: dict) -> list[set[str]]:
    """Minecraft names (lowercase) of each account that said "I'm coming!" on the website."""
    from . import auth
    ids = set(community.signups([e["signup"]]).get(e["signup"]) or [])
    if not ids:
        return []
    return [{p["name"].lower() for p in u["players"]} for u in auth.list_users() if u["id"] in ids]


def _merge_signups(e: dict, online: list[str], st: dict) -> list[str]:
    """Online players whose account signed up on the website (and didn't /trigger leave): in. The names added."""
    have, gone = set(joined(e["key"], st)), set(st["left"].get(e["key"]) or [])
    added = []
    for names in _accounts_signed(e):
        for n in online:
            low = n.lower()
            if low in names and low not in have and low not in gone:
                have.add(low)
                added.append(n)
    if added:
        st["joined"][e["key"]] = sorted(have)
    return added


def players(kind: str, item: dict, online: list[str]) -> list[str]:
    """Who takes part, of those online: everyone, or those who joined (website sign-ups included)."""
    if not item.get("optin"):
        return list(online)
    st = _state()
    e = next((x for x in events(item["server"]) if x["key"] == key(kind, item)), None)
    if e and _merge_signups(e, online, st):
        _save_state(st)
    have = set(joined(key(kind, item), st))
    return [n for n in online if n.lower() in have]


def annotate(kind: str, items: list[dict]) -> list[dict]:
    """For the admin pages: who has joined each event that players join (still to come, or on now)."""
    st = _state()
    for it in items:
        if it.get("optin"):
            it["joined"] = joined(key(kind, it), st)
    return items


def is_in(kind: str, item: dict, name: str) -> bool:
    return not item.get("optin") or name.lower() in joined(key(kind, item))


# ------------------------------------------------------------------ messages
def left_words(sec: float) -> str:
    sec = max(0, round(sec))
    if sec >= 90:
        m = round(sec / 60)
        return f"{m} minutes"
    if sec >= 50:
        return "1 minute"
    return f"{max(1, sec)} second{'s' if sec != 1 else ''}"


def lines(text: str, player: str, srv, e: dict | None, now: float | None = None, st: dict | None = None) -> list[str]:
    now = now or time.time()
    vals = {"join": f"/trigger {JOIN}", "leave": f"/trigger {LEAVE}"}
    if e:
        vals |= {"event": e["title"], "left": left_words(e["start"] - now),
                 "time": datetime.fromtimestamp(e["start"], db.tz()).strftime("%I:%M %p").lstrip("0"),
                 "count": str(len(joined(e["key"], st)))}
    for k, v in vals.items():
        text = text.replace("{" + k + "}", v)
    return welcome.commands(player, welcome.fill(text, player, srv.display_name))


async def _tell(srv, player: str, text: str, e: dict | None, st: dict | None = None) -> None:
    await welcome.send(srv, lines(text, player, srv, e, st=st), 0)


# ------------------------------------------------------------------ in the game
_ready: set[str] = set()                       # servers with the trigger objectives made (this run)
_polled: dict[str, float] = {}


def _window(cfg: dict) -> float:
    return max(cfg["open_minutes"] * 60, max(cfg["alerts"], default=0) + 5)


def busy() -> bool:
    """An event soon (alerts and joining) or a contest on that can still be joined."""
    now, cfg = time.time(), config()
    w = _window(cfg)
    return any((e["state"] == "scheduled" and e["start"] - now <= w) or (e["optin"] and e["late"] and e["state"] == "running")
               for e in events())


def _open(evs: list[dict], now: float, cfg: dict) -> list[dict]:
    """Events that can be joined now: running contests first, then the soonest."""
    out = [e for e in evs if e["optin"] and ((e["state"] == "scheduled" and 0 < e["start"] - now <= cfg["open_minutes"] * 60)
                                             or (e["state"] == "running" and e["late"]))]
    return sorted(out, key=lambda e: (e["state"] != "running", e["start"]))


async def _score(srv, name: str, obj: str) -> int:
    from .challenges import _SCORE
    m = _SCORE.search(await srv.rcon(f"scoreboard players get {name} {obj}") or "")
    return int(m.group(1)) if m else 0


async def join(srv, name: str, now: float | None = None) -> str:
    """/trigger join: into the next event they're not in. Returns what happened (for tests and logs)."""
    now, cfg = now or time.time(), config()
    st, evs = _state(), events(srv.id)
    can = _open(evs, now, cfg)
    low = name.lower()
    e = next((x for x in can if low not in joined(x["key"], st)), None)
    if e is None:
        if can:
            await _tell(srv, name, cfg["already_text"], can[0], st)
            return "already"
        late = next((x for x in evs if x["optin"] and x["state"] == "running"), None)
        await _tell(srv, name, cfg["closed_text"] if late else cfg["none_text"], late)
        return "closed" if late else "none"
    st["joined"][e["key"]] = sorted({*joined(e["key"], st), low})
    st["left"][e["key"]] = [n for n in st["left"].get(e["key"], []) if n != low]
    _save_state(st)
    if e["state"] == "running":
        from . import challenges
        await challenges.late_join(srv, e["item"]["id"], name)
        await _tell(srv, name, cfg["joined_late_text"], e, st)
    else:
        await _tell(srv, name, cfg["joined_text"], e, st)
    log.info("%s joined %s", name, e["title"])
    return e["key"]


async def leave(srv, name: str, now: float | None = None) -> str:
    """/trigger leave: out of the soonest one they're in that hasn't started (or else the contest that's on)."""
    now, cfg = now or time.time(), config()
    st = _state()
    low = name.lower()
    mine = [x for x in _open(events(srv.id), now, cfg) if low in joined(x["key"], st)]
    mine.sort(key=lambda x: (x["state"] == "running", x["start"]))
    if not mine:
        await _tell(srv, name, cfg["none_text"], None)
        return "none"
    e = mine[0]
    st["joined"][e["key"]] = [n for n in joined(e["key"], st) if n != low]
    st["left"][e["key"]] = sorted({*st["left"].get(e["key"], []), low})
    _save_state(st)
    await _tell(srv, name, cfg["left_text"], e, st)
    return e["key"]


async def _poll(srv, online: list[str], now: float) -> None:
    """Who has used /trigger join or /trigger leave since the last look."""
    if srv.id not in _ready:
        for obj in (JOIN, LEAVE):
            await srv.rcon(f"scoreboard objectives add {obj} trigger")
        _ready.add(srv.id)
    for obj in (JOIN, LEAVE):
        await srv.rcon(f"scoreboard players enable @a {obj}")
    for obj, act in ((JOIN, join), (LEAVE, leave)):
        if "passed" not in (await srv.rcon(f"execute if entity @a[scores={{{obj}=1..}}]") or "").lower():
            continue
        for n in online:
            if await _score(srv, n, obj) >= 1:
                await srv.rcon(f"scoreboard players set {n} {obj} 0")
                await act(srv, n, now)


async def _alerts(srv, evs: list[dict], online: list[str], now: float, cfg: dict, st: dict) -> bool:
    """The countdown in chat; a time that went by unseen (the event was made later) is skipped."""
    changed = False
    for e in evs:
        if e["state"] != "scheduled":
            continue
        left = e["start"] - now
        said = st["said"].setdefault(e["key"], [])
        for a in cfg["alerts"]:
            if a in said or left > a:
                continue
            said.append(a)
            changed = True
            if left < a - 20 or not e["say"]:
                continue
            have = set(joined(e["key"], st))
            for n in online:
                text = (cfg["alert_all_text"] if not e["optin"] else cfg["alert_in_text"] if n.lower() in have else cfg["alert_text"])
                await _tell(srv, n, text, e, st)
    return changed


async def tick(servers: list) -> None:
    from . import servers as S
    now, cfg = time.time(), config()
    st = _state()
    changed = False
    every = events()
    live = {e["key"] for e in every}
    for part in ("joined", "left", "said"):                 # finished or called off: forgotten
        for k in [k for k in st[part] if k not in live]:
            del st[part][k]
            changed = True
    for srv in [s for s in servers if s.is_java and s.rcon_conf()]:
        evs = [e for e in every if e["server"] == srv.id]
        soon = [e for e in evs if (e["state"] == "scheduled" and e["start"] - now <= _window(cfg)) or (e["optin"] and e["late"] and e["state"] == "running")]
        if not soon:
            continue
        try:
            online, src = await S.online_players(srv)
            if src != "rcon" or not online:
                continue
            changed |= await _alerts(srv, soon, online, now, cfg, st)
            for e in _open(soon, now, cfg):
                if e["state"] == "scheduled":
                    for n in _merge_signups(e, online, st):
                        changed = True
                        await _tell(srv, n, cfg["signed_text"], e, st)
            if changed:
                _save_state(st)
                changed = False
            if now - _polled.get(srv.id, 0) >= POLL and _open(soon, now, cfg):
                _polled[srv.id] = now
                await _poll(srv, online, now)
                st = _state()
        except Exception:
            log.exception("joining check failed on %s", srv.id)
    if changed:
        _save_state(st)


async def started(srv, kind: str, item: dict, online: list[str]) -> None:
    """A contest that can still be joined has started: those not in hear they can."""
    if not item.get("optin") or kind != "contest" or not item.get("say", True):
        return
    cfg = config()
    e = next((x for x in events(srv.id) if x["key"] == key(kind, item)), None)
    have = set(joined(key(kind, item)))
    for n in online:
        if n.lower() not in have:
            await _tell(srv, n, cfg["started_text"], e)


def on_join(srv, player: str) -> None:
    """Joined the server: the next event (if one is coming up soon), after the welcome and the reminders."""
    cfg = config()
    if not cfg["on_join"] or not srv.rcon_conf():
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    now = time.time()
    st = _state()
    for e in _open(events(srv.id), now, cfg):
        if player.lower() in joined(e["key"], st):
            continue
        if e["state"] == "running":
            text = cfg["started_text"]
        elif e["start"] - now <= max(cfg["alerts"], default=600):
            text = cfg["alert_text"]
        else:
            continue
        loop.create_task(welcome.send(srv, lines(text, player, srv, e, now, st), 9))
        return
