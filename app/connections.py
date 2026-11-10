"""Connections: what Solstone asks about running servers (Manage → Solstone → Server setup → Connections).

Two kinds, set up in Solstone itself (not in the container's settings):
- **Crafty 4** (crafty): a Crafty Controller, usually on the same machine. Solstone lists its servers from it, and
  asks it whether each is running, its CPU and memory, and to start, stop, restart or back one up. Its servers' files
  are read from the servers folder Solstone can see.
- **A host's panel** (panel): Pterodactyl or Pelican, which most game hosts run. Its API key can see the servers on
  that account; a server somewhere else (remote.py) is linked to one of them for the same things.

There can be more than one of each. Older Solstones took Crafty from the container's CRAFTY_URL and CRAFTY_TOKEN:
those are brought in once, the first time this version starts, as a Crafty connection (so nothing needs setting up
again), and after that it's the one in Solstone that counts. The container settings can then be removed.
"""
from __future__ import annotations

import logging
import re
import secrets
import threading

import httpx

from . import settings_store
from .config import config

log = logging.getLogger("solstone.connections")

SECTION = "connections"                 # {cid: {...}}
IMPORTED = "connections_env_imported"   # the container's Crafty settings were brought in (once: removing it sticks)
SECRETS = ("token", "password", "key")
TYPES = {"crafty": "Crafty 4", "panel": "Pterodactyl or Pelican"}
_lock = threading.Lock()


# ------------------------------------------------------------------ the saved connections
def _import_env(data: dict) -> bool:
    """The container's CRAFTY_URL and CRAFTY_TOKEN (an older setup), as a Crafty connection: once."""
    if settings_store.load().get(IMPORTED) or not config.crafty_url:
        return False
    if not (config.crafty_token or (config.crafty_user and config.crafty_password)):
        return False
    data["crafty"] = {"type": "crafty", "name": "Crafty", "url": config.crafty_url, "token": config.crafty_token,
                      "user": config.crafty_user, "password": config.crafty_password, "verify_ssl": config.crafty_verify_ssl,
                      "from_env": True}
    return True


def all_cfg() -> dict[str, dict]:
    with _lock:
        data = dict(settings_store.load().get(SECTION) or {})
        if _import_env(data):
            settings_store.save_section(SECTION, data)
            settings_store.save_section(IMPORTED, True)
            log.info("brought in the container's Crafty settings (%s) as a connection", config.crafty_url)
        return data


def get(cid: str | None) -> dict | None:
    return all_cfg().get(cid or "")


def of_type(kind: str) -> dict[str, dict]:
    return {k: v for k, v in all_cfg().items() if v.get("type") == kind}


def public(cfg: dict) -> dict:
    out = {k: v for k, v in cfg.items() if k not in SECRETS}
    for k in SECRETS:
        out[f"{k}_set"] = bool(cfg.get(k))
    out["type_name"] = TYPES.get(cfg.get("type"), cfg.get("type"))
    return out


def clean(body: dict, old: dict | None = None) -> dict:
    """An admin's settings for a connection, checked. A secret left blank keeps the one saved."""
    old = old or {}
    kind = body.get("type") or old.get("type")
    if kind not in TYPES:
        raise ValueError("Pick what kind it is: Crafty 4, or Pterodactyl or Pelican")
    url = str(body.get("url") if body.get("url") is not None else old.get("url") or "").strip().rstrip("/")
    if not re.fullmatch(r"https?://[^\s/]+(/\S*)?", url):
        raise ValueError("Its address starts with https:// (or http://), like https://192.168.1.10:8443")
    cfg = {"type": kind, "name": " ".join(str(body.get("name") or old.get("name") or TYPES[kind]).split())[:40],
           "url": url, "verify_ssl": bool(body.get("verify_ssl", old.get("verify_ssl", kind == "panel")))}
    for k in SECRETS:
        v = body.get(k)
        cfg[k] = str(v) if v else old.get(k, "")
    if kind == "crafty":
        cfg["user"] = " ".join(str(body.get("user") if body.get("user") is not None else old.get("user") or "").split())[:80]
        if not cfg["token"] and not (cfg["user"] and cfg["password"]):
            raise ValueError("Crafty needs an API token (in Crafty: your user → API Keys), or a username and password")
        cfg["key"] = ""
    else:
        if not cfg["key"]:
            raise ValueError("The panel needs an API key (in the panel: Account → API Credentials → Create)")
        cfg["token"] = cfg["password"] = ""
    return cfg


