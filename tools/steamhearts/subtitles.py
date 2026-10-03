"""Voice subtitles for the visual scenes.

Pieces put on the disc:
  SUB.BIN    subtitle code (assets/subtitle/SUB.BIN, built from tools/subtitle/), loaded once
             into RAM nobody uses (0x06086340..0x0608E000, between BSS end and the game heap)
  SUBn.DAT   one per scene: glyphs used by the scene + cues, loaded at BASE + 0x1000
  MAIN.BIN   three unreferenced library version strings become a 32-byte stub pair and the
             file name; in every subtitled scene function three literals are redirected:
             picture loader -> stub, vblank wait -> frame hook, voice player -> play hook.

Cue timing is in real vblanks from the moment the n-th voice of the scene starts sounding
(SUB.BIN watches the sound driver key on the stream slot), at 59.826 Hz (Saturn NTSC).
"""
import struct
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from . import iso9660, sa

MAIN_BASE = 0x06010000
BASE = 0x06086340
DATA_LIMIT = 0x0608E000 - (BASE + 0x1000)       # 27,840 bytes per scene
CODE_LIMIT = 0x1000
CODE_MAGIC = 0x4B485355                         # "KHSU" at BASE + 0x10
DATA_MAGIC = 0x4B485332                         # "KHS2"
FRAME_HOOK = BASE + 0x0A
PLAY_HOOK = BASE + 0x14
FPS = 59.826
ROWS = 12
FONT_PX = 22
MAX_LINE_W = 624
SCREEN_W = 640

FAST, SLOW, NAME = 0x06054398, 0x06059560, 0x0605A36C
ORIG_STRINGS = {FAST: b"SYS Version 2.53 1997-12-15\0", SLOW: b"CDC Version 1.22 1997-02-27\0",
                NAME: b"BUP Version 1.25 1997-06-20\0"}
LOADER, WAIT, PLAY, READ = 0x06030E78, 0x0604A500, 0x06010EB8, 0x06010CD4

# scene number (1-7) -> (picture-loader literal, vblank-wait literal, voice-player literals)
SCENES = {
    1: (0x06033CF4, 0x06033D94, (0x06033D20,)),
    2: (0x06033F44, 0x0603400C, (0x06033F70, 0x06034000)),
    3: (0x060341EC, 0x060342EC, (0x0603421C, 0x060342D8)),
    4: (0x06034498, 0x06034564, (0x060344C4, 0x06034558)),
    5: (0x0603473C, 0x0603484C, (0x0603476C, 0x06034840)),
    6: (0x060349FC, 0x06034AB4, (0x06034A28,)),
    7: (0x06034D58, 0x06034D94, (0x06034D6C,)),
}


class SubtitleError(ValueError):
    pass


def _words(*ws):
    return b"".join(struct.pack(">H", w) for w in ws)


def _longs(*ls):
    return b"".join(struct.pack(">I", v) for v in ls)


# fast path: SUB.BIN present (magic at BASE+0x10)? jump to BASE : go to the slow path
FAST_CODE = _words(0xD504,      # mov.l  L_base,r5
                   0x5054,      # mov.l  @(0x10,r5),r0
                   0xD104,      # mov.l  L_magic,r1
                   0x3010,      # cmp/eq r1,r0
                   0x8902,      # bt     go
                   0xD004,      # mov.l  L_slow,r0
                   0x402B,      # jmp    @r0
                   0x0009,      # nop
                   0x452B,      # go: jmp @r5
                   0x0009) + _longs(BASE, CODE_MAGIC, SLOW)
# slow path: read SUB.BIN to BASE, then jump there (it purges the cache first)
SLOW_CODE = _words(0x4F22,      # sts.l  pr,@-r15
                   0x2F46,      # mov.l  r4,@-r15          picture name
                   0x2F56,      # mov.l  r5,@-r15          BASE
                   0xD404,      # mov.l  L_name,r4
                   0xD004,      # mov.l  L_read,r0
                   0x400B,      # jsr    @r0
                   0x0009,      # nop
                   0x65F6,      # mov.l  @r15+,r5
                   0x64F6,      # mov.l  @r15+,r4
                   0x452B,      # jmp    @r5
                   0x4F26,      # lds.l  @r15+,pr          (delay slot)
                   0x0009) + _longs(NAME, READ)
