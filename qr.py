"""QR-Code als SVG, ohne Fremdbibliothek (0.39: Kopplung mit dem Handy, Prüfbericht r36-05).

Nur was tinyops braucht: Byte-Modus, Fehlerkorrektur M, Version 1 bis 10 (bis 213 Byte). Der Ablauf folgt der Norm
ISO/IEC 18004 und dem bekannten Referenz-Code von Nayuki (Reed-Solomon, Muster, Maske mit der kleinsten Strafe)."""

# Fehlerkorrektur M, Index = Version (0 unbenutzt)
_ECC_PER_BLOCK = (-1, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26)
_BLOCKS = (-1, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5)
_FORMAT_M = 0          # Format-Bits für M
MAX_VERSION = 10


class QrError(ValueError):
    pass


def _raw_modules(ver):
    n = (16 * ver + 128) * ver + 64
    if ver >= 2:
        k = ver // 7 + 2
        n -= (25 * k - 10) * k - 55
        if ver >= 7:
            n -= 36
    return n


def _data_codewords(ver):
    return _raw_modules(ver) // 8 - _ECC_PER_BLOCK[ver] * _BLOCKS[ver]


def _gf_mul(x, y):
    z = 0
    for i in reversed(range(8)):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((y >> i) & 1) * x
    return z


def _rs_divisor(degree):
    out = [0] * (degree - 1) + [1]
    root = 1
    for _ in range(degree):
        for j in range(degree):
            out[j] = _gf_mul(out[j], root)
            if j + 1 < degree:
                out[j] ^= out[j + 1]
        root = _gf_mul(root, 2)
    return out


def _rs_remainder(data, divisor):
    out = [0] * len(divisor)
    for b in data:
        f = b ^ out.pop(0)
        out.append(0)
        for i, c in enumerate(divisor):
            out[i] ^= _gf_mul(c, f)
    return out


def _codewords(data, ver):
    """Datenbits → Codewörter mit Fehlerkorrektur, verschränkt."""
    cc = 8 if ver <= 9 else 16
    cap = _data_codewords(ver) * 8
    bits = [0, 1, 0, 0] + [(len(data) >> i) & 1 for i in reversed(range(cc))]
    for b in data:
        bits += [(b >> i) & 1 for i in reversed(range(8))]
    bits += [0] * min(4, cap - len(bits))
    bits += [0] * (-len(bits) % 8)
    words = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]
    pad = 0xEC
    while len(words) < cap // 8:
        words.append(pad)
        pad ^= 0xEC ^ 0x11
    nblocks, ecl = _BLOCKS[ver], _ECC_PER_BLOCK[ver]
    raw = _raw_modules(ver) // 8
    nshort, shortlen = nblocks - raw % nblocks, raw // nblocks
    div = _rs_divisor(ecl)
    blocks, k = [], 0
    for i in range(nblocks):
        dat = words[k:k + shortlen - ecl + (0 if i < nshort else 1)]
        k += len(dat)
        ecc = _rs_remainder(dat, div)
        if i < nshort:
            dat = dat + [0]
        blocks.append(dat + ecc)
    out = []
    for i in range(len(blocks[0])):
        for j, blk in enumerate(blocks):
            if i != shortlen - ecl or j >= nshort:
                out.append(blk[i])
    return out


