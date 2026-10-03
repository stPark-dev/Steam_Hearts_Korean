"""Product build: verified source disc -> Korean BIN/CUE + manifest.

Every replaced file goes back into its own sectors. A file that grows past its old byte size
(but not past its sectors) gets its ISO 9660 size updated. All sector changes go through one
WritePlan (expected source bytes, no overlap, final-difference audit).
"""
import hashlib
import json
import re
import shutil
from pathlib import Path

from . import cdsector, credits, iso9660, logo, lzss, sa, spt, subtitles
from .disc import TRACK1_SHA1, SourceDisc, parse_cue
from .writeplan import WritePlan

ROOT = Path(__file__).resolve().parents[2]
OUT_NAME = "Steam-Hearts (Korean)"
ELIGIBLE = "distribution_eligible"


class BuildError(RuntimeError):
    pass


def place(entry: iso9660.Entry, data: bytes, read) -> tuple[list[tuple[int, bytes]], int]:
    """User-data sectors for `data` stored at `entry`, and the size to record for it."""
    cap = entry.sectors * 2048
    if len(data) > cap:
        raise BuildError(f"{entry.name}: {len(data)} bytes exceed its {entry.sectors} sectors")
    size = max(entry.size, len(data))
    body = data + bytes(size - len(data))
    out = []
    for i in range(entry.sectors):
        old = read(entry.lba + i)
        lo = i * 2048
        chunk = body[lo:lo + 2048]
        out.append((entry.lba + i, chunk + old[len(chunk):]))
    return out, size


def merge_sectors(writes: dict, secs: list, name: str) -> None:
    for lba, user in secs:
        if lba in writes:
            raise BuildError(f"{name}: LBA {lba} already written by another replacement")
        writes[lba] = user


def checked_stream(stream: bytes, raw: bytes, name: str) -> bytes:
    """Decode as the game would with arbitrary stale window tails; tokens must end exactly."""
    try:
        ok = (lzss.decompress(stream, stale=b"\xA5" * lzss.STALE_LEN) == raw
              and lzss.decompress(stream, stale=b"\x5A" * lzss.STALE_LEN) == raw
              and lzss.decode_tokens_end(stream) == len(raw))
    except lzss.LzssError as ex:
        raise BuildError(f"{name}: {ex}") from ex
    if not ok:
        raise BuildError(f"{name}: compressed stream does not decode exactly as the game would")
    return stream


def check_sa_coverage(layout: dict, texts: dict) -> None:
    missing = sorted({p["id"] for lay in layout.values() for p in lay["paragraphs"]} - set(texts))
    if missing:
        raise BuildError(f"layout paragraphs without translation: {missing}")


def check_spt_blobs(data: bytes, frames: list, name: str) -> None:
    parsed = spt.parse(data)
    ends = [g.blob_offset for g in parsed.frames[1:]] + [len(data)]
    for k, (f, g) in enumerate(zip(frames, parsed.frames)):
        checked_stream(data[g.blob_offset:ends[k]], f.raw, f"{name} frame {k}")


def _load_json(rel: str):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def sa_files(disc: SourceDisc, files: dict) -> tuple[dict[str, bytes], list[dict]]:
    layout = {k: v for k, v in _load_json("assets/sa/layout.json").items() if not k.startswith("_")}
    entries = _load_json("translation/sa.json")["entries"]
    texts = {e["id"]: e["ko"] for e in entries}
    for e in entries:
        if e["file"] not in layout or not any(p["id"] == e["id"] for p in layout[e["file"]]["paragraphs"]):
            raise BuildError(f"translation {e['id']} has no layout slot in {e['file']}")
    check_sa_coverage(layout, texts)
    out = {}
    for name, lay in layout.items():
        e = files[name]
        old = disc.read_file(e.lba, e.size)
        if old[3] != 0:
            raise BuildError(f"{name}: expected LZSS kind 0, found {old[3]}")
        src = sa.decode(lzss.decompress(old), lay["width"])
        try:
            px = sa.compose(src, lay, texts)
        except sa.LayoutError as ex:
            raise BuildError(str(ex)) from ex
        raw = sa.encode(px)
        out[name] = checked_stream(lzss.compress(raw, 0), raw, name)
    return out, entries


