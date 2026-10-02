#!/bin/sh
# 스팀하츠 원본 디스크 실행 — Mednafen (창 모드, 소리 켬)
# 원본 위치는 SOURCE_CUE로 바꿀 수 있음. BIOS: 프로젝트 폴더의 sega_101.bin
cd "$(dirname "$0")"
CUE="${SOURCE_CUE:-work/disc/Steam-Hearts (Japan).cue}"
exec ./tools/mednafen.sh "$CUE" "$@"
