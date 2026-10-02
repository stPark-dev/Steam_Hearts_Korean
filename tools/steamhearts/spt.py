"""Sprite banks (*.SPT), big-endian.

  u16 buffer_size   largest decompressed frame blob (the loader's scratch buffer)
  u16 palette_count
  palette_count x 16 RGB555 colors
  u32 frame_count
  frame_count x 24-byte entries: u32 part_table, u32 blob, u32 record, s16 x, s16 y,
                                 u16 part_count, u16 0, u32 0
  part tables: 6 bytes per part: u16 VRAM offset / 8 (inside the frame blob), u8 x, u8 y,
               u8 width / 8, u8 height        (VDP1 4bpp, high nibble = left pixel)
  20-byte record(s) referenced by entries (meaning unknown, kept verbatim)
  LZSS kind 1 blobs, one per frame
Checked against the title screen VDP1 command table (part sizes, relative positions, sources).
"""
import struct
from dataclasses import dataclass, field

import numpy as np

from . import lzss

BAND = 8
SPAN_GAP = 16
RECORD_LEN = 20


class SptError(ValueError):
    pass


@dataclass(frozen=True)
class Part:
    off8: int
    x: int
    y: int
    w: int
    h: int


@dataclass
class Frame:
    x: int
    y: int
    parts: list
    raw: bytes
    z1: int = 0
    z2: int = 0


@dataclass
class ParsedFrame:
    x: int
    y: int
    parts: list
    blob_offset: int
    record_offset: int
    part_table: int
    z1: int = 0
    z2: int = 0


@dataclass
class Spt:
    buffer_size: int
    palettes: list
    frames: list = field(default_factory=list)


def parse(data: bytes) -> Spt:
    try:
        size, npal = struct.unpack_from(">HH", data, 0)
        pals = [list(struct.unpack_from(">16H", data, 4 + 32 * i)) for i in range(npal)]
        o = 4 + 32 * npal
        count = struct.unpack_from(">I", data, o)[0]
        o += 4
        if not npal or not count:
            raise SptError("sprite bank without palette or frames")
        frames = []
        for k in range(count):
            pl, bo, rec, x, y, n, z1, z2 = struct.unpack_from(">IIIhhHHI", data, o + 24 * k)
            parts = []
            for i in range(n):
                off8, px, py, w8, h = struct.unpack_from(">HBBBB", data, pl + 6 * i)
                parts.append(Part(off8, px, py, w8 * 8, h))
            frames.append(ParsedFrame(x, y, parts, bo, rec, pl, z1, z2))
    except struct.error as ex:
        raise SptError(f"truncated sprite bank: {ex}") from ex
    return Spt(size, pals, frames)


def tile(index: np.ndarray, gap: int = SPAN_GAP) -> tuple[list, bytes]:
    """Split a 4-bit indexed image (0 = transparent) into 8-row parts covering every
    opaque pixel; returns the parts and the raw blob they point into."""
    h, w = index.shape
    parts, raw = [], bytearray()
    for y0 in range(0, h, BAND):
        band = np.zeros((BAND, w), np.uint8)
        band[: min(BAND, h - y0)] = index[y0:y0 + BAND]
        cols = np.where(band.any(0))[0]
        if not len(cols):
            continue
        spans, s, p = [], cols[0], cols[0]
        for c in cols[1:]:
            if c - p > gap:
                spans.append((s, p))
                s = c
            p = c
        spans.append((s, p))
        for s, e in spans:
            pw = (e - s + 1 + 7) // 8 * 8
            if s > 255 or y0 > 255 or pw > 255 * 8:
                raise SptError(f"part at ({s},{y0}) width {pw} does not fit the part table fields")
            blk = np.zeros((BAND, pw), np.uint8)
            seg = band[:, s:s + pw]
            blk[:, :seg.shape[1]] = seg
            parts.append(Part(len(raw) // 8, int(s), y0, pw, BAND))
            raw += ((blk[:, 0::2] << 4) | blk[:, 1::2]).astype(np.uint8).tobytes()
    return parts, bytes(raw)


def untile(parts: list, raw: bytes, shape: tuple) -> np.ndarray:
    h, w = shape
    out = np.zeros((h + 255, w + 255 * 8), np.uint8)
    for p in parts:
        b = np.frombuffer(raw[p.off8 * 8:p.off8 * 8 + p.w * p.h // 2], np.uint8).reshape(p.h, p.w // 2)
        px = np.stack([b >> 4, b & 15], -1).reshape(p.h, p.w)
        reg = out[p.y:p.y + p.h, p.x:p.x + p.w]
        reg[px != 0] = px[px != 0]
    return out[:h, :w]


def build(palette: list, frames: list, record: bytes) -> bytes:
    if len(palette) != 16 or len(record) != RECORD_LEN:
        raise SptError("need 16 colors and a 20-byte record")
    blobs = [lzss.compress(f.raw, 1) for f in frames]
    head = 4 + 32 + 4 + 24 * len(frames)
    tables, pls = bytearray(), []
    for f in frames:
        pls.append(head + len(tables))
        for p in f.parts:
            tables += struct.pack(">HBBBB", p.off8, p.x, p.y, p.w // 8, p.h)
    rec_off = head + len(tables)
    blob_off = rec_off + RECORD_LEN
    out = bytearray(struct.pack(">HH", max(len(f.raw) for f in frames), 1))
    out += struct.pack(">16H", *palette)
    out += struct.pack(">I", len(frames))
    pos = blob_off
    for f, pl, b in zip(frames, pls, blobs):
        out += struct.pack(">IIIhhHHI", pl, pos, rec_off, f.x, f.y, len(f.parts), f.z1, f.z2)
        pos += len(b)
    out += tables + record
    for b in blobs:
        out += b
    return bytes(out)
