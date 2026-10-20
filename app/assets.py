"""Game assets: item icons, language strings and advancement definitions.

The Minecraft client jar for the server's version is downloaded once from
Mojang's official launcher endpoints and the parts we need are extracted to
DATA_DIR/assets/<version>/. Item icons are rendered on demand (flat items and
isometric blocks) and cached as PNGs. Fabric/Quilt mod jars in the server's
mods folder are used as extra asset sources for modded items.
"""
from __future__ import annotations

import io
import json
import logging
import math
import re
import shutil
import threading
import zipfile
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx
import numpy as np
from PIL import Image, ImageDraw

from .config import config

log = logging.getLogger("lodestone.assets")

MANIFEST = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
KEEP_PREFIXES = (
    "assets/minecraft/textures/item/",
    "assets/minecraft/textures/block/",
    "assets/minecraft/textures/mob_effect/",
    "assets/minecraft/textures/gui/sprites/hud/",
    "assets/minecraft/textures/gui/sprites/advancements/",
    "assets/minecraft/textures/gui/sprites/container/",
    "assets/minecraft/textures/entity/chest/",
    "assets/minecraft/models/",
    "assets/minecraft/items/",
    "assets/minecraft/lang/en_us.json",
    "data/minecraft/advancement/",
    "data/minecraft/advancements/",
)
_SAFE = re.compile(r"^[a-z0-9_./-]+$")
ICON = 64          # output icon size
SS = 4             # supersampling for isometric renders


# =============================================================== download / store
class VersionStore:
    def __init__(self, version: str) -> None:
        self.version = version
        self.dir = config.data_dir / "assets" / re.sub(r"[^A-Za-z0-9._-]", "_", version)
        self.state = "ready" if (self.dir / ".complete").exists() else "missing"
        self.error: str | None = None
        self.progress = 0.0
        self._thread: threading.Thread | None = None

    def ensure(self) -> None:
        if self.state in ("ready", "downloading"):
            return
        manual = self.dir / "client.jar"
        if not config.download_assets and not manual.exists():
            self.state, self.error = "disabled", "Asset download disabled (DOWNLOAD_ASSETS=false)"
            return
        self.state = "downloading"
        self._thread = threading.Thread(target=self._download, daemon=True)
        self._thread.start()

    def _download(self) -> None:
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            jar = self.dir / "client.jar"
            if not jar.exists():
                with httpx.Client(timeout=60, follow_redirects=True) as c:
                    manifest = c.get(MANIFEST).json()
                    entry = next((v for v in manifest["versions"] if v["id"] == self.version), None)
                    if not entry:
                        raise RuntimeError(f"Version {self.version} not found in Mojang manifest")
                    meta = c.get(entry["url"]).json()
                    url = meta["downloads"]["client"]["url"]
                    size = meta["downloads"]["client"].get("size") or 1
                    tmp = jar.with_suffix(".part")
                    with c.stream("GET", url) as r, tmp.open("wb") as fh:
                        r.raise_for_status()
                        done = 0
                        for chunk in r.iter_bytes(1 << 16):
                            fh.write(chunk)
                            done += len(chunk)
                            self.progress = min(done / size, 1.0) * 0.9
                    tmp.replace(jar)
            with zipfile.ZipFile(jar) as z:
                members = [m for m in z.namelist() if m.startswith(KEEP_PREFIXES) and not m.endswith("/")]
                for i, m in enumerate(members):
                    target = self.dir / "x" / m
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(m) as src, target.open("wb") as dst:
                        shutil.copyfileobj(src, dst)
                    self.progress = 0.9 + 0.1 * (i / max(len(members), 1))
            if config.download_assets:
                jar.unlink(missing_ok=True)  # keep only what we extracted (~10 MB)
            (self.dir / ".complete").write_text(self.version)
            self.state, self.progress = "ready", 1.0
            log.info("Assets for %s ready", self.version)
        except Exception as e:
            self.state, self.error = "error", f"{type(e).__name__}: {e}"
            log.warning("Asset download for %s failed: %s", self.version, self.error)

    def status(self) -> dict:
        return {"version": self.version, "state": self.state, "progress": round(self.progress, 3),
                "error": self.error}

    def path(self, rel: str) -> Path:
        return self.dir / "x" / rel


