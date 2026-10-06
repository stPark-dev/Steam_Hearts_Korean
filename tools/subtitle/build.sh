#!/bin/sh
# Build assets/subtitle/SUB.BIN from crt.S + sub.c.
# Needs a big-endian SH cross gcc 13 or newer: apt install gcc-sh4-linux-gnu on Debian trixie /
# recent Ubuntu, or the container in tools/subtitle/Dockerfile.  There is no -m2, so we build
# for SH-4 without FPU and reject every instruction the SH-2 lacks.  gcc 12.2 (Debian bookworm)
# is refused: it drops the test in "if (x)" for values loaded from memory.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
OUT="${OUT:-$HERE/../../assets/subtitle/SUB.BIN}"
TMP="${TMPDIR:-/tmp}/khsub"
mkdir -p "$TMP"
CC=${CC:-sh4-linux-gnu-gcc}
PFX=${CC%gcc}
MAJOR=$($CC -dumpversion | cut -d. -f1)
if [ "$MAJOR" -lt 13 ]; then
    echo "gcc $($CC -dumpversion) miscompiles SH code (sh_treg_combine); use gcc 13+ (tools/subtitle/Dockerfile)" >&2
    exit 1
fi
FLAGS="-m4-nofpu -mb -Os -ffreestanding -fno-builtin -nostdlib -fno-pic -fno-zero-initialized-in-bss \
       -fno-tree-loop-distribute-patterns -Wall -Wextra -Werror $EXTRA"
$CC $FLAGS -c "$HERE/crt.S" -o "$TMP/crt.o"
$CC $FLAGS -c "$HERE/sub.c" -o "$TMP/sub.o"
${PFX}ld -EB --no-warn-rwx-segments -z noexecstack -T "$HERE/sub.ld" "$TMP/crt.o" "$TMP/sub.o" -o "$TMP/sub.elf"
${PFX}objdump -d "$TMP/sub.elf" > "$TMP/sub.lst"
python3 "$HERE/check_sh2.py" "$TMP/sub.lst"
${PFX}objcopy -O binary "$TMP/sub.elf" "$OUT"
${PFX}nm -n "$TMP/sub.elf" | grep -E " (T|t) "
ls -l "$OUT"
