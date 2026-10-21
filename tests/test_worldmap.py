"""The top-down world map: reading chunks from region files and drawing them."""
import io
import struct
import zlib

import nbtlib
import numpy as np
from nbtlib import Compound, Int, List, LongArray, String
from PIL import Image


def _pack(indices, bits):
    per = 64 // bits
    longs = []
    for i in range(0, len(indices), per):
        v = 0
        for k, x in enumerate(indices[i:i + per]):
            v |= (x & ((1 << bits) - 1)) << (k * bits)
        if v >= 1 << 63:
            v -= 1 << 64
        longs.append(v)
    return longs


def _chunk(cx, cz, column):
    """column(x, z) -> list of (y, name) for the solid blocks; everything else is air."""
    sections = {}
    for x in range(16):
        for z in range(16):
            for y, name in column(cx * 16 + x, cz * 16 + z):
                sy = y // 16
                sec = sections.setdefault(sy, {})
                sec[(y % 16, z, x)] = name
    out = []
    for sy, blocks in sorted(sections.items()):
        palette = ["minecraft:air"] + sorted(set(blocks.values()))
        idx = [0] * 4096
        for (y, z, x), name in blocks.items():
            idx[y * 256 + z * 16 + x] = palette.index(name)
        bits = max(4, (len(palette) - 1).bit_length())
        out.append(Compound({"Y": nbtlib.Byte(sy), "block_states": Compound({
            "palette": List[Compound]([Compound({"Name": String(n)}) for n in palette]),
            "data": LongArray(_pack(idx, bits))})}))
    return Compound({"DataVersion": Int(4556), "xPos": Int(cx), "zPos": Int(cz), "Status": String("minecraft:full"),
                     "sections": List[Compound](out), "block_entities": List[Compound]([])})


