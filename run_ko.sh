#!/bin/sh
# 스팀하츠 한글판 실행 (out/ko, 먼저 tools/khpatch.py build) — Mednafen (창 모드, 소리 켬)
cd "$(dirname "$0")"
exec ./tools/mednafen.sh "out/ko/Steam-Hearts (Korean).cue" "$@"
