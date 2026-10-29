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


def test_palette_as_plain_names():
    """Newer layouts may list block names as text (with [properties]) instead of compounds."""
    from app import worldmap
    c = _chunk(0, 0, lambda x, z: [(y, "minecraft:grass_block") for y in range(60, 64)])
    for s in c["sections"]:
        bs = s["block_states"]
        bs["palette"] = List[String]([String(p["Name"] + ("[snowy=false]" if "grass" in p["Name"] else "")) for p in bs["palette"]])
    buf = io.BytesIO(); nbtlib.File(c).write(buf)
    got = worldmap.render_chunk(worldmap.read_chunk(buf.getvalue()), worldmap.Colors(None), False)
    assert got is not None and (got[1] == 63).all()
    assert worldmap._block_name({"name": "oak_log"}) == "minecraft:oak_log"


def _hm(heights_zx, min_y=-64):
    """A WORLD_SURFACE heightmap (9 bits, x + z*16) for absolute top-block heights."""
    vals = [int(heights_zx[z][x]) + 1 - min_y for z in range(16) for x in range(16)]
    return LongArray(_pack(vals, 9))


def test_narrow_packing_and_heightmap_check():
    """Newer worlds can pack a 2-block section with 1 bit per block (the length says so)."""
    from app import worldmap
    col = lambda x, z: [(y, "minecraft:stone") for y in range(0, 10 + x)]    # noqa: E731 - slopes up eastwards
    c = _chunk(0, 0, col)
    for s in c["sections"]:
        bs = s["block_states"]
        names = [p["Name"] for p in bs["palette"]]
        if len(names) == 2:                                                # repack at 1 bit per block
            per = 4096 // 64
            flat = []
            for v in bs["data"]:
                v = int(v) & ((1 << 64) - 1)
                flat += [(v >> (4 * k)) & 0xF for k in range(16)]
            bs["data"] = LongArray(_pack(flat[:4096], 1))
            assert len(bs["data"]) == per
    c["yPos"] = Int(-4)
    c["Heightmaps"] = Compound({"WORLD_SURFACE": _hm([[9 + x for x in range(16)] for z in range(16)])})
    buf = io.BytesIO(); nbtlib.File(c).write(buf)
    stats = {}
    rgb, h = worldmap.render_chunk(worldmap.read_chunk(buf.getvalue()), worldmap.Colors(None), False, stats)
    assert (h[0] == np.arange(9, 25)).all()
    assert stats["narrow_sections"] >= 1 and stats["checked"] == 1 and stats["agree"] == 1.0 and stats["layouts"] == {"yzx": 1}


def test_turned_chunk_is_put_right():
    from app import worldmap
    c = _chunk(0, 0, lambda x, z: [(y, "minecraft:stone") for y in range(0, 10 + x)])
    c["yPos"] = Int(-4)
    c["Heightmaps"] = Compound({"WORLD_SURFACE": _hm([[9 + z for x in range(16)] for z in range(16)])})   # the game says: rises southwards
    buf = io.BytesIO(); nbtlib.File(c).write(buf)
    stats = {}
    rgb, h = worldmap.render_chunk(worldmap.read_chunk(buf.getvalue()), worldmap.Colors(None), False, stats)
    assert stats["layouts"] == {"yxz": 1} and (h[:, 0] == np.arange(9, 25)).all()