_stores: dict[str, VersionStore] = {}
_stores_lock = threading.Lock()


def store(version: str) -> VersionStore:
    with _stores_lock:
        if version not in _stores:
            _stores[version] = VersionStore(version)
        return _stores[version]


# =============================================================== asset source
class Assets:
    """Reads asset files from the extracted client jar plus mod jars."""

    def __init__(self, version: str, mod_jars: list[Path], cache_key: str) -> None:
        self.vs = store(version)
        self.mod_jars = mod_jars
        self.cache_key = cache_key
        self._index: dict[str, Path] | None = None

    @property
    def ready(self) -> bool:
        return self.vs.state == "ready"

    def _mod_index(self) -> dict[str, Path]:
        if self._index is None:
            idx: dict[str, Path] = {}
            for jar in self.mod_jars:
                try:
                    with zipfile.ZipFile(jar) as z:
                        for n in z.namelist():
                            if n.startswith(("assets/", "data/")) and not n.endswith("/"):
                                idx.setdefault(n, jar)
                except Exception:
                    continue
            self._index = idx
        return self._index

    def read(self, rel: str) -> bytes | None:
        if rel.startswith(("assets/minecraft/", "data/minecraft/")):
            p = self.vs.path(rel)
            if p.is_file():
                return p.read_bytes()
        jar = self._mod_index().get(rel)
        if jar:
            try:
                with zipfile.ZipFile(jar) as z:
                    return z.read(rel)
            except Exception:
                return None
        return None

    def json(self, rel: str) -> Any:
        raw = self.read(rel)
        if raw is None:
            return None
        try:
            return json.loads(raw.decode("utf-8", "replace"))
        except Exception:
            return None

    def texture(self, ref: str) -> Image.Image | None:
        ns, path = split_ref(ref)
        raw = self.read(f"assets/{ns}/textures/{path}.png")
        if raw is None:
            return None
        img = Image.open(io.BytesIO(raw)).convert("RGBA")
        if img.height > img.width and img.height % img.width == 0:  # animated strip
            img = img.crop((0, 0, img.width, img.width))
        return img

    # ------------------------------------------------------------ lang
    def lang(self) -> dict[str, str]:
        out: dict[str, str] = {}
        base = self.json("assets/minecraft/lang/en_us.json")
        if isinstance(base, dict):
            out.update(base)
        for rel in self._mod_index():
            if rel.endswith("/lang/en_us.json"):
                d = self.json(rel)
                if isinstance(d, dict):
                    out.update({k: v for k, v in d.items() if isinstance(v, str)})
        return out

    # ------------------------------------------------------------ advancements
    def advancements(self) -> list[dict]:
        out = []
        for sub in ("advancement", "advancements"):
            root = self.vs.path(f"data/minecraft/{sub}")
            if not root.is_dir():
                continue
            for f in root.rglob("*.json"):
                rel = f.relative_to(root).with_suffix("").as_posix()
                if rel.startswith("recipes/"):
                    continue
                try:
                    d = json.loads(f.read_text(encoding="utf-8"))
                except Exception:
                    continue
                disp = d.get("display")
                if not disp:
                    continue
                icon = disp.get("icon") or {}
                out.append({
                    "id": f"minecraft:{rel}",
                    "category": rel.split("/", 1)[0],
                    "parent": d.get("parent"),
                    "title": disp.get("title"),
                    "description": disp.get("description"),
                    "icon": icon.get("id") or icon.get("item"),
                    "frame": disp.get("frame", "task"),
                    "hidden": bool(disp.get("hidden", False)),
                })
            if out:
                break
        return out

    # ------------------------------------------------------------ icons
    def icon_path(self, item_id: str) -> Path:
        ns, name = split_ref(item_id)
        sub = "vanilla" if ns == "minecraft" else f"mods-{self.cache_key}"
        return self.vs.dir / "icons" / sub / ns / f"{name}.png"

    def icon(self, item_id: str) -> bytes | None:
        p = self.icon_path(item_id)
        if p.is_file():
            return p.read_bytes()
        try:
            img = render_item(self, item_id)
        except Exception as e:
            log.debug("render failed for %s: %s", item_id, e)
            img = None
        if img is None:
            return None
        buf = io.BytesIO()
        img.save(buf, "PNG", optimize=True)
        data = buf.getvalue()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return data


