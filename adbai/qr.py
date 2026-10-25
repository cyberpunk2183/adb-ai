"""A QR encoder in the standard library, because a QR is the shortest path in.

Android 11 and newer can pair over Wi-Fi by camera: the phone's "Pair device
with QR code" screen reads a code off your terminal and does the rest. That
replaces the part of pairing people get wrong - reading an IP, a port and six
digits off one screen and typing them into another.

Every QR library on PyPI would do this. None of them may be here: this project
installs with no dependencies so that it is the same install on Windows, macOS,
Linux and Termux. So the encoder is ours. It is deliberately small - byte mode
only, versions 1 to 9, correction levels L and M - which is far more than the
~50 characters a pairing payload needs, and keeps the code readable enough to
check against the spec.
"""

from __future__ import annotations

from typing import List, Sequence, Tuple

Matrix = List[List[bool]]

# Correction level -> the two bits that go into the format information.
_ECL_BITS = {"L": 1, "M": 0, "Q": 3, "H": 2}

# (version, level) -> (ec codewords per block, [data codewords per block]).
# Only what we support; the totals are the ones in the spec's table 9.
_BLOCKS = {
    (1, "L"): (7, [19]),
    (1, "M"): (10, [16]),
    (2, "L"): (10, [34]),
    (2, "M"): (16, [28]),
    (3, "L"): (15, [55]),
    (3, "M"): (26, [44]),
    (4, "L"): (20, [80]),
    (4, "M"): (18, [32, 32]),
    (5, "L"): (26, [108]),
    (5, "M"): (24, [43, 43]),
    (6, "L"): (18, [68, 68]),
    (6, "M"): (16, [27, 27, 27, 27]),
    (7, "L"): (20, [78, 78]),
    (7, "M"): (18, [31, 31, 31, 31]),
    (8, "L"): (24, [97, 97]),
    (8, "M"): (22, [38, 38, 39, 39]),
    (9, "L"): (30, [116, 116]),
    (9, "M"): (22, [36, 36, 36, 37, 37]),
}

# Centres of the alignment patterns, per version.
_ALIGNMENT = {
    1: [],
    2: [6, 18],
    3: [6, 22],
    4: [6, 26],
    5: [6, 30],
    6: [6, 34],
    7: [6, 22, 38],
    8: [6, 24, 42],
    9: [6, 26, 46],
}

MAX_VERSION = 9


class QrError(ValueError):
    """The payload does not fit, or the arguments do not make sense."""


# --- GF(256), the field the error correction lives in ------------------------

_EXP = [0] * 512
_LOG = [0] * 256


def _build_tables() -> None:
    x = 1
    for i in range(255):
        _EXP[i] = x
        _LOG[x] = i
        x <<= 1
        if x & 0x100:  # the field's generating polynomial, x^8+x^4+x^3+x^2+1
            x ^= 0x11D
    for i in range(255, 512):
        _EXP[i] = _EXP[i - 255]


_build_tables()


def _mul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return _EXP[_LOG[a] + _LOG[b]]


def _generator(degree: int) -> List[int]:
    """(x - 2^0)(x - 2^1)...(x - 2^(degree-1)), coefficients high to low."""
    poly = [1]
    for i in range(degree):
        nxt = [0] * (len(poly) + 1)
        for j, coef in enumerate(poly):
            nxt[j] ^= coef
            nxt[j + 1] ^= _mul(coef, _EXP[i])
        poly = nxt
    return poly


def _ec_codewords(data: Sequence[int], count: int) -> List[int]:
    gen = _generator(count)
    rest = list(data) + [0] * count
    for i in range(len(data)):
        coef = rest[i]
        if coef:
            for j in range(1, len(gen)):
                rest[i + j] ^= _mul(gen[j], coef)
    return rest[len(data):]


# --- Payload -> codewords ----------------------------------------------------


def _smallest_version(length: int, ecl: str) -> int:
    for version in range(1, MAX_VERSION + 1):
        capacity = sum(_BLOCKS[(version, ecl)][1]) - 2  # 4 mode bits + 8 count bits
        if length <= capacity:
            return version
    raise QrError(
        f"{length} bytes does not fit in a version-{MAX_VERSION} QR at level {ecl}; "
        "this encoder is sized for pairing payloads, not for documents"
    )


def _codewords(data: bytes, version: int, ecl: str) -> List[int]:
    ec_per_block, block_sizes = _BLOCKS[(version, ecl)]
    total_data = sum(block_sizes)

    bits: List[int] = []
    for value, width in ((0b0100, 4), (len(data), 8)):
        bits.extend((value >> i) & 1 for i in reversed(range(width)))
    for byte in data:
        bits.extend((byte >> i) & 1 for i in reversed(range(8)))

    bits.extend([0] * min(4, total_data * 8 - len(bits)))  # terminator
    bits.extend([0] * (-len(bits) % 8))

    words = [int("".join(str(b) for b in bits[i:i + 8]), 2) for i in range(0, len(bits), 8)]
    for pad in range(total_data - len(words)):
        words.append(0xEC if pad % 2 == 0 else 0x11)

    blocks: List[List[int]] = []
    ec_blocks: List[List[int]] = []
    at = 0
    for size in block_sizes:
        block = words[at:at + size]
        at += size
        blocks.append(block)
        ec_blocks.append(_ec_codewords(block, ec_per_block))

    # The blocks are interleaved so that damage to one area of the symbol is
    # spread across blocks instead of destroying a single one.
    out: List[int] = []
    for i in range(max(block_sizes)):
        for block in blocks:
            if i < len(block):
                out.append(block[i])
    for i in range(ec_per_block):
        for block in ec_blocks:
            out.append(block[i])
    return out


