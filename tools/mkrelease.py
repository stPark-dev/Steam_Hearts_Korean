#!/usr/bin/env python3
"""Make the distribution zip from a finished build (BPS patches only, no game data).

  python tools/mkrelease.py --source "/path/Steam-Hearts (Japan).cue" --version 0.2.1

Layout (same as v0.2):
  Steam_Hearts_KR_v<ver>/README.txt                          <- docs/release/README.txt
  Steam_Hearts_KR_v<ver>/Redump/Steam-Heart's (Japan) (Track 01).bin.bps   track 1 -> Korean track 1
  Steam_Hearts_KR_v<ver>/Redump/Steam-Heart's (Korean).cue   Korean track 1 + original tracks 2-18
  Steam_Hearts_KR_v<ver>/CHD/Steam-Heart's (Japan).bin.bps    whole CHD BIN -> whole Korean BIN
  Steam_Hearts_KR_v<ver>/CHD/Steam-Heart's (Korean).cue

The source must be the single-BIN CUE that chdman extractcd writes (= the Redump tracks joined).
Every patch is applied back to its source and checked against the build before zipping.
"""
import argparse
import hashlib
import re
import sys
import zipfile
import zlib
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from steamhearts.disc import TRACK1_SECTORS, TRACK1_SHA1  # noqa: E402

RAW = 2352
CHD_SHA1 = "6f7ec1792e5f87bd080ad87dd9026514cb2e88e4"
MERGE_GAP = 16      # equal runs shorter than this stay inside a TargetRead


def _num(n: int) -> bytes:
    out = bytearray()
    while True:
        x = n & 0x7F
        n >>= 7
        if n == 0:
            out.append(0x80 | x)
            return bytes(out)
        out.append(x)
        n -= 1


def bps_create(src: bytes, tgt: bytes) -> bytes:
    """Linear BPS: SourceRead where the bytes match in place, TargetRead elsewhere."""
    n = min(len(src), len(tgt))
    a = np.frombuffer(src, np.uint8, n)
    b = np.frombuffer(tgt, np.uint8, n)
    diff = np.flatnonzero(a != b)
    runs = []                                    # [start, end) of differing bytes
    if len(diff):
        cut = np.flatnonzero(np.diff(diff) > MERGE_GAP)
        starts = np.concatenate(([diff[0]], diff[cut + 1]))
        ends = np.concatenate((diff[cut], [diff[-1]])) + 1
        runs = list(zip(starts.tolist(), ends.tolist()))
    if len(tgt) > n:
        if runs and runs[-1][1] >= n - MERGE_GAP:
            runs[-1] = (runs[-1][0], len(tgt))
        else:
            runs.append((n, len(tgt)))
    out = bytearray(b"BPS1" + _num(len(src)) + _num(len(tgt)) + _num(0))
    pos = 0
    for s, e in runs:
        if s > pos:
            out += _num(((s - pos) - 1) << 2 | 0)
        out += _num(((e - s) - 1) << 2 | 1) + tgt[s:e]
        pos = e
    if pos < len(tgt):
        out += _num(((len(tgt) - pos) - 1) << 2 | 0)
    out += (zlib.crc32(src) & 0xFFFFFFFF).to_bytes(4, "little")
    out += (zlib.crc32(tgt) & 0xFFFFFFFF).to_bytes(4, "little")
    out += (zlib.crc32(out) & 0xFFFFFFFF).to_bytes(4, "little")
    return bytes(out)


def bps_apply(patch: bytes, src: bytes) -> bytes:
    """Full BPS decoder (all four actions), used to check every patch we write."""
    assert patch[:4] == b"BPS1"
    assert zlib.crc32(patch[:-4]) & 0xFFFFFFFF == int.from_bytes(patch[-4:], "little"), "patch crc"
    p = 4

    def num():
        nonlocal p
        data, shift = 0, 1
        while True:
            x = patch[p]
            p += 1
            data += (x & 0x7F) * shift
            if x & 0x80:
                return data
            shift <<= 7
            data += shift

    ssize, tsize, msize = num(), num(), num()
    p += msize
    assert ssize == len(src), "source size"
    assert zlib.crc32(src) & 0xFFFFFFFF == int.from_bytes(patch[-12:-8], "little"), "source crc"
    out = bytearray(tsize)
    o = srel = trel = 0
    end = len(patch) - 12
    while p < end:
        d = num()
        cmd, ln = d & 3, (d >> 2) + 1
        if cmd == 0:
            out[o:o + ln] = src[o:o + ln]
        elif cmd == 1:
            out[o:o + ln] = patch[p:p + ln]
            p += ln
        else:
            v = num()
            delta = -(v >> 1) if v & 1 else v >> 1
            if cmd == 2:
                srel += delta
                out[o:o + ln] = src[srel:srel + ln]
                srel += ln
            else:
                trel += delta
                for i in range(ln):
                    out[o + i] = out[trel + i]
                trel += ln
        o += ln
    assert o == tsize, "target size"
    assert zlib.crc32(out) & 0xFFFFFFFF == int.from_bytes(patch[-8:-4], "little"), "target crc"
    return bytes(out)


