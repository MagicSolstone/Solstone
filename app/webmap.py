"""A server's web map (BlueMap, squaremap, Dynmap) through Solstone, so it works from anywhere without putting the
map itself on the internet: only people signed in, who may see that server's map, get it.

The map can show things players typed (BlueMap shows Flan's claim names, which can hold anything), so it never
runs as part of Solstone's pages: every answer carries a "sandbox" policy, which gives the map a separate,
anonymous origin with no access to Solstone's sign-in or pages. Its own requests can't carry the sign-in cookie
either, so the permission travels in the address instead: /map/<server>/<pass>/..., a pass that says who it was
made for and runs out after a while. Every request still checks that person may see the map right now.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time

import httpx
from fastapi import HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from starlette.background import BackgroundTask

from . import settings_store

PASS_HOURS = 12
KEEP_HEADERS = ("content-type", "content-encoding", "cache-control", "etag", "last-modified", "content-length",
                "content-range", "accept-ranges")
ASK_HEADERS = ("accept", "accept-encoding", "accept-language", "if-none-match", "if-modified-since", "range")
# The map's pages: a sandbox (an anonymous origin of its own), scripts and pictures as the map needs them.
SANDBOX_CSP = "; ".join([
    "sandbox allow-scripts allow-popups allow-popups-to-escape-sandbox allow-downloads",
    "default-src * data: blob: 'unsafe-inline' 'unsafe-eval'",
    "frame-ancestors 'self'",
    "base-uri 'none'",
    "form-action 'none'",
])
# In a sandbox the browser refuses localStorage, and maps keep their settings there (BlueMap reads it without
# checking): a stand-in that forgets them when the page closes, before the map's own scripts run.
STORAGE_SHIM = (b"<script>(function(){function m(){var d={};return{getItem:function(k){return Object.prototype."
                b"hasOwnProperty.call(d,k)?d[k]:null},setItem:function(k,v){d[k]=String(v)},removeItem:function(k){"
                b"delete d[k]},clear:function(){d={}},key:function(i){return Object.keys(d)[i]||null},get length(){"
                b"return Object.keys(d).length}}}['localStorage','sessionStorage'].forEach(function(n){try{window[n]"
                b".length}catch(e){try{Object.defineProperty(window,n,{value:m(),configurable:true})}catch(_){}}})"
                b"})();</script>")

_client: httpx.AsyncClient | None = None


def _secret() -> bytes:
    s = settings_store.load().get("webmap_secret")
    if not s:
        s = secrets.token_hex(32)
        settings_store.save_section("webmap_secret", s)
    return bytes.fromhex(s)


def make_pass(uid: int, sid: str) -> str:
    exp = int(time.time()) + PASS_HOURS * 3600
    sig = hmac.new(_secret(), f"{uid}.{sid}.{exp}".encode(), hashlib.sha256).hexdigest()[:32]
    return f"{uid}-{exp}-{sig}"


def read_pass(token: str, sid: str) -> int | None:
    """The user id the pass was made for, if it's genuine, for this server, and still good."""
    try:
        uid_s, exp_s, sig = token.split("-")
        uid, exp = int(uid_s), int(exp_s)
    except ValueError:
        return None
    want = hmac.new(_secret(), f"{uid}.{sid}.{exp}".encode(), hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(want, sig) or exp < time.time():
        return None
    return uid


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=httpx.Timeout(20, connect=5), follow_redirects=False,
                                    limits=httpx.Limits(max_connections=32, max_keepalive_connections=16))
    return _client


def _target(base: str, path: str, query: str) -> str:
    parts = path.split("/")
    if any(p in ("..", ".") for p in parts) or "\\" in path or "://" in path or path.startswith("/"):
        raise HTTPException(400, "Bad map address")
    url = base.rstrip("/") + "/" + path
    return f"{url}?{query}" if query else url


async def proxy(base: str, path: str, request: Request, prefix: str) -> Response:
    """Fetch path from the map at base and hand it on, as it is (still compressed if it was)."""
    url = _target(base, path, request.url.query)
    headers = {k: v for k in ASK_HEADERS if (v := request.headers.get(k))}
    if path == "" or path.endswith(("/", ".html")):
        headers.pop("accept-encoding", None)            # pages come plain, so the storage stand-in can go in
    client = _get_client()
    try:
        r = await client.send(client.build_request(request.method, url, headers=headers), stream=True)
    except httpx.HTTPError:
        return Response("The web map isn't answering. Is it running?", status_code=502, media_type="text/plain")
    out = {k: v for k, v in r.headers.items() if k.lower() in KEEP_HEADERS}
    out.update({"Content-Security-Policy": SANDBOX_CSP, "Access-Control-Allow-Origin": "*", "Referrer-Policy": "no-referrer",
                "X-Frame-Options": "SAMEORIGIN", "X-Content-Type-Options": "nosniff"})
    if r.status_code in (204, 404):                     # "nothing drawn here yet": never kept, so it shows once drawn
        out["Cache-Control"] = "no-store"
    if r.is_redirect:                                   # keep the map's own redirects inside /map/...
        loc = r.headers.get("location", "")
        await r.aclose()
        if loc.startswith(base.rstrip("/")):
            loc = prefix + loc[len(base.rstrip("/")):].lstrip("/")
        elif "://" in loc or loc.startswith("//"):
            loc = prefix
        out["Location"] = loc
        return Response(status_code=r.status_code, headers=out)
    if "text/html" in r.headers.get("content-type", "") and not r.headers.get("content-encoding") and r.status_code == 200:
        body = await r.aread()                          # the map's page: the storage stand-in goes in first
        await r.aclose()
        i = body.lower().find(b"<head>")
        body = body[:i + 6] + STORAGE_SHIM + body[i + 6:] if i >= 0 else STORAGE_SHIM + body
        out.pop("content-length", None)
        return Response(body, status_code=200, headers=out)
    return StreamingResponse(r.aiter_raw(), status_code=r.status_code, headers=out, background=BackgroundTask(r.aclose))
