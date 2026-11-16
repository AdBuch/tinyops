"""QR-Code als SVG, ohne Abhängigkeiten (0.35.2, für «App koppeln»).

Bewusst klein: nur Byte-Modus, Fehlerkorrektur M, Versionen 1 bis 10 (bis 213 Bytes). Das reicht für einen Link mit Einmal-Code.
Aufbau nach ISO/IEC 18004; die Tests lesen die erzeugten Codes mit einem unabhängigen Decoder zurück."""

MAX_BYTES = 213

# Version -> (Korrekturwörter je Block, [(Anzahl Blöcke, Datenwörter je Block), ...]) für Stufe M
_BLOCKS = {
    1: (10, [(1, 16)]), 2: (16, [(1, 28)]), 3: (26, [(1, 44)]), 4: (18, [(2, 32)]), 5: (24, [(2, 43)]),
    6: (16, [(4, 27)]), 7: (18, [(4, 31)]), 8: (22, [(2, 38), (2, 39)]), 9: (22, [(3, 36), (2, 37)]), 10: (26, [(4, 43), (1, 44)]),
}
_ALIGN = {1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34], 7: [6, 22, 38], 8: [6, 24, 42], 9: [6, 26, 46], 10: [6, 28, 50]}

# Galois-Feld GF(256) mit dem Polynom 0x11D
_EXP = [0] * 512
_LOG = [0] * 256
_x = 1
for _i in range(255):
    _EXP[_i] = _x
    _LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D
for _i in range(255, 512):
    _EXP[_i] = _EXP[_i - 255]


def _mul(a, b):
    return 0 if a == 0 or b == 0 else _EXP[_LOG[a] + _LOG[b]]


def _rs_remainder(data, n):
    """Reed-Solomon: n Korrekturwörter zu den Datenwörtern."""
    gen = [1]
    for i in range(n):
        nxt = [0] * (len(gen) + 1)
        for j, g in enumerate(gen):
            nxt[j] ^= g
            nxt[j + 1] ^= _mul(g, _EXP[i])
        gen = nxt
    rem = [0] * n
    for d in data:
        factor = d ^ rem[0]
        rem = rem[1:] + [0]
        for j in range(n):
            rem[j] ^= _mul(gen[j + 1], factor)
    return rem


def _capacity(version):
    return sum(count * size for count, size in _BLOCKS[version][1])


def _version_for(n_bytes):
    for v in range(1, 11):
        header_bits = 4 + (8 if v <= 9 else 16)
        if header_bits + 8 * n_bytes <= 8 * _capacity(v):
            return v
    raise ValueError("Text zu lang für den QR-Code (höchstens %d Bytes)." % MAX_BYTES)


