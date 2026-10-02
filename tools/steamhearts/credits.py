"""Ending staff roll (SR.SPT): 18 credit blocks, each drawn as a left frame (x < 0) and a right
frame (x >= 0) around the screen center. The roll is shown on the 640x240 screen, so glyphs are
drawn square and then halved vertically (about 21 x 11 pixels per syllable, 12-row pitch).
Shading: palette indices 1..4 = the original four grays from dark to white (Korean uses 2..4).
"""
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from . import sa, spt

PITCH = 12          # rows per line
FONT_PX = 21        # em size in screen pixels before the vertical halving
HALF = 256          # canvas columns on each side of the center
SHADES = 4
MIN_SHADE = 2       # the darkest gray is dropped: keeps the roll inside its 10 sectors
SPAN_GAP = 4
SUPER = 4


class CreditsError(ValueError):
    pass


@dataclass
class Canvas:
    index: np.ndarray   # rows x 2*HALF, column HALF is screen x = 0
    top: int            # screen-relative y of row 0


def _line(text: str, font_path: str) -> np.ndarray:
    font = ImageFont.truetype(font_path, FONT_PX * SUPER, index=sa.FONT_INDEX_KR)
    w = int(font.getlength(text)) + 2 * SUPER
    h = 2 * PITCH * SUPER
    im = Image.new("L", (w, h), 0)
    ImageDraw.Draw(im).text((SUPER, h // 2), text, font=font, fill=255, anchor="lm")
    im = im.resize((max(1, w // SUPER), PITCH), Image.LANCZOS)
    lv = np.round(np.asarray(im).astype(float) / 255 * SHADES).astype(np.uint8)
    lv[lv < MIN_SHADE] = 0
    cols = np.where(lv.any(0))[0]
    return lv[:, cols.min():cols.max() + 1] if len(cols) else lv[:, :0]


def render_block(lines: list, top: int, keep: tuple | None = None,
                 font_path: str = sa.DEFAULT_FONT) -> Canvas:
    rows = len(lines) * PITCH
    if keep is not None and any(lines[keep[1]:]):
        raise CreditsError(f"lines from {keep[1] + 1} on would be hidden by the kept original rows")
    if keep is not None:
        rows = max(rows, keep[0].index.shape[0])
    idx = np.zeros((rows, 2 * HALF), np.uint8)
    for i, text in enumerate(lines):
        if not text:
            continue
        miss = sa.missing_glyphs(text, font_path)
        if miss:
            raise CreditsError(f"characters missing from font: {miss} in {text!r}")
        lv = _line(text, font_path)
        w = lv.shape[1]
        x0 = HALF - w // 2
        if x0 < 1 or x0 + w > 2 * HALF - 1:
            raise CreditsError(f"line {text!r} is {w} pixels wide, more than the {2 * HALF - 2} available")
        reg = idx[i * PITCH:(i + 1) * PITCH, x0:x0 + w]
        reg[lv > 0] = lv[lv > 0]
    if keep is not None:
        orig, line = keep
        if orig.top != top:
            raise CreditsError("kept rows must share the block top")
        idx[line * PITCH:orig.index.shape[0]] = orig.index[line * PITCH:]
    return Canvas(idx, top)


def _frame(sub: np.ndarray, x_origin: int, top: int) -> spt.Frame:
    ys, xs = np.nonzero(sub)
    if not len(ys):
        return spt.Frame(x_origin, top, [spt.Part(0, 0, 0, 8, 8)], bytes(32))
    y0, x0 = int(ys.min()), int(xs.min())
    parts, raw = spt.tile(sub[y0:, x0:], SPAN_GAP)
    return spt.Frame(x_origin + x0, top + y0, parts, raw)


def split(c: Canvas) -> tuple[spt.Frame, spt.Frame]:
    return _frame(c.index[:, :HALF], -HALF, c.top), _frame(c.index[:, HALF:], 0, c.top)


def from_frames(left: spt.Frame, right, raw_of) -> Canvas:
    """Rebuild a block canvas from original frames (raw_of(frame) gives its raw blob)."""
    top = min(left.y, right.y)
    rows = max(f.y - top + max(p.y + p.h for p in f.parts) for f in (left, right))
    idx = np.zeros((rows, 2 * HALF), np.uint8)
    for f in (left, right):
        img = spt.untile(f.parts, raw_of(f), (rows + 255, 2 * HALF + 255 * 8))
        ys, xs = np.nonzero(img)
        cx = xs + f.x + HALF
        if len(cx) and (cx.min() < 0 or cx.max() >= 2 * HALF):
            raise CreditsError("original frame reaches outside the block canvas")
        idx[ys + f.y - top, cx] = img[ys, xs]
    first = int(np.where(idx.any(1))[0].min())     # frame origins sit above the first drawn row
    return Canvas(idx[first:], top + first)
