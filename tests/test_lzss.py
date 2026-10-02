import os
import random

import pytest

from steamhearts import lzss

# header: size 3 bytes LE, byte 3 = window kind (0 -> 4096 via 0.BIN decoder, 1 -> 1024 via MAIN.BIN decoders)


def test_decode_literal_then_overlapping_reference_1024():
    # flag 0x01: literal 'A' lands at ring 0x3EE; reference 0x3EE len 3 -> "AAAA"
    stream = bytes.fromhex("040000" "01" "01" "41" "EE30")
    assert lzss.decompress(stream) == b"AAAA"


def test_decode_literal_then_overlapping_reference_4096():
    stream = bytes.fromhex("040000" "00" "01" "41" "EEF0")
    assert lzss.decompress(stream) == b"AAAA"


def test_decode_reference_into_cleared_window_yields_zeros():
    stream = bytes.fromhex("120000" "01" "00" "000F")
    assert lzss.decompress(stream) == bytes(18)


def test_decode_stops_at_output_size_even_mid_reference():
    # the game copies the whole reference but the caller only owns `size` bytes
    stream = bytes.fromhex("020000" "01" "00" "000F")
    assert lzss.decompress(stream) == bytes(2)


def test_decode_rejects_unknown_window_kind():
    with pytest.raises(lzss.LzssError):
        lzss.decompress(bytes.fromhex("010000" "02" "01" "41"))


def test_decode_rejects_truncated_stream():
    with pytest.raises(lzss.LzssError):
        lzss.decompress(bytes.fromhex("100000" "01" "01" "41"))


def test_stale_tail_model_changes_output_of_stream_that_reads_it():
    stream = bytes.fromhex("030000" "01" "00" "FF30")  # ring 0x3FF before it is written
    assert lzss.decompress(stream, stale=b"\x11" * 18) != lzss.decompress(stream, stale=b"\x22" * 18)


@pytest.mark.parametrize("kind", [0, 1])
@pytest.mark.parametrize("data", [
    b"",
    b"A",
    bytes(5000),
    b"GIGA32K\0" + bytes(range(256)) * 20,
    bytes(random.Random(7).randrange(4) for _ in range(30000)),
    os.urandom(3000),
])
def test_roundtrip_and_independent_of_stale_tail(kind, data):
    stream = lzss.compress(data, kind)
    assert stream[3] == kind
    assert lzss.decompress(stream, stale=b"\x00" * 18) == data
    assert lzss.decompress(stream, stale=b"\xA5" * 18) == data


def test_compress_never_overshoots_output_size():
    # last token must end exactly at the size so the game never writes past its buffer
    data = bytes(40)
    stream = lzss.compress(data, 1)
    assert lzss.decode_tokens_end(stream) == len(data)


def test_compress_shrinks_repetitive_data():
    assert len(lzss.compress(bytes(10000), 1)) < 1300


def test_compress_rejects_oversize():
    with pytest.raises(lzss.LzssError):
        lzss.compress(bytes(1 << 24), 1)