def _codewords(data, version):
    bits = [0, 1, 0, 0]                                             # Byte-Modus
    count_bits = 8 if version <= 9 else 16
    bits += [(len(data) >> i) & 1 for i in range(count_bits - 1, -1, -1)]
    for byte in data:
        bits += [(byte >> i) & 1 for i in range(7, -1, -1)]
    cap = 8 * _capacity(version)
    bits += [0] * min(4, cap - len(bits))                           # Abschluss
    bits += [0] * (-len(bits) % 8)
    words = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]
    pad = (0xEC, 0x11)
    words += [pad[i % 2] for i in range(cap // 8 - len(words))]

    ec_len, groups = _BLOCKS[version]
    blocks, pos = [], 0
    for count, size in groups:
        for _ in range(count):
            blocks.append(words[pos:pos + size])
            pos += size
    ecs = [_rs_remainder(b, ec_len) for b in blocks]
    out = []
    for i in range(max(len(b) for b in blocks)):                    # Datenblöcke verschränken
        out += [b[i] for b in blocks if i < len(b)]
    for i in range(ec_len):
        out += [e[i] for e in ecs]
    return out


_MASKS = (
    lambda x, y: (x + y) % 2 == 0,
    lambda x, y: y % 2 == 0,
    lambda x, y: x % 3 == 0,
    lambda x, y: (x + y) % 3 == 0,
    lambda x, y: (x // 3 + y // 2) % 2 == 0,
    lambda x, y: x * y % 2 + x * y % 3 == 0,
    lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0,
    lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0,
)


class _Grid:
    def __init__(self, version):
        self.version = version
        self.size = n = 17 + 4 * version
        self.m = [[False] * n for _ in range(n)]       # m[y][x]: dunkel?
        self.fn = [[False] * n for _ in range(n)]      # Funktionsmuster, wird nicht maskiert

    def set_fn(self, x, y, dark):
        self.m[y][x] = bool(dark)
        self.fn[y][x] = True

    def _finder(self, cx, cy):
        for dy in range(-4, 5):
            for dx in range(-4, 5):
                x, y = cx + dx, cy + dy
                if 0 <= x < self.size and 0 <= y < self.size:
                    self.set_fn(x, y, max(abs(dx), abs(dy)) not in (2, 4))

    def function_patterns(self):
        n = self.size
        for i in range(n):                                          # Taktlinien
            self.set_fn(6, i, i % 2 == 0)
            self.set_fn(i, 6, i % 2 == 0)
        self._finder(3, 3)
        self._finder(n - 4, 3)
        self._finder(3, n - 4)
        pos = _ALIGN[self.version]
        for cy in pos:                                              # Ausrichtungsmuster, nicht auf den drei Suchmustern
            for cx in pos:
                if (cx, cy) in ((6, 6), (6, pos[-1]), (pos[-1], 6)):
                    continue
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        self.set_fn(cx + dx, cy + dy, max(abs(dx), abs(dy)) != 1)
        self.format_bits(0)                                         # Platz reservieren
        self.version_bits()

    def format_bits(self, mask):
        data = (0 << 3) | mask                                      # Stufe M hat die Kennung 00
        rem = data
        for _ in range(10):
            rem = (rem << 1) ^ ((rem >> 9) * 0x537)
        bits = ((data << 10) | rem) ^ 0x5412
        bit = lambda i: (bits >> i) & 1                             # noqa: E731
        n = self.size
        for i in range(6):
            self.set_fn(8, i, bit(i))
        self.set_fn(8, 7, bit(6))
        self.set_fn(8, 8, bit(7))
        self.set_fn(7, 8, bit(8))
        for i in range(9, 15):
            self.set_fn(14 - i, 8, bit(i))
        for i in range(8):
            self.set_fn(n - 1 - i, 8, bit(i))
        for i in range(8, 15):
            self.set_fn(8, n - 15 + i, bit(i))
        self.set_fn(8, n - 8, True)                                 # immer dunkel

    def version_bits(self):
        if self.version < 7:
            return
        rem = self.version
        for _ in range(12):
            rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
        bits = (self.version << 12) | rem
        for i in range(18):
            a, b = self.size - 11 + i % 3, i // 3
            self.set_fn(a, b, (bits >> i) & 1)
            self.set_fn(b, a, (bits >> i) & 1)

    def place(self, words):
        n, i, total = self.size, 0, len(words) * 8
        right = n - 1
        while right >= 1:
            if right == 6:
                right = 5
            for vert in range(n):
                for j in range(2):
                    x = right - j
                    upward = ((right + 1) & 2) == 0
                    y = n - 1 - vert if upward else vert
                    if not self.fn[y][x] and i < total:
                        self.m[y][x] = bool((words[i >> 3] >> (7 - (i & 7))) & 1)
                        i += 1
            right -= 2

    def apply_mask(self, mask):
        f = _MASKS[mask]
        for y in range(self.size):
            for x in range(self.size):
                if not self.fn[y][x] and f(x, y):
                    self.m[y][x] = not self.m[y][x]

    def penalty(self):
        n, m, score = self.size, self.m, 0
        lines = [row for row in m] + [[m[y][x] for y in range(n)] for x in range(n)]
        for line in lines:
            run, prev = 0, None
            for v in line:                                          # lange Läufe gleicher Farbe
                if v == prev:
                    run += 1
                    if run == 5:
                        score += 3
                    elif run > 5:
                        score += 1
                else:
                    run, prev = 1, v
            s = "".join("1" if v else "0" for v in line)            # Muster, die wie ein Suchmuster aussehen
            score += 40 * (s.count("10111010000") + s.count("00001011101"))
        for y in range(n - 1):                                      # 2x2-Blöcke
            for x in range(n - 1):
                if m[y][x] == m[y][x + 1] == m[y + 1][x] == m[y + 1][x + 1]:
                    score += 3
        dark = sum(sum(row) for row in m)                           # Verhältnis hell/dunkel
        score += 10 * (abs(dark * 20 - n * n * 10) // (n * n))
        return score


def matrix(text, mask=None):
    """Der QR-Code als Liste von Zeilen mit True für dunkle Module. mask=None wählt die beste Maske."""
    data = text.encode("utf-8") if isinstance(text, str) else bytes(text)
    version = _version_for(len(data))
    words = _codewords(data, version)
    best = None
    for k in (range(8) if mask is None else [mask]):
        g = _Grid(version)
        g.function_patterns()
        g.place(words)
        g.apply_mask(k)
        g.format_bits(k)
        p = g.penalty()
        if best is None or p < best[0]:
            best = (p, g.m)
    return best[1]


def svg(text, scale=6, border=4):
    """SVG mit hellem Rand (Ruhezone). Fest schwarz auf weiss, damit der Code auch im dunklen Design lesbar bleibt."""
    m = matrix(text)
    n = len(m) + 2 * border
    path = "".join("M%d,%dh1v1h-1z" % (x + border, y + border) for y, row in enumerate(m) for x, dark in enumerate(row) if dark)
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d" shape-rendering="crispEdges" role="img" aria-label="QR-Code">'
            '<rect width="100%%" height="100%%" fill="#fff"/><path d="%s" fill="#000"/></svg>' % (n, n, n * scale, n * scale, path))
