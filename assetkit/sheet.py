#!/usr/bin/env python3
"""A contact sheet the builder reads to critique its own textures.

    python3 assetkit/sheet.py sheet.png textures/*.png
    python3 assetkit/sheet.py sheet.png some/folder/ --columns 4

Each entry shows the texture at 8x on a checkerboard, its palette, and its colour count. Blocks are also
tiled 3x3, because seams and repeating blotches only show when tiled. Animations show their frames.
Anything over MAX_COLOURS is flagged in the label.
"""
import argparse
import pathlib
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

SCALE, TILE_SCALE, GAP = 8, 4, 8
MAX_COLOURS = 10
BG, INK, WARN = (46, 46, 52), (226, 226, 226), (255, 150, 90)


def checker(w, h, size=8):
    """A light and dark grey checkerboard to show transparency against."""
    ys, xs = np.mgrid[0:h, 0:w]
    v = np.where(((xs // size) + (ys // size)) % 2 == 0, 152, 112).astype(np.uint8)
    return Image.fromarray(np.stack([v, v, v, np.full_like(v, 255)], axis=2))


def is_block(img):
    """Blocks fill the frame edge to edge. Items and plants stay inside a margin, or are mostly clear."""
    a = np.asarray(img.convert("RGBA"))[..., 3] > 0
    edges = a[0].any() and a[-1].any() and a[:, 0].any() and a[:, -1].any()
    return bool(edges and a.mean() > 0.6)


def _on_checker(img, scale):
    big = img.convert("RGBA").resize((img.width * scale, img.height * scale), Image.NEAREST)
    base = checker(*big.size)
    base.alpha_composite(big)
    return base


def _tiled(img, scale, n=3):
    t = Image.new("RGBA", (img.width * n, img.height * n))
    for y in range(n):
        for x in range(n):
            t.paste(img, (x * img.width, y * img.height))
    return _on_checker(t, scale)


def _frames(img):
    """A strip taller than wide, by a whole number of squares, is an animation."""
    w, h = img.size
    if h > w and h % w == 0:
        return [img.crop((0, i * w, w, (i + 1) * w)) for i in range(h // w)]
    return [img]


def _colours(img):
    a = np.asarray(img.convert("RGBA")).reshape(-1, 4)
    colours = {tuple(int(v) for v in p[:3]) for p in a[a[:, 3] > 0]}
    return sorted(colours, key=lambda c: 0.3 * c[0] + 0.59 * c[1] + 0.11 * c[2])


def _cell(path, img, scale, tile_scale, font):
    frames = _frames(img)
    first = frames[0]
    block = is_block(first)
    parts = [_on_checker(first, scale)]
    if block:
        parts.append(_tiled(first, tile_scale))
    colours = _colours(first)
    width = sum(p.width for p in parts) + GAP * (len(parts) - 1)
    height = max(p.height for p in parts)
    strip_img = None
    if len(frames) > 1:  # animation frames go under the main row, so the cell stays narrow
        strip = Image.new("RGBA", (first.width * min(len(frames), 8), first.height), (0, 0, 0, 0))
        for i, frame in enumerate(frames[:8]):
            strip.paste(frame, (i * first.width, 0))
        strip_img = _on_checker(strip, max(1, min(tile_scale, max(width, 96) // strip.width)))
        height += strip_img.height + GAP
    label_h = 12 * 2 + 10
    cell = Image.new("RGBA", (max(width, 96), height + label_h), BG + (255,))
    x = 0
    for p in parts:
        cell.paste(p, (x, 0))
        x += p.width + GAP
    if strip_img:
        cell.paste(strip_img, (0, height - strip_img.height))
    draw = ImageDraw.Draw(cell)
    draw.text((0, height + 2), path.stem[:max(width, 96) // 6], fill=INK, font=font)
    note = f"{first.width}x{first.height} {len(colours)}c" + (f" {len(frames)}f" if len(frames) > 1 else "")
    too_many = len(colours) > MAX_COLOURS
    draw.text((0, height + 14), note + (" TOO MANY" if too_many else ""), fill=WARN if too_many else INK, font=font)
    if too_many:
        draw.rectangle((0, 0, cell.width - 1, height - 1), outline=WARN, width=2)
    swatch = min(8, max(4, (cell.width - 2) // max(len(colours), 1)))
    for i, c in enumerate(colours):
        draw.rectangle((i * swatch, height + 26, i * swatch + swatch - 1, height + 32), fill=c)
    return cell


def contact_sheet(paths, out=None, scale=SCALE, tile_scale=TILE_SCALE, columns=None):
    """Build the sheet from PNG paths (folders are expanded). Returns the image, and saves it if `out`."""
    files = []
    for p in map(pathlib.Path, paths):
        files += sorted(p.rglob("*.png")) if p.is_dir() else [p]
    if not files:
        raise ValueError("no PNG files given")
    font = ImageFont.load_default()
    cells = [_cell(f, Image.open(f).convert("RGBA"), scale, tile_scale, font) for f in files]
    cell_w = max(c.width for c in cells)
    columns = columns or max(1, min(len(cells), round(1400 / (cell_w + GAP * 2))))
    rows = [cells[i:i + columns] for i in range(0, len(cells), columns)]
    widths = [0] * columns
    for row in rows:
        for i, c in enumerate(row):
            widths[i] = max(widths[i], c.width)
    total_w = sum(widths) + GAP * 2 * (columns + 1)
    total_h = sum(max(c.height for c in row) + GAP * 2 for row in rows) + GAP * 2
    sheet = Image.new("RGBA", (total_w, total_h), BG + (255,))
    y = GAP * 2
    for row in rows:
        x = GAP * 2
        for i, c in enumerate(row):
            sheet.paste(c, (x, y))
            x += widths[i] + GAP * 2
        y += max(c.height for c in row) + GAP * 2
    if out:
        pathlib.Path(out).parent.mkdir(parents=True, exist_ok=True)
        sheet.convert("RGB").save(out)
    return sheet


def main(argv=None):
    parser = argparse.ArgumentParser(description="Make a contact sheet from PNG textures.")
    parser.add_argument("out", help="output image")
    parser.add_argument("paths", nargs="+", help="PNG files or folders")
    parser.add_argument("--scale", type=int, default=SCALE)
    parser.add_argument("--tile-scale", type=int, default=TILE_SCALE)
    parser.add_argument("--columns", type=int)
    args = parser.parse_args(argv)
    contact_sheet(args.paths, args.out, args.scale, args.tile_scale, args.columns)
    print(args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