def split_ref(ref: str) -> tuple[str, str]:
    ref = str(ref)
    if ":" in ref:
        ns, path = ref.split(":", 1)
    else:
        ns, path = "minecraft", ref
    return ns, path


# =============================================================== model resolution
def _find_model_ref(node: Any) -> str | None:
    """Walk a 1.21.4+ item definition to its most representative model."""
    if not isinstance(node, dict):
        return None
    t = str(node.get("type", "")).replace("minecraft:", "")
    if t == "model":
        return node.get("model")
    if t == "special":
        return node.get("base")
    for key in ("fallback", "on_false", "on_true"):
        r = _find_model_ref(node.get(key))
        if r:
            return r
    for key in ("models",):
        for m in node.get(key) or []:
            r = _find_model_ref(m)
            if r:
                return r
    for key in ("cases", "entries"):
        for c in node.get(key) or []:
            r = _find_model_ref(c.get("model") if isinstance(c, dict) else None)
            if r:
                return r
    return None


def _definition_tints(node: Any) -> list[int | None]:
    tints = []
    if isinstance(node, dict):
        t = str(node.get("type", "")).replace("minecraft:", "")
        if t == "model":
            for tint in node.get("tints") or []:
                tt = str(tint.get("type", "")).replace("minecraft:", "")
                val = tint.get("value", tint.get("default"))
                if isinstance(val, list) and len(val) >= 3:  # [r,g,b] floats
                    val = (int(val[0] * 255) << 16) | (int(val[1] * 255) << 8) | int(val[2] * 255)
                if val is None:
                    val = {"grass": 0x7CBD6B, "foliage": 0x48B518, "dye": 0xA06540,
                           "potion": 0x385DC6, "firework": 0x8A8A8A, "map_color": 0x46402E}.get(tt)
                tints.append(int(val) & 0xFFFFFF if val is not None else None)
            return tints
        for key in ("fallback", "on_false", "on_true", "base"):
            if key in node:
                r = _definition_tints(node[key])
                if r:
                    return r
        for m in node.get("models") or []:
            r = _definition_tints(m)
            if r:
                return r
        for key in ("cases", "entries"):
            for c in node.get(key) or []:
                r = _definition_tints(c.get("model") if isinstance(c, dict) else None)
                if r:
                    return r
    return tints


def resolve_model(a: Assets, ref: str, depth: int = 0) -> dict:
    """Merge a model with its parents. Returns textures, elements, kind."""
    ns, path = split_ref(ref)
    if path in ("builtin/generated",):
        return {"textures": {}, "elements": None, "kind": "generated"}
    if path in ("builtin/entity",):
        return {"textures": {}, "elements": None, "kind": "entity"}
    model = a.json(f"assets/{ns}/models/{path}.json")
    if model is None or depth > 20:
        return {"textures": {}, "elements": None, "kind": "missing"}
    parent = model.get("parent")
    base = resolve_model(a, parent, depth + 1) if parent else {"textures": {}, "elements": None, "kind": "none"}
    textures = {**base["textures"], **(model.get("textures") or {})}
    elements = model.get("elements") if model.get("elements") is not None else base["elements"]
    kind = base["kind"]
    if model.get("elements") is not None:
        kind = "elements"
    if kind in ("none", "missing") and elements:
        kind = "elements"
    return {"textures": textures, "elements": elements, "kind": kind}


def resolve_texture(textures: dict, ref: str | None, depth: int = 0) -> str | None:
    if ref is None or depth > 10:
        return None
    if isinstance(ref, dict):  # 1.21.x {"sprite": ...}
        ref = ref.get("sprite")
    if isinstance(ref, str) and ref.startswith("#"):
        return resolve_texture(textures, textures.get(ref[1:]), depth + 1)
    return ref


