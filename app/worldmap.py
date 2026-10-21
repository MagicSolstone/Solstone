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
        n = r.i32()                     # read first: `r.i += r.i32()` would lose the 4-byte length
        r.i += n
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
        n = r.i32()
        r.i += 4 * n
    elif t == 12:
        n = r.i32()
        r.i += 8 * n


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
    if len(data) != -(-count // per) and len(data) * 64 >= count * bits:
        # 1.13-1.15: values run straight across long boundaries
        bitarr = np.unpackbits(data.astype(">u8").view(np.uint8).reshape(-1, 8)[:, ::-1], axis=1, bitorder="little").reshape(-1)
        bitarr = bitarr[:count * bits].reshape(count, bits)
        return (bitarr.astype(np.int32) << np.arange(bits, dtype=np.int32)).sum(axis=1).astype(np.int32)
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


def _lz4(body: bytes) -> bytes:
    """Minecraft's LZ4 chunks: lz4-java "LZ4Block" frames (magic, token, sizes, checksum, data)."""
    import lz4.block
    out, i = bytearray(), 0
    while i + 21 <= len(body) and body[i:i + 8] == b"LZ4Block":
        token = body[i + 8]
        clen, dlen = struct.unpack_from("<ii", body, i + 9)
        i += 21
        if dlen == 0:
            break
        chunk = body[i:i + clen]
        i += clen
        out += chunk if token & 0xF0 == 0x10 else lz4.block.decompress(chunk, uncompressed_size=dlen)
    return bytes(out)


def _top_keys(raw: bytes) -> list[str]:
    """Names of a chunk's top-level tags (for the map check)."""
    r = _R(raw)
    if r.u8() != 10:
        return []
    r.s()
    out = []
    while r.i < len(r.b):
        t = r.u8()
        if t == 0:
            break
        out.append(r.s())
        _skip(r, t)
    return out


def _decompress(ctype: int, body: bytes, path: Path, i: int) -> bytes | None:
    if ctype & 0x80:                                # too big for the region file: in c.<x>.<z>.mcc beside it
        rx, rz = (int(v) for v in path.name.split(".")[1:3])
        ext = path.with_name(f"c.{rx * 32 + i % 32}.{rz * 32 + i // 32}.mcc")
        body, ctype = ext.read_bytes(), ctype & 0x7F
    if ctype == 2:
        return zlib.decompress(body)
    if ctype == 1:
        import gzip
        return gzip.decompress(body)
    if ctype == 3:
        return body
    if ctype == 4:
        return _lz4(body)                           # region-file-compression=lz4 (1.20.5+)
    raise ValueError(f"unknown compression type {ctype}")


def render_region(path: Path, colors: Colors, nether: bool = False, info: dict | None = None) -> Image.Image | None:
    """The 512x512 picture of one region file. `info`, if given, is filled with what happened:
    chunks, drawn, blank (no blocks), failed, error, compression types and a sample chunk."""
    info = info if info is not None else {}
    info.update(chunks=0, drawn=0, blank=0, failed=0, error="", compression={}, sample=None)
    try:
        data = path.read_bytes()
    except OSError as e:
        info["error"] = f"can't read the file: {e}"
        return None
    info["bytes"] = len(data)
    if len(data) < 8192:
        info["error"] = "file is smaller than a region header"
        return None
    rgb = np.zeros((TILE, TILE, 3), dtype=np.float32)
    heights = np.full((TILE, TILE), -9999, dtype=np.int32)
    alpha = np.zeros((TILE, TILE), dtype=np.uint8)
    for i in range(1024):
        loc = struct.unpack_from(">I", data, i * 4)[0]
        if not loc:
            continue
        info["chunks"] += 1
        off = (loc >> 8) * 4096
        try:
            if off + 5 > len(data):
                raise ValueError("chunk points past the end of the file")
            length, ctype = struct.unpack_from(">IB", data, off)
            info["compression"][str(ctype)] = info["compression"].get(str(ctype), 0) + 1
            if ctype == 0 or length <= 1:           # an allocated slot with nothing in it
                info["blank"] += 1
                continue
            raw = _decompress(ctype, data[off + 5: off + 4 + length], path, i)
            nbt = read_chunk(raw)
            if info["sample"] is None:
                info["sample"] = {"chunk": i, "keys": _top_keys(raw)[:40], "status": "", "sections": 0}
                lvl = nbt.get("Level") if isinstance(nbt.get("Level"), dict) else nbt
                secs = lvl.get("sections") or lvl.get("Sections") or []
                info["sample"]["sections"] = len(secs)
                if secs:
                    info["sample"]["section_keys"] = sorted(secs[len(secs) // 2].keys())
            got = render_chunk(nbt, colors, nether)
        except Exception as e:
            info["failed"] += 1
            info["error"] = info["error"] or f"chunk {i}: {e!r}"[:300]
            continue
        if not got:
            info["blank"] += 1
            continue
        info["drawn"] += 1
        cx, cz = i % 32, i // 32
        c_rgb, c_h = got
        rgb[cz * 16:cz * 16 + 16, cx * 16:cx * 16 + 16] = c_rgb
        heights[cz * 16:cz * 16 + 16, cx * 16:cx * 16 + 16] = c_h
        alpha[cz * 16:cz * 16 + 16, cx * 16:cx * 16 + 16] = np.where(c_h != -9999, 255, 0)
    if info["failed"]:
        log.warning("map %s: %d of %d chunks couldn't be read (first: %s)", path.name, info["failed"], info["chunks"], info["error"])
    elif info["chunks"] and not info["drawn"]:
        log.warning("map %s: none of %d chunks had blocks to draw (sample: %s)", path.name, info["chunks"], info["sample"])
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


RENDER_VERSION = 2          # bump when the drawing changes: older cached tiles are redrawn


def _tile_path(sid: str, dim: str, rx: int, rz: int) -> Path:
    return config.data_dir / "maptiles" / f"v{RENDER_VERSION}" / sid / dim.replace(":", "_").replace("/", "_") / f"{rx}.{rz}.png"


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
            info: dict = {}
            img = render_region(src, colors, nether, info)
            colors.save()
            dst.parent.mkdir(parents=True, exist_ok=True)
            info.pop("sample", None)
            dst.with_suffix(".json").write_text(json.dumps(info))
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


_tidied = False


def _tidy_old_tiles() -> None:
    """Drop tiles drawn by an older renderer (once per start)."""
    global _tidied
    if _tidied:
        return
    _tidied = True
    root = config.data_dir / "maptiles"
    if not root.is_dir():
        return
    import shutil
    for d in root.iterdir():
        if d.is_dir() and d.name != f"v{RENDER_VERSION}":
            shutil.rmtree(d, ignore_errors=True)


def tile_info(path: Path) -> dict:
    try:
        return json.loads(path.with_suffix(".json").read_text())
    except (OSError, ValueError):
        return {}


def check(sid: str, world: Path, dim: str, near: list[tuple[float, float]], assets) -> dict:
    """What the map sees, for the admin's map check: folders, region files, and a fresh
    render of the regions where players are (or the first few) with what went wrong."""
    d = region_dir(world, dim)
    out: dict = {"world": str(world), "world_exists": world.is_dir(), "region_dir": str(d) if d else None,
                 "renderer": RENDER_VERSION, "regions": [], "checked": []}
    if not d:
        out["error"] = "No region folder for this dimension"
        return out
    files = sorted(d.glob("r.*.*.mca"))
    out["regions"] = len(files)
    out["region_sizes"] = {"empty_or_tiny": sum(1 for f in files if f.stat().st_size < 8192)}
    want = {(int(x // 512), int(z // 512)) for x, z in near}
    pick = [f for f in files if tuple(int(v) for v in f.name.split(".")[1:3]) in want] or files[:3]
    colors = Colors(assets)
    for f in pick[:4]:
        info: dict = {"file": f.name}
        img = render_region(f, colors, dim.endswith("the_nether"), info)
        info["picture"] = "drawn" if img is not None else "empty"
        rx, rz = (int(v) for v in f.name.split(".")[1:3])
        cached = _tile_path(sid, dim, rx, rz)
        if cached.is_file():
            try:
                w, h = Image.open(cached).size
                info["cached_tile"] = f"{w}x{h}, {int(time.time() - cached.stat().st_mtime)} s old"
            except OSError as e:
                info["cached_tile"] = f"unreadable: {e}"
        else:
            info["cached_tile"] = "not drawn yet"
        out["checked"].append(info)
    colors.save()
    return out


def tile(sid: str, world: Path, dim: str, rx: int, rz: int, assets) -> tuple[str, Path | None]:
    """('ready', path) when there's a picture (maybe slightly old), ('working', None) while it's
    being drawn for the first time, ('none', None) when that region doesn't exist."""
    global _worker
    _tidy_old_tiles()
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
