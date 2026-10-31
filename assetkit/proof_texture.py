#!/usr/bin/env python3
"""Writes a 16x16 test texture to stdout as a PNG, using only the standard library.

It's deliberately unlike any vanilla block, so a screenshot shows at a glance whether the
resource pack reached the client. Usage: proof_texture.py [variant], where each variant has its
own colours, so a texture change is easy to see.
"""
import struct
import sys
import zlib

SIZE = 16
PALETTES = [
    ((43, 30, 70), (74, 52, 120), (127, 209, 174), (232, 247, 214)),
    ((70, 30, 24), (140, 62, 36), (240, 190, 70), (255, 244, 200)),
    ((16, 48, 66), (30, 96, 130), (240, 110, 150), (255, 226, 236)),
    ((28, 56, 30), (58, 110, 56), (214, 224, 96), (248, 250, 214)),
]


def pixel(x, y, palette):
    border, field, ring, core = palette
    distance = max(abs(x - 7.5), abs(y - 7.5))
    if distance > 7:
        return border
    if distance < 2:
        return core
    if 3 < distance < 5:
        return ring
    return field


def chunk(kind, data):
    body = kind + data
    return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))


def main():
    variant = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    palette = PALETTES[variant % len(PALETTES)]
    rows = b"".join(
        b"\x00" + bytes(channel for x in range(SIZE) for channel in pixel(x, y, palette))
        for y in range(SIZE)
    )
    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", SIZE, SIZE, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(rows, 9))
    png += chunk(b"IEND", b"")
    sys.stdout.buffer.write(png)


if __name__ == "__main__":
    main()