# =============================================================== rendering
def render_item(a: Assets, item_id: str) -> Image.Image | None:
    if not a.ready and split_ref(item_id)[0] == "minecraft":
        return None
    ns, name = split_ref(item_id)
    definition = a.json(f"assets/{ns}/items/{name}.json")
    tints: list[int | None] = []
    model_ref = None
    if isinstance(definition, dict) and "model" in definition:
        model_ref = _find_model_ref(definition["model"])
        tints = _definition_tints(definition["model"])
    if not model_ref:
        model_ref = f"{ns}:item/{name}"
    model = resolve_model(a, model_ref)
    if model["kind"] == "missing":
        alt = resolve_model(a, f"{ns}:block/{name}")
        if alt["kind"] != "missing":
            model = alt
    tex = model["textures"]

    if model["kind"] == "generated":
        layers = []
        i = 0
        while f"layer{i}" in tex:
            layers.append(resolve_texture(tex, tex[f"layer{i}"]))
            i += 1
        img = _flat(a, layers, tints, item_id)
        if img is not None:
            return img
    if model["kind"] == "elements" and model["elements"]:
        img = render_elements(a, model["elements"], tex, tints)
        if img is not None:
            return img
    # Special/entity models (chests, beds, heads...): draw the particle texture as a cube
    particle = resolve_texture(tex, tex.get("particle"))
    if particle:
        img = render_elements(a, [_full_cube("#particle")], {"particle": particle}, [])
        if img is not None:
            return img
    # Last resorts: a bare texture with the item's name
    for ref in (f"{ns}:item/{name}", f"{ns}:block/{name}"):
        img = _flat(a, [ref], [], item_id)
        if img is not None:
            return img
    return None


def _full_cube(t: str) -> dict:
    faces = {f: {"texture": t} for f in ("up", "down", "north", "south", "east", "west")}
    return {"from": [0, 0, 0], "to": [16, 16, 16], "faces": faces}


def _tint(img: Image.Image, color: int | None, shade: float = 1.0) -> Image.Image:
    if color is None and shade == 1.0:
        return img
    arr = np.asarray(img).astype(np.float32)
    if color is not None:
        rgb = np.array([(color >> 16) & 255, (color >> 8) & 255, color & 255], np.float32) / 255
        arr[..., :3] *= rgb
    arr[..., :3] *= shade
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGBA")


def _flat(a: Assets, layers: list[str | None], tints: list, item_id: str) -> Image.Image | None:
    base: Image.Image | None = None
    for i, ref in enumerate(layers):
        if not ref:
            continue
        t = a.texture(ref)
        if t is None:
            continue
        tint = tints[i] if i < len(tints) else None
        if tint is None and i == 0 and "leather_" in item_id and ref.endswith(("leather_helmet", "leather_chestplate",
                                                                           "leather_leggings", "leather_boots",
                                                                           "leather_horse_armor")):
            tint = 0xA06540
        t = _tint(t, tint)
        if base is None:
            base = Image.new("RGBA", t.size, (0, 0, 0, 0))
        if t.size != base.size:
            t = t.resize(base.size, Image.NEAREST)
        base.alpha_composite(t)
    if base is None:
        return None
    return base.resize((ICON, ICON), Image.NEAREST)


C45 = math.cos(math.radians(45))
C30, S30 = math.cos(math.radians(30)), math.sin(math.radians(30))
SHADE = {"up": 1.0, "north": 0.8, "west": 0.62}


def _project(x: float, y: float, z: float) -> tuple[float, float]:
    """Isometric GUI view: north face on the left, west face on the right."""
    return (z - x) * C45, -y * C30 - (x + z) * C45 * S30


def _depth(x: float, y: float, z: float) -> float:
    return (x + z) * C45 * C30 - y * S30


def _affine(dst: list[tuple[float, float]], src: list[tuple[float, float]]) -> tuple:
    """Coefficients mapping output (dst) points to input (src) points for PIL AFFINE."""
    A = np.array([[dx, dy, 1.0] for dx, dy in dst])
    bx = np.array([s[0] for s in src])
    by = np.array([s[1] for s in src])
    a, b, c = np.linalg.solve(A, bx)
    d, e, f = np.linalg.solve(A, by)
    return (a, b, c, d, e, f)


