import json
import pathlib
import struct

import numpy as np
import pytest

from steamhearts import iso9660, subtitles as st

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _rec(name: bytes, lba: int, size: int, flags: int = 0) -> bytes:
    body = bytearray(33 + len(name) + (1 - len(name) % 2))
    body[0] = len(body)
    body[2:10] = struct.pack("<I", lba) + struct.pack(">I", lba)
    body[10:18] = iso9660.size_field(size)
    body[25] = flags
    body[32] = len(name)
    body[33:33 + len(name)] = name
    return bytes(body)


def _image(records, sectors=2):
    pvd = bytearray(2048)
    pvd[:6] = b"\x01CD001"
    pvd[156:190] = _rec(b"\x00", 20, 2048 * sectors, 2)[:34]
    data = _rec(b"\x00", 20, 2048, 2) + _rec(b"\x01", 20, 2048, 2) + b"".join(records)
    out = {16: bytes(pvd)}
    for i in range(sectors):
        out[20 + i] = bytes(data[i * 2048:(i + 1) * 2048].ljust(2048, b"\0"))
    return lambda lba: out.get(lba, bytes(2048))


def _pc_literal(code: bytes, base: int, off: int) -> int:
    """Value loaded by the mov.l @(disp,PC) at `off`."""
    w = struct.unpack(">H", code[off:off + 2])[0]
    assert w >> 12 == 0xD
    addr = ((base + off) & ~3) + 4 + (w & 0xFF) * 4
    return struct.unpack(">I", code[addr - base:addr - base + 4])[0]


def test_stubs_fit_and_load_the_right_constants():
    assert len(st.FAST_CODE) == len(st.SLOW_CODE) == len(st.NAME_DATA) == 32
    assert _pc_literal(st.FAST_CODE, st.FAST, 0) == st.BASE
    assert _pc_literal(st.FAST_CODE, st.FAST, 4) == st.CODE_MAGIC
    assert _pc_literal(st.FAST_CODE, st.FAST, 10) == st.SLOW
    assert struct.unpack(">H", st.FAST_CODE[2:4])[0] == 0x5054        # mov.l @(0x10,r5),r0
    assert _pc_literal(st.SLOW_CODE, st.SLOW, 6) == st.NAME
    assert _pc_literal(st.SLOW_CODE, st.SLOW, 8) == st.READ
    assert st.NAME_DATA.startswith(b"SUB.BIN\0")


def _fake_main():
    main = bytearray(0x06070000 - st.MAIN_BASE)
    for addr, s in st.ORIG_STRINGS.items():
        main[addr - st.MAIN_BASE:addr - st.MAIN_BASE + len(s)] = s
    for loader, wait, plays in st.SCENES.values():
        for a, v in [(loader, st.LOADER), (wait, st.WAIT)] + [(p, st.PLAY) for p in plays]:
            main[a - st.MAIN_BASE:a - st.MAIN_BASE + 4] = struct.pack(">I", v)
    return bytes(main)


def test_patch_main_hooks_only_requested_scenes():
    main = _fake_main()
    out = st.patch_main(main, [1, 3])
    lit = lambda a: struct.unpack(">I", out[a - st.MAIN_BASE:a - st.MAIN_BASE + 4])[0]
    assert lit(st.SCENES[1][0]) == st.FAST and lit(st.SCENES[1][1]) == st.FRAME_HOOK
    assert all(lit(p) == st.PLAY_HOOK for p in st.SCENES[3][2])
    assert lit(st.SCENES[2][0]) == st.LOADER and lit(st.SCENES[2][1]) == st.WAIT
    assert out[st.FAST - st.MAIN_BASE:st.FAST - st.MAIN_BASE + 32] == st.FAST_CODE
    diff = sum(a != b for a, b in zip(main, out))
    assert diff <= 3 * 32 + 4 * (2 + 1 + 2)


def test_patch_main_refuses_unexpected_bytes():
    main = bytearray(_fake_main())
    main[st.SCENES[4][1] - st.MAIN_BASE] ^= 1
    with pytest.raises(st.SubtitleError):
        st.patch_main(bytes(main), [4])
    st.patch_main(bytes(main), [1])


def test_shipped_code_has_entry_points():
    code = (ROOT / "assets/subtitle/SUB.BIN").read_bytes()
    st.check_code(code)
    assert struct.unpack(">I", code[0x10:0x14])[0] == st.CODE_MAGIC