def sha1(b: bytes) -> str:
    return hashlib.sha1(b).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True, help="single-BIN CUE from chdman extractcd")
    ap.add_argument("--build", default=str(ROOT / "out/ko"), help="khpatch build output")
    ap.add_argument("--version", required=True)
    ap.add_argument("--out", default=str(ROOT / "out/release"))
    a = ap.parse_args()

    src_cue = Path(a.source)
    m = re.search(r'FILE\s+"([^"]+)"', src_cue.read_text(encoding="utf-8"))
    src = (src_cue.parent / m.group(1)).read_bytes()
    build = Path(a.build)
    tgt_cue_text = next(build.glob("*.cue")).read_text(encoding="utf-8")
    tgt = next(build.glob("*.bin")).read_bytes()
    if sha1(src) != CHD_SHA1:
        sys.exit(f"source BIN is not the supported single BIN (SHA-1 {CHD_SHA1})")
    t1 = TRACK1_SECTORS * RAW
    if sha1(src[:t1]) != TRACK1_SHA1 or len(tgt) != len(src) or tgt[t1:] != src[t1:]:
        sys.exit("build does not match the source layout (track 1 only may differ)")

    name = f"Steam_Hearts_KR_v{a.version}"
    top = Path(a.out) / name
    (top / "Redump").mkdir(parents=True, exist_ok=True)
    (top / "CHD").mkdir(exist_ok=True)
    readme = (ROOT / "docs/release/README.txt").read_text(encoding="utf-8")
    (top / "README.txt").write_bytes(readme.encode("utf-8"))

    redump = bps_create(src[:t1], tgt[:t1])
    assert bps_apply(redump, src[:t1]) == tgt[:t1]
    (top / "Redump/Steam-Heart's (Japan) (Track 01).bin.bps").write_bytes(redump)
    cue = ["FILE \"Steam-Heart's (Korean) (Track 01).bin\" BINARY", "  TRACK 01 MODE1/2352",
           "    INDEX 01 00:00:00"]
    for t in range(2, 19):
        cue += [f"FILE \"Steam-Heart's (Japan) (Track {t:02d}).bin\" BINARY", f"  TRACK {t:02d} AUDIO",
                "    INDEX 00 00:00:00", "    INDEX 01 00:02:00"]
    (top / "Redump/Steam-Heart's (Korean).cue").write_bytes(("\r\n".join(cue) + "\r\n").encode())

    chd = bps_create(src, tgt)
    assert bps_apply(chd, src) == tgt
    (top / "CHD/Steam-Heart's (Japan).bin.bps").write_bytes(chd)
    chd_cue = re.sub(r'FILE\s+"[^"]+"', "FILE \"Steam-Heart's (Korean).bin\"", tgt_cue_text, count=1)
    (top / "CHD/Steam-Heart's (Korean).cue").write_bytes(chd_cue.replace("\r\n", "\n").replace("\n", "\r\n").encode())

    zpath = Path(a.out) / f"{name}.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in sorted(top.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(top.parent).as_posix())
    print(f"Korean track 1  SHA-1 {sha1(tgt[:t1])}")
    print(f"Korean BIN      SHA-1 {sha1(tgt)}")
    print(f"Redump patch    {len(redump):,} bytes, CHD patch {len(chd):,} bytes")
    print(f"{zpath}  {zpath.stat().st_size:,} bytes  SHA-1 {sha1(zpath.read_bytes())}")


if __name__ == "__main__":
    main()