# --- Codewords -> modules ----------------------------------------------------


class _Symbol:
    def __init__(self, version: int) -> None:
        self.version = version
        self.size = version * 4 + 17
        self.modules: Matrix = [[False] * self.size for _ in range(self.size)]
        self.function: List[List[bool]] = [[False] * self.size for _ in range(self.size)]

    def set(self, row: int, col: int, dark: bool) -> None:
        self.modules[row][col] = dark
        self.function[row][col] = True

    def draw_function_patterns(self) -> None:
        for i in range(self.size):
            self.set(6, i, i % 2 == 0)
            self.set(i, 6, i % 2 == 0)

        for row, col in ((3, 3), (3, self.size - 4), (self.size - 4, 3)):
            self._finder(row, col)

        centres = _ALIGNMENT[self.version]
        for row in centres:
            for col in centres:
                corner = (row, col) in (
                    (centres[0], centres[0]),
                    (centres[0], centres[-1]),
                    (centres[-1], centres[0]),
                )
                if not corner:
                    self._alignment(row, col)

        self.draw_format(0)
        self._version_info()

    def _finder(self, row: int, col: int) -> None:
        for dr in range(-4, 5):
            for dc in range(-4, 5):
                r, c = row + dr, col + dc
                if 0 <= r < self.size and 0 <= c < self.size:
                    dist = max(abs(dr), abs(dc))
                    self.set(r, c, dist != 2 and dist != 4)

    def _alignment(self, row: int, col: int) -> None:
        for dr in range(-2, 3):
            for dc in range(-2, 3):
                self.set(row + dr, col + dc, max(abs(dr), abs(dc)) != 1)

    def draw_format(self, mask: int, ecl: str = "M") -> None:
        data = _ECL_BITS[ecl] << 3 | mask
        rem = data
        for _ in range(10):
            rem = (rem << 1) ^ ((rem >> 9) * 0x537)
        bits = (data << 10 | rem) ^ 0x5412

        def bit(i: int) -> bool:
            return (bits >> i) & 1 == 1

        for i in range(6):
            self.set(i, 8, bit(i))
        self.set(7, 8, bit(6))
        self.set(8, 8, bit(7))
        self.set(8, 7, bit(8))
        for i in range(9, 15):
            self.set(8, 14 - i, bit(i))

        for i in range(8):
            self.set(8, self.size - 1 - i, bit(i))
        for i in range(8, 15):
            self.set(self.size - 15 + i, 8, bit(i))
        self.set(self.size - 8, 8, True)  # always dark, for no reason anyone records

    def _version_info(self) -> None:
        if self.version < 7:
            return
        rem = self.version
        for _ in range(12):
            rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
        bits = self.version << 12 | rem
        for i in range(18):
            dark = (bits >> i) & 1 == 1
            a, b = self.size - 11 + i % 3, i // 3
            self.set(b, a, dark)
            self.set(a, b, dark)

    def draw_codewords(self, words: Sequence[int]) -> None:
        i = 0
        total = len(words) * 8
        right = self.size - 1
        while right >= 1:
            if right == 6:  # the vertical timing pattern is not a data column
                right = 5
            for vert in range(self.size):
                for j in range(2):
                    col = right - j
                    upward = ((right + 1) & 2) == 0
                    row = self.size - 1 - vert if upward else vert
                    if not self.function[row][col] and i < total:
                        self.modules[row][col] = (words[i >> 3] >> (7 - (i & 7))) & 1 == 1
                        i += 1
            right -= 2

    def apply_mask(self, mask: int) -> None:
        for row in range(self.size):
            for col in range(self.size):
                if self.function[row][col]:
                    continue
                if mask == 0:
                    flip = (row + col) % 2 == 0
                elif mask == 1:
                    flip = row % 2 == 0
                elif mask == 2:
                    flip = col % 3 == 0
                elif mask == 3:
                    flip = (row + col) % 3 == 0
                elif mask == 4:
                    flip = (row // 2 + col // 3) % 2 == 0
                elif mask == 5:
                    flip = row * col % 2 + row * col % 3 == 0
                elif mask == 6:
                    flip = (row * col % 2 + row * col % 3) % 2 == 0
                else:
                    flip = ((row + col) % 2 + row * col % 3) % 2 == 0
                if flip:
                    self.modules[row][col] = not self.modules[row][col]

    def penalty(self) -> int:
        size, mods = self.size, self.modules
        score = 0

        # Runs of five or more, and the finder-like 1:1:3:1:1 sequence, in both
        # directions. A scanner looks for that sequence; a run of it in the data
        # is how a symbol becomes ambiguous.
        finders = ([1, 0, 1, 1, 1, 0, 1, 0, 0, 0, 0], [0, 0, 0, 0, 1, 0, 1, 1, 1, 0, 1])
        for line in [row[:] for row in mods] + [list(col) for col in zip(*mods)]:
            run = 1
            for i in range(1, size):
                if line[i] == line[i - 1]:
                    run += 1
                else:
                    if run >= 5:
                        score += 3 + run - 5
                    run = 1
            if run >= 5:
                score += 3 + run - 5
            as_ints = [1 if v else 0 for v in line]
            for i in range(size - 10):
                if as_ints[i:i + 11] in finders:
                    score += 40

        for row in range(size - 1):
            for col in range(size - 1):
                here = mods[row][col]
                if here == mods[row][col + 1] == mods[row + 1][col] == mods[row + 1][col + 1]:
                    score += 3

        dark = sum(sum(1 for v in row if v) for row in mods)
        total = size * size
        score += ((abs(dark * 20 - total * 10) + total - 1) // total - 1) * 10
        return score


def encode(text: str, ecl: str = "M") -> Matrix:
    """The modules of the smallest QR that holds ``text``. True means dark."""
    if ecl not in ("L", "M"):
        raise QrError(f"this encoder carries levels L and M, not {ecl!r}")
    data = text.encode("utf-8")
    version = _smallest_version(len(data), ecl)
    words = _codewords(data, version, ecl)

    best: Tuple[int, Matrix] = (-1, [])
    for mask in range(8):
        symbol = _Symbol(version)
        symbol.draw_function_patterns()
        symbol.draw_codewords(words)
        symbol.draw_format(mask, ecl)
        symbol.apply_mask(mask)
        score = symbol.penalty()
        if not best[1] or score < best[0]:
            best = (score, symbol.modules)
    return best[1]


# --- Modules -> something a camera can read ----------------------------------

_QUIET = 4  # the spec's margin; without it, scanners hunt for an edge and fail


def render(matrix: Matrix, half_blocks: bool = True) -> str:
    """Draw the symbol for a terminal.

    The colours are written out rather than left to the terminal's palette: a
    QR drawn in "default foreground on default background" is inverted on a
    light theme, and an inverted QR does not scan on most phones.

    ``half_blocks`` packs two rows into one character cell, which keeps a
    version-4 symbol inside 41 columns - narrow enough for a phone terminal.
    Turn it off where a font renders the half block badly; the result is twice
    as wide and twice as tall.
    """
    size = len(matrix)
    padded = [[False] * (size + 2 * _QUIET) for _ in range(_QUIET)]
    for row in matrix:
        padded.append([False] * _QUIET + list(row) + [False] * _QUIET)
    padded.extend([[False] * (size + 2 * _QUIET) for _ in range(_QUIET)])

    if not half_blocks:
        lines = []
        for row in padded:
            lines.append("".join("\x1b[40m  " if v else "\x1b[107m  " for v in row) + "\x1b[0m")
        return "\n".join(lines)

    if len(padded) % 2:
        padded.append([False] * len(padded[0]))

    lines = []
    for i in range(0, len(padded), 2):
        top, bottom = padded[i], padded[i + 1]
        cells = []
        for t, b in zip(top, bottom):
            # Foreground paints the upper half, background the lower half.
            cells.append(("\x1b[30m" if t else "\x1b[97m") + ("\x1b[40m" if b else "\x1b[107m") + "▀")
        lines.append("".join(cells) + "\x1b[0m")
    return "\n".join(lines)


def to_png_bytes(matrix: Matrix, scale: int = 8) -> bytes:
    """Write the symbol as a PNG, for when a terminal is the wrong screen.

    Some terminals - Termux's among them - draw the half block with a gap that
    breaks the symbol, and some places to show a QR are not terminals at all.
    zlib and struct are in the standard library, and a greyscale PNG is a small
    enough format to emit by hand.
    """
    import struct
    import zlib

    size = len(matrix) + 2 * _QUIET
    canvas = [[False] * size for _ in range(_QUIET)]
    for row in matrix:
        canvas.append([False] * _QUIET + list(row) + [False] * _QUIET)
    canvas.extend([[False] * size for _ in range(_QUIET)])

    raw = bytearray()
    for row in canvas:
        line = bytearray()
        for dark in row:
            line.extend(b"\x00" * scale if dark else b"\xff" * scale)
        for _ in range(scale):
            raw.append(0)  # PNG filter type 0 for each scanline
            raw.extend(line)

    def chunk(kind: bytes, payload: bytes) -> bytes:
        body = kind + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))

    side = size * scale
    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", side, side, 8, 0, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    png += chunk(b"IEND", b"")
    return png


def to_png(matrix: Matrix, path: str, scale: int = 8) -> str:
    """``to_png_bytes``, written to a file. Returns the path, for a message."""
    with open(path, "wb") as handle:
        handle.write(to_png_bytes(matrix, scale=scale))
    return path