def _spec(entries, naudio=1):
    return {"scene": 1, "audio": [{"file": "X.AIF"}] * naudio, "entries": entries}


def test_cue_frames_lead_hold_and_stop_at_next_line():
    spec = _spec([
        {"id": "a", "audio": 0, "start": 1.0, "end": 1.5, "ko": "가"},
        {"id": "b", "audio": 0, "start": 2.0, "end": 3.0, "ko": "나"},
        {"id": "c", "audio": 1, "start": 0.05, "end": 4.0, "ko": "다"},
    ], naudio=2)
    a, b, c = st.cue_frames(spec)
    assert a[1] == round(0.9 * st.FPS)
    assert a[2] == b[1]                         # 1.5 + hold would overlap "b": clipped
    assert b[2] == round(3.6 * st.FPS)
    assert c[0] == 1 and c[1] == 0              # lead never goes before the voice starts


def test_build_data_layout_round_trips():
    spec = _spec([{"id": "a", "audio": 0, "start": 1.0, "end": 2.0, "ko": "안녕, 세상"},
                  {"id": "b", "audio": 0, "start": 3.0, "end": 4.0, "ko": "세상아"}])
    data = st.build_data(spec)
    magic, ncues, nglyphs, cues, glyphs, text, bits = struct.unpack(">I2H4I", data[:24])
    assert magic == st.DATA_MAGIC and ncues == 2 and nglyphs == len(set("안녕, 세상아"))
    assert bits % 4 == 0
    audio, _, s, e, t, n, x = struct.unpack(">BBHHHHH", data[cues:cues + 12])
    ids = struct.unpack(f">{n}H", data[text + 2 * t:text + 2 * t + 2 * n])
    widths = [struct.unpack(">2H", data[glyphs + 4 * i:glyphs + 4 * i + 4])[0] for i in ids]
    assert x == (st.SCREEN_W - sum(widths)) // 2
    # first glyph decodes back to the rendered levels
    w, off = struct.unpack(">2H", data[glyphs + 4 * ids[0]:glyphs + 4 * ids[0] + 4])
    pitch = (w + 3) // 4
    raw = data[bits + off:bits + off + st.ROWS * pitch]
    lv = np.array([[(raw[y * pitch + x // 4] >> (6 - 2 * (x % 4))) & 3 for x in range(w)] for y in range(st.ROWS)])
    assert (lv == st.render_glyph("안")).all()


def test_build_data_rejects_overlong_lines():
    with pytest.raises(st.SubtitleError):
        st.build_data(_spec([{"id": "a", "audio": 0, "start": 1, "end": 2, "ko": "가" * 40}]))


def test_repack_root_inserts_in_iso_order_and_updates_sizes():
    read = _image([_rec(b"A.BIN;1", 30, 10), _rec(b"ST8.AIF;1", 40, 20), _rec(b"SWORD.AIF;1", 50, 30)])
    secs = st.repack_root(read, {"A.BIN": 99}, [("SUB.BIN", 100, 744), ("SUB1.DAT", 101, 5000)])
    files = iso9660.list_files(lambda lba: secs.get(lba, read(lba)))
    assert files["SUB1.DAT"] == iso9660.Entry("SUB1.DAT", 101, 5000)
    assert files["A.BIN"].size == 99
    names = [iso9660._name(r).decode() for _, _, r in iso9660._records(lambda lba: secs.get(lba, read(lba)))][2:]
    assert names == ["A.BIN;1", "ST8.AIF;1", "SUB.BIN;1", "SUB1.DAT;1", "SWORD.AIF;1"]


def test_voice_translations_build():
    for path in sorted((ROOT / "translation/voice").glob("vis*.json")):
        spec = json.loads(path.read_text(encoding="utf-8"))
        assert spec["scene"] in st.SCENES
        assert {e["audio"] for e in spec["entries"]} <= set(range(len(spec["audio"])))
        assert all(e["status"] in ("needs_review", "needs_human_review", "distribution_eligible")
                   for e in spec["entries"])
        ids = [e["id"] for e in spec["entries"]]
        assert len(ids) == len(set(ids))
        assert len(st.build_data(spec)) <= st.DATA_LIMIT
