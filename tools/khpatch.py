#!/usr/bin/env python3
"""스팀하츠 한글판 빌드.  python3 tools/khpatch.py build --source <원본.cue> [--out out/ko] [--sa original] [--title original] [--credits original] [--subtitles original]"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from steamhearts.build import BuildError, build  # noqa: E402

COMPONENTS = ["sa", "title", "credits", "subtitles"]


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--source", required=True, type=Path)
    b.add_argument("--out", default="out/ko", type=Path)
    for c in COMPONENTS:
        b.add_argument(f"--{c}", choices=["ko", "original"], default="ko")
    a = ap.parse_args()
    comps = {c: getattr(a, c) == "ko" for c in COMPONENTS}
    try:
        m = build(a.source, a.out, comps)
    except BuildError as ex:
        print(f"빌드 실패: {ex}", file=sys.stderr)
        return 1
    print(json.dumps(m, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
