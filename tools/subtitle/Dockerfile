# Build environment for SUB.BIN: gcc 14 for SH-4 (Debian trixie).
# gcc 12.2 (Debian bookworm) miscompiles "if (x)" on values loaded from memory: its
# sh_treg_combine pass drops the tst (see docs/subtitle-pilot.md 10.3).
#   docker build -t khsub tools/subtitle
#   docker run --rm -u "$(id -u):$(id -g)" -v "$PWD:/w" -w /w khsub sh tools/subtitle/build.sh
FROM debian@sha256:913f6706df59a68922d1dd08f78c2476560a8d367897200a6005b00e5f67c2d5
RUN apt-get update && apt-get install -y --no-install-recommends gcc-sh4-linux-gnu python3 \
    && rm -rf /var/lib/apt/lists/*
