import numpy as np
from PIL import Image

from steamhearts import logo, spt


def _png(tmp_path):
    im = Image.new("RGBA", (300, 100), (0, 0, 0, 0))
    a = np.zeros((100, 300, 4), np.uint8)
    a[10:60, 20:280] = (240, 240, 240, 255)
    a[60:90, 80:200] = (220, 30, 40, 255)
    a[30:40, 50:250] = (60, 60, 60, 255)
    im = Image.fromarray(a, "RGBA")
    p = tmp_path / "l.png"
    im.save(p)
    return p


def test_convert_gives_transparent_zero_and_opaque_colors(tmp_path):
    pal, idx = logo.convert(_png(tmp_path), 150, 25)
    assert idx.shape == (25, 150)
    assert pal[0] == 0 and all(c & 0x8000 for c in pal[1:])
    assert idx.max() <= 15 and (idx == 0).any() and (idx > 0).any()


def test_convert_is_deterministic(tmp_path):
    a = logo.convert(_png(tmp_path), 150, 25)
    b = logo.convert(_png(tmp_path), 150, 25)
    assert a[0] == b[0] and (a[1] == b[1]).all()


def test_frames_cover_each_pixel_once_and_place_at_screen_position():
    idx = np.zeros((40, 500), np.uint8)
    idx[2:30, 5:495] = 3
    idx[30:38, 100:340] = 7
    frames = logo.frames(idx, pos=(70, 72), base=(320, 112), count=8, sub_box=(96, 28, 252, 12))
    assert len(frames) == 8
    canvas = np.zeros((300, 800), np.uint8)
    hits = np.zeros((300, 800), np.uint8)
    for f in frames:
        img = spt.untile(f.parts, f.raw, (64, 2048))
        ys, xs = np.nonzero(img)
        sy, sx = ys + f.y + 112, xs + f.x + 320
        canvas[sy, sx] = img[ys, xs]
        hits[sy, sx] += 1
    assert hits.max() == 1
    assert (canvas[72:112, 70:570] == idx).all()


def test_frames_keep_part_fields_in_range():
    idx = np.full((88, 506), 5, np.uint8)
    frames = logo.frames(idx, pos=(79, 72), base=(320, 112), count=8, sub_box=(104, 56, 252, 32))
    for f in frames:
        for p in f.parts:
            assert 0 <= p.x <= 255 and 0 <= p.y <= 255