_MASKS = (
    lambda x, y: (x + y) % 2, lambda x, y: y % 2, lambda x, y: x % 3, lambda x, y: (x + y) % 3,
    lambda x, y: (x // 3 + y // 2) % 2, lambda x, y: x * y % 2 + x * y % 3,
    lambda x, y: (x * y % 2 + x * y % 3) % 2, lambda x, y: ((x + y) % 2 + x * y % 3) % 2,
)


class _Grid:
    def __init__(self, ver):
        self.ver, self.size = ver, ver * 4 + 17
        self.m = [[False] * self.size for _ in range(self.size)]
        self.fn = [[False] * self.size for _ in range(self.size)]

    def set_fn(self, x, y, dark):
        self.m[y][x] = dark
        self.fn[y][x] = True

    def align_pos(self):
        if self.ver == 1:
            return []
        k = self.ver // 7 + 2
        step = (self.ver * 8 + k * 3 + 5) // (k * 4 - 4) * 2
        return sorted([self.size - 7 - i * step for i in range(k - 1)] + [6])

    def function_patterns(self):
        n = self.size
        for i in range(n):
            self.set_fn(6, i, i % 2 == 0)
            self.set_fn(i, 6, i % 2 == 0)
        for cx, cy in ((3, 3), (n - 4, 3), (3, n - 4)):
            for dy in range(-4, 5):
                for dx in range(-4, 5):
                    x, y = cx + dx, cy + dy
                    if 0 <= x < n and 0 <= y < n:
                        self.set_fn(x, y, max(abs(dx), abs(dy)) not in (2, 4))
        pos = self.align_pos()
        last = len(pos) - 1
        for i, ax in enumerate(pos):
            for j, ay in enumerate(pos):
                if (i, j) in ((0, 0), (0, last), (last, 0)):
                    continue
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        self.set_fn(ax + dx, ay + dy, max(abs(dx), abs(dy)) != 1)
        self.format_bits(0)
        if self.ver >= 7:
            rem = self.ver
            for _ in range(12):
                rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
            bits = self.ver << 12 | rem
            for i in range(18):
                bit = (bits >> i) & 1 == 1
                a, b = n - 11 + i % 3, i // 3
                self.set_fn(a, b, bit)
                self.set_fn(b, a, bit)

    def format_bits(self, mask):
        data = _FORMAT_M << 3 | mask
        rem = data
        for _ in range(10):
            rem = (rem << 1) ^ ((rem >> 9) * 0x537)
        bits = (data << 10 | rem) ^ 0x5412
        g = lambda i: (bits >> i) & 1 == 1      # noqa: E731
        n = self.size
        for i in range(6):
            self.set_fn(8, i, g(i))
        self.set_fn(8, 7, g(6))
        self.set_fn(8, 8, g(7))
        self.set_fn(7, 8, g(8))
        for i in range(9, 15):
            self.set_fn(14 - i, 8, g(i))
        for i in range(8):
            self.set_fn(n - 1 - i, 8, g(i))
        for i in range(8, 15):
            self.set_fn(8, n - 15 + i, g(i))
        self.set_fn(8, n - 8, True)

    def codewords(self, words):
        n, i, total = self.size, 0, len(words) * 8
        right = n - 1
        while right >= 1:
            if right == 6:
                right = 5
            for vert in range(n):
                for j in range(2):
                    x = right - j
                    up = (right + 1) & 2 == 0
                    y = n - 1 - vert if up else vert
                    if not self.fn[y][x] and i < total:
                        self.m[y][x] = (words[i >> 3] >> (7 - (i & 7))) & 1 == 1
                        i += 1
            right -= 2

    def mask(self, k):
        f = _MASKS[k]
        for y in range(self.size):
            for x in range(self.size):
                if not self.fn[y][x] and f(x, y) == 0:
                    self.m[y][x] = not self.m[y][x]

    def penalty(self):
        """Strafe nach der Norm: lange Reihen, 2×2-Blöcke, Muster wie ein Suchmuster, Verhältnis hell zu dunkel."""
        n, m, p = self.size, self.m, 0

        def add(hist, run):
            if hist[0] == 0:
                run += n                     # heller Rand vor der ersten Reihe
            hist.insert(0, run)
            del hist[7:]

        def count(hist):
            k = hist[1]
            core = k > 0 and hist[2] == hist[4] == hist[5] == k and hist[3] == k * 3
            return (core and hist[0] >= k * 4 and hist[6] >= k) + (core and hist[6] >= k * 4 and hist[0] >= k)

        for line in list(m) + [list(c) for c in zip(*m)]:
            color, run, hist = False, 0, [0] * 7
            for v in line:
                if v == color:
                    run += 1
                    if run == 5:
                        p += 3
                    elif run > 5:
                        p += 1
                else:
                    add(hist, run)
                    if not color:
                        p += count(hist) * 40
                    color, run = v, 1
            if color:
                add(hist, run)
                run = 0
            add(hist, run + n)
            p += count(hist) * 40
        for y in range(n - 1):
            for x in range(n - 1):
                if m[y][x] == m[y][x + 1] == m[y + 1][x] == m[y + 1][x + 1]:
                    p += 3
        dark, total = sum(v for row in m for v in row), n * n
        p += ((abs(dark * 20 - total * 10) + total - 1) // total - 1) * 10
        return p


def matrix(text):
    """Module als Liste von Zeilen (True = dunkel)."""
    data = text.encode("utf-8")
    for ver in range(1, MAX_VERSION + 1):
        cc = 8 if ver <= 9 else 16
        if 4 + cc + 8 * len(data) <= _data_codewords(ver) * 8:
            break
    else:
        raise QrError("zu lang für einen QR-Code (%d Byte)" % len(data))
    words = _codewords(data, ver)
    best = None
    for k in range(8):
        g = _Grid(ver)
        g.function_patterns()
        g.codewords(words)
        g.mask(k)
        g.format_bits(k)
        pen = g.penalty()
        if best is None or pen < best[0]:
            best = (pen, g)
    return best[1].m


def svg(text, px=4, quiet=4):
    """QR-Code als SVG-Text. px = Grösse eines Moduls, quiet = Rand in Modulen."""
    m = matrix(text)
    n = len(m) + 2 * quiet
    path = "".join("M%d %dh1v1h-1z" % (x + quiet, y + quiet) for y, row in enumerate(m) for x, v in enumerate(row) if v)
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d" shape-rendering="crispEdges" role="img" '
            'aria-label="QR-Code"><rect width="100%%" height="100%%" fill="#fff"/><path fill="#000" d="%s"/></svg>') % (n, n, n * px, n * px, path)