def save(cid: str | None, body: dict) -> str:
    data = all_cfg()
    old = data.get(cid) if cid else None
    if cid and old is None:
        raise KeyError(cid)
    cid = cid or f"{(body.get('type') or 'c')[:6]}-{secrets.token_hex(3)}"
    data[cid] = clean(body, old)
    with _lock:
        settings_store.save_section(SECTION, data)
    _clients.pop(cid, None)
    return cid


def remove(cid: str) -> None:
    data = all_cfg()
    data.pop(cid, None)
    with _lock:
        settings_store.save_section(SECTION, data)
        settings_store.save_section(IMPORTED, True)       # (the container's settings aren't brought back in)
    _clients.pop(cid, None)


# ------------------------------------------------------------------ Crafty clients, one per Crafty connection
_clients: dict[str, tuple[tuple, object]] = {}


def crafty_client(cid: str | None):
    """The Crafty client for a connection (made again when its settings change). None if there's no such Crafty."""
    from .crafty import CraftyClient
    cfg = get(cid) if cid else None
    if not cfg or cfg.get("type") != "crafty":
        return None
    sig = (cfg["url"], cfg.get("token"), cfg.get("user"), cfg.get("password"), cfg.get("verify_ssl"))
    hit = _clients.get(cid)
    if hit and hit[0] == sig:
        return hit[1]
    client = CraftyClient(cfg)
    _clients[cid] = (sig, client)
    return client


def crafties() -> list[tuple[str, object]]:
    return [(cid, crafty_client(cid)) for cid in of_type("crafty")]


def for_server(srv):
    """The Crafty client that runs a server Solstone found in Crafty (None for any other)."""
    if not getattr(srv, "crafty", None):
        return None
    return crafty_client(srv.crafty.get("_conn") or next(iter(of_type("crafty")), None))


async def close_all() -> None:
    for _sig, c in list(_clients.values()):
        try:
            await c.close()
        except Exception:
            pass
    _clients.clear()


# ------------------------------------------------------------------ trying one, and a panel's servers
async def test(cfg: dict) -> dict:
    """Does it answer, and which servers does it have? (Nothing is saved.)"""
    if cfg["type"] == "crafty":
        from .crafty import CraftyClient
        c = CraftyClient(cfg)
        try:
            listed = await c.servers()
        finally:
            await c.close()
        if listed is None:
            return {"ok": False, "error": _crafty_why(c.last_error or "")}
        return {"ok": True, "servers": [{"id": str(s.get("server_id")), "name": s.get("server_name") or str(s.get("server_id"))} for s in listed]}
    try:
        return {"ok": True, "servers": await panel_servers(cfg)}
    except Exception as e:
        from .remote import _panel_why
        return {"ok": False, "error": _panel_why(e)}


def _crafty_why(err: str) -> str:
    if "401" in err or "403" in err:
        return "Crafty didn't accept the token (or the username and password)"
    if "ConnectError" in err or "ConnectTimeout" in err:
        return "Nothing answered at that address. Is it Crafty's address and port (usually https://<this machine>:8443)?"
    if "SSL" in err or "certificate" in err.lower():
        return "Crafty's certificate wasn't trusted: untick Check its certificate (Crafty makes its own)"
    return err or "Crafty didn't answer"


async def panel_servers(cfg: dict) -> list[dict]:
    """The servers a panel's API key can see: {id, name, node}. (The client API lists them, a page at a time.)"""
    out, page = [], 1
    async with httpx.AsyncClient(timeout=10, verify=cfg.get("verify_ssl", True)) as client:
        while page <= 10:
            r = await client.get(f"{cfg['url']}/api/client", params={"page": page},
                                 headers={"Authorization": f"Bearer {cfg.get('key', '')}", "Accept": "application/json"})
            r.raise_for_status()
            body = r.json()
            for s in body.get("data") or []:
                a = s.get("attributes") or {}
                out.append({"id": a.get("identifier") or "", "name": a.get("name") or "", "node": a.get("node") or ""})
            pages = ((body.get("meta") or {}).get("pagination") or {}).get("total_pages") or 1
            if page >= pages:
                break
            page += 1
    return out