def render_elements(a: Assets, elements: list, textures: dict, tints: list) -> Image.Image | None:
    size = ICON * SS
    # Fit a full block into the canvas so slabs/stairs keep their proportions.
    corners = [_project(x, y, z) for x in (0, 16) for y in (0, 16) for z in (0, 16)]
    minx, maxx = min(c[0] for c in corners), max(c[0] for c in corners)
    miny, maxy = min(c[1] for c in corners), max(c[1] for c in corners)
    margin = size * 0.04
    scale = (size - 2 * margin) / max(maxx - minx, maxy - miny)
    offx = (size - (maxx - minx) * scale) / 2 - minx * scale
    offy = (size - (maxy - miny) * scale) / 2 - miny * scale

    def scr(x, y, z):
        px, py = _project(x, y, z)
        return (px * scale + offx, py * scale + offy)

    faces = []
    for el in elements:
        if not isinstance(el, dict) or "from" not in el:
            continue
        x0, y0, z0 = el["from"]
        x1, y1, z1 = el["to"]
        fdefs = el.get("faces") or {}
        geo = {
            "up": [(x0, y1, z0), (x1, y1, z0), (x1, y1, z1), (x0, y1, z1)],
            "north": [(x1, y1, z0), (x0, y1, z0), (x0, y0, z0), (x1, y0, z0)],
            "west": [(x0, y1, z0), (x0, y1, z1), (x0, y0, z1), (x0, y0, z0)],
        }
        default_uv = {
            "up": [x0, z0, x1, z1],
            "north": [16 - x1, 16 - y1, 16 - x0, 16 - y0],
            "west": [z0, 16 - y1, z1, 16 - y0],
        }
        for fname, pts in geo.items():
            fd = fdefs.get(fname)
            if not fd:
                continue
            cx = sum(p[0] for p in pts) / 4
            cy = sum(p[1] for p in pts) / 4
            cz = sum(p[2] for p in pts) / 4
            faces.append((_depth(cx, cy, cz), fname, pts, fd, default_uv[fname]))
    if not faces:
        return None
    faces.sort(key=lambda f: -f[0])  # far to near

    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    drew = False
    for _d, fname, pts, fd, duv in faces:
        ref = resolve_texture(textures, fd.get("texture"))
        tex = a.texture(ref) if ref else None
        if tex is None:
            continue
        tw, th = tex.size
        u0, v0, u1, v1 = fd.get("uv") or duv
        uv = [(u0, v0), (u1, v0), (u1, v1), (u0, v1)]
        k = int(fd.get("rotation", 0)) // 90 % 4
        uv = [uv[(i - k) % 4] for i in range(4)]
        src = [(u * tw / 16, v * th / 16) for u, v in uv]
        dst = [scr(*p) for p in pts]
        try:
            coeffs = _affine([dst[0], dst[1], dst[3]], [src[0], src[1], src[3]])
        except np.linalg.LinAlgError:
            continue
        tint = None
        if "tintindex" in fd:
            ti = int(fd["tintindex"])
            tint = tints[ti] if ti < len(tints) and tints[ti] is not None else 0x7CBD6B
        shaded = _tint(tex, tint, SHADE[fname])
        warped = shaded.transform((size, size), Image.AFFINE, coeffs, resample=Image.NEAREST)
        mask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(mask).polygon(dst, fill=255)
        alpha = Image.fromarray(np.minimum(np.asarray(warped)[..., 3], np.asarray(mask)).astype(np.uint8), "L")
        warped.putalpha(alpha)
        canvas.alpha_composite(warped)
        drew = True
    if not drew:
        return None
    return canvas.resize((ICON, ICON), Image.LANCZOS)


@lru_cache(maxsize=64)
def assets_for(version: str, jars: tuple[str, ...], cache_key: str) -> Assets:
    return Assets(version, [Path(j) for j in jars], cache_key)


def safe_texture_path(path: str) -> str | None:
    path = path.strip("/")
    if not _SAFE.match(path) or ".." in path:
        return None
    return f"assets/minecraft/textures/{path}.png"
