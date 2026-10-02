import pytest

from steamhearts import disc

CHD_CUE = """FILE "Steam-Hearts (Japan).bin" BINARY
  TRACK 01 MODE1/2352
    INDEX 01 00:00:00
  TRACK 02 AUDIO
    INDEX 00 21:33:33
    INDEX 01 21:35:33
"""

REDUMP_CUE = """FILE "Steam-Hearts (Japan) (Track 01).bin" BINARY
  TRACK 01 MODE1/2352
    INDEX 01 00:00:00
FILE "Steam-Hearts (Japan) (Track 02).bin" BINARY
  TRACK 02 AUDIO
    INDEX 00 00:00:00
    INDEX 01 00:02:00
"""


def test_single_file_cue_track1_ends_at_track2_index0():
    t = disc.parse_cue(CHD_CUE)
    assert t.file == "Steam-Hearts (Japan).bin"
    assert t.offset == 0
    assert t.sectors == (21 * 60 + 33) * 75 + 33 == 97008


def test_split_cue_track1_is_its_own_file():
    t = disc.parse_cue(REDUMP_CUE)
    assert t.file == "Steam-Hearts (Japan) (Track 01).bin"
    assert t.sectors is None          # whole file


def test_rejects_non_mode1_first_track():
    with pytest.raises(disc.DiscError):
        disc.parse_cue(CHD_CUE.replace("MODE1/2352", "MODE2/2352"))


def test_msf_parse():
    assert disc.msf("00:02:00") == 150
    with pytest.raises(disc.DiscError):
        disc.msf("00:60:00")


def test_verify_fails_on_truncated_bin_instead_of_looping(tmp_path):
    (tmp_path / "Steam-Hearts (Japan).cue").write_text(CHD_CUE)
    (tmp_path / "Steam-Hearts (Japan).bin").write_bytes(bytes(2352 * 3))
    d = disc.SourceDisc(tmp_path / "Steam-Hearts (Japan).cue")
    with pytest.raises(disc.DiscError, match="truncated"):
        d.verify()
