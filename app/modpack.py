"""A packwiz modpack per server, so Prism keeps every family PC's mods in step automatically.

Each PC's Prism instance runs packwiz-installer before launching (a pre-launch command); it reads
the pack from Solstone and downloads whatever changed. The pack has two parts:

- **From the server:** jars from the server's own mods folder (Tide, Fabric API...), served by
  Solstone straight from that folder (read-only), so clients always match the server exactly.
- **From Modrinth:** client mods, resource packs and shaders, pinned to a version until you
  "update all".

The pack is public behind a secret token in its address (the installer can't sign in).
Format: https://packwiz.infra.link/reference/pack-format/
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
from pathlib import Path
from urllib.parse import quote

import httpx

from . import servers as S
from . import settings_store
from .config import config

SECTION = "modpacks"
MODRINTH = "https://api.modrinth.com/v2"
UA = "MagicSolstone/Solstone (family Minecraft dashboard)"
BOOTSTRAP_URL = "https://github.com/packwiz/packwiz-installer-bootstrap/releases/latest/download/packwiz-installer-bootstrap.jar"
DEFAULT_SERVER_MODS = ("tide", "fabric-api")             # needed on every client for Tide
KINDS = {"mod": "mods", "resourcepack": "resourcepacks", "shader": "shaderpacks"}
_SLUG = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


# ------------------------------------------------------------------ settings
def _all() -> dict:
    return dict(settings_store.load().get(SECTION) or {})


def get(sid: str) -> dict:
    cfg = _all().get(sid) or {}
    cfg.setdefault("enabled", False)
    cfg.setdefault("token", "")
    cfg.setdefault("server_mods", None)                 # None: the defaults (Tide, Fabric API)
    cfg.setdefault("extra", [])
    return cfg


def save(sid: str, cfg: dict) -> dict:
    d = _all()
    if not cfg.get("token"):
        cfg["token"] = secrets.token_urlsafe(18)
    d[sid] = cfg
    settings_store.save_section(SECTION, d)
    return cfg


def by_token(token: str) -> tuple[str, dict] | None:
    for sid, cfg in _all().items():
        if cfg.get("token") and secrets.compare_digest(cfg["token"], token) and cfg.get("enabled"):
            return sid, get(sid)
    return None


# ------------------------------------------------------------------ the server's own jars
def server_mods(srv) -> list[dict]:
    """The server's mods, marked with whether the pack includes them. Server-only mods can't be picked."""
    cfg = get(srv.id)
    chosen = set(cfg["server_mods"]) if cfg["server_mods"] is not None else None
    out = []
    for m in S.mods(srv):
        mid = m.get("id") or m["file"]
        server_only = m.get("environment") == "server"
        on = (mid in chosen) if chosen is not None else (mid in DEFAULT_SERVER_MODS)
        out.append({"id": mid, "name": m.get("name") or mid, "version": m.get("version"), "file": m["file"],
                    "environment": m.get("environment", "*"), "included": on and not server_only, "server_only": server_only})
    return out


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def server_jar(srv, token: str, filename: str) -> Path | None:
    """A jar the pack serves from the server's mods folder (only ones the pack includes)."""
    if "/" in filename or "\\" in filename or not filename.endswith(".jar"):
        return None
    if not any(m["file"] == filename and m["included"] for m in server_mods(srv)):
        return None
    p = srv.dir / "mods" / filename
    return p if p.is_file() else None


# ------------------------------------------------------------------ Modrinth
async def _get_json(url: str, params: dict | None = None):
    async with httpx.AsyncClient(timeout=15, headers={"User-Agent": UA}, follow_redirects=True) as c:
        r = await c.get(url, params=params)
        r.raise_for_status()
        return r.json()


def _loaders(kind: str) -> list[str]:
    return {"mod": ["fabric"], "resourcepack": ["minecraft"], "shader": ["iris"]}[kind]


async def search(query: str, mc: str, kind: str = "mod", limit: int = 8) -> list[dict]:
    facets = [[f"versions:{mc}"], [f"project_type:{kind}"]]
    if kind == "mod":
        facets.append(["categories:fabric"])
    data = await _get_json(f"{MODRINTH}/search", {"query": query, "limit": limit, "facets": json.dumps(facets)})
    return [{"slug": h["slug"], "title": h["title"], "kind": kind, "description": h.get("description", ""),
             "icon": h.get("icon_url"), "downloads": h.get("downloads", 0)} for h in data.get("hits", [])]


