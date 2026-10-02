"""Minimal ISO 9660 reader for this disc: root directory only (the disc has no subdirectories)."""
import struct
from dataclasses import dataclass
from typing import Callable

ReadUser = Callable[[int], bytes]   # lba -> 2048 bytes of user data


class IsoError(ValueError):
    pass


@dataclass(frozen=True)
class Entry:
    name: str
    lba: int
    size: int

    @property
    def sectors(self) -> int:
        return (self.size + 2047) // 2048


def _records(read: ReadUser):
    """Yield (sector LBA, offset in sector, record) for every root-directory record."""
    pvd = read(16)
    if pvd[:6] != b"\x01CD001":
        raise IsoError("no primary volume descriptor at LBA 16")
    root = pvd[156:190]
    lba, size = struct.unpack("<I", root[2:6])[0], struct.unpack("<I", root[10:14])[0]
    data = b"".join(read(lba + i) for i in range((size + 2047) // 2048))
    p = 0
    while p < len(data):
        ln = data[p]
        if ln == 0:
            p = (p // 2048 + 1) * 2048
            continue
        yield lba + p // 2048, p % 2048, data[p:p + ln]
        p += ln


def _name(rec: bytes) -> bytes:
    return rec[33:33 + rec[32]]


def size_field(size: int) -> bytes:
    """Both-endian 32-bit data length (record bytes 10..17)."""
    return struct.pack("<I", size) + struct.pack(">I", size)


def record_location(read: ReadUser, name: str) -> tuple[int, int]:
    for lba, off, rec in _records(read):
        if _name(rec).decode("latin1").split(";")[0] == name:
            return lba, off
    raise IsoError(f"{name} not in root directory")


def list_files(read: ReadUser) -> dict[str, Entry]:
    out: dict[str, Entry] = {}
    for _, _, rec in _records(read):
        nm = _name(rec)
        if nm in (b"\x00", b"\x01"):
            continue
        name = nm.decode("latin1").split(";")[0]
        if rec[25] & 2:
            raise IsoError(f"unexpected subdirectory {name}")
        out[name] = Entry(name, struct.unpack("<I", rec[2:6])[0], struct.unpack("<I", rec[10:14])[0])
    return out
