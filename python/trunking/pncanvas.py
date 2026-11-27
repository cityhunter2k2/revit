"""Tiny dependency-free raster canvas + PNG writer.

Only used to render documentation previews of the generated families, so it
stays deliberately small: scanline polygon fill with 4x supersampling, thick
lines, z-sorted painting.  No third-party packages - the repository must build
on a bare Python install (a Revit box has no pip access).
"""

from __future__ import annotations

import math
import struct
import zlib
from typing import Iterable, Sequence, Tuple

Color = Tuple[int, int, int]


class Canvas:
    def __init__(self, width: int, height: int, background: Color = (255, 255, 255)) -> None:
        self.width = width
        self.height = height
        self.pixels = bytearray(bytes(background) * (width * height))

    # -- primitives -------------------------------------------------------- #
    def set(self, x: int, y: int, color: Color) -> None:
        if 0 <= x < self.width and 0 <= y < self.height:
            i = (y * self.width + x) * 3
            self.pixels[i : i + 3] = bytes(color)

    def get(self, x: int, y: int) -> Color:
        i = (y * self.width + x) * 3
        return (
            self.pixels[i],
            self.pixels[i + 1],
            self.pixels[i + 2],
        )

    def blend(self, x: int, y: int, color: Color, alpha: float) -> None:
        if not (0 <= x < self.width and 0 <= y < self.height):
            return
        if alpha >= 0.999:
            self.set(x, y, color)
            return
        r, g, b = self.get(x, y)
        self.set(
            x,
            y,
            (
                int(r + (color[0] - r) * alpha),
                int(g + (color[1] - g) * alpha),
                int(b + (color[2] - b) * alpha),
            ),
        )

    def fill_polygon(self, points: Sequence[Tuple[float, float]], color: Color, alpha: float = 1.0) -> None:
        if len(points) < 3:
            return
        ys = [p[1] for p in points]
        y0 = max(0, int(math.floor(min(ys))))
        y1 = min(self.height - 1, int(math.ceil(max(ys))))
        n = len(points)
        for y in range(y0, y1 + 1):
            yc = y + 0.5
            xs = []
            for i in range(n):
                x_a, y_a = points[i]
                x_b, y_b = points[(i + 1) % n]
                if (y_a > yc) != (y_b > yc):
                    xs.append(x_a + (yc - y_a) * (x_b - x_a) / (y_b - y_a))
            xs.sort()
            for i in range(0, len(xs) - 1, 2):
                x_start = int(math.ceil(xs[i] - 0.5))
                x_end = int(math.floor(xs[i + 1] - 0.5))
                for x in range(max(0, x_start), min(self.width - 1, x_end) + 1):
                    self.blend(x, y, color, alpha)

    def draw_line(
        self, a: Tuple[float, float], b: Tuple[float, float], color: Color, width: float = 1.0
    ) -> None:
        x0, y0 = a
        x1, y1 = b
        length = math.hypot(x1 - x0, y1 - y0)
        steps = max(1, int(length * 2))
        half = max(0.5, width / 2.0)
        for i in range(steps + 1):
            t = i / steps
            x = x0 + (x1 - x0) * t
            y = y0 + (y1 - y0) * t
            xi, yi = int(round(x)), int(round(y))
            r = int(math.ceil(half - 0.5))
            for dx in range(-r, r + 1):
                for dy in range(-r, r + 1):
                    if dx * dx + dy * dy <= (half + 0.3) ** 2:
                        self.blend(xi + dx, yi + dy, color, 0.9)

    def dashed(self, a, b, color: Color, width: float = 1.0, dash: float = 6.0, gap: float = 4.0) -> None:
        x0, y0 = a
        x1, y1 = b
        length = math.hypot(x1 - x0, y1 - y0)
        if length < 1e-6:
            return
        dirx, diry = (x1 - x0) / length, (y1 - y0) / length
        pos = 0.0
        while pos < length:
            seg = min(dash, length - pos)
            self.draw_line(
                (x0 + dirx * pos, y0 + diry * pos),
                (x0 + dirx * (pos + seg), y0 + diry * (pos + seg)),
                color,
                width,
            )
            pos += dash + gap

    def rect(self, x: int, y: int, w: int, h: int, color: Color) -> None:
        for yy in range(y, y + h):
            for xx in range(x, x + w):
                self.set(xx, yy, color)

    # -- output ------------------------------------------------------------ #
    def save(self, path: str) -> None:
        raw = bytearray()
        stride = self.width * 3
        for y in range(self.height):
            raw.append(0)  # filter type 0
            raw.extend(self.pixels[y * stride : (y + 1) * stride])

        def chunk(kind: bytes, data: bytes) -> bytes:
            return (
                struct.pack(">I", len(data))
                + kind
                + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
            )

        header = struct.pack(">IIBBBBB", self.width, self.height, 8, 2, 0, 0, 0)
        png = (
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + chunk(b"IEND", b"")
        )
        with open(path, "wb") as handle:
            handle.write(png)