async def resolve(slug: str, mc: str, kind: str = "mod") -> dict | None:
    """The newest version of a project for this Minecraft version: its file, hashes and required dependencies."""
    if not _SLUG.match(slug) or kind not in KINDS:
        return None
    versions = await _get_json(f"{MODRINTH}/project/{slug}/version",
                               {"game_versions": json.dumps([mc]), "loaders": json.dumps(_loaders(kind))})
    if not versions:
        return None
    v = versions[0]
    f = next((x for x in v["files"] if x.get("primary")), v["files"][0])
    project = await _get_json(f"{MODRINTH}/project/{slug}")
    return {"slug": project.get("slug", slug), "project_id": v["project_id"], "title": project.get("title", slug), "kind": kind,
            "version_id": v["id"], "version": v.get("version_number", ""), "filename": f["filename"], "url": f["url"],
            "sha512": f["hashes"]["sha512"], "size": f.get("size", 0), "icon": project.get("icon_url"),
            "requires": [d["project_id"] for d in v.get("dependencies", []) if d.get("dependency_type") == "required" and d.get("project_id")]}


async def add(srv, slug: str, kind: str = "mod") -> list[dict]:
    """Add a project and anything it requires that the pack doesn't have yet. A requirement the
    server already has (Fabric API, say) is taken from the server instead. Returns what was added."""
    mc = srv.mc_version or ""
    cfg = get(srv.id)
    have = {e["slug"] for e in cfg["extra"]} | {e["project_id"] for e in cfg["extra"]}
    on_server = {m["id"] for m in server_mods(srv) if not m["server_only"]}
    chosen = set(cfg["server_mods"]) if cfg["server_mods"] is not None else {m["id"] for m in server_mods(srv) if m["included"]}
    added, todo = [], [(slug, kind)]
    while todo:
        s, k = todo.pop(0)
        if s in have:
            continue
        e = await resolve(s, mc, k)
        if not e or e["slug"] in have or e["project_id"] in have:
            continue
        have |= {e["slug"], e["project_id"]}
        if e["slug"] in on_server:                  # use the server's own copy
            chosen.add(e["slug"])
            continue
        cfg["extra"].append(e)
        added.append(e)
        todo += [(d, "mod") for d in e["requires"]]
    cfg["server_mods"] = sorted(chosen)
    save(srv.id, cfg)
    return added


async def add_names(srv, text: str) -> dict:
    """A pasted list (one per line, or commas): each name searched on Modrinth for this version,
    best match added. Lines may start with "resourcepack:" or "shader:" (mods otherwise)."""
    added, missing = [], []
    for raw in re.split(r"[\n,]+", text):
        name = raw.strip()
        if not name:
            continue
        kind = "mod"
        m = re.match(r"^(mod|resourcepack|resource pack|shader)s?\s*:\s*(.+)$", name, re.I)
        if m:
            kind = {"resource pack": "resourcepack"}.get(m.group(1).lower(), m.group(1).lower())
            name = m.group(2).strip()
        try:
            hits = await search(name, srv.mc_version or "", kind, limit=1)
        except httpx.HTTPError:
            hits = []
        if not hits:
            missing.append(name)
            continue
        got = await add(srv, hits[0]["slug"], kind)
        added += [{"asked": name, "title": e["title"], "slug": e["slug"]} for e in got] or [{"asked": name, "title": hits[0]["title"], "slug": hits[0]["slug"], "already": True}]
    return {"added": added, "missing": missing}


def remove(sid: str, slug: str) -> None:
    cfg = get(sid)
    cfg["extra"] = [e for e in cfg["extra"] if e["slug"] != slug]
    save(sid, cfg)


async def check_updates(sid: str, mc: str) -> list[dict]:
    """Newer versions for this Minecraft version, without changing anything."""
    out = []
    for e in get(sid)["extra"]:
        try:
            n = await resolve(e["slug"], mc, e["kind"])
        except httpx.HTTPError:
            n = None
        if n and n["version_id"] != e["version_id"]:
            out.append({"slug": e["slug"], "title": e["title"], "current": e["version"], "latest": n["version"]})
    return out


