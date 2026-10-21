"""A top-down map of the world, drawn from the region files (no mods needed).

Each region file (32 x 32 chunks, 512 x 512 blocks) becomes one 512 x 512 PNG: the top block
of every column, coloured from the game's own block textures, shaded by height the way
Minecraft's maps are, with water drawn by depth. The Nether shows the cave floor under its
ceiling. Pictures are cached and redrawn only when the region file changes (at most every
few minutes), one at a time in the background.
"""
from __future__ import annotations

import io
import json
import logging
import struct
import threading
import time
import zlib
from pathlib import Path

import numpy as np
from PIL import Image

from .config import config

log = logging.getLogger("solstone.worldmap")

TILE = 512
REDRAW_AFTER = 300            # seconds: a busy region is redrawn at most this often
_AIR = {"air", "cave_air", "void_air", "light", "barrier", "structure_void"}
_WATERY = {"water", "bubble_column", "kelp", "kelp_plant", "seagrass", "tall_seagrass"}

# ------------------------------------------------------------------ a small NBT reader
# Region chunks are big; only the block palettes, packed block data and section heights
# are needed, so everything else is skipped without being decoded.
_WANT = {"sections", "Sections", "Level", "block_states", "palette", "Palette", "data", "BlockStates", "Y", "Name", "yPos"}


class _R:
    __slots__ = ("b", "i")

    def __init__(self, b: bytes) -> None:
        self.b, self.i = b, 0

    def u8(self) -> int:
        v = self.b[self.i]; self.i += 1; return v

    def i16(self) -> int:
        v = struct.unpack_from(">h", self.b, self.i)[0]; self.i += 2; return v

    def i32(self) -> int:
        v = struct.unpack_from(">i", self.b, self.i)[0]; self.i += 4; return v

    def s(self) -> str:
        n = struct.unpack_from(">H", self.b, self.i)[0]; self.i += 2
        v = self.b[self.i:self.i + n].decode("utf-8", "replace"); self.i += n; return v


_SIZES = {1: 1, 2: 2, 3: 4, 4: 8, 5: 4, 6: 8}


def _skip(r: _R, t: int) -> None:
    if t in _SIZES:
        r.i += _SIZES[t]
    elif t == 7:
        r.i += r.i32()
    elif t == 8:
        r.i += struct.unpack_from(">H", r.b, r.i)[0] + 2
    elif t == 9:
        et, n = r.u8(), r.i32()
        if et in _SIZES:
            r.i += _SIZES[et] * n
        else:
            for _ in range(n):
                _skip(r, et)
    elif t == 10:
        while True:
            ct = r.u8()
            if ct == 0:
                return
            r.i += struct.unpack_from(">H", r.b, r.i)[0] + 2
            _skip(r, ct)
    elif t == 11:
        r.i += 4 * r.i32()
    elif t == 12:
        r.i += 8 * r.i32()


def _val(r: _R, t: int):
    if t == 1:
        v = struct.unpack_from(">b", r.b, r.i)[0]; r.i += 1; return v
    if t == 2:
        return r.i16()
    if t == 3:
        return r.i32()
    if t == 8:
        return r.s()
    if t == 10:
        return _compound(r)
    if t == 9:
        et, n = r.u8(), r.i32()
        if et == 10:
            return [_compound(r) for _ in range(n)]
        if et == 8:
            return [r.s() for _ in range(n)]
        for _ in range(n):
            _skip(r, et)
        return []
    if t == 12:
        n = r.i32()
        arr = np.frombuffer(r.b, dtype=">i8", count=n, offset=r.i).astype(np.int64)
        r.i += 8 * n
        return arr
    _skip(r, t)
    return None


def _compound(r: _R) -> dict:
    out = {}
    while True:
        t = r.u8()
        if t == 0:
            return out
        name = r.s()
        if name in _WANT:
            out[name] = _val(r, t)
        else:
            _skip(r, t)


def read_chunk(raw: bytes) -> dict:
    r = _R(raw)
    t = r.u8()
    if t != 10:
        return {}
    r.s()
    return _compound(r)