def test_upside_down_sections_are_found():
    """A layout where y runs top-down inside each section is spotted from the height map."""
    from app import worldmap
    c = _chunk(0, 0, lambda x, z: [(y, "minecraft:stone") for y in range(0, 5 + x // 2)])
    for sec in c["sections"]:                                           # store every section upside down
        bs = sec["block_states"]
        n = len(bs["palette"])
        idx = worldmap._unpack(np.array([int(v) for v in bs["data"]], dtype=np.int64), n).reshape(16, 16, 16)[::-1].reshape(-1)
        bs["data"] = LongArray(_pack([int(v) for v in idx], max(4, (n - 1).bit_length())))
    c["yPos"] = Int(-4)
    c["Heightmaps"] = Compound({"WORLD_SURFACE": _hm([[4 + x // 2 for x in range(16)] for z in range(16)])})
    buf = io.BytesIO(); nbtlib.File(c).write(buf)
    stats = {}
    rgb, h = worldmap.render_chunk(worldmap.read_chunk(buf.getvalue()), worldmap.Colors(None), False, stats)
    assert stats["layouts"] == {"yzx-ydown": 1} and (h[0] == [4 + x // 2 for x in range(16)]).all()


def test_mixed_palette_26_1():
    """26.1+: a palette mixing plain names and blocks with properties stores every entry as a
    compound, {"": "deepslate"} for plain ones and {id: ..., properties: ...} for the rest."""
    from app import worldmap
    c = _chunk(0, 0, lambda x, z: [(y, "minecraft:stone") for y in range(0, 60)] + [(60, "minecraft:glow_lichen" if x == 0 else "minecraft:grass_block")])
    for s in c["sections"]:
        bs = s["block_states"]
        bs["palette"] = List[Compound]([Compound({"id": String(p["Name"].split(":")[1]), "properties": Compound({"up": String("true")})})
                                        if "lichen" in p["Name"] else Compound({"": String(p["Name"].split(":")[1])}) for p in bs["palette"]])
    c["yPos"] = Int(-4)
    c["Heightmaps"] = Compound({"WORLD_SURFACE": _hm([[60] * 16 for _ in range(16)])})
    buf = io.BytesIO(); nbtlib.File(c).write(buf)
    stats = {}
    rgb, h = worldmap.render_chunk(worldmap.read_chunk(buf.getvalue()), worldmap.Colors(None), False, stats)
    assert (h == 60).all() and stats["agree"] == 1.0
    assert worldmap._block_name({"": "deepslate"}) == "minecraft:deepslate"
    assert worldmap._block_name({"id": "glow_lichen", "properties": {}}) == "minecraft:glow_lichen"


def test_region_grid_shows_holes(tmp_path):
    from app import worldmap
    for x, z in [(-1, -1), (0, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (0, 1), (1, 1)]:
        (tmp_path / f"r.{x}.{z}.mca").write_bytes(b"\0" * 9000)
    g = worldmap.region_grid(sorted(tmp_path.glob("*.mca")))
    assert g["rows"] == ["###", "#o#", "###"] and g["missing_inside"] == 1
    (tmp_path / "r.0.0.mca").write_bytes(b"\0" * 100)
    g = worldmap.region_grid(sorted(tmp_path.glob("*.mca")))
    assert g["rows"][1] == "#@#" and g["missing_inside"] == 0


def test_check_a_spot_with_no_region(tmp_path):
    from app import worldmap
    reg = tmp_path / "region"
    reg.mkdir()
    (reg / "r.0.0.mca").write_bytes(b"\0" * 9000)
    out = worldmap.check("t", tmp_path, "minecraft:overworld", [], None, at=(5000, -3000))
    assert out["checked"][0]["file"] == "r.9.-6.mca" and "No region file" in out["checked"][0]["error"]


def test_check_counts_unfinished_chunks(tmp_path):
    from app import worldmap
    started = _chunk(1, 0, lambda x, z: [])
    started["Status"] = String("minecraft:structure_starts")
    _region(tmp_path / "r.0.0.mca", {(0, 0): _chunk(0, 0, _land), (1, 0): started})
    info = {}
    worldmap.render_region(tmp_path / "r.0.0.mca", worldmap.Colors(None), False, info)
    assert info["statuses"] == {"full": 1, "structure_starts": 1}


def test_newest_first_and_the_rest_in_the_background(tmp_path, monkeypatch):
    import time

    from app import worldmap
    from app.config import config
    monkeypatch.setattr(config, "data_dir", tmp_path / "data")
    monkeypatch.setattr(worldmap, "FILL_PAUSE", 0)
    world = tmp_path / "world"
    (world / "region").mkdir(parents=True)
    for x in range(3):
        _region(world / "region" / f"r.{x}.0.mca", {(x * 32, 0): _chunk(x * 32, 0, _land)})
    with worldmap._qlock:                                  # hold the worker back while asking for squares
        monkeypatch.setattr(worldmap, "_worker", object())
        worldmap._asked.clear()
        worldmap._queue.clear()
        worldmap._queued.clear()
        worldmap._fill.clear()
    worldmap.tile("q", world, "minecraft:overworld", 0, 0, None)
    worldmap._asked[("q", "minecraft:overworld", 0, 0)] -= 60         # asked a while ago: scrolled past
    worldmap.tile("q", world, "minecraft:overworld", 1, 0, None)
    with worldmap._qlock:
        job, background = worldmap._next()
        assert job[0][2] == 1 and not background                       # what's on screen now goes first
        job2, background2 = worldmap._next()
        assert background2 and job2[0][2] in (0, 2)                    # the old ask was dropped; the rest comes after
        worldmap._queued.discard(job2[0])
        worldmap._fill.insert(0, job2)
        monkeypatch.setattr(worldmap, "_worker", None)
    worldmap.tile("q", world, "minecraft:overworld", 1, 0, None)        # start the worker
    for _ in range(200):
        if all(worldmap._tile_path("q", "minecraft:overworld", x, 0).is_file() for x in (0, 2)):
            break
        time.sleep(0.05)
    assert all(worldmap._tile_path("q", "minecraft:overworld", x, 0).is_file() for x in (0, 2))   # drawn in the background
