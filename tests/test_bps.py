import random

from mkrelease import bps_apply, bps_create


def _variant(src: bytes, rng: random.Random) -> bytes:
    tgt = bytearray(src)
    for _ in range(40):
        p = rng.randrange(len(tgt))
        for i in range(rng.randrange(1, 30)):
            if p + i < len(tgt):
                tgt[p + i] = rng.randrange(256)
    return bytes(tgt)


def test_roundtrip_same_size():
    rng = random.Random(1)
    src = bytes(rng.randrange(256) for _ in range(20000))
    tgt = _variant(src, rng)
    patch = bps_create(src, tgt)
    assert bps_apply(patch, src) == tgt
    assert len(patch) < 4000


def test_roundtrip_identical_longer_and_edges():
    rng = random.Random(2)
    src = bytes(rng.randrange(256) for _ in range(5000))
    assert bps_apply(bps_create(src, src), src) == src
    longer = _variant(src, rng) + b"tail" * 100
    assert bps_apply(bps_create(src, longer), src) == longer
    edges = b"\xff" + src[1:-1] + b"\x00"
    assert bps_apply(bps_create(src, edges), src) == edges


def test_known_vector():
    # SourceRead 2, TargetRead "Z", SourceRead 1
    patch = bps_create(b"abcd", b"abZd")
    assert patch[:7] == b"BPS1\x84\x84\x80"
    assert patch[7:-12] == bytes([0x80 | (1 << 2 | 0), 0x80 | (0 << 2 | 1)]) + b"Z" + bytes([0x80])