NAME_DATA = b"SUB.BIN\0".ljust(32, b"\0")


def check_code(code: bytes) -> None:
    if len(code) > CODE_LIMIT:
        raise SubtitleError(f"SUB.BIN is {len(code)} bytes, limit {CODE_LIMIT}")
    if struct.unpack(">I", code[0x10:0x14])[0] != CODE_MAGIC:
        raise SubtitleError("SUB.BIN has no magic at +0x10")
    for off in (0x0A, 0x14):
        if code[off] & 0xF0 != 0xA0:
            raise SubtitleError(f"SUB.BIN +{off:#x} is not a branch")


def patch_main(main: bytes, scenes) -> bytes:
    """MAIN.BIN with the stubs installed and the given scenes hooked (originals verified)."""
    out = bytearray(main)

    def put(addr, old, new):
        off = addr - MAIN_BASE
        if bytes(out[off:off + len(old)]) != old:
            raise SubtitleError(f"MAIN.BIN {addr:#010x}: unexpected original bytes")
        out[off:off + len(new)] = new

    for addr, code in ((FAST, FAST_CODE), (SLOW, SLOW_CODE), (NAME, NAME_DATA)):
        assert len(code) == 32
        put(addr, ORIG_STRINGS[addr], code)
    for n in scenes:
        loader, wait, plays = SCENES[n]
        put(loader, _longs(LOADER), _longs(FAST))
        put(wait, _longs(WAIT), _longs(FRAME_HOOK))
        for p in plays:
            put(p, _longs(PLAY), _longs(PLAY_HOOK))
    return bytes(out)


def data_name(scene: int) -> str:
    return f"SUB{scene}.DAT"


# --- glyphs and data ---------------------------------------------------------------------

@lru_cache(maxsize=None)
def _font(path: str):
    return ImageFont.truetype(path, FONT_PX, index=sa.FONT_INDEX_KR)


def render_glyph(ch: str, font_path: str = sa.DEFAULT_FONT) -> np.ndarray:
    """12 rows of 0..3: drawn square on 24 rows, then halved (a 640x240 pixel is 1:2)."""
    font = _font(font_path)
    adv = max(1, round(font.getlength(ch)))
    im = Image.new("L", (adv + 2, 2 * ROWS), 0)
    ImageDraw.Draw(im).text((1, 19), ch, font=font, fill=255, anchor="ls")
    a = np.asarray(im, dtype=np.float32)
    a = (a[0::2] + a[1::2]) / 2
    lv = np.clip(np.rint(a / 255 * 3), 0, 3).astype(np.uint8)
    cols = np.flatnonzero(lv.any(axis=0))
    w = adv if ch == " " or not len(cols) else max(adv, cols[-1] + 1)
    return lv[:, :w]