# ------------------------------------------------------------------ block colours
_COLOR_CACHE: dict[str, dict[str, tuple[int, int, int]]] = {}
_FALLBACK = {
    "water": (63, 118, 228), "lava": (207, 92, 20), "sand": (219, 207, 163), "gravel": (136, 126, 126), "snow": (249, 254, 254),
    "ice": (145, 183, 253), "grass": (124, 189, 107), "leaves": (89, 174, 48), "log": (102, 81, 51), "wood": (102, 81, 51),
    "planks": (162, 130, 78), "dirt": (134, 96, 67), "stone": (125, 125, 125), "deepslate": (80, 80, 82), "netherrack": (97, 38, 38),
    "end_stone": (219, 222, 158), "terracotta": (152, 94, 67), "clay": (160, 166, 179), "mud": (60, 57, 61), "moss": (89, 109, 45),
}
_TINTS = {
    "grass_block": (145, 189, 89), "short_grass": (145, 189, 89), "grass": (145, 189, 89), "tall_grass": (145, 189, 89), "fern": (145, 189, 89),
    "large_fern": (145, 189, 89), "sugar_cane": (145, 189, 89), "oak_leaves": (89, 174, 48), "jungle_leaves": (89, 174, 48), "acacia_leaves": (89, 174, 48),
    "dark_oak_leaves": (89, 174, 48), "mangrove_leaves": (89, 174, 48), "vine": (89, 174, 48), "birch_leaves": (128, 167, 85),
    "spruce_leaves": (97, 153, 97), "water": (63, 118, 228), "bubble_column": (63, 118, 228), "lily_pad": (32, 128, 48), "attached_melon_stem": (89, 174, 48),
}
_SUFFIXES = ("_slab", "_stairs", "_wall", "_fence_gate", "_fence", "_button", "_pressure_plate", "_trapdoor", "_door", "_sign", "_wall_sign", "_hanging_sign", "_carpet")


def _avg(img: Image.Image) -> tuple[int, int, int] | None:
    a = np.asarray(img.convert("RGBA"), dtype=np.float32).reshape(-1, 4)
    a = a[a[:, 3] > 20]
    if not len(a):
        return None
    return tuple(int(x) for x in a[:, :3].mean(axis=0))


def _candidates(name: str) -> list[str]:
    n = name
    out = [f"block/{n}_top", f"block/{n}"]
    for suf in _SUFFIXES:
        if n.endswith(suf):
            base = n[: -len(suf)]
            out += [f"block/{base}_planks", f"block/{base}s", f"block/{base}", f"block/{base}_top", f"block/{base}_block"]
    if n.endswith(("_log", "_stem")):
        out.insert(0, f"block/{n}_top")
    if n.endswith("_wood"):
        out.append(f"block/{n[:-5]}_log")
    if n in ("water", "lava"):
        out.insert(0, f"block/{n}_still")
    if n in ("dirt_path",):
        out.insert(0, "block/dirt_path_top")
    if n.startswith("potted_") or n.endswith("_bed"):
        out.append("block/dirt" if n.startswith("potted_") else "block/red_wool")
    return out


def _fallback(name: str) -> tuple[int, int, int]:
    for k, c in _FALLBACK.items():
        if k in name:
            return c
    return (128, 128, 128)


class Colors:
    """Block name -> map colour, from the textures of the server's Minecraft version (and mods)."""

    def __init__(self, assets) -> None:
        self.a = assets
        key = assets.cache_key if assets else "none"
        self.cache = _COLOR_CACHE.setdefault(key, {})
        self.file = config.data_dir / "maptiles" / f"colors-{key}.json"
        if not self.cache and self.file.is_file():
            try:
                self.cache.update({k: tuple(v) for k, v in json.loads(self.file.read_text()).items()})
            except (OSError, ValueError):
                pass
        self.dirty = False

    def of(self, full: str) -> tuple[int, int, int]:
        c = self.cache.get(full)
        if c is not None:
            return c
        ns, _, name = full.partition(":") if ":" in full else ("minecraft", "", full)
        color = None
        if self.a is not None and self.a.ready:
            for ref in _candidates(name):
                try:
                    img = self.a.texture(f"{ns}:{ref}")
                except Exception:
                    img = None
                if img is not None:
                    color = _avg(img)
                    if color:
                        break
        color = color or _fallback(name)
        tint = _TINTS.get(name)
        if tint:
            g = sum(color) / 3 / 255
            color = tuple(int(tint[i] * (0.55 + 0.6 * g)) for i in range(3))
        color = tuple(max(0, min(255, int(v))) for v in color)
        self.cache[full] = color
        self.dirty = True
        return color

    def save(self) -> None:
        if self.dirty:
            try:
                self.file.parent.mkdir(parents=True, exist_ok=True)
                self.file.write_text(json.dumps(self.cache))
            except OSError:
                pass
            self.dirty = False


