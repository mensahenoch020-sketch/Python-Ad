#!/usr/bin/env python3
"""
make_icons.py — generate PWA/app icons with the standard library only.

Run once; commits the PNGs in static/icons. Avoids adding Pillow as a runtime
dependency. Produces a TikTok-brand diagonal gradient with a white upward
"growth" triangle:

    python make_icons.py
"""
import os
import struct
import zlib

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "icons")

# Brand gradient endpoints (cyan -> magenta/red), white mark.
C1 = (37, 244, 238)    # #25F4EE
C2 = (254, 44, 85)     # #FE2C55
WHITE = (255, 255, 255, 255)


def _lerp(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _in_triangle(px, py, a, b, c):
    def sign(p, q, r):
        return (p[0] - r[0]) * (q[1] - r[1]) - (q[0] - r[0]) * (p[1] - r[1])
    d1, d2, d3 = sign((px, py), a, b), sign((px, py), b, c), sign((px, py), c, a)
    neg = (d1 < 0) or (d2 < 0) or (d3 < 0)
    pos = (d1 > 0) or (d2 > 0) or (d3 > 0)
    return not (neg and pos)


def _pixel(x, y, s):
    # Diagonal gradient background.
    t = (x + y) / (2 * (s - 1))
    r, g, b = _lerp(C1, C2, t)
    # White upward triangle (growth arrow), centered.
    apex = (0.5 * s, 0.26 * s)
    bl = (0.27 * s, 0.74 * s)
    br = (0.73 * s, 0.74 * s)
    if _in_triangle(x, y, apex, bl, br):
        return WHITE
    return (r, g, b, 255)


def write_png(path, s):
    raw = bytearray()
    for y in range(s):
        raw.append(0)  # filter type 0 (None) per scanline
        for x in range(s):
            raw.extend(_pixel(x, y, s))

    def chunk(tag, data):
        c = tag + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", s, s, 8, 6, 0, 0, 0)  # 8-bit RGBA
    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", ihdr)
           + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
           + chunk(b"IEND", b""))
    with open(path, "wb") as fh:
        fh.write(png)
    print(f"wrote {path} ({s}x{s})")


def main():
    os.makedirs(OUT, exist_ok=True)
    write_png(os.path.join(OUT, "icon-192.png"), 192)
    write_png(os.path.join(OUT, "icon-512.png"), 512)
    write_png(os.path.join(OUT, "apple-touch-icon.png"), 180)


if __name__ == "__main__":
    main()
