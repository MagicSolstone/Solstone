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
import math
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
_WANT = {"sections", "Sections", "Level", "block_states", "BlockStates", "blocks", "palette", "Palette", "data", "Data", "Y", "y",
         "Name", "name", "id", "", "yPos", "xPos", "zPos", "Heightmaps", "WORLD_SURFACE"}


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
def _bits_for(n_longs: int, count: int, n_palette: int) -> tuple[int, bool]:
    """(bits per entry, spans long boundaries) from the array's length. Usually the length
    matches max(4, ceil(log2(palette))) packed whole-entries-per-long, but older worlds pack
    across longs (1.13-1.15) and newer ones may use fewer bits; the length tells which."""
    want = max(4, int(np.ceil(np.log2(n_palette))))
    padded = lambda b: -(-count // (64 // b))                       # noqa: E731
    if n_longs == padded(want):
        return want, False
    need = max(1, int(np.ceil(np.log2(n_palette))))
    for b in range(need, 17):
        if n_longs == padded(b):
            return b, False
    if (n_longs * 64) % count == 0 and n_longs * 64 // count >= need:
        return n_longs * 64 // count, True
    return want, n_longs * 64 >= count * want and n_longs != padded(want)


def _unpack_bits(data: np.ndarray, bits: int, spanning: bool, count: int) -> np.ndarray:
    if spanning:
        bitarr = np.unpackbits(data.astype(">u8").view(np.uint8).reshape(-1, 8)[:, ::-1], axis=1, bitorder="little").reshape(-1)
        bitarr = bitarr[:count * bits].reshape(count, bits)
        return (bitarr.astype(np.int32) << np.arange(bits, dtype=np.int32)).sum(axis=1).astype(np.int32)
    per = 64 // bits
    shifts = (np.arange(per, dtype=np.uint64) * np.uint64(bits))
    vals = (data.view(np.uint64)[:, None] >> shifts[None, :]) & np.uint64((1 << bits) - 1)
    return vals.reshape(-1)[:count].astype(np.int32)


def _unpack(data: np.ndarray | None, n_palette: int, count: int = 4096, stats: dict | None = None) -> np.ndarray:
    if n_palette <= 1 or data is None or not len(data):
        return np.zeros(count, dtype=np.int32)
    bits, spanning = _bits_for(len(data), count, n_palette)
    if stats is not None and not spanning and bits < 4:
        stats["narrow_sections"] = stats.get("narrow_sections", 0) + 1     # fewer bits than the old 4-bit minimum
    out = _unpack_bits(data, bits, spanning, count)
    return np.minimum(out, n_palette - 1)                           # never index past the palette


def _short(name: str) -> str:
    return name.split(":", 1)[-1]


def _block_name(p) -> str:
    """One palette entry, in any of the layouts Minecraft has used:
    {Name: "minecraft:stone", Properties: …} (1.13-1.21), plain text "minecraft:stone"
    (possibly "minecraft:oak_log[axis=y]"), or, in a list mixing both kinds (26.1+),
    {id: "glow_lichen", properties: …} and {"": "deepslate"} for the plain ones."""
    if isinstance(p, dict):
        n = p.get("Name") or p.get("name") or p.get("id") or p.get("") or "minecraft:air"
    elif isinstance(p, str):
        n = p
    else:
        return "minecraft:air"
    n = str(n).split("[", 1)[0].strip()
    return n if ":" in n else f"minecraft:{n}"


def _section_blocks(s: dict) -> tuple[list[str], np.ndarray | None]:
    """(block names in the palette, packed indices) for one section, whatever the layout."""
    bs = next((s[k] for k in ("block_states", "BlockStates", "blocks") if isinstance(s.get(k), dict)), None)
    if bs is not None:
        palette, data = bs.get("palette") or bs.get("Palette"), bs.get("data") if bs.get("data") is not None else bs.get("Data")
    else:                                            # 1.13-1.17: straight on the section
        palette, data = s.get("Palette"), s.get("BlockStates")
    if not palette:
        return [], None
    return [_block_name(p) for p in palette], data


def _surface_from_heightmap(lvl: dict, min_y: int) -> np.ndarray | None:
    """The game's own record of the top block in each column ([z, x], absolute y)."""
    hm = lvl.get("Heightmaps")
    data = hm.get("WORLD_SURFACE") if isinstance(hm, dict) else None
    if data is None or not len(data):
        return None
    bits, spanning = _bits_for(len(data), 256, 512)
    vals = _unpack_bits(data, bits, spanning, 256).reshape(16, 16)
    return np.where(vals > 0, vals - 1 + min_y, -9999)


# Ways a section's 4096 block indices could be laid out: an axis order for the stored (a, b, c)
# relative to (y, z, x), and whether y runs downwards. The first is Minecraft's; the rest are
# only tried when a chunk doesn't match the game's own height map.
_LAYOUTS = [((0, 1, 2), False)] + [((a, b, c), f) for (a, b, c) in
            [(0, 2, 1), (1, 0, 2), (1, 2, 0), (2, 0, 1), (2, 1, 0), (0, 1, 2)] for f in (False, True)
            if ((a, b, c), f) != ((0, 1, 2), False)]


def _layout_name(lay) -> str:
    (a, b, c), flip = lay
    axes = "yzx"
    order = "".join(axes[[a, b, c].index(i)] for i in range(3))
    return order + ("-ydown" if flip else "")


def _volume(layers, top_y: int, height: int, lay, gids: dict[str, int] | None) -> np.ndarray:
    """Top-down volume [height, z, x] of block ids (0 = air) for one layout."""
    perm, flip = lay
    vol = np.zeros((height, 16, 16), dtype=np.int32)
    for y0, names, idx in layers:
        if gids is None:
            table = np.array([0 if _short(n) in _AIR else 1 for n in names], dtype=np.int32)
        else:
            table = np.array([0 if _short(n) in _AIR else gids.setdefault(n, len(gids) + 1) for n in names], dtype=np.int32)
        a = np.transpose(idx, np.argsort(perm)) if perm != (0, 1, 2) else idx      # -> y, z, x
        if flip:
            a = a[::-1]
        start = top_y - (y0 * 16 + 15)
        vol[start:start + 16] = table[a][::-1]
    return vol


def _tops(vol: np.ndarray, top_y: int) -> np.ndarray:
    solid = vol != 0
    has = solid.any(axis=0)
    return np.where(has, top_y - solid.argmax(axis=0), -9999)


def render_chunk(nbt: dict, colors: Colors, nether: bool, stats: dict | None = None) -> tuple[np.ndarray, np.ndarray] | None:
    """16x16 colours and heights for one chunk (None if it has no block data)."""
    stats = stats if stats is not None else {}
    lvl = nbt.get("Level") if isinstance(nbt.get("Level"), dict) else nbt
    sections = lvl.get("sections") or lvl.get("Sections") or []
    layers = []                                   # (y, names, idx[16,16,16] as stored)
    for s in sections:
        names, data = _section_blocks(s)
        if not names or all(_short(n) in _AIR for n in names):
            continue
        idx = _unpack(data, len(names), stats=stats).reshape(16, 16, 16)          # y, z, x in Minecraft's layout
        layers.append((int(s.get("Y", s.get("y", 0))), names, idx))
    if not layers:
        return None
    layers.sort(key=lambda x: -x[0])
    top_y = layers[0][0] * 16 + 15
    bottom_y = layers[-1][0] * 16
    height = top_y - bottom_y + 1

    # Which layout? Check against the game's own height map (the top block of every column).
    # The region's last winner is tried first; the others only when it doesn't fit.
    lay = stats.get("layout_pref") or _LAYOUTS[0]
    if not nether:
        hm = _surface_from_heightmap(lvl, int(lvl.get("yPos", 0)) * 16)   # before 1.18 (no yPos) the world starts at 0
        if hm is not None:
            def score(cand) -> float | None:
                t = _tops(_volume(layers, top_y, height, cand, None), top_y)
                ok = (hm != -9999) & (t != -9999)
                return float((np.abs(t - hm)[ok] <= 1).mean()) if ok.sum() >= 32 else None
            best = score(lay)
            if best is not None:
                if best < 0.9:
                    for cand in _LAYOUTS:
                        if cand == lay:
                            continue
                        sc = score(cand)
                        if sc is not None and sc >= 0.9 and sc > best + 0.15:
                            best, lay = sc, cand
                stats["checked"] = stats.get("checked", 0) + 1
                stats["agree"] = stats.get("agree", 0.0) + best
                stats.setdefault("layouts", {})
                stats["layouts"][_layout_name(lay)] = stats["layouts"].get(_layout_name(lay), 0) + 1
                stats["layout_pref"] = lay
    gids: dict[str, int] = {}
    vol = _volume(layers, top_y, height, lay, gids)
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


def _describe(raw: bytes) -> dict:
    """The real layout of one chunk's sections (all tags, not just the ones the map reads), so
    a format change can be seen from the map check."""
    try:
        import nbtlib
        root = nbtlib.File.parse(io.BytesIO(raw))
        lvl = root.get("Level", root)
        secs = lvl.get("sections") or lvl.get("Sections") or []
        out: dict = {"data_version": int(root.get("DataVersion", 0) or 0)}
        solid = None
        for sec in secs:                                 # the first section with more than air in it
            names, _ = _section_blocks(_plain(sec))
            if names and not all(_short(n) in _AIR for n in names):
                solid = sec
                break
        sec = solid if solid is not None else (secs[len(secs) // 2] if secs else None)
        if sec is None:
            return out
        out["section_tags"] = {k: type(v).__name__ for k, v in sec.items()}
        bs = next((sec[k] for k in ("block_states", "BlockStates", "blocks") if hasattr(sec.get(k), "items")), None)
        if bs is not None:
            out["block_states_tags"] = {k: type(v).__name__ for k, v in bs.items()}
            pal = bs.get("palette") if bs.get("palette") is not None else bs.get("Palette")
            if pal is not None:
                out["palette_size"] = len(pal)
                out["palette_first"] = [str(p)[:80] for p in list(pal)[:4]]
        out["names_seen"] = _section_blocks(_plain(sec))[0][:6]
        return out
    except Exception as e:                               # the description must never break the check
        return {"describe_error": repr(e)[:200]}


def _plain(tag):
    """nbtlib tags -> plain dicts/lists/str/ints (enough for _section_blocks)."""
    if hasattr(tag, "items"):
        return {k: _plain(v) for k, v in tag.items()}
    if isinstance(tag, str):
        return str(tag)
    if isinstance(tag, list):
        return [_plain(v) for v in tag]
    try:
        import numpy as _np
        if hasattr(tag, "dtype") or type(tag).__name__.endswith("Array"):
            return _np.asarray(tag, dtype=_np.int64)
    except Exception:
        pass
    return tag


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
    layout: dict = {}
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
                info["sample"].update(_describe(raw))
            got = render_chunk(nbt, colors, nether, layout)
        except Exception as e:
            info["failed"] += 1
            info["error"] = info["error"] or f"chunk {i}: {e!r}"[:300]
            continue
        if not got:
            info["blank"] += 1
            continue
        info["drawn"] += 1
        cx, cz = i % 32, i // 32
        lvl = nbt.get("Level") if isinstance(nbt.get("Level"), dict) else nbt
        if isinstance(lvl.get("xPos"), int) and isinstance(lvl.get("zPos"), int):
            if (lvl["xPos"] & 31, lvl["zPos"] & 31) != (cx, cz):
                layout["moved"] = layout.get("moved", 0) + 1      # the chunk says it belongs elsewhere
            cx, cz = lvl["xPos"] & 31, lvl["zPos"] & 31
        c_rgb, c_h = got
        rgb[cz * 16:cz * 16 + 16, cx * 16:cx * 16 + 16] = c_rgb
        heights[cz * 16:cz * 16 + 16, cx * 16:cx * 16 + 16] = c_h
        alpha[cz * 16:cz * 16 + 16, cx * 16:cx * 16 + 16] = np.where(c_h != -9999, 255, 0)
    layout.pop("layout_pref", None)
    if layout.get("checked"):
        layout["agree"] = round(layout["agree"] / layout["checked"], 3)
    info["layout"] = layout
    if info["failed"]:
        log.warning("map %s: %d of %d chunks couldn't be read (first: %s)", path.name, info["failed"], info["chunks"], info["error"])
    elif info["chunks"] and not info["drawn"]:
        log.warning("map %s: none of %d chunks had blocks to draw (sample: %s)", path.name, info["chunks"], info["sample"])
    if not alpha.any():
        return None
    out = _shade(rgb, heights).astype(np.uint8)
    return Image.fromarray(np.dstack([out, alpha]), "RGBA")


def surface_y(world: Path, dim: str, x: float, z: float) -> int | None:
    """The top block at a spot, read straight from its chunk (for placing race checkpoints)."""
    d = region_dir(world, dim)
    if not d:
        return None
    bx, bz = int(math.floor(x)), int(math.floor(z))
    path = d / f"r.{bx >> 9}.{bz >> 9}.mca"
    try:
        data = path.read_bytes()
    except OSError:
        return None
    i = ((bz >> 4) & 31) * 32 + ((bx >> 4) & 31)
    loc = struct.unpack_from(">I", data, i * 4)[0] if len(data) >= 8192 else 0
    if not loc:
        return None
    off = (loc >> 8) * 4096
    try:
        length, ctype = struct.unpack_from(">IB", data, off)
        got = render_chunk(read_chunk(_decompress(ctype, data[off + 5: off + 4 + length], path, i)), Colors(None), dim.endswith("the_nether"))
    except Exception:
        return None
    if not got:
        return None
    h = int(got[1][bz & 15, bx & 15])
    return None if h == -9999 else h + 1


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


RENDER_VERSION = 6          # bump when the drawing changes: older cached tiles are redrawn


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


def clear_tiles(sid: str) -> int:
    """Forget the map pictures drawn for a server (a new world): they're drawn again as they're looked at."""
    import shutil
    root = config.data_dir / "maptiles" / f"v{RENDER_VERSION}" / sid
    n = sum(1 for _ in root.rglob("*.png")) if root.is_dir() else 0
    shutil.rmtree(root, ignore_errors=True)
    return n
