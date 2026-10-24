import io
import os
import time

from PIL import Image

from app import skins

U = "0123456789abcdef0123456789abcdef"


def _skin(slim=False, h=64):
    img = Image.new("RGBA", (64, h), (0, 0, 0, 0))
    img.paste((255, 0, 0, 255), (8, 8, 16, 16))          # face red
    img.paste((0, 0, 255, 255), (20, 20, 28, 32))        # shirt blue
    img.paste((0, 255, 0, 255), (44, 20, 47 if slim else 48, 32))   # right arm front
    img.paste((0, 255, 0, 255), (48, 20, 56 if not slim else 54, 32))
    buf = io.BytesIO(); img.save(buf, "PNG")
    return buf.getvalue()


def _render(png, uuid=U):
    return Image.open(io.BytesIO(skins.body(png, uuid, 64))).convert("RGBA")


def test_body_front_view():
    out = _render(_skin())
    assert out.size == (32, 64)                            # 16x32 skin pixels, scaled by 2
    assert out.getpixel((8 * 2 + 1, 2))[:3] == (255, 0, 0)          # the face
    assert out.getpixel((8 * 2, 12 * 2))[:3] == (0, 0, 255)         # the shirt
    assert out.getpixel((1 * 2, 10 * 2))[:3] == (0, 255, 0)         # a classic (4 wide) arm


def test_slim_arms_from_the_skin():
    out = _render(_skin(slim=True), "f" * 32)
    assert out.getpixel((0, 10 * 2))[3] == 0                         # 3-wide arm: column 0 empty
    assert out.getpixel((1 * 2, 10 * 2))[:3] == (0, 255, 0)


def test_old_skins_mirror_the_left_limbs():
    out = _render(_skin(h=32), "e" * 32)
    assert out.getpixel((13 * 2, 10 * 2))[:3] == (0, 255, 0)


def test_stale_makes_the_next_request_recheck(tmp_path, monkeypatch):
    monkeypatch.setattr(skins, "_dir", tmp_path)
    p = tmp_path / f"{U}.png"
    p.write_bytes(b"x")
    skins._misses[U] = time.monotonic()
    skins.stale(U)
    assert os.stat(p).st_mtime == 0 and U not in skins._misses