# ------------------------------------------------------------------ chunks -> pixels
def _unpack(data: np.ndarray | None, n_palette: int, count: int = 4096) -> np.ndarray:
    if n_palette <= 1 or data is None or not len(data):
        return np.zeros(count, dtype=np.int32)
    bits = max(4, int(np.ceil(np.log2(n_palette))))
    per = 64 // bits
    shifts = (np.arange(per, dtype=np.uint64) * np.uint64(bits))
    vals = (data.view(np.uint64)[:, None] >> shifts[None, :]) & np.uint64((1 << bits) - 1)
    return vals.reshape(-1)[:count].astype(np.int32)


def _short(name: str) -> str:
    return name.split(":", 1)[-1]


def render_chunk(nbt: dict, colors: Colors, nether: bool) -> tuple[np.ndarray, np.ndarray] | None:
    """16x16 colours and heights for one chunk (None if it has no block data)."""
    lvl = nbt.get("Level") if isinstance(nbt.get("Level"), dict) else nbt
    sections = lvl.get("sections") or lvl.get("Sections") or []
    layers = []                                   # (y, names, idx[16,16,16])
    for s in sections:
        bs = s.get("block_states")
        palette = bs.get("palette") if isinstance(bs, dict) else s.get("Palette")
        data = bs.get("data") if isinstance(bs, dict) else s.get("BlockStates")
        if not palette:
            continue
        names = [p.get("Name", "minecraft:air") if isinstance(p, dict) else "minecraft:air" for p in palette]
        if all(_short(n) in _AIR for n in names):
            continue
        idx = _unpack(data, len(names)).reshape(16, 16, 16)          # y, z, x
        layers.append((int(s.get("Y", 0)), names, idx))
    if not layers:
        return None
    layers.sort(key=lambda x: -x[0])
    top_y = layers[0][0] * 16 + 15
    bottom_y = layers[-1][0] * 16
    height = top_y - bottom_y + 1
    # one column of names per block, top down: build a palette-wide id table
    gids: dict[str, int] = {}
    vol = np.zeros((height, 16, 16), dtype=np.int32)                # 0 = air
    for y0, names, idx in layers:
        table = np.array([0 if _short(n) in _AIR else gids.setdefault(n, len(gids) + 1) for n in names], dtype=np.int32)
        start = top_y - (y0 * 16 + 15)
        vol[start:start + 16] = table[idx][::-1]
    names_by_id = {v: k for k, v in gids.items()}
    solid = vol != 0
    if nether:                                     # look under the bedrock ceiling: start at y 100
        cut = max(0, top_y - 100)
        sub = solid[cut:]
        opened = np.zeros_like(sub)
        opened[1:] = sub[1:] & ~sub[:-1]
        opened[0] = sub[0] & False
        has = opened.any(axis=0)
        first = np.where(has, opened.argmax(axis=0) + cut, solid.argmax(axis=0))
    else:
        has = solid.any(axis=0)
        first = solid.argmax(axis=0)
    zz, xx = np.meshgrid(np.arange(16), np.arange(16), indexing="ij")
    ids = vol[first, zz, xx]
    rgb = np.zeros((16, 16, 3), dtype=np.float32)
    heights = (top_y - first).astype(np.int32)
    water_ids = {gid for n, gid in gids.items() if _short(n) in _WATERY}
    for gid in np.unique(ids):
        if gid == 0:
            continue
        rgb[ids == gid] = colors.of(names_by_id[gid])
    if water_ids:                                  # water: darker the deeper it is
        wmask = np.isin(vol, list(water_ids))
        top_is_water = np.isin(ids, list(water_ids))
        if top_is_water.any():
            depth = np.zeros((16, 16), dtype=np.int32)
            for z in range(16):
                for x in range(16):
                    if top_is_water[z, x]:
                        col = wmask[first[z, x]:, z, x]
                        d = int(np.argmin(col)) if not col.all() else len(col)
                        depth[z, x] = d
            shade = np.clip(1.15 - depth / 28.0, 0.55, 1.15)[..., None]
            rgb = np.where(top_is_water[..., None], rgb * shade, rgb)
    rgb[~has] = 0
    heights[~has] = -9999
    return rgb, heights


def _shade(rgb: np.ndarray, heights: np.ndarray) -> np.ndarray:
    """Minecraft-map style relief: brighter where the ground rises northwards, darker where it falls."""
    north = np.vstack([heights[:1], heights[:-1]])
    diff = heights - north
    f = np.where(diff > 0, 1.12, np.where(diff < 0, 0.84, 1.0))[..., None]
    out = np.clip(rgb * f, 0, 255)
    out[heights == -9999] = 0
    return out


