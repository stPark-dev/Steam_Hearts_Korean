"""Title logo: provided RGBA artwork -> 16-color VDP1 sprite frames for SHLOGO.SPT.

The title screen is 640x240 (pixels twice as tall as wide), so the artwork is resampled to
the target width x height in screen pixels. Colors: k-means (fixed seed) over opaque pixels,
15 colors + transparent index 0.
"""
from pathlib import Path

import numpy as np
from PIL import Image

from . import spt

ALPHA_CUT = 0.5
CROP_ALPHA = 64         # pixels fainter than this (out of 255) do not count for the crop
KMEANS_ITER = 40
SEED = 1


def _resample(path: Path, w: int, h: int) -> tuple[np.ndarray, np.ndarray]:
    im = Image.open(path).convert("RGBA")
    im = im.crop(im.getchannel("A").point(lambda v: 255 if v >= CROP_ALPHA else 0).getbbox())
    a = np.asarray(im).astype(float) / 255
    a[..., :3] *= a[..., 3:4]                    # premultiply so edges do not darken
    r = np.asarray(Image.fromarray((a * 255).round().astype(np.uint8), "RGBA")
                   .resize((w, h), Image.LANCZOS)).astype(float) / 255
    alpha = r[..., 3]
    rgb = np.clip(r[..., :3] / np.maximum(alpha[..., None], 1e-6), 0, 1)
    return rgb, alpha >= ALPHA_CUT


def _kmeans(x: np.ndarray, k: int) -> np.ndarray:
    rng = np.random.default_rng(SEED)
    centers = [x[rng.integers(len(x))]]
    for _ in range(k - 1):
        d = np.min(((x[:, None] - np.array(centers)[None]) ** 2).sum(-1), 1)
        centers.append(x[rng.choice(len(x), p=d / d.sum())] if d.sum() else x[0])
    c = np.array(centers)
    for _ in range(KMEANS_ITER):
        lab = np.argmin(((x[:, None] - c[None]) ** 2).sum(-1), 1)
        c = np.array([x[lab == i].mean(0) if (lab == i).any() else c[i] for i in range(k)])
    return c


def convert(path: Path, w: int, h: int, colors: int = 15) -> tuple[list, np.ndarray]:
    rgb, mask = _resample(path, w, h)
    px = rgb[mask] * 31
    k = min(colors, 15, len(np.unique(np.round(px), axis=0)))
    c5 = np.clip(np.round(_kmeans(px, k)), 0, 31).astype(int)
    lab = np.argmin(((px[:, None] - c5[None]) ** 2).sum(-1), 1)
    idx = np.zeros((h, w), np.uint8)
    idx[mask] = lab + 1
    pal = [0] + [0x8000 | int(b) << 10 | int(g) << 5 | int(r) for r, g, b in c5]
    pal += [0x8000] * (16 - len(pal))
    return pal, idx


def frames(idx: np.ndarray, pos: tuple, base: tuple, count: int, sub_box: tuple, gap: int = spt.SPAN_GAP) -> list:
    """Split the indexed logo into `count` frames: the last takes `sub_box` (x, y, w, h in logo
    pixels), the others take equal vertical strips of the rest. Frame x/y are relative to the
    sprite base so the logo lands at screen `pos`."""
    h, w = idx.shape
    owner = np.zeros((h, w), int)
    sx, sy, sw, sh = sub_box
    strips = count - 1
    edges = np.linspace(0, w, strips + 1).round().astype(int)
    for i in range(strips):
        owner[:, edges[i]:edges[i + 1]] = i
    owner[sy:sy + sh, sx:sx + sw] = count - 1
    out = []
    for i in range(count):
        m = (owner == i) & (idx > 0)
        if not m.any():
            ys, xs = np.array([0]), np.array([edges[min(i, strips - 1)]])
        else:
            ys, xs = np.nonzero(m)
        y0, x0 = int(ys.min()), int(xs.min())
        sub = np.where(m, idx, 0)[y0:, x0:]
        parts, raw = spt.tile(sub, gap)
        if not parts:                                  # keep a frame drawable
            parts, raw = [spt.Part(0, 0, 0, 8, 8)], bytes(32)
        out.append(spt.Frame(pos[0] + x0 - base[0], pos[1] + y0 - base[1], parts, raw))
    return out
