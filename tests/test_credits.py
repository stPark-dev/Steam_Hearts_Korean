import numpy as np
import pytest

from steamhearts import credits, spt


def test_lines_land_in_their_rows_and_use_four_shades():
    c = credits.render_block(["가나다", "", "라"], top=-12)
    assert c.top == -12 and c.index.max() <= 4 and c.index.max() >= 3
    rows = np.where(c.index.any(1))[0] + c.top
    assert rows.min() >= -12 and rows.max() < -12 + 3 * credits.PITCH


def test_blank_line_stays_empty():
    c = credits.render_block(["가", "", "다"], top=-12)
    assert not c.index[credits.PITCH:2 * credits.PITCH].any()


def test_lines_are_centered():
    c = credits.render_block(["가나다라마"], top=-12)
    xs = np.where(c.index.any(0))[0] - credits.HALF
    assert abs(xs.min() + xs.max()) <= 3


def test_missing_glyph_fails():
    with pytest.raises(credits.CreditsError, match="missing"):
        credits.render_block(["가"], top=-12)


def test_too_wide_line_fails():
    with pytest.raises(credits.CreditsError):
        credits.render_block(["가" * 40], top=-12)


def test_keep_rows_copies_original_from_given_line():
    orig = credits.Canvas(np.full((48, 2 * credits.HALF), 2, np.uint8), -12)
    c = credits.render_block(["가"], top=-12, keep=(orig, 1))
    assert (c.index[credits.PITCH:] == 2).all()


def test_split_and_rejoin_reproduces_canvas():
    c = credits.render_block(["캐릭터 디자인 / 작화 감독", "키무라 타카히로"], top=-12)
    left, right = credits.split(c)
    assert left.x < 0 and right.x == 0
    back = np.zeros_like(c.index)
    for f in (left, right):
        img = spt.untile(f.parts, f.raw, (c.index.shape[0], 256 + 255 * 8))
        ys, xs = np.nonzero(img)
        back[ys + f.y - c.top, xs + f.x + credits.HALF] = img[ys, xs]
    assert (back == c.index).all()


def test_from_frames_top_is_first_content_row():
    idx = np.zeros((8, 16), np.uint8)
    idx[3, 2] = 4
    parts, raw = spt.tile(idx)
    left = spt.Frame(-16, -20, parts, raw)       # frame origin above its first drawn row
    right = spt.Frame(0, -20, [spt.Part(0, 0, 0, 8, 8)], bytes(32))
    c = credits.from_frames(left, right, lambda f: f.raw)
    assert c.top == -17 and c.index[0].any()


def test_keep_rows_refuse_to_hide_translated_lines():
    orig = credits.Canvas(np.full((48, 2 * credits.HALF), 2, np.uint8), -12)
    with pytest.raises(credits.CreditsError):
        credits.render_block(["가", "나"], top=-12, keep=(orig, 1))
