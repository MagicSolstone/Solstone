"""Players make their own account, proved by a code sent to them in the game.

1. On the sign-in page they type their Minecraft name (Java, or Bedrock through Geyser).
2. If they're playing on one of the public servers right now, Solstone whispers a six-digit
   code to them in the game chat (tellraw to that player only), so only whoever is at that
   player's keyboard sees it. Being on the whitelist is what lets someone in at all.
3. They type the code with a login and password of their choice, and get a "player" account
   linked to that Minecraft player, which sees the server they signed up on (an admin can add more).

The answer to step 1 is the same whether or not the player is online, so the page can't be used
to see who's playing. Codes last ten minutes, take five tries, and are stored only as a hash.
A player can be sent a few codes an hour, so nobody can flood their chat.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import time

from fastapi import HTTPException, Request

from . import auth, board
from . import servers as S
from .control import component

CODE_TTL = 10 * 60
CODE_TRIES = 5
PER_PLAYER = 3               # codes per player per window
PER_ADDRESS = 10             # code requests per address per window
WINDOW = 60 * 60
NAME_RE = re.compile(r"^\.?[A-Za-z0-9_]{1,17}$")

_codes: dict[str, dict] = {}            # player uuid -> {hash, name, expires, tries}
_sent: dict[str, list[float]] = {}      # rate limits: "p:<uuid>" and "ip:<address>"

SENT_TEXT = ("If you're playing on the server right now, a code is waiting for you in the game chat. "
             "Nothing there? Check you're in the game and the name is spelled as it shows there.")


def _hash(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def _hit(key: str, limit: int) -> bool:
    """Count one, and say whether the limit was already reached."""
    now = time.time()
    hits = [t for t in _sent.get(key, []) if now - t < WINDOW]
    if len(hits) >= limit:
        _sent[key] = hits
        return True
    _sent[key] = hits + [now]
    if len(_sent) > 5000:
        for k in [k for k, v in _sent.items() if not v or now - v[-1] > WINDOW]:
            _sent.pop(k, None)
    return False


def _names(typed: str) -> set[str]:
    """What they typed, and the Bedrock form with or without Floodgate's dot in front."""
    t = typed.lower()
    return {t, t.lstrip("."), "." + t.lstrip(".")}


async def _find_online(servers: list[S.Server], typed: str) -> tuple[S.Server, str, str] | None:
    """(server, uuid, exact name) for a player playing right now on one of these servers."""
    want = _names(typed)
    for srv in servers:
        if not srv.is_java or not srv.rcon_conf():
            continue
        try:
            online, _src = await S.online_players(srv)
        except Exception:
            continue
        name = next((n for n in online if n.lower() in want), None)
        if not name:
            continue
        uuid = next((u for u, p in S.known_players(srv).items() if p["name"].lower() == name.lower()), None)
        if uuid:
            return srv, uuid, name
    return None


async def start(request: Request, typed: str, servers: list[S.Server]) -> str:
    typed = (typed or "").strip()
    if not NAME_RE.match(typed):
        raise HTTPException(400, "Type your Minecraft name as it shows in the game")
    if _hit(f"ip:{auth.client_ip(request)}", PER_ADDRESS):
        raise HTTPException(429, "Too many tries. Wait an hour and try again")
    found = await _find_online(servers, typed)
    if not found:
        return SENT_TEXT
    srv, uuid, name = found
    if _hit(f"p:{uuid}", PER_PLAYER):
        return SENT_TEXT
    existing = auth.user_for_player(uuid)
    if existing:
        msg = component([("[Website] ", "gold"), ("You already have an account: ", "yellow"), (existing, "white"),
                         (". Forgot the password? Ask an admin to set a new one.", "yellow")])
    else:
        code = f"{secrets.randbelow(10**6):06d}"
        _codes[uuid] = {"hash": _hash(code), "name": name, "server": srv.id, "expires": time.time() + CODE_TTL, "tries": 0}
        msg = component([("[Website] ", "gold"), ("Your sign-up code is ", "yellow"), (code, "green"),
                         (". It's only for you: don't share it. It works for 10 minutes.", "yellow")])
    try:
        await srv.rcon(f"tellraw {name} {msg}")
    except Exception:
        _codes.pop(uuid, None)
    return SENT_TEXT