# --------------------------------------------------------------------------- #
# 5x7 bitmap font (enough for the previews' labels)
# --------------------------------------------------------------------------- #
_GLYPHS = {
    "0": ("01110", "10001", "10011", "10101", "11001", "10001", "01110"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
    "3": ("11110", "00001", "00001", "01110", "00001", "00001", "11110"),
    "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
    "5": ("11111", "10000", "11110", "00001", "00001", "10001", "01110"),
    "6": ("00110", "01000", "10000", "11110", "10001", "10001", "01110"),
    "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    "9": ("01110", "10001", "10001", "01111", "00001", "00010", "01100"),
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "B": ("11110", "10001", "10001", "11110", "10001", "10001", "11110"),
    "C": ("01110", "10001", "10000", "10000", "10000", "10001", "01110"),
    "D": ("11110", "10001", "10001", "10001", "10001", "10001", "11110"),
    "E": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
    "F": ("11111", "10000", "10000", "11110", "10000", "10000", "10000"),
    "G": ("01110", "10001", "10000", "10111", "10001", "10001", "01111"),
    "H": ("10001", "10001", "10001", "11111", "10001", "10001", "10001"),
    "I": ("01110", "00100", "00100", "00100", "00100", "00100", "01110"),
    "K": ("10001", "10010", "10100", "11000", "10100", "10010", "10001"),
    "L": ("10000", "10000", "10000", "10000", "10000", "10000", "11111"),
    "M": ("10001", "11011", "10101", "10101", "10001", "10001", "10001"),
    "N": ("10001", "11001", "10101", "10011", "10001", "10001", "10001"),
    "O": ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    "P": ("11110", "10001", "10001", "11110", "10000", "10000", "10000"),
    "Q": ("01110", "10001", "10001", "10001", "10101", "10010", "01101"),
    "R": ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
    "S": ("01111", "10000", "10000", "01110", "00001", "00001", "11110"),
    "T": ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
    "U": ("10001", "10001", "10001", "10001", "10001", "10001", "01110"),
    "V": ("10001", "10001", "10001", "10001", "10001", "01010", "00100"),
    "W": ("10001", "10001", "10001", "10101", "10101", "11011", "10001"),
    "X": ("10001", "10001", "01010", "00100", "01010", "10001", "10001"),
    "Y": ("10001", "10001", "01010", "00100", "00100", "00100", "00100"),
    "Z": ("11111", "00001", "00010", "00100", "01000", "10000", "11111"),
    "-": ("00000", "00000", "00000", "11111", "00000", "00000", "00000"),
    "+": ("00000", "00100", "00100", "11111", "00100", "00100", "00000"),
    ".": ("00000", "00000", "00000", "00000", "00000", "01100", "01100"),
    ":": ("00000", "01100", "01100", "00000", "01100", "01100", "00000"),
    "/": ("00001", "00010", "00010", "00100", "01000", "01000", "10000"),
    "(": ("00010", "00100", "01000", "01000", "01000", "00100", "00010"),
    ")": ("01000", "00100", "00010", "00010", "00010", "00100", "01000"),
    "x": ("00000", "00000", "10001", "01010", "00100", "01010", "10001"),
    "=": ("00000", "00000", "11111", "00000", "11111", "00000", "00000"),
    "*": ("00000", "10101", "01110", "11111", "01110", "10101", "00000"),
    " ": ("00000", "00000", "00000", "00000", "00000", "00000", "00000"),
}


def draw_text(
    canvas: Canvas,
    x: float,
    y: float,
    text: str,
    color: Color = (30, 30, 30),
    scale: int = 2,
) -> None:
    cursor = x
    for char in text.upper():
        glyph = _GLYPHS.get(char, _GLYPHS[" "])
        for row, bits in enumerate(glyph):
            for col, bit in enumerate(bits):
                if bit == "1":
                    for dy in range(scale):
                        for dx in range(scale):
                            canvas.set(int(cursor + col * scale + dx), int(y + row * scale + dy), color)
        cursor += 6 * scale


def text_width(text: str, scale: int = 2) -> float:
    return len(text) * 6 * scale