def title_file(disc: SourceDisc, files: dict) -> tuple[dict[str, bytes], bool]:
    lay = _load_json("assets/title/layout.json")
    e = files[lay["file"]]
    old = disc.read_file(e.lba, e.size)
    src = spt.parse(old)
    if len(src.frames) != lay["frames"] or len({f.record_offset for f in src.frames}) != 1:
        raise BuildError(f"{lay['file']}: unexpected frame structure")
    old_total = sum(len(lzss.decompress(old[f.blob_offset:])) for f in src.frames)
    record = old[src.frames[0].record_offset:src.frames[0].record_offset + spt.RECORD_LEN]
    pal, idx = logo.convert(ROOT / lay["source"], *lay["size"], colors=lay["colors"])
    frames = logo.frames(idx, tuple(lay["pos"]), tuple(lay["base"]), lay["frames"], tuple(lay["sub_box"]),
                         gap=lay["span_gap"])
    total = sum(len(f.raw) for f in frames)
    biggest = max(len(f.raw) for f in frames)
    if total > old_total:
        raise BuildError(f"title logo needs {total} bytes of VDP1 VRAM, original used {old_total}")
    if biggest > src.buffer_size:
        raise BuildError(f"title logo frame of {biggest} bytes exceeds the {src.buffer_size}-byte buffer")
    data = spt.build(pal, frames, record)
    check_spt_blobs(data, frames, lay["file"])
    return {lay["file"]: data}, bool(lay.get("approved"))


def credits_file(disc: SourceDisc, files: dict) -> tuple[dict[str, bytes], list[dict]]:
    blocks = _load_json("translation/credits.json")["blocks"]
    e = files["SR.SPT"]
    old = disc.read_file(e.lba, e.size)
    src = spt.parse(old)
    if len(src.frames) != 2 * len(blocks) or len({f.record_offset for f in src.frames}) != 1:
        raise BuildError("SR.SPT: frame count does not match the 18 credit blocks")
    raw_of = lambda f: lzss.decompress(old[f.blob_offset:])
    old_total = sum(len(raw_of(f)) for f in src.frames)
    frames = []
    for b, blk in enumerate(blocks):
        orig = credits.from_frames(src.frames[2 * b], src.frames[2 * b + 1], raw_of)
        keep = (orig, blk["keep_from_line"]) if "keep_from_line" in blk else None
        try:
            canvas = credits.render_block(blk["ko"], orig.top, keep)
        except credits.CreditsError as ex:
            raise BuildError(f"{blk['id']}: {ex}") from ex
        frames += credits.split(canvas)
    total = sum(len(f.raw) for f in frames)
    biggest = max(len(f.raw) for f in frames)
    if total > old_total:
        raise BuildError(f"staff roll needs {total} bytes of VRAM, original used {old_total}")
    if biggest > src.buffer_size:
        raise BuildError(f"staff roll frame of {biggest} bytes exceeds the {src.buffer_size}-byte buffer")
    record = old[src.frames[0].record_offset:src.frames[0].record_offset + spt.RECORD_LEN]
    data = spt.build(src.palettes[0], frames, record)
    check_spt_blobs(data, frames, "SR.SPT")
    return {"SR.SPT": data}, blocks


def subtitle_files(disc: SourceDisc, files: dict) -> tuple[dict[str, bytes], dict[str, bytes], list[dict], list[int]]:
    """(replaced files, new files, translation entries, scene numbers) for the voice subtitles."""
    voice_dir = ROOT / "translation/voice"
    specs = sorted((_load_json(str(p.relative_to(ROOT))) for p in voice_dir.glob("vis*.json")),
                   key=lambda s: s["scene"])
    stage_specs = sorted((_load_json(str(p.relative_to(ROOT))) for p in voice_dir.glob("st*.json")),
                         key=lambda s: s["stage"])
    if not specs:
        raise BuildError("no translation/voice/vis*.json")
    code = (ROOT / "assets/subtitle/SUB.BIN").read_bytes()
    new = {"SUB.BIN": code}
    entries, scenes = [], []
    try:
        subtitles.check_code(code)
        for spec in specs:
            n = spec["scene"]
            if n not in subtitles.SCENES or n in scenes:
                raise BuildError(f"voice translation for unknown or repeated scene {n}")
            new[subtitles.data_name(n)] = subtitles.build_data(spec)
            entries += spec["entries"]
            scenes.append(n)
        stages = []
        for spec in stage_specs:
            n = spec["stage"]
            if not 1 <= n <= 9 or n in stages:
                raise BuildError(f"voice translation for unknown or repeated stage {n}")
            new[subtitles.stage_name(n)] = subtitles.build_stage_data(spec)
            entries += spec["entries"]
            stages.append(n)
        e = files["MAIN.BIN"]
        main = subtitles.patch_main(disc.read_file(e.lba, e.size), scenes)
    except subtitles.SubtitleError as ex:
        raise BuildError(str(ex)) from ex
    return {"MAIN.BIN": main}, new, entries, scenes


def _sha1(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 22), b""):
            h.update(b)
    return h.hexdigest()


