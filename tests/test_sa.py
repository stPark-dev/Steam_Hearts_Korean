import numpy as np
import pytest

from steamhearts import sa

FONT = sa.DEFAULT_FONT


def test_decode_encode_roundtrip_keeps_crlf_trailer():
    px = np.arange(6, dtype=np.uint16).reshape(2, 3)
    raw = sa.encode(px)
    assert raw.endswith(b"\r\n") and len(raw) == 2 * 6 + 2
    assert (sa.decode(raw, 3) == px).all()


def test_decode_rejects_wrong_width_or_trailer():
    with pytest.raises(sa.SaError):
        sa.decode(bytes(14), 4)
    with pytest.raises(sa.SaError):
        sa.decode(bytes(12) + b"\r\n", 5)


def test_white_ramp_reproduces_original_levels():
    levels = sorted({int(sa.shade((31, 31, 31), k)) & 31 for k in range(17)})
    assert levels == [0, 2, 4, 6, 8, 10, 12, 14, 16, 17, 19, 21, 23, 25, 27, 29, 31]


def test_ramp_full_level_is_the_color_and_zero_is_black():
    assert sa.shade((31, 0, 0), 16) == 0x001F
    assert sa.shade((9, 16, 31), 16) == 0x7E09
    assert sa.shade((31, 31, 31), 0) == 0


def _layout(**kw):
    base = dict(width=64, height=32, paragraphs=[
        dict(id="p1", clear=[0, 0, 64, 16], x=2, y=1, color=[31, 31, 31])])
    base.update(kw)
    return base


def test_compose_clears_box_and_draws_inside_it():
    src = np.full((32, 64), 0x1234, np.uint16)
    out = sa.compose(src, _layout(), {"p1": "가"}, FONT)
    assert (out[16:] == 0x1234).all()                      # outside the box untouched
    box = out[:16]
    assert ((box == 0) | (box & 0x8000 == 0)).all()
    assert (box != 0).any() and (box != 0x1234).all()


def test_compose_keeps_paragraph_without_translation_as_original():
    src = np.full((32, 64), 7, np.uint16)
    out = sa.compose(src, _layout(), {}, FONT)
    assert (out == src).all()


def test_compose_fails_when_text_overflows_the_box():
    with pytest.raises(sa.LayoutError):
        sa.compose(np.zeros((32, 64), np.uint16), _layout(), {"p1": "아주 긴 한국어 문장입니다"}, FONT)


def test_compose_fails_when_lines_exceed_box_height():
    with pytest.raises(sa.LayoutError):
        sa.compose(np.zeros((32, 64), np.uint16), _layout(), {"p1": "가\n나\n다"}, FONT)


def test_centered_paragraph_is_centered():
    lay = _layout(paragraphs=[dict(id="p1", clear=[0, 0, 64, 16], x="center", y=1, color=[31, 31, 31])])
    out = sa.compose(np.zeros((32, 64), np.uint16), lay, {"p1": "가"}, FONT)
    cols = np.where((out != 0).any(0))[0]
    assert abs((cols.min() + cols.max()) / 2 - 31.5) <= 2


def test_text_size_must_match_source_shape():
    with pytest.raises(sa.LayoutError):
        sa.compose(np.zeros((10, 10), np.uint16), _layout(), {}, FONT)


def test_compose_fails_on_character_missing_from_font():
    with pytest.raises(sa.LayoutError, match="missing"):
        sa.compose(np.zeros((32, 64), np.uint16), _layout(), {"p1": "가"}, FONT)