def pack_glyph(lv: np.ndarray) -> bytes:
    h, w = lv.shape
    pitch = (w + 3) // 4
    out = bytearray(h * pitch)
    for y in range(h):
        for x in range(w):
            out[y * pitch + x // 4] |= int(lv[y, x]) << (6 - 2 * (x % 4))
    return bytes(out)


def cue_frames(spec: dict, lead: float = 0.1, hold: float = 0.6, minimum: float = 1.2):
    """(audio, start, end, ko) in vblanks after the voice starts, end clipped to the next cue."""
    audio = spec["audio"]
    cues = []
    for e in spec["entries"]:
        a = e["audio"]
        if not 0 <= a < len(audio):
            raise SubtitleError(f"{e['id']}: audio {a} out of range")
        s = max(0, round((e["start"] - lead) * FPS))
        t = round(max(e["end"] + hold, e["start"] + minimum) * FPS)
        if t > 0xFFFF:
            raise SubtitleError(f"{e['id']}: time out of range")
        cues.append([a, s, t, e["ko"], e["id"]])
    cues.sort(key=lambda c: (c[0], c[1]))
    for c, n in zip(cues, cues[1:]):
        if c[0] == n[0]:
            c[2] = min(c[2], n[1])
    return cues


def build_data(spec: dict, font_path: str = sa.DEFAULT_FONT) -> bytes:
    cues = cue_frames(spec)
    missing = sa.missing_glyphs("".join(c[3] for c in cues), font_path)
    if missing:
        raise SubtitleError(f"characters missing from font: {missing}")
    chars = sorted({ch for c in cues for ch in c[3]})
    ids = {ch: i for i, ch in enumerate(chars)}
    glyphs = [render_glyph(ch, font_path) for ch in chars]
    text, cue_rec = [], []
    for a, s, t, ko, cid in cues:
        w = sum(glyphs[ids[ch]].shape[1] for ch in ko)
        if w > MAX_LINE_W:
            raise SubtitleError(f"{cid}: line is {w} px, limit {MAX_LINE_W}: {ko}")
        cue_rec.append(struct.pack(">BBHHHHH", a, 0, s, t, len(text), len(ko), (SCREEN_W - w) // 2))
        text += [ids[ch] for ch in ko]
    bits, glyph_rec = bytearray(), []
    for g in glyphs:
        glyph_rec.append(struct.pack(">2H", g.shape[1], len(bits)))
        bits += pack_glyph(g)
    cues_off = 24
    glyphs_off = cues_off + 12 * len(cue_rec)
    text_off = glyphs_off + 4 * len(glyph_rec)
    bits_off = text_off + 2 * len(text)
    bits_off += -bits_off % 4
    data = struct.pack(">I2H4I", DATA_MAGIC, len(cue_rec), len(glyph_rec), cues_off, glyphs_off, text_off, bits_off)
    data += b"".join(cue_rec) + b"".join(glyph_rec) + struct.pack(f">{len(text)}H", *text)
    data += bytes(bits_off - len(data)) + bits
    if len(data) > DATA_LIMIT:
        raise SubtitleError(f"scene {spec['scene']}: {len(data)} bytes, limit {DATA_LIMIT}")
    return data


# --- ISO 9660 root directory ---------------------------------------------------------------

def iso_key(name: str):
    stem, _, ext = name.partition(".")
    return stem.ljust(8), ext.ljust(3)


def _record(template: bytes, name: str, lba: int, size: int) -> bytes:
    ident = (name + ";1").encode()
    rec = bytearray(template[:33]) + ident
    if len(ident) % 2 == 0:
        rec += b"\0"
    rec[0] = len(rec)
    rec[2:10] = struct.pack("<I", lba) + struct.pack(">I", lba)
    rec[10:18] = iso9660.size_field(size)
    rec[25] = 0
    rec[32] = len(ident)
    return bytes(rec)


def repack_root(read, sizes: dict, new_files) -> dict:
    """Root directory sectors {lba: user data}: sizes updated, new (name, lba, size) records
    inserted in ISO order, records re-packed into the same sectors."""
    records = list(iso9660._records(read))
    dir_lbas = sorted({lba for lba, _, _ in records})
    dots, plain = [], []
    for _, _, rec in records:
        (dots if rec[32] == 1 and rec[33] in (0, 1) else plain).append(rec)
    names = [iso9660._name(r).decode("latin1").split(";")[0] for r in plain]
    if names != sorted(names, key=iso_key):
        raise SubtitleError("root directory is not in ISO order")
    out = []
    for name, rec in zip(names, plain):
        rec = bytearray(rec)
        if name in sizes:
            rec[10:18] = iso9660.size_field(sizes[name])
        out.append(bytes(rec))
    have = set(names)
    for name, lba, size in new_files:
        if name in have:
            raise SubtitleError(f"{name} is already on the disc")
        out.append(_record(plain[-1], name, lba, size))
    out.sort(key=lambda r: iso_key(iso9660._name(r).decode("latin1").split(";")[0]))
    blob, cur = bytearray(), bytearray()
    for rec in dots + out:
        if len(cur) + len(rec) > 2048:
            blob += cur.ljust(2048, b"\0")
            cur = bytearray()
        cur += rec
    blob += cur.ljust(2048, b"\0")
    if len(blob) > 2048 * len(dir_lbas):
        raise SubtitleError("root directory would need another sector")
    blob = blob.ljust(2048 * len(dir_lbas), b"\0")
    return {lba: bytes(blob[i * 2048:(i + 1) * 2048]) for i, lba in enumerate(dir_lbas)}