def render_region(path: Path, colors: Colors, nether: bool = False) -> Image.Image | None:
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if len(data) < 8192:
        return None
    rgb = np.zeros((TILE, TILE, 3), dtype=np.float32)
    heights = np.full((TILE, TILE), -9999, dtype=np.int32)
    alpha = np.zeros((TILE, TILE), dtype=np.uint8)
    for i in range(1024):
        loc = struct.unpack_from(">I", data, i * 4)[0]
        if not loc:
            continue
        off = (loc >> 8) * 4096
        if off + 5 > len(data):
            continue
        length, ctype = struct.unpack_from(">IB", data, off)
        body = data[off + 5: off + 4 + length]
        try:
            if ctype == 2:
                raw = zlib.decompress(body)
            elif ctype == 1:
                import gzip
                raw = gzip.decompress(body)
            elif ctype == 3:
                raw = body
            else:
                continue                            # LZ4 or an external file: skip that chunk
            got = render_chunk(read_chunk(raw), colors, nether)
        except Exception as e:
            log.debug("chunk %d in %s: %s", i, path.name, e)
            continue
        if not got:
            continue
        cx, cz = i % 32, i // 32
        c_rgb, c_h = got
        rgb[cz * 16:cz * 16 + 16, cx * 16:cx * 16 + 16] = c_rgb
        heights[cz * 16:cz * 16 + 16, cx * 16:cx * 16 + 16] = c_h
        alpha[cz * 16:cz * 16 + 16, cx * 16:cx * 16 + 16] = np.where(c_h != -9999, 255, 0)
    if not alpha.any():
        return None
    out = _shade(rgb, heights).astype(np.uint8)
    return Image.fromarray(np.dstack([out, alpha]), "RGBA")


# ------------------------------------------------------------------ files, cache and the queue
def region_dir(world: Path, dim: str) -> Path | None:
    simple = {"minecraft:overworld": world / "region", "minecraft:the_nether": world / "DIM-1" / "region", "minecraft:the_end": world / "DIM1" / "region"}
    if dim in simple and simple[dim].is_dir():
        return simple[dim]
    ns, _, rest = dim.partition(":")
    p = world / "dimensions" / ns / rest / "region"
    return p if p.is_dir() else None


def regions(world: Path, dim: str) -> list[list[int]]:
    d = region_dir(world, dim)
    out = []
    if d:
        for f in d.glob("r.*.*.mca"):
            try:
                _, x, z, _ = f.name.split(".")
                if f.stat().st_size >= 8192:
                    out.append([int(x), int(z)])
            except (ValueError, OSError):
                continue
    return out


def _tile_path(sid: str, dim: str, rx: int, rz: int) -> Path:
    return config.data_dir / "maptiles" / sid / dim.replace(":", "_").replace("/", "_") / f"{rx}.{rz}.png"


_queue: list[tuple] = []
_queued: set = set()
_qlock = threading.Lock()
_worker: threading.Thread | None = None


def _work() -> None:
    while True:
        with _qlock:
            if not _queue:
                global _worker
                _worker = None
                return
            job = _queue.pop(0)
        key, src, dst, assets, nether = job
        try:
            colors = Colors(assets)
            img = render_region(src, colors, nether)
            colors.save()
            dst.parent.mkdir(parents=True, exist_ok=True)
            if img is None:
                img = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
            buf = io.BytesIO()
            img.save(buf, "PNG", optimize=False, compress_level=6)
            tmp = dst.with_suffix(".tmp")
            tmp.write_bytes(buf.getvalue())
            tmp.replace(dst)
        except Exception:
            log.exception("map tile %s failed", key)
        finally:
            with _qlock:
                _queued.discard(key)


def tile(sid: str, world: Path, dim: str, rx: int, rz: int, assets) -> tuple[str, Path | None]:
    """('ready', path) when there's a picture (maybe slightly old), ('working', None) while it's
    being drawn for the first time, ('none', None) when that region doesn't exist."""
    global _worker
    d = region_dir(world, dim)
    src = d / f"r.{rx}.{rz}.mca" if d else None
    if not src or not src.is_file():
        return "none", None
    dst = _tile_path(sid, dim, rx, rz)
    try:
        src_m = src.stat().st_mtime
        dst_m = dst.stat().st_mtime if dst.is_file() else 0
    except OSError:
        return "none", None
    stale = dst_m < src_m and time.time() - dst_m > REDRAW_AFTER
    if not dst_m or stale:
        key = (sid, dim, rx, rz)
        with _qlock:
            if key not in _queued:
                _queued.add(key)
                _queue.append((key, src, dst, assets, dim.endswith("the_nether")))
            if _worker is None:
                _worker = threading.Thread(target=_work, daemon=True, name="map-tiles")
                _worker.start()
    return ("ready", dst) if dst_m else ("working", None)
