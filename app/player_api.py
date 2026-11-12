"""A player's page on the server: their details, travels, a Bedrock account linked to a Java one, and the
leaderboards (with an admin's adjustments). The routes main.py includes; main's helpers are looked up when a route runs."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request

from . import adventures, auth, stacks
from . import servers as S

router = APIRouter()


@router.get("/api/servers/{sid}/players/{uuid}")
async def get_player(sid: str, uuid: str):
    from . import main as M
    if not M._own(uuid):
        raise HTTPException(404, "Player not found")
    srv = await M._server(sid)
    data = await S.player_detail(srv, uuid)
    if data:                                     # their other Minecraft accounts, and everyone's progress added up
        data["together"] = await asyncio.to_thread(stacks.together, srv, data["name"])
    if data and not M._shows_play_time():
        data = M._no_durations(data)
    if not data:
        raise HTTPException(404, "Player not found")
    return data


@router.get("/api/servers/{sid}/players/{uuid}/travels")
async def get_player_travels(sid: str, uuid: str, span: str = "all"):
    """Where a player (all their accounts) has been: the chunks, how often, and their records. Their own page only, for
    a player account, like the rest of it."""
    from . import main as M
    if not M._own(uuid):
        raise HTTPException(404, "Player not found")
    srv = await M._server(sid)
    p = S.known_players(srv).get(S.norm_uuid(uuid))
    if not p:
        raise HTTPException(404, "Player not found")
    tog = await asyncio.to_thread(stacks.together, srv, p["name"])
    names = [a["name"] for a in (tog or {}).get("accounts", [])] or [p["name"]]
    data = await asyncio.to_thread(adventures.travels if span == "recent" else adventures.travels_all, srv.id, names)
    spawn = (await asyncio.to_thread(S.world_info, srv, False)).get("spawn")
    data = adventures.farthest_from(data, spawn)
    return {**data, "names": names, "span": "recent" if span == "recent" else "all"}


@router.get("/api/servers/{sid}/players/{uuid}/link")
async def get_player_link(sid: str, uuid: str):
    """Floodgate's link between a Bedrock and a Java account, as GeyserMC has it: for a Bedrock player, the Java player
    they join as; for a Java player, any Bedrock accounts here linked to them. Only read, never changed."""
    from . import main as M
    from . import bedrocklink
    from .skins import bedrock_xuid
    if not M._own(uuid):
        raise HTTPException(404, "Player not found")
    srv = await M._server(sid)
    known = S.known_players(srv)
    p = known.get(S.norm_uuid(uuid))
    if not p:
        raise HTTPException(404, "Player not found")
    def here(u: str) -> dict:
        k = known.get(S.norm_uuid(u))
        return {"uuid": k["uuid"] if k else u, "name": k["name"] if k else "", "here": bool(k)}
    if bedrock_xuid(p["uuid"]) is not None:
        try:
            link = await bedrocklink.linked_java(p["uuid"])
        except Exception as e:
            return {"bedrock": True, "error": f"Couldn't ask GeyserMC: {type(e).__name__}"}
        return {"bedrock": True, "plays_as": {**here(link["java_uuid"]), "name": link["java_name"] or here(link["java_uuid"])["name"]} if link else None}
    bedrock = [u for u in known if bedrock_xuid(u) is not None]
    found = await bedrocklink.bedrock_for(p["uuid"], bedrock) if bedrock else []
    return {"bedrock": False, "linked_bedrock": [here(u) for u in found]}


@router.get("/api/servers/{sid}/leaderboard")
async def get_leaderboard(sid: str):
    from . import main as M
    return stacks.leaderboard(await S.leaderboard(await M._server(sid)))


def _board_rows(srv: S.Server, uuid: str) -> list[dict]:
    raw = S.player_board_values(srv, uuid)
    minus = S.board_adjustments(srv.id).get(uuid) or {}
    return [{"key": k, "title": t, "kind": f, "real": raw.get(k, 0), "minus": minus.get(k, 0),
             "shown": max(0, raw.get(k, 0) - minus.get(k, 0))} for k, t, f in S.LEADERBOARDS if k not in S.NOT_ADJUSTABLE]


@router.get("/api/servers/{sid}/leaderboard/adjust/{uuid}")
async def get_board_adjust(sid: str, uuid: str, request: Request):
    """Admin: a player's numbers on the boards that can be adjusted: the game's, what's taken off, what shows."""
    from . import main as M
    auth.require_admin(request)
    srv = await M._server(sid)
    return await asyncio.to_thread(_board_rows, srv, uuid)


@router.put("/api/servers/{sid}/leaderboard/adjust/{uuid}")
async def put_board_adjust(sid: str, uuid: str, request: Request):
    """Admin: what a player's board shows from now on: a number (0: don't count what's happened so far), or null to
    show the game's own number again. keys: one board or several. The game's statistics aren't touched."""
    from . import main as M
    user = auth.require_admin(request)
    srv = await M._server(sid)
    body = await M._body(request)
    keys = body.get("keys") or ([body["key"]] if body.get("key") else [])
    allowed = {k for k, _t, _f in S.LEADERBOARDS if k not in S.NOT_ADJUSTABLE}
    if not keys or any(k not in allowed for k in keys):
        raise HTTPException(400, "Pick a board that can be adjusted")
    to = body.get("to")
    raw = await asyncio.to_thread(S.player_board_values, srv, uuid)
    for k in keys:
        if to is None:
            S.set_board_adjustment(sid, uuid, k, None)
            continue
        try:
            n = int(to)
        except (TypeError, ValueError):
            raise HTTPException(400, "A whole number") from None
        if n < 0 or n > raw.get(k, 0):
            raise HTTPException(400, f"Between 0 and the game's own number ({raw.get(k, 0)})")
        S.set_board_adjustment(sid, uuid, k, raw.get(k, 0) - n)
    name = S.known_players(srv).get(uuid, {}).get("name", uuid)
    auth.audit(user, sid, "leaderboard:adjust", f"{name}: {', '.join(keys)} " + ("back to the game's numbers" if to is None else f"shown as {to}"))
    return await asyncio.to_thread(_board_rows, srv, uuid)