def build(source_cue: Path, out_dir: Path, components: dict[str, bool]) -> dict:
    """Run the product build; every failure surfaces as BuildError."""
    source_cue = Path(source_cue)
    try:
        disc = SourceDisc(source_cue)
    except (OSError, ValueError) as ex:
        raise BuildError(str(ex)) from ex
    try:
        return _build(disc, source_cue, Path(out_dir), components)
    except BuildError:
        raise
    except (OSError, ValueError, RuntimeError) as ex:
        raise BuildError(f"{type(ex).__name__}: {ex}") from ex
    finally:
        disc.close()


def _build(disc: SourceDisc, source_cue: Path, out_dir: Path, components: dict[str, bool]) -> dict:
    disc.verify()
    files = iso9660.list_files(disc.user)
    replaced: dict[str, bytes] = {}
    entries: list[dict] = []
    if components.get("sa"):
        r, entries = sa_files(disc, files)
        replaced.update(r)
    if components.get("credits"):
        r, blocks = credits_file(disc, files)
        replaced.update(r)
        entries = entries + blocks
    logo_ok = True
    if components.get("title"):
        r, logo_ok = title_file(disc, files)
        replaced.update(r)
    added: dict[str, bytes] = {}
    sub_scenes: list[int] = []
    if components.get("subtitles"):
        r, added, sub_entries, sub_scenes = subtitle_files(disc, files)
        replaced.update(r)
        entries = entries + sub_entries

    plan = WritePlan(disc.bin)
    user_writes: dict[int, bytes] = {}
    report = {}
    sizes: dict[str, int] = {}
    for name, data in sorted(replaced.items()):
        e = files[name]
        secs, size = place(e, data, disc.user)
        merge_sectors(user_writes, secs, name)
        if size != e.size:
            sizes[name] = size
        report[name] = {"old_size": e.size, "new_size": size, "stream": len(data)}
    if added:
        # new files go after the last file, inside track 1; the root directory is re-packed
        lba = max(e.lba + e.sectors for e in files.values())
        placed = []
        for name, data in added.items():
            n = (len(data) + 2047) // 2048
            if lba + n > disc.sectors:
                raise BuildError(f"no room for {name}: track 1 ends at LBA {disc.sectors}")
            merge_sectors(user_writes, [(lba + i, data[i * 2048:(i + 1) * 2048].ljust(2048, bytes(1)))
                                        for i in range(n)], name)
            placed.append((name, lba, len(data)))
            report[name] = {"lba": lba, "new_size": len(data)}
            lba += n
        try:
            dir_secs = subtitles.repack_root(disc.user, sizes, placed)
        except subtitles.SubtitleError as ex:
            raise BuildError(str(ex)) from ex
        merge_sectors(user_writes, sorted(dir_secs.items()), "root directory")
    else:
        for name, size in sizes.items():
            dl, off = iso9660.record_location(disc.user, name)
            sec = bytearray(user_writes.get(dl, disc.user(dl)))
            sec[off + 10:off + 18] = iso9660.size_field(size)
            user_writes[dl] = bytes(sec)
    for lba, user in sorted(user_writes.items()):
        raw = disc.raw(lba)
        sec = bytearray(raw)
        sec[16:16 + 2048] = user
        cdsector.fix_mode1(sec)
        if bytes(sec) != raw:
            plan.add(f"lba{lba}", disc.offset + lba * cdsector.RAW, raw, bytes(sec))

    out_dir.mkdir(parents=True, exist_ok=True)
    cue_text = source_cue.read_text(encoding="utf-8", errors="replace")
    track1 = parse_cue(cue_text).file
    out_bin = out_dir / f"{OUT_NAME}.bin"
    plan.apply(out_bin)
    cue_out = cue_text.replace(track1, out_bin.name)
    for other in sorted(set(_cue_files(cue_text)) - {track1}):
        dst = out_dir / other.replace("Japan", "Korean")
        if dst.resolve() == source_cue.with_name(other).resolve():
            raise BuildError(f"output {dst} would overwrite the source track file")
        shutil.copyfile(source_cue.with_name(other), dst)
        cue_out = cue_out.replace(other, dst.name)
    (out_dir / f"{OUT_NAME}.cue").write_text(cue_out, encoding="utf-8")

    pending = sorted(e["id"] for e in entries if e.get("status") != ELIGIBLE)
    manifest = {
        "source_track1_sha1": TRACK1_SHA1,
        "components": components,
        "files": report,
        "sectors_changed": len(plan.writes),
        "output_bin": out_bin.name,
        "output_sha1": _sha1(out_bin),
        "translation_pending": pending,
        "title_logo_approved": logo_ok,
        "subtitle_scenes": sub_scenes,
        "distribution": bool(entries) and not pending and logo_ok and all(components.values()),
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def _cue_files(text: str) -> list[str]:
    return re.findall(r'FILE\s+"(.+)"\s+BINARY', text)
