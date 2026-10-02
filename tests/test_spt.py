import numpy as np
import pytest

from steamhearts import lzss, spt


def _img(h, w, seed=0):
    rng = np.random.default_rng(seed)
    a = rng.integers(1, 16, size=(h, w)).astype(np.uint8)
    a[:, : w // 3] = 0
    a[h // 2:, -5:] = 0
    return a


def test_tile_covers_every_opaque_pixel_and_decodes_back():
    a = _img(20, 50)
    parts, raw = spt.tile(a)
    assert all(p.w % 8 == 0 and 1 <= p.h <= 8 for p in parts)
    back = spt.untile(parts, raw, a.shape)
    assert (back == a).all()


def test_tile_skips_empty_bands():
    a = np.zeros((24, 16), np.uint8)
    a[17, 3] = 5
    parts, raw = spt.tile(a)
    assert len(parts) == 1 and parts[0].y == 16 and parts[0].x <= 3
    assert len(raw) == parts[0].w * parts[0].h // 2


def test_tile_rejects_offsets_beyond_a_byte():
    a = np.zeros((8, 300), np.uint8)
    a[0, 290] = 1
    with pytest.raises(spt.SptError):
        spt.tile(a)


def test_build_then_parse_roundtrip():
    frames = []
    for k in range(3):
        parts, raw = spt.tile(_img(16, 40, k))
        frames.append(spt.Frame(x=-10 * k, y=5, parts=parts, raw=raw))
    pal = [0] + [0x8000 | i for i in range(1, 16)]
    rec = bytes(range(20))
    data = spt.build(pal, frames, rec)
    s = spt.parse(data)
    assert s.palettes == [pal]
    assert s.buffer_size == max(len(f.raw) for f in frames)
    for f, g in zip(frames, s.frames):
        assert (g.x, g.y) == (f.x, f.y)
        assert g.parts == f.parts
        assert lzss.decompress(data[g.blob_offset:]) == f.raw
        assert data[g.record_offset:g.record_offset + 20] == rec


def test_parse_rejects_truncated():
    with pytest.raises(spt.SptError):
        spt.parse(bytes(10))
