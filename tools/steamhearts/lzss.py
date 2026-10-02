"""LZSS codec of Steam-Heart's (Saturn).

Header: output size, 3 bytes little-endian, then a kind byte.
  kind 0: 4096-byte window, decoder in 0.BIN (0x060106A0 when loaded at 0x06010000). It reads
          all 4 header bytes as the size, so kind 0 is part of the size there.
  kind 1: 1024-byte window, decoders in MAIN.BIN (file offsets 0x1FC94 and 0x1FD74); they read
          only 3 size bytes.
Payload: flag byte read LSB first; bit 1 = literal byte, bit 0 = 2-byte reference
    pos = lo | (hi & 0xF0) << 4 (masked to the window), length = (hi & 0x0F) + 3.
The window is cleared on [0, N-18) and the first write goes to N-18; the 18-byte tail keeps
whatever was there before (stack or static buffer). Decoding ends when `size` bytes are out.
"""

MIN_MATCH = 3
MAX_MATCH = 18
WINDOWS = {0: 4096, 1: 1024}
STALE_LEN = MAX_MATCH


class LzssError(ValueError):
    pass


def _header(stream: bytes) -> tuple[int, int]:
    if len(stream) < 4:
        raise LzssError("stream shorter than its 4-byte header")
    kind = stream[3]
    if kind not in WINDOWS:
        raise LzssError(f"unknown window kind {kind}")
    return int.from_bytes(stream[:3], "little"), WINDOWS[kind]


def _tokens(stream: bytes, n: int):
    """Yield (literal_byte, None) or (None, (pos, length)) until the stream ends."""
    i = 4
    while i < len(stream):
        flags = stream[i]
        i += 1
        for _ in range(8):
            if i >= len(stream):
                return
            if flags & 1:
                yield stream[i], None
                i += 1
            else:
                if i + 1 >= len(stream):
                    raise LzssError("truncated reference")
                lo, hi = stream[i], stream[i + 1]
                i += 2
                yield None, ((lo | (hi & 0xF0) << 4) & (n - 1), (hi & 0x0F) + MIN_MATCH)
            flags >>= 1


def decompress(stream: bytes, stale: bytes | None = None) -> bytes:
    """Decode like the game; `stale` models the uncleared 18-byte window tail."""
    size, n = _header(stream)
    start = n - STALE_LEN
    win = bytearray(n)
    if stale is not None:
        if len(stale) != STALE_LEN:
            raise LzssError("stale tail must be 18 bytes")
        win[start:] = stale
    r = start
    out = bytearray()
    for lit, ref in _tokens(stream, n):
        if len(out) >= size:
            break
        if ref is None:
            out.append(lit)
            win[r] = lit
            r = (r + 1) & (n - 1)
            continue
        pos, ln = ref
        for k in range(ln):
            c = win[(pos + k) & (n - 1)]
            out.append(c)
            win[r] = c
            r = (r + 1) & (n - 1)
    if len(out) < size:
        raise LzssError(f"stream ended after {len(out)} of {size} bytes")
    return bytes(out[:size])


def decode_tokens_end(stream: bytes) -> int:
    """Number of bytes all tokens of the stream would write (detects overshoot)."""
    _, n = _header(stream)
    return sum(1 if ref is None else ref[1] for _, ref in _tokens(stream, n))


def compress(data: bytes, kind: int, chain_limit: int = 512) -> bytes:
    """Optimal-parse LZSS (literal 9 bits, reference 17 bits). References read only the cleared
    window and bytes already produced, never the stale tail, and the last token ends exactly
    at len(data)."""
    if kind not in WINDOWS:
        raise LzssError(f"unknown window kind {kind}")
    if len(data) >= 1 << 24:
        raise LzssError("data too large for a 3-byte size")
    n = WINDOWS[kind]
    start = n - STALE_LEN
    buf = bytes(start) + data          # linear index; ring slot = index & (n - 1)
    total = len(buf)
    head: dict[int, int] = {}
    prev = [-1] * total

    def insert(p: int) -> None:
        if p + 2 < total:
            key = buf[p] | buf[p + 1] << 8 | buf[p + 2] << 16
            prev[p] = head.get(key, -1)
            head[key] = p

    def longest(c: int) -> tuple[int, int]:
        if c + 2 >= total:
            return 0, 0
        key = buf[c] | buf[c + 1] << 8 | buf[c + 2] << 16
        best_len = best_pos = 0
        p = head.get(key, -1)
        tries = 0
        limit = min(MAX_MATCH, total - c)
        while p >= 0 and c - p <= n - 1 and tries < chain_limit:
            ln = 0
            while ln < limit and buf[p + ln] == buf[c + ln]:
                ln += 1
            if ln > best_len:
                best_len, best_pos = ln, p
                if ln == limit:
                    break
            p = prev[p]
            tries += 1
        return (best_len, best_pos) if best_len >= MIN_MATCH else (0, 0)

    for p in range(start):
        insert(p)
    matches = []
    for c in range(start, total):
        matches.append(longest(c))
        insert(c)
    m = total - start
    cost = [0] * (m + 1)
    step = [0] * (m + 1)
    for k in range(m - 1, -1, -1):
        best, how = cost[k + 1] + 9, 0
        ln, _ = matches[k]
        for L in range(MIN_MATCH, ln + 1):
            v = cost[k + L] + 17
            if v < best:
                best, how = v, L
        cost[k], step[k] = best, how
    items: list = []
    k = 0
    while k < m:
        L = step[k]
        if L:
            items.append((matches[k][1] & (n - 1), L))
            k += L
        else:
            items.append(buf[start + k])
            k += 1
    payload = bytearray()
    for g in range(0, len(items), 8):
        flag = 0
        body = bytearray()
        for b, it in enumerate(items[g:g + 8]):
            if isinstance(it, int):
                flag |= 1 << b
                body.append(it)
            else:
                off, ln = it
                body += bytes([off & 0xFF, ((off >> 4) & 0xF0) | (ln - MIN_MATCH)])
        payload.append(flag)
        payload += body
    return len(data).to_bytes(3, "little") + bytes([kind]) + bytes(payload)