def _region(path, chunks):
    header, body = bytearray(8192), bytearray()
    for (cx, cz), nbt in chunks.items():
        buf = io.BytesIO()
        nbtlib.File(nbt).write(buf)
        data = zlib.compress(buf.getvalue())
        blob = struct.pack(">IB", len(data) + 1, 2) + data
        blob += b"\0" * (-len(blob) % 4096)
        sector = 2 + len(body) // 4096
        struct.pack_into(">I", header, ((cz % 32) * 32 + (cx % 32)) * 4, (sector << 8) | (len(blob) // 4096))
        body += blob
    path.write_bytes(bytes(header) + bytes(body))


def _land(x, z):
    """Stone below, grass on top, a lake in one corner, a tree."""
    if x < 8 and z < 8:                          # lake, 3 deep, sand floor
        return [(y, "minecraft:stone") for y in range(-64, 58)] + [(58, "minecraft:sand")] + [(y, "minecraft:water") for y in (59, 60, 61)]
    h = 62 + (z // 4) % 3                        # little steps north to south, for the shading
    col = [(y, "minecraft:stone") for y in range(-64, h)] + [(h, "minecraft:grass_block")]
    if (x, z) == (20, 20):
        col += [(h + 1 + i, "minecraft:oak_log") for i in range(4)] + [(h + 5, "minecraft:oak_leaves")]
    return col


def test_reader_and_render(tmp_path):
    from app import worldmap
    reg = tmp_path / "region"
    reg.mkdir()
    _region(reg / "r.0.0.mca", {(cx, cz): _chunk(cx, cz, _land) for cx in range(2) for cz in range(2)})
    raw = zlib.decompress((reg / "r.0.0.mca").read_bytes()[8192 + 5:8192 + 5 + 200000][: struct.unpack_from(">I", (reg / "r.0.0.mca").read_bytes(), 8192)[0] - 1])
    nbt = worldmap.read_chunk(raw)
    assert "sections" in nbt and "block_entities" not in nbt                       # skipped what isn't needed
    colors = worldmap.Colors(None)                                                   # no game files: built-in colours
    img = worldmap.render_region(reg / "r.0.0.mca", colors)
    assert img.size == (512, 512)
    px = np.asarray(img)
    lake, grass, tree, empty = px[2, 2], px[12, 12], px[20, 20], px[100, 100]
    assert lake[3] == 255 and lake[2] > lake[0]                                      # blue water
    assert grass[1] > grass[0] and grass[1] > grass[2]                               # green grass
    assert tuple(tree[:3]) != tuple(grass[:3])                                       # the tree top shows
    assert empty[3] == 0                                                             # no chunk there: see-through
    # relief: a step up toward the north is drawn lighter than flat ground
    col = px[8:28, 24, :3].astype(int).sum(axis=1)
    assert col.max() > col.min()


def test_tiles_are_cached_and_queued(tmp_path, monkeypatch):
    import time

    from app import worldmap
    from app.config import config
    monkeypatch.setattr(config, "data_dir", tmp_path / "data")
    world = tmp_path / "world"
    (world / "region").mkdir(parents=True)
    _region(world / "region" / "r.-1.0.mca", {(-1, 0): _chunk(-1, 0, _land)})
    assert worldmap.regions(world, "minecraft:overworld") == [[-1, 0]]
    assert worldmap.tile("s", world, "minecraft:overworld", 5, 5, None) == ("none", None)
    state, _ = worldmap.tile("s", world, "minecraft:overworld", -1, 0, None)
    assert state == "working"
    for _ in range(100):
        state, path = worldmap.tile("s", world, "minecraft:overworld", -1, 0, None)
        if state == "ready":
            break
        time.sleep(0.05)
    assert state == "ready" and Image.open(path).size == (512, 512)


def test_old_chunk_format_and_nether(tmp_path):
    from app import worldmap
    # pre-1.18: a "Level" wrapper with Sections / Palette / BlockStates
    new = _chunk(0, 0, lambda x, z: [(y, "minecraft:stone") for y in range(0, 10)])
    old_sections = List[Compound]([Compound({"Y": s["Y"], "Palette": s["block_states"]["palette"], "BlockStates": s["block_states"]["data"]}) for s in new["sections"]])
    old = Compound({"Level": Compound({"Sections": old_sections})})
    buf = io.BytesIO(); nbtlib.File(old).write(buf)
    rgb, h = worldmap.render_chunk(worldmap.read_chunk(buf.getvalue()), worldmap.Colors(None), False)
    assert (h == 9).all() and rgb[0, 0, 0] > 0                                      # top of the stone
    # Nether: a bedrock roof at 127 hides nothing; the floor under it is drawn
    nether = _chunk(0, 0, lambda x, z: [(y, "minecraft:netherrack") for y in range(0, 40)] + [(127, "minecraft:bedrock")])
    buf = io.BytesIO(); nbtlib.File(nether).write(buf)
    rgb, h = worldmap.render_chunk(worldmap.read_chunk(buf.getvalue()), worldmap.Colors(None), True)
    assert tuple(rgb[0, 0].astype(int)) == worldmap._FALLBACK["netherrack"]


def test_lz4_compressed_chunks(tmp_path):
    """region-file-compression=lz4: lz4-java "LZ4Block" frames."""
    import lz4.block

    from app import worldmap
    buf = io.BytesIO(); nbtlib.File(_chunk(0, 0, _land)).write(buf)
    raw = buf.getvalue()
    half = len(raw) // 2
    frames = b""
    for part in (raw[:half], raw[half:]):
        comp = lz4.block.compress(part, store_size=False)
        frames += b"LZ4Block" + bytes([0x20 | 6]) + struct.pack("<iii", len(comp), len(part), 0) + comp
    frames += b"LZ4Block" + bytes([0x10]) + struct.pack("<iii", 0, 0, 0)
    blob = struct.pack(">IB", len(frames) + 1, 4) + frames
    blob += b"\0" * (-len(blob) % 4096)
    header = bytearray(8192)
    struct.pack_into(">I", header, 0, (2 << 8) | (len(blob) // 4096))
    (tmp_path / "r.0.0.mca").write_bytes(bytes(header) + blob)
    img = worldmap.render_region(tmp_path / "r.0.0.mca", worldmap.Colors(None))
    assert img is not None and np.asarray(img)[12, 12, 3] == 255


def test_real_chunk_arrays_are_skipped():
    """Real chunks carry heightmaps (long arrays), light (byte arrays) and int arrays before the
    sections; skipping them must step over their length too."""
    from nbtlib import ByteArray, IntArray

    from app import worldmap
    c = _chunk(0, 0, _land)
    c["Heightmaps"] = Compound({"WORLD_SURFACE": LongArray([1] * 37)})
    c["Biomes"] = IntArray([1] * 64)
    for s in c["sections"]:
        s["BlockLight"] = ByteArray([0] * 2048)
    ordered = Compound({"Heightmaps": c.pop("Heightmaps"), "Biomes": c.pop("Biomes"), **c})
    buf = io.BytesIO(); nbtlib.File(ordered).write(buf)
    nbt = worldmap.read_chunk(buf.getvalue())
    assert len(nbt["sections"]) > 0
    assert worldmap.render_chunk(nbt, worldmap.Colors(None), False) is not None


def test_spanning_block_states():
    """1.13-1.15 pack block indices straight across long boundaries."""
    from app import worldmap
    bits, vals = 5, [(i * 7) % 17 for i in range(4096)]
    big = 0
    for k, v in enumerate(vals):
        big |= v << (k * bits)
    longs = [(big >> (64 * j)) & ((1 << 64) - 1) for j in range(4096 * bits // 64)]
    data = np.array([x - (1 << 64) if x >= 1 << 63 else x for x in longs], dtype=np.int64)
    assert worldmap._unpack(data, 17).tolist() == vals


def test_render_reports_what_happened(tmp_path):
    from app import worldmap
    _region(tmp_path / "r.0.0.mca", {(0, 0): _chunk(0, 0, _land)})
    data = bytearray((tmp_path / "r.0.0.mca").read_bytes())
    struct.pack_into(">I", data, 4, (2 << 8) | 1)                       # chunk 1 points at chunk 0's data...
    data[8192 + 4] = 9                                                  # ...whose compression byte is now nonsense
    (tmp_path / "r.0.0.mca").write_bytes(bytes(data))
    info = {}
    img = worldmap.render_region(tmp_path / "r.0.0.mca", worldmap.Colors(None), False, info)
    assert img is None and info["chunks"] == 2 and info["failed"] == 2 and "compression type 9" in info["error"]
    assert info["compression"] == {"9": 2}
