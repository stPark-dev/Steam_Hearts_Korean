import pytest

from steamhearts import build
from steamhearts.iso9660 import Entry


def _reader(fill: dict[int, bytes]):
    return lambda lba: fill.get(lba, bytes([lba & 0xFF]) * 2048)


def test_smaller_file_is_zero_padded_to_old_size_and_tail_kept():
    e = Entry("A.SA", 10, 3000)
    secs, size = build.place(e, b"\x11" * 100, _reader({}))
    assert size == 3000
    assert [lba for lba, _ in secs] == [10, 11]
    data = b"".join(s for _, s in secs)
    assert data[:100] == b"\x11" * 100
    assert data[100:3000] == bytes(2900)
    assert data[3000:] == bytes([11]) * (4096 - 3000)     # bytes after the file kept


def test_bigger_file_within_its_sectors_grows_size():
    e = Entry("A.SA", 10, 3000)
    secs, size = build.place(e, b"\x22" * 4000, _reader({}))
    assert size == 4000
    data = b"".join(s for _, s in secs)
    assert data[:4000] == b"\x22" * 4000 and data[4000:] == bytes([11]) * 96


def test_file_beyond_its_sectors_is_rejected():
    with pytest.raises(build.BuildError):
        build.place(Entry("A.SA", 10, 3000), bytes(4097), _reader({}))


def test_merge_refuses_a_sector_written_twice():
    writes = {}
    build.merge_sectors(writes, [(10, bytes(2048))], "A.SA")
    with pytest.raises(build.BuildError, match="already"):
        build.merge_sectors(writes, [(10, bytes(2048))], "B.SA")


def test_sa_layout_paragraph_without_translation_fails():
    layout = {"A.SA": {"paragraphs": [{"id": "a.1"}, {"id": "a.2"}]}}
    with pytest.raises(build.BuildError, match="a.2"):
        build.check_sa_coverage(layout, {"a.1": "가"})


def test_checked_stream_rejects_stale_tail_reference():
    from steamhearts import lzss
    bad = bytes.fromhex("030000" "01" "00" "FF30")   # reads ring 0x3FF before it is written
    with pytest.raises(build.BuildError):
        build.checked_stream(bad, bytes(3), "X")
    good = lzss.compress(b"abcabcabc", 1)
    assert build.checked_stream(good, b"abcabcabc", "X") == good