def finish(typed: str, code: str, username: str, password: str, real_name: str = "", birthday: dict | None = None) -> auth.User:
    """Check the code and make the player's account. Raises if it's wrong, used up or old."""
    want = _names((typed or "").strip())
    uuid = next((u for u, c in _codes.items() if c["name"].lower() in want), None)
    entry = _codes.get(uuid) if uuid else None
    if not entry or entry["expires"] < time.time():
        if uuid:
            _codes.pop(uuid, None)
        raise HTTPException(400, "That code has run out. Ask for a new one")
    entry["tries"] += 1
    if not hmac.compare_digest(entry["hash"], _hash(re.sub(r"\D", "", code or ""))):
        if entry["tries"] >= CODE_TRIES:
            _codes.pop(uuid, None)
            raise HTTPException(400, "Wrong code too many times. Ask for a new one")
        raise HTTPException(400, "That code isn't right")
    # they see the server they signed up on; an admin can give them more in Users
    user = auth.create_user(username.strip(), password, "player", player=(uuid, entry["name"]), servers=[entry["server"]])
    _codes.pop(uuid, None)
    try:
        auth.set_display_name(user.id, entry["name"].lstrip("."))
    except HTTPException:
        pass                    # their in-game name is someone's login already: they can pick one later
    if real_name.strip():
        try:
            auth.set_real_name(user.id, real_name)
        except HTTPException:
            pass
    if birthday:
        board.add_birthday(entry["name"], birthday.get("month"), birthday.get("day"))
    return auth.get_user(user.id)


# ---------------------------------------------------------------- linking another Minecraft account to a login
# The same proof as signing up: a code sent in the game chat to that player only. For someone with a Java and a
# Bedrock account (two names), so both show as theirs.
_link_codes: dict[str, dict] = {}       # player uuid -> {hash, name, uid, expires, tries}


async def start_link(request: Request, user: auth.User, typed: str, servers: list[S.Server]) -> str:
    typed = (typed or "").strip()
    if not NAME_RE.match(typed):
        raise HTTPException(400, "Type the Minecraft name as it shows in the game (Bedrock names start with a dot)")
    if _hit(f"ip:{auth.client_ip(request)}", PER_ADDRESS) or _hit(f"u:{user.id}", PER_PLAYER * 2):
        raise HTTPException(429, "Too many tries. Wait an hour and try again")
    found = await _find_online(servers, typed)
    if not found:
        return SENT_TEXT
    srv, uuid, name = found
    if _hit(f"p:{uuid}", PER_PLAYER):
        return SENT_TEXT
    owner = auth.user_for_player(S.norm_uuid(uuid))
    if owner and owner.lower() == user.username.lower():
        msg = component([("[Website] ", "gold"), ("This player is already linked to your login.", "yellow")])
    elif owner:
        msg = component([("[Website] ", "gold"), ("This player belongs to another login. Ask an admin if that's wrong.", "yellow")])
    else:
        code = f"{secrets.randbelow(10**6):06d}"
        _link_codes[uuid] = {"hash": _hash(code), "name": name, "uid": user.id, "expires": time.time() + CODE_TTL, "tries": 0}
        msg = component([("[Website] ", "gold"), ("Your code to link this player to the login ", "yellow"), (user.username, "white"),
                         (" is ", "yellow"), (code, "green"), (". Don't share it. It works for 10 minutes.", "yellow")])
    try:
        await srv.rcon(f"tellraw {name} {msg}")
    except Exception:
        _link_codes.pop(uuid, None)
    return SENT_TEXT


def finish_link(user: auth.User, typed: str, code: str) -> auth.User:
    want = _names((typed or "").strip())
    uuid = next((u for u, c in _link_codes.items() if c["name"].lower() in want and c["uid"] == user.id), None)
    entry = _link_codes.get(uuid) if uuid else None
    if not entry or entry["expires"] < time.time():
        if uuid:
            _link_codes.pop(uuid, None)
        raise HTTPException(400, "That code has run out. Ask for a new one")
    entry["tries"] += 1
    if not hmac.compare_digest(entry["hash"], _hash(re.sub(r"\D", "", code or ""))):
        if entry["tries"] >= CODE_TRIES:
            _link_codes.pop(uuid, None)
            raise HTTPException(400, "Wrong code too many times. Ask for a new one")
        raise HTTPException(400, "That code isn't right")
    _link_codes.pop(uuid, None)
    return auth.add_player(user.id, (S.norm_uuid(uuid), entry["name"]))