async def update_all(sid: str, mc: str) -> list[dict]:
    cfg = get(sid)
    changed = []
    for i, e in enumerate(cfg["extra"]):
        try:
            n = await resolve(e["slug"], mc, e["kind"])
        except httpx.HTTPError:
            continue
        if n and n["version_id"] != e["version_id"]:
            changed.append({"slug": e["slug"], "title": e["title"], "from": e["version"], "to": n["version"]})
            cfg["extra"][i] = n
    save(sid, cfg)
    return changed


# ------------------------------------------------------------------ the pack files
def _q(s: str) -> str:
    return json.dumps(str(s))                  # a TOML basic string (same escapes as JSON)


def _metafile(name: str, filename: str, side: str, url: str, hash_format: str, digest: str) -> str:
    return "\n".join([f"name = {_q(name)}", f"filename = {_q(filename)}", f"side = {_q(side)}", "",
                      "[download]", f"url = {_q(url)}", f"hash-format = {_q(hash_format)}", f"hash = {_q(digest)}", ""])


def files(srv, base_url: str) -> dict[str, str]:
    """Every file of the pack: index.toml, the per-mod metafiles and pack.toml, by path."""
    cfg = get(srv.id)
    base = f"{base_url.rstrip('/')}/api/public/pack/{cfg['token']}"
    out: dict[str, str] = {}
    for m in server_mods(srv):
        if not m["included"]:
            continue
        jar = srv.dir / "mods" / m["file"]
        digest = S._cache.get(("sha256", str(jar)), jar, _sha256)
        if not digest:
            continue
        out[f"mods/{m['id']}.pw.toml"] = _metafile(m["name"], m["file"], "both", f"{base}/jar/{quote(m['file'])}", "sha256", digest)
    for e in cfg["extra"]:
        side = "client"
        out[f"{KINDS[e['kind']]}/{e['slug']}.pw.toml"] = _metafile(e["title"], e["filename"], side, e["url"], "sha512", e["sha512"])
    index = ['hash-format = "sha256"', ""]
    for path, body in sorted(out.items()):
        index += ["[[files]]", f"file = {_q(path)}", f"hash = {_q(hashlib.sha256(body.encode()).hexdigest())}", "metafile = true", ""]
    index_text = "\n".join(index)
    versions = [f"minecraft = {_q(srv.mc_version or '')}"]
    loader = fabric_loader_version(srv)
    if loader:
        versions.append(f"fabric = {_q(loader)}")
    pack = "\n".join([f"name = {_q(srv.display_name)}", 'author = "Solstone"',
                      f"version = {_q(hashlib.sha256(index_text.encode()).hexdigest()[:12])}", 'pack-format = "packwiz:1.1.0"', "",
                      "[index]", 'file = "index.toml"', 'hash-format = "sha256"', f"hash = {_q(hashlib.sha256(index_text.encode()).hexdigest())}", "",
                      "[versions]", *versions, ""])
    return {"pack.toml": pack, "index.toml": index_text, **out}


def fabric_loader_version(srv) -> str | None:
    """The server's Fabric Loader version, from its log ("- fabricloader 0.19.5")."""
    try:
        with (srv.dir / "logs" / "latest.log").open("rb") as fh:
            head = fh.read(200_000).decode("utf-8", "replace")
    except OSError:
        return None
    m = re.search(r"fabricloader[ @](\d+\.\d+\.\d+)", head)
    return m.group(1) if m else None


# ------------------------------------------------------------------ the installer, for Prism
def bootstrap_path() -> Path:
    return config.data_dir / "packwiz-installer-bootstrap.jar"


async def bootstrap_jar() -> bytes:
    """packwiz-installer-bootstrap.jar (from GitHub, kept after the first download)."""
    p = bootstrap_path()
    if p.is_file() and p.stat().st_size > 1000:
        return p.read_bytes()
    async with httpx.AsyncClient(timeout=30, headers={"User-Agent": UA}, follow_redirects=True) as c:
        r = await c.get(BOOTSTRAP_URL)
        r.raise_for_status()
        p.write_bytes(r.content)
        return r.content


def prism_command(pack_url: str) -> str:
    return f'"$INST_JAVA" -jar packwiz-installer-bootstrap.jar {pack_url}'
