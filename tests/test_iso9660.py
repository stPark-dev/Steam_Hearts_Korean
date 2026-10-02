import struct

import pytest

from steamhearts import iso9660


def _rec(name: bytes, lba: int, size: int, flags: int = 0) -> bytes:
    body = bytearray(33 + len(name) + (1 - len(name) % 2))
    body[0] = len(body)
    body[2:10] = struct.pack("<I", lba) + struct.pack(">I", lba)
    body[10:18] = struct.pack("<I", size) + struct.pack(">I", size)
    body[25] = flags
    body[32] = len(name)
    body[33:33 + len(name)] = name
    return bytes(body)


def _image(records: list[bytes]) -> dict[int, bytes]:
    pvd = bytearray(2048)
    pvd[:6] = b"\x01CD001"
    pvd[156:190] = _rec(b"\x00", 20, 2048, 2)[:34]
    root = bytearray(2048)
    data = _rec(b"\x00", 20, 2048, 2) + _rec(b"\x01", 20, 2048, 2) + b"".join(records)
    root[:len(data)] = data
    return {16: bytes(pvd), 20: bytes(root)}


def test_lists_root_files_without_version_suffix():
    sec = _image([_rec(b"MAIN.BIN;1", 314, 372588), _rec(b"YESNO.SA;1", 66052, 1202)])
    files = iso9660.list_files(lambda lba: sec.get(lba, bytes(2048)))
    assert files["MAIN.BIN"] == iso9660.Entry("MAIN.BIN", 314, 372588)
    assert files["YESNO.SA"].lba == 66052


def test_entry_sector_count():
    assert iso9660.Entry("A", 0, 2049).sectors == 2
    assert iso9660.Entry("A", 0, 2048).sectors == 1


def test_rejects_missing_pvd():
    with pytest.raises(iso9660.IsoError):
        iso9660.list_files(lambda lba: bytes(2048))


def test_rejects_subdirectories():
    sec = _image([_rec(b"SUB", 30, 2048, 2)])
    with pytest.raises(iso9660.IsoError):
        iso9660.list_files(lambda lba: sec.get(lba, bytes(2048)))


def test_record_location_points_at_the_directory_record():
    sec = _image([_rec(b"MAIN.BIN;1", 314, 372588), _rec(b"YESNO.SA;1", 66052, 1202)])
    lba, off = iso9660.record_location(lambda lba: sec.get(lba, bytes(2048)), "YESNO.SA")
    rec = sec[lba][off:]
    assert rec[33:41] == b"YESNO.SA"
    assert struct.unpack_from("<I", rec, 10)[0] == 1202


def test_size_field_bytes_are_both_endian():
    assert iso9660.size_field(0x01020304) == bytes.fromhex("04030201" "01020304")
