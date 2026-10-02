"""Backup-RAM notice images (*.SA): RGB555 big-endian pixels + CR LF, LZSS kind 0.

Korean text is drawn over the original picture: each paragraph clears its box and draws its
lines with the original look (italic, 16-step anti-alias ramp of one color). Anything outside
the paragraph boxes (separator lines, untranslated words) stays byte-identical.
"""
from functools import lru_cache

import numpy as np
from fontTools.ttLib import TTCollection
from PIL import Image, ImageDraw, ImageFont

DEFAULT_FONT = "/usr/share/fonts/opentype/noto/NotoSansCJK-Medium.ttc"
FONT_INDEX_KR = 1           # "Noto Sans CJK KR Medium" inside the collection
SUPER = 4                   # supersampling factor
LEVELS = 16


class SaError(ValueError):
    pass


class LayoutError(ValueError):
    pass


def decode(raw: bytes, width: int) -> np.ndarray:
    if not raw.endswith(b"\r\n") or (len(raw) - 2) % (2 * width):
        raise SaError(f"{len(raw)} bytes is not width {width} RGB555 + CR LF")
    return np.frombuffer(raw[:-2], dtype=">u2").reshape(-1, width).astype(np.uint16)


def encode(px: np.ndarray) -> bytes:
    return px.astype(">u2").tobytes() + b"\r\n"


@lru_cache(maxsize=None)
def _cmap(font_path: str) -> frozenset:
    return frozenset(TTCollection(font_path).fonts[FONT_INDEX_KR].getBestCmap())


def missing_glyphs(text: str, font_path: str = DEFAULT_FONT) -> list[str]:
    cmap = _cmap(font_path)
    return sorted({ch for ch in text if ch != "\n" and ord(ch) not in cmap})


def shade(color, level: int) -> int:
    r, g, b = (round(c * level / LEVELS) for c in color)
    return r | g << 5 | b << 10


def _line_alpha(text: str, size: int, pitch: int, shear: float, font_path: str) -> np.ndarray:
    """Coverage 0..255 of one line, `pitch` rows tall, width as needed (+ shear margin)."""
    font = ImageFont.truetype(font_path, size * SUPER, index=FONT_INDEX_KR)
    w = int(font.getlength(text)) + pitch * SUPER
    h = pitch * SUPER
    im = Image.new("L", (w, h), 0)
    ImageDraw.Draw(im).text((0, round((pitch + size * 0.78) / 2 * SUPER)), text, font=font, fill=255, anchor="ls")
    # italic: shift each row right in proportion to its height above the line center
    im = im.transform(im.size, Image.AFFINE, (1, shear, -shear * h / 2, 0, 1, 0), Image.BICUBIC)
    im = im.resize((w // SUPER, pitch), Image.LANCZOS)
    return np.asarray(im)


def _levels(alpha: np.ndarray) -> np.ndarray:
    lv = np.round(alpha.astype(float) / 255 * LEVELS).astype(int)
    lv[alpha < 12] = 0
    return lv


def compose(src: np.ndarray, layout: dict, texts: dict, font_path: str = DEFAULT_FONT) -> np.ndarray:
    if src.shape != (layout["height"], layout["width"]):
        raise LayoutError(f"source {src.shape} does not match layout {layout['height']}x{layout['width']}")
    out = src.copy()
    size = layout.get("size", 12)
    pitch = layout.get("pitch", 14)
    shear = layout.get("shear", 0.2)
    for p in layout["paragraphs"]:
        text = texts.get(p["id"])
        if text is None:
            continue
        missing = missing_glyphs(text, font_path)
        if missing:
            raise LayoutError(f"{p['id']}: characters missing from font: {missing}")
        x0, y0, bw, bh = p["clear"]
        if x0 < 0 or y0 < 0 or x0 + bw > out.shape[1] or y0 + bh > out.shape[0]:
            raise LayoutError(f"{p['id']}: box {p['clear']} is outside the image")
        out[y0:y0 + bh, x0:x0 + bw] = 0
        lut = np.array([shade(p["color"], k) for k in range(LEVELS + 1)], np.uint16)
        for i, line in enumerate(text.split("\n")):
            lv = _levels(_line_alpha(line, p.get("size", size), pitch, shear, font_path))
            cols = np.where(lv.any(0))[0]
            if not len(cols):
                continue
            lv = lv[:, cols.min():cols.max() + 1]
            lw = lv.shape[1]
            x = (x0 + (bw - lw) // 2) if p["x"] == "center" else p["x"]
            y = p["y"] + i * p.get("pitch", pitch)
            rows = np.where(lv.any(1))[0]
            top, bot = y + rows.min(), y + rows.max() + 1
            if x < x0 or x + lw > x0 + bw or top < y0 or bot > y0 + bh:
                raise LayoutError(f"{p['id']} line {i + 1} ({line!r}) leaves its box "
                                  f"{p['clear']}: x {x}..{x + lw}, y {top}..{bot}")
            region = out[y:y + pitch, x:x + lw]
            lv = lv[:region.shape[0]]          # rows past the image are empty (checked above)
            m = lv > 0
            region[m] = lut[lv[m]]
    return out
