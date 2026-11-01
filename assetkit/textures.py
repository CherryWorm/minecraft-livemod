#!/usr/bin/env python3
"""Seeded Minecraft-style textures. Every generator returns a PIL RGBA image (or a list of frames).

    from assetkit import textures as tx
    tx.ore("#e8742c", base="deepslate", seed=3).save("ember_ore.png")

Command line:  python3 assetkit/textures.py ore --color "#e8742c" --base deepslate --seed 3 -o ember_ore.png
               python3 assetkit/textures.py list

The look comes from a few rules: 4 to 6 colours from a hue-shifted ramp, soft contrast, shapes built
from clusters of pixels instead of per-pixel noise, blocks that wrap at the edges, and items drawn as
hand-placed sprites with a dark outline in their own hue, lit from the top left.
"""
import argparse
import colorsys
import inspect
import json
import pathlib
import sys

import numpy as np
from PIL import Image, ImageDraw

SIZE = 16


# ---------------------------------------------------------------- palette helpers

def rgb(color):
    """'#rrggbb' or an (r, g, b[, a]) sequence -> an (r, g, b) tuple of ints."""
    if isinstance(color, str):
        text = color.lstrip("#")
        return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))
    return tuple(int(v) for v in color[:3])



def mix(a, b, t=0.5):
    a, b = rgb(a), rgb(b)
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def _toward(hue, target, amount):
    """Move a hue (0..1) toward a target by at most `amount`, along the shorter way round."""
    delta = (target - hue + 0.5) % 1.0 - 0.5
    return (hue + max(-amount, min(amount, delta))) % 1.0


def ramp(base, steps=5, contrast=1.0, shift=1.0):
    """A dark-to-light list of colours around `base`, the way pixel artists build them.

    Shadows are more saturated and drift toward blue; highlights are less saturated and drift toward
    yellow. An odd `steps` keeps `base` itself as the middle colour. Raise `contrast` for items and
    lower it for big block surfaces. Greys get a faint cool/warm tint so they don't look dead.
    """
    r, g, b = (v / 255 for v in rgb(base))
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    out, mid = [], (steps - 1) / 2
    for i in range(steps):
        k = i - mid
        step = abs(k) * contrast * (0.035 + 0.115 * v)
        nv = v - step if k < 0 else v + step
        if k == 0:
            ns, nh = s, h
        elif s < 0.06:  # grey: no hue of its own to shift, so tint it instead
            nh, ns = (0.61, s + abs(k) * 0.022 * shift) if k < 0 else (0.12, s + k * 0.022 * shift)
        elif k < 0:
            nh, ns = _toward(h, 0.667, abs(k) * 0.02 * shift), min(1.0, s + abs(k) * 0.045)
        else:
            nh, ns = _toward(h, 0.167, k * 0.02 * shift), max(0.0, s - k * 0.055)
        if nv > 1.0:  # out of value headroom: go paler instead
            ns, nv = max(0.0, ns - (nv - 1.0) * 1.1), 1.0
        out.append(tuple(int(round(c * 255)) for c in colorsys.hsv_to_rgb(nh, ns, max(0.0, nv))))
    return out


def palette(img):
    """The distinct opaque colours of an image, darkest first."""
    a = np.asarray(img.convert("RGBA")).reshape(-1, 4)
    colors = {tuple(int(v) for v in p[:3]) for p in a[a[:, 3] > 0]}
    return sorted(colors, key=lambda c: 0.3 * c[0] + 0.59 * c[1] + 0.11 * c[2])


def tile_score(img):
    """Does the wrap-around seam stand out? It compares the seam with the strongest line inside the
    texture, on each axis, so a row of mortar at the seam is fine if the other rows have mortar too.
    Seamless textures are usually under 1. A deliberate frame (metal, machine) scores 1.5 to 4."""
    a = np.asarray(img.convert("RGBA")).astype(float)
    rows = np.abs(a[1:] - a[:-1]).mean(axis=(1, 2))
    cols = np.abs(a[:, 1:] - a[:, :-1]).mean(axis=(0, 2))
    row_seam = np.abs(a[0] - a[-1]).mean()
    col_seam = np.abs(a[:, 0] - a[:, -1]).mean()
    # The floor stops a nearly flat texture from scoring high over differences nobody can see.
    return float(max(row_seam / max(rows.max(), 4.0), col_seam / max(cols.max(), 4.0)))


def recolor(img, base, contrast=1.0):
    """Remap an image onto a ramp of `base`, keeping its light and dark structure and its alpha."""
    a = np.asarray(img.convert("RGBA")).copy()
    pal = palette(img)
    new = ramp(base, max(len(pal), 2), contrast)
    lookup = {c: new[i] for i, c in enumerate(pal)}
    for y, x in zip(*np.nonzero(a[..., 3])):
        a[y, x, :3] = lookup[tuple(int(v) for v in a[y, x, :3])]
    return Image.fromarray(a)


# ---------------------------------------------------------------- pixel plumbing

def _rng(seed, salt=0):
    return np.random.default_rng([abs(int(seed)), salt])


def _paint(idx, pal, alpha=None):
    """Index map plus palette -> RGBA image. Negative indices are transparent."""
    lut = np.array([tuple(rgb(c)) + (255,) for c in pal], dtype=np.uint8)
    out = lut[np.clip(idx, 0, len(pal) - 1)]
    out[..., 3] = np.where(idx < 0, 0, 255)
    if alpha is not None:
        out[..., 3] = np.minimum(out[..., 3], alpha)
    return Image.fromarray(out)


def _grow(rng, n, hbias=1.0, vbias=1.0):
    """A random connected cluster of n cells around (0, 0). The bias stretches it along an axis."""
    cells, seen = [(0, 0)], {(0, 0)}
    moves, weight = [(1, 0), (-1, 0), (0, 1), (0, -1)], np.array([hbias, hbias, vbias, vbias], float)
    weight /= weight.sum()
    while len(cells) < n:
        x, y = cells[rng.integers(len(cells))]
        dx, dy = moves[rng.choice(4, p=weight)]
        if (x + dx, y + dy) not in seen:
            seen.add((x + dx, y + dy))
            cells.append((x + dx, y + dy))
    return cells


def _stamp(idx, rng, count, size, value, hbias=1.0, vbias=1.0, only=None):
    """Stamp `count` clusters of `value` with wrap-around, so the result tiles. `only` limits which
    existing values may be overwritten, and clusters then start on one of them, so accents land on
    the shapes they belong to instead of missing."""
    h, w = idx.shape
    scale = (h * w) / 256
    for _ in range(int(round(count * scale))):
        cx, cy = int(rng.integers(w)), int(rng.integers(h))
        if only is not None:
            spots = np.argwhere(np.isin(idx, only))
            if len(spots):
                cy, cx = (int(v) for v in spots[int(rng.integers(len(spots)))])
        n = int(rng.integers(size[0], size[1] + 1))
        for dx, dy in _grow(rng, max(1, int(round(n * max(1, scale ** 0.5)))), hbias, vbias):
            y, x = (cy + dy) % h, (cx + dx) % w
            if only is None or idx[y, x] in only:
                idx[y, x] = value
    return idx


def _streaks(idx, rng, count, length, value, only=None):
    """Straight vertical runs with wrap-around, for bark. A rare one-pixel jog keeps them organic."""
    h, w = idx.shape
    for _ in range(int(round(count * w / SIZE))):
        x, y = int(rng.integers(w)), int(rng.integers(h))
        for i in range(int(rng.integers(length[0], length[1] + 1)) * h // SIZE):
            if rng.random() < 0.08:
                x = (x + int(rng.choice((-1, 1)))) % w
            if only is None or idx[(y + i) % h, x] in only:
                idx[(y + i) % h, x] = value
    return idx


def _despeckle(idx, rng, keep=0.12):
    """Remove lone pixels, which read as noise at 16x16: each takes its most common neighbour's value."""
    h, w = idx.shape
    out = idx.copy()
    for y in range(h):
        for x in range(w):
            near = [idx[(y - 1) % h, x], idx[(y + 1) % h, x], idx[y, (x - 1) % w], idx[y, (x + 1) % w]]
            if idx[y, x] not in near and rng.random() > keep:
                values, counts = np.unique(near, return_counts=True)
                out[y, x] = values[np.argmax(counts)]
    return out


def _sized(img, size):
    """Upscale a 16x16 sprite when a bigger multiple of 16 was asked for."""
    return img if size == img.width else img.resize((size, size), Image.NEAREST)


def _jitter(color, rng, amount=0.012):
    """A barely visible per-seed colour change, so two seeds aren't the same flat ramp."""
    r, g, b = (v / 255 for v in rgb(color))
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    h = (h + rng.uniform(-amount, amount)) % 1.0
    v = min(1.0, max(0.0, v + rng.uniform(-amount, amount)))
    return tuple(int(round(c * 255)) for c in colorsys.hsv_to_rgb(h, s, v))


def _voronoi(rng, size, cells):
    """Cell id per pixel on a torus, from a jittered grid of seeds. Returns ids, border mask, seeds."""
    n = int(round(cells ** 0.5))
    ox, oy = rng.uniform(0, size, 2)  # so cell borders don't line up with the tile edges
    pts = [(((i + rng.uniform(0.2, 0.8)) * size / n + ox) % size, ((j + rng.uniform(0.2, 0.8)) * size / n + oy) % size)
           for j in range(n) for i in range(n)]
    ys, xs = np.mgrid[0:size, 0:size]
    dists = []
    for px, py in pts:
        dx = np.minimum(np.abs(xs - px), size - np.abs(xs - px))
        dy = np.minimum(np.abs(ys - py), size - np.abs(ys - py))
        dists.append(dx * dx + dy * dy * 1.3)
    ids = np.argmin(np.stack(dists), axis=0)
    right, down = np.roll(ids, -1, axis=1), np.roll(ids, -1, axis=0)
    border = (ids != right) | (ids != down)
    return ids, border, pts


# ---------------------------------------------------------------- stone-like blocks

def _rock(rng, size, hbias=2.2, dark=7, light=5):
    """The index map behind stone: flat mid tone, dark and light clusters, and a few accents."""
    idx = np.full((size, size), 2)
    _stamp(idx, rng, dark, (4, 9), 1, hbias=hbias)
    _stamp(idx, rng, light, (3, 7), 3, hbias=hbias, only=(2,))
    _stamp(idx, rng, 3, (2, 4), 0, hbias=hbias, only=(1,))
    _stamp(idx, rng, 2, (1, 3), 4, hbias=hbias, only=(3,))
    return _despeckle(idx, rng)


def stone(color=(126, 126, 126), seed=0, size=SIZE, style="stone"):
    """Rock. style: stone (soft blotches), deepslate (dark horizontal strata), cobble, bricks, smooth."""
    rng = _rng(seed, 1)
    color = rgb(color)
    if style == "stone":
        return _paint(_rock(rng, size), ramp(color, 5, 0.62))
    if style == "deepslate":
        idx = np.full((size, size), 2)
        _stamp(idx, rng, 9, (5, 11), 1, hbias=9)
        _stamp(idx, rng, 6, (4, 8), 3, hbias=9, only=(2,))
        _stamp(idx, rng, 4, (2, 5), 0, hbias=9, only=(1,))
        return _paint(_despeckle(idx, rng), ramp(color, 4, 0.8))
    if style == "cobble":
        ids, border, _ = _voronoi(rng, size, 9 * (size // SIZE) ** 2)
        idx = rng.integers(2, 4, ids.max() + 1)[ids]
        lit = (np.roll(border, 1, 0) | np.roll(border, 1, 1)) & ~border
        shade = (np.roll(border, -1, 0) | np.roll(border, -1, 1)) & ~border & ~lit
        idx = np.where(lit, idx + 1, np.where(shade, idx - 1, idx))
        return _paint(np.where(border, 0, idx), ramp(color, 5, 0.8))
    if style == "bricks":
        idx = np.full((size, size), 2)
        course = size // 4
        for row in range(4):
            top = row * course
            idx[top + course - 1, :] = 0
            idx[top, :] = 3
            offset = (size // 4 if row % 2 else 0) + size // 8
            for x in (offset, offset + size // 2):
                x %= size
                idx[top:top + course, x] = 0
                idx[top:top + course - 1, (x + 1) % size] = 3
        idx[(idx == 2) & (rng.random((size, size)) < 0.14)] = 1
        return _paint(idx, ramp(color, 4, 0.75))
    if style == "smooth":
        idx = np.full((size, size), 2)
        idx[0, :], idx[:, 0] = 3, 3
        idx[-1, :], idx[:, -1] = 1, 1
        _stamp(idx, rng, 3, (2, 4), 1, hbias=4, only=(2,))
        return _paint(idx, ramp(color, 4, 0.5))
    raise ValueError(f"unknown stone style {style!r}")


# Ore clusters: m is ore mid tone, l light, h highlight, s ore shadow. Space is left as stone.
_FLECKS = [
    [".lm", "lhm", "mms"],
    ["lm.", "hms", ".ms"],
    [".l.", "lhm", ".ms"],
    ["lhm", "mms"],
    ["lm", "ms"],
    [".lm.", "lhmm", ".mms"],
]


def ore(color, base="stone", seed=0, size=SIZE, clusters=4, stone_color=None):
    """A stone-like base with clustered flecks. base: 'stone', 'deepslate' or another stone() style."""
    rng = _rng(seed, 2)
    if isinstance(base, Image.Image):
        img = base.convert("RGBA").copy()
        shadow = palette(img)[0]
    else:
        stone_color = stone_color or ((76, 76, 84) if base == "deepslate" else (126, 126, 126))
        img = stone(stone_color, seed, size, base)
        shadow = ramp(stone_color, 5, 0.62)[0] if base != "deepslate" else ramp(stone_color, 4, 0.8)[0]
    pix = np.asarray(img).copy()
    tones = ramp(color, 4, 1.15)
    lut = {"s": tones[0], "m": tones[1], "l": tones[2], "h": tones[3]}
    scale = size // SIZE
    placed = []
    for i in range(clusters * scale * scale):
        shape = _FLECKS[int(rng.integers(len(_FLECKS)))] if i else _FLECKS[int(rng.integers(3))]
        gh, gw = len(shape), len(shape[0])
        for _ in range(40):
            x, y = int(rng.integers(1, size - gw - 1)), int(rng.integers(1, size - gh - 1))
            if all(abs(x + gw / 2 - px) + abs(y + gh / 2 - py) > 6.5 for px, py in placed):
                break
        placed.append((x + gw / 2, y + gh / 2))
        for j, row in enumerate(shape):
            for k, ch in enumerate(row):
                if ch != ".":
                    pix[y + j, x + k, :3] = lut[ch]
        # A soft dark contact shadow under the fleck gives it depth, like vanilla ores.
        for j, row in enumerate(shape):
            for k, ch in enumerate(row):
                below = j + 1 >= gh or shape[j + 1][k] == "."
                right = k + 1 >= gw or row[k + 1] == "."
                if ch != "." and below:
                    pix[y + j + 1, x + k, :3] = shadow
                if ch != "." and right and rng.random() < 0.6:
                    pix[y + j, x + k + 1, :3] = shadow
    return Image.fromarray(pix)


def soil(color=(134, 96, 67), seed=0, size=SIZE, style="dirt"):
    """Soft ground. style: dirt, gravel, sand, mud."""
    rng = _rng(seed, 3)
    if style == "dirt":
        idx = np.full((size, size), 2)
        _stamp(idx, rng, 11, (2, 5), 1)
        _stamp(idx, rng, 8, (2, 4), 3, only=(2,))
        _stamp(idx, rng, 4, (1, 3), 0, only=(1,))
        return _paint(_despeckle(idx, rng, 0.2), ramp(color, 4, 0.85))
    if style == "gravel":
        ids, border, _ = _voronoi(rng, size, 16 * (size // SIZE) ** 2)
        idx = rng.integers(1, 4, ids.max() + 1)[ids]
        idx = np.where(border, 0, idx)
        return _paint(_despeckle(idx, rng, 0.25), ramp(color, 4, 0.95))
    if style == "sand":
        idx = np.full((size, size), 2)
        _stamp(idx, rng, 8, (1, 3), 1)
        _stamp(idx, rng, 8, (1, 3), 3, only=(2,))
        _stamp(idx, rng, 2, (1, 2), 0, only=(1,))
        return _paint(idx, ramp(color, 4, 0.34))
    if style == "mud":
        idx = np.full((size, size), 2)
        _stamp(idx, rng, 6, (5, 10), 1, hbias=3)
        _stamp(idx, rng, 3, (3, 5), 3, hbias=3, only=(2,))
        _stamp(idx, rng, 3, (2, 4), 0, hbias=3, only=(1,))
        return _paint(_despeckle(idx, rng), ramp(color, 4, 0.55))
    raise ValueError(f"unknown soil style {style!r}")


# ---------------------------------------------------------------- wood

def planks(color=(162, 130, 78), seed=0, size=SIZE):
    """Four horizontal boards with staggered joints, soft grain and a dark gap below each board."""
    rng = _rng(seed, 4)
    idx = np.full((size, size), 2)
    board = size // 4
    start = int(rng.integers(0, size))
    for row in range(4):
        top = row * board
        # Grain: long thin streaks that stay inside the board.
        for _ in range(int(3 * size / SIZE)):
            y = top + int(rng.integers(0, board - 1))
            x, n = int(rng.integers(size)), int(rng.integers(3, 8))
            idx[y, [(x + i) % size for i in range(n)]] = int(rng.choice((1, 3), p=(0.55, 0.45)))
        idx[top + board - 1, :] = 0  # the gap between boards
        joint = (start + row * 5 + int(rng.integers(-1, 2))) % size
        idx[top:top + board, joint] = 0
    return _paint(idx, ramp(color, 4, 0.72))


def log_side(color=(103, 76, 47), seed=0, size=SIZE):
    """Bark with vertical furrows. Wraps both ways."""
    rng = _rng(seed, 5)
    idx = np.full((size, size), 2)
    _streaks(idx, rng, 9, (5, 11), 1)
    _streaks(idx, rng, 8, (4, 8), 3, only=(2,))
    _streaks(idx, rng, 5, (3, 7), 0, only=(1,))
    return _paint(_despeckle(idx, rng, 0.25), ramp(color, 4, 0.8))


def log_top(wood=(170, 136, 86), bark=(103, 76, 47), seed=0, size=SIZE):
    """End grain: a bark rim around soft rounded rings."""
    rng = _rng(seed, 6)
    c = (size - 1) / 2
    ys, xs = np.mgrid[0:size, 0:size]
    d = ((np.abs(xs - c) ** 3.0 + np.abs(ys - c) ** 3.0) ** (1 / 3.0)) * (SIZE / size)
    wobble = rng.uniform(-0.4, 0.4, (4, 4))[(ys * 4 // size), (xs * 4 // size)]
    rings = ((d + wobble) / 2.1).astype(int) % 2
    w, b = ramp(wood, 4, 0.55), ramp(bark, 3, 0.7)
    idx = np.where(d < 1.0, 0, 1 + rings)
    run = (xs * 3 + ys * 5 + int(rng.integers(50))) // 4
    rim = np.array([3, 4, 4, 5, 4, 3, 4])[run % 7]
    edge = np.minimum.reduce([xs, ys, size - 1 - xs, size - 1 - ys])
    return _paint(np.where(edge < size // SIZE, rim, idx), [w[0], w[1], w[2], b[0], b[1], b[2]])


# ---------------------------------------------------------------- foliage (transparent)

def leaves(color=(72, 132, 44), seed=0, size=SIZE, holes=0.16):
    """Overlapping leaf clumps with see-through gaps. For the cutout family. Wraps."""
    rng = _rng(seed, 7)
    idx = np.full((size, size), 0)
    h, w = idx.shape
    clump = ((0, 0, 2), (-1, 0, 2), (0, -1, 2), (1, 0, 2), (0, 1, 1), (1, 1, 1), (-1, 1, 1), (-1, -1, 3), (1, -1, 2))
    grid = max(1, int(round(size / 4)))  # one clump per jittered grid cell, so coverage stays even
    for j in range(grid):
        for i in range(grid):
            cx = (i * w // grid + int(rng.integers(0, 4))) % w
            cy = (j * h // grid + int(rng.integers(0, 4))) % h
            for dx, dy, tone in clump:
                idx[(cy + dy) % h, (cx + dx) % w] = 2 if tone == 3 and rng.random() < 0.35 else tone
    idx = _despeckle(idx, rng, 0.3)
    # Gaps grow as small clusters out of the shadow between clumps, never as lone pixels.
    alpha = np.full((size, size), 255, dtype=np.uint8)
    want = int(holes * size * size)
    for _ in range(200):
        if (alpha == 0).sum() >= want:
            break
        spots = np.argwhere((idx == 0) & (alpha == 255))
        if not len(spots):
            break
        y, x = (int(v) for v in spots[int(rng.integers(len(spots)))])
        for dx, dy in _grow(rng, int(rng.integers(2, 5))):
            if idx[(y + dy) % h, (x + dx) % w] <= 1:
                alpha[(y + dy) % h, (x + dx) % w] = 0
    return _paint(idx, ramp(color, 4, 0.95), alpha)


_PLANTS = {
    # 1-3 stem and leaf, 4 and 5 are bloom tones a-d, read top to bottom. Plants have no outline.
    "flower": [
        ["................", "................", "......bb.b......", ".....bcdcb......", ".....cdadcb.....",
         "......cccb......", ".......b........", ".......2........", ".......2..3.....", ".....3.2.32.....",
         ".....232.2......", "......22.2......", ".......2.2......", ".......22.......", ".......2........", ".......2........"],
        ["................", "................", "................", "........bc......", "......bcdcb.....",
         "......cdadc.....", "......bcdcb.....", "........cb......", "........2.......", "...3....2..3....",
         "....32..2.32....", ".....22.222.....", "......222.......", ".......2........", ".......2........", ".......2........"],
    ],
    "tulip": [
        ["................", "................", "................", "......b.c.b.....", "......bcdcb.....",
         "......bcdcb.....", "......abcba.....", ".......aba......", "........2.......", "........2..3....",
         "...3....2.32....", "....32..222.....", ".....22.2.......", "......2222......", "........2.......", "........2......."],
    ],
    "grass": [
        ["................", "................", "................", "........3.......", "..3.....3.......",
         "...3....2..3....", "...2...32..2....", "...2...2...2..3.", "3..22..2..22.2..", ".2..2..2..2..2..",
         ".2..22.22.2.22..", ".22..2.2.22.2...", "..2..2.2.2.22...", "..1.21.2.1.2....", "..1.1..1.1.1....", "...1.1.1.1......"],
    ],
    "sapling": [
        ["................", "................", "......33........", ".....3323.3.....", "....32223332....",
         "...3222322223...", "....22221222....", "...322.1222223..", "....2221.122....", ".......1.2......",
         ".......1........", ".......1........", ".......1........", ".......1........", ".......1........", ".......1........"],
    ],
    "mushroom": [
        ["................", "................", "................", "................", "......dccb......",
         "....dddcccba....", "...ddcdcccbba...", "...dcccccbbba...", "...acbbbbbaaa...", ".....3322.......",
         "......32........", "......32........", "......32........", "......321.......", ".....3221.......", ".....3221......."],
    ],
    "crystal": [
        ["................", "................", ".........d......", ".........dc.....", "........ddcb....",
         "...c....dccb....", "...dc...dcbb....", "..ddcb..dcbb....", "..dcbb.ddcba.c..", "..dcba.dccba.dc.",
         "..ccba.dcbba.cb.", "...cba.ccbaa.cb.", "...cbaacbba..ba.", "....baacba..cba.", "....aa.aaa..aa..", "..aaaaaaaaaaaa.."],
    ],
}


def plant(kind="flower", color=(214, 74, 96), stem=(66, 122, 46), seed=0, size=SIZE):
    """A cross-model plant on transparency, rooted on the bottom row. kind: flower, tulip, grass,
    sapling, mushroom, crystal. `color` is the bloom, cap or crystal. For tinted_plant blocks pass a
    grey `stem`, since the game multiplies by the biome colour."""
    rng = _rng(seed, 8)
    rows = _PLANTS[kind][int(rng.integers(len(_PLANTS[kind])))]
    leaf, bloom = ramp(stem, 3, 1.1), ramp(color, 4, 1.05)
    lut = {"1": leaf[0], "2": leaf[1], "3": leaf[2], "a": bloom[0], "b": bloom[1], "c": bloom[2], "d": bloom[3]}
    out = np.zeros((SIZE, SIZE, 4), dtype=np.uint8)
    flip = bool(rng.integers(2))
    for y, row in enumerate(rows):
        for x, ch in enumerate(row[::-1] if flip else row):
            if ch != ".":
                out[y, x] = lut[ch] + (255,)
    return _sized(Image.fromarray(out), size)


# ---------------------------------------------------------------- metal, glow, machines

def metal(color=(205, 205, 212), seed=0, size=SIZE, style="plate"):
    """A refined storage block. style: plate (brushed), rivets (corner bolts), gem (one cut facet).
    Its frame is deliberate: storage blocks in the game show a grid when placed next to each other."""
    rng = _rng(seed, 9)
    pal = ramp(color, 5, 0.62)
    t = max(1, size // SIZE)
    if style == "gem":
        c = (size - 1) / 2
        ys, xs = np.mgrid[0:size, 0:size]
        dx, dy = (xs - c) * SIZE / size, (ys - c) * SIZE / size
        idx = np.where(np.abs(dx) > np.abs(dy), np.where(dx < 0, 3, 1), np.where(dy < 0, 4, 0))
        table = np.maximum(np.abs(dx), np.abs(dy)) < 4
        idx = np.where(table, 2, idx)
        idx = np.where(table & (dx + dy < -2.5), 3, idx)
        idx = np.where(table & (dx + dy < -5), 4, idx)
        return _paint(idx, ramp(color, 5, 0.85))
    idx = np.full((size, size), 2)
    _stamp(idx, rng, 5, (5, 9), 3, hbias=14, vbias=0.2)
    _stamp(idx, rng, 4, (4, 8), 1, hbias=14, vbias=0.2, only=(2,))
    for _ in range(2 * t):  # small diagonal glints
        x, y = int(rng.integers(3, size - 5)), int(rng.integers(3, size - 5))
        for i in range(3):
            idx[y + 2 - i, x + i] = 4
    if style == "rivets":
        inset = 2 * t
        for yy in (inset, size - inset - t):
            for xx in (inset, size - inset - t):
                idx[yy:yy + t, xx:xx + t] = 4
                idx[yy + t:yy + 2 * t, xx:xx + t] = 0
                idx[yy:yy + 2 * t, xx + t:xx + 2 * t] = 0
    idx[:t, :], idx[:, :t] = 4, 3
    idx[-t:, :], idx[:, -t:] = 0, 1
    idx[:t, :t], idx[-t:, -t:] = 4, 0
    return _paint(idx, pal)


def glow(color=(255, 196, 92), seed=0, size=SIZE, style="crystal"):
    """A light-giving block. style: crystal (bright cells with soft seams, wraps) or lamp (framed panes)."""
    rng = _rng(seed, 10)
    base = ramp(color, 5, 0.9)
    pal = [mix(base[0], (40, 22, 34), 0.35), base[0], base[1], base[2], base[4]]
    ys, xs = np.mgrid[0:size, 0:size]
    if style == "lamp":
        c = (size - 1) / 2
        dx, dy = np.abs(xs - c) * SIZE / size, np.abs(ys - c) * SIZE / size
        d, near = np.maximum(dx, dy), dx + dy
        idx = np.where(near < 5.5, 4, np.where(near < 9, 3, 2))
        bars = (dx < 1) | (dy < 1)
        idx = np.where(bars, np.where(near < 2, 2, 1), idx)
        idx = np.where(d > 6.5, 1, idx)
        return _paint(np.where(d > 7, 0, idx), pal)
    if style == "crystal":
        ids, border, pts = _voronoi(rng, size, 9 * (size // SIZE) ** 2)
        idx = rng.integers(2, 4, ids.max() + 1)[ids]
        for i, (px, py) in enumerate(pts):
            dx = np.minimum(np.abs(xs - px), size - np.abs(xs - px))
            dy = np.minimum(np.abs(ys - py), size - np.abs(ys - py))
            idx = np.where((ids == i) & (dx + dy < 1.3 * size / SIZE), 4, idx)
        idx = np.where(border, 1, idx)
        idx = np.where(border & (rng.random((size, size)) < 0.25), 0, idx)
        return _paint(idx, pal)
    raise ValueError(f"unknown glow style {style!r}")


def machine(face="side", casing=(112, 112, 122), accent=(232, 142, 54), on=False, seed=0, size=SIZE):
    """One face of a machine: front (opening with a grate, lit if on), side (vents), top (hatch),
    bottom (plate), back (port). Use the same casing and seed on all faces of a block."""
    rng = _rng(seed, 11)
    pal = ramp(casing, 5, 0.78)
    glow_pal = ramp(accent, 4, 1.0)
    dark = mix(pal[0], (18, 16, 24), 0.6)
    full = [dark] + pal + glow_pal  # 0 void, 1-5 casing dark to light, 6-9 accent dark to light
    s = size // SIZE
    idx = np.full((SIZE, SIZE), 3)
    _stamp(idx, rng, 4, (2, 4), 2, hbias=3)
    idx[0, :], idx[:, 0] = 5, 4
    idx[-1, :], idx[:, -1] = 1, 2
    idx[1, 1:-1], idx[-2, 1:-1] = 4, 2
    idx[1:-1, 1], idx[1:-1, -2] = 4, 2
    idx[1, 1], idx[-2, -2] = 5, 1
    for y, x in ((2, 2), (2, 13), (13, 2), (13, 13)):  # corner bolts
        idx[y, x] = 5
        idx[y + 1, x] = 1
    if face == "front":
        idx[4:13, 4:12] = 0  # the opening, lit from below when running
        idx[3, 3:13], idx[3:14, 3], idx[3:14, 12] = 1, 1, 4
        idx[13, 3:13] = 4
        idx[5:13, [5, 7, 9]] = 2  # grate bars
        idx[5:13, [6, 8, 10]] = 0
        if on:
            idx[12, 4:12] = 8
            idx[11, 4:12] = np.where(rng.random(8) < 0.8, 7, 0)
            idx[10, 4:12] = np.where(rng.random(8) < 0.5, 6, 0)
            idx[9, 4:12] = np.where(rng.random(8) < 0.2, 6, 0)
            idx[5:13, [5, 7, 9]] = np.where(idx[5:13, [5, 7, 9]] == 2, 1, idx[5:13, [5, 7, 9]])
            idx[12, int(rng.integers(4, 12))] = 9
    elif face == "side":
        for y in (5, 7, 9):  # vents
            idx[y, 4:12], idx[y + 1, 4:12] = 1, 4
    elif face == "top":
        idx[4:12, 4:12] = 2
        idx[4, 4:12], idx[4:12, 4] = 1, 1
        idx[11, 4:12], idx[4:12, 11] = 4, 4
        idx[6:10, 6:10] = 6 if on else 1
        idx[6, 6:10], idx[6:10, 6] = (7, 7) if on else (0, 0)
    elif face == "bottom":
        idx[6:10, 2:14] = 2
        idx[6, 2:14], idx[9, 2:14] = 1, 3
    elif face == "back":
        ys, xs = np.mgrid[0:SIZE, 0:SIZE]  # one round socket, since two holes would read as a face
        d = np.hypot(xs - 7.5, ys - 7.5)
        idx = np.where(d < 4.4, 1, idx)
        idx = np.where((d < 4.4) & (xs + ys > 17), 4, idx)
        idx = np.where(d < 3.2, 0, idx)
        idx = np.where(d < 1.6, 8 if on else 2, idx)
    else:
        raise ValueError(f"unknown machine face {face!r}")
    return _sized(_paint(idx, full), size)


# ---------------------------------------------------------------- item sprites

def panel_back(casing=(112, 112, 122), width=176, height=166, slots=(), inventory=(8, 84)):
    """A plain background for a panel: its colour, with an edge and a frame for each slot, for where the item goes at (x, y) in the panel.
    The frames for a player's inventory go at inventory, unless that's None. It's a start to draw over."""
    light, frame, dark = mix(casing, (255, 255, 255), 0.55), mix(casing, (255, 255, 255), 0.25), mix(casing, (0, 0, 0), 0.5)
    image = Image.new("RGBA", (width, height), (*light, 255))
    pen = ImageDraw.Draw(image)
    pen.rectangle((0, 0, width - 1, height - 1), outline=(*dark, 255))
    places = list(slots)
    if inventory is not None:
        for row in range(4):
            y = inventory[1] + row * 18 + (4 if row == 3 else 0)
            places += [(inventory[0] + column * 18, y) for column in range(9)]
    for x, y in places:
        pen.rectangle((x - 1, y - 1, x + 16, y + 16), fill=(*frame, 255), outline=(*dark, 255))
    return image


def _item_ramp(color):
    """Outline first, then five fill tones. The outline is dark in the same hue, never pure black."""
    fill = ramp(color, 5, 1.12)
    return [mix(fill[0], (22, 16, 30), 0.58)] + fill


def _sprite(rows, primary, secondary=None, outline=True):
    """Render a template. Digits 1-5 are primary tones, a-d secondary tones, '.' is transparent. Empty
    cells touching a filled one become the outline of that material."""
    p, s = _item_ramp(primary), _item_ramp(secondary or primary)
    lut = {str(i): p[i] for i in range(1, 6)}
    lut.update({"a": s[2], "b": s[3], "c": s[4], "d": s[5]})
    h, w = len(rows), len(rows[0])
    out = np.zeros((h, w, 4), dtype=np.uint8)
    for y, row in enumerate(rows):
        for x, ch in enumerate(row):
            if ch != ".":
                out[y, x] = lut[ch] + (255,)
    if outline:
        for y in range(h):
            for x in range(w):
                if rows[y][x] != ".":
                    continue
                near = [rows[j][i] for j, i in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1))
                        if 0 <= j < h and 0 <= i < w and rows[j][i] != "."]
                if near:
                    out[y, x] = (p[0] if any(c.isdigit() for c in near) else s[0]) + (255,)
    return Image.fromarray(out)


def _lumps(rng, circles, speckle=0):
    """Rows for a rounded object: overlapping circles shaded from the top left. Later circles are in
    front. `circles` is a list of (x, y, radius)."""
    tone = np.zeros((SIZE, SIZE), dtype=int)
    for cx, cy, r in circles:
        for y in range(SIZE):
            for x in range(SIZE):
                dx, dy = (x - cx) / r, (y - cy) / r
                if dx * dx + dy * dy <= 1.0:
                    light = -(dx + dy * 1.15) * 0.72
                    if (dx + 0.4) ** 2 + (dy + 0.45) ** 2 < 0.07:
                        light = 1.5
                    tone[y, x] = int(np.clip(round(3 + light * 1.6), 1, 5))
    for _ in range(speckle):
        ys, xs = np.nonzero(tone > 1)
        i = int(rng.integers(len(ys)))
        for dx, dy in _grow(rng, int(rng.integers(2, 4))):
            y, x = ys[i] + dy, xs[i] + dx
            if 0 <= y < SIZE and 0 <= x < SIZE and tone[y, x]:
                tone[y, x] = max(1, tone[y, x] - 1)
    return ["".join(str(v) if v else "." for v in row) for row in tone]


_INGOTS = [
    ["................", "................", "................", "................", "...........55...",
     ".........55444..", ".......55444422.", ".....5544442221.", "...554444222211.", ".5544442222211..",
     ".33442222211....", ".333322211......", ".2333221........", "...221..........", "................", "................"],
    ["................", "................", "................", "................", "................",
     "....55555444....", "...5544444433...", "...4444443333...", "..333333333322..", "..322222222211..",
     "..222222211111..", "..111111111111..", "................", "................", "................", "................"],
]

_GEMS = [
    ["................", "................", "................", ".....455543.....", "....45544433....",
     "...4554443332...", "..344444333321..", "...3444333221...", "....34433221....", ".....343221.....",
     "......3321......", ".......31.......", "................", "................", "................", "................"],
    ["................", "................", ".....444443.....", "....34444432....", "...3344444322...",
     "...3355544422...", "...3355444422...", "...3354444322...", "...3344443322...", "...2332222221...",
     "....22222211....", ".....211111.....", "................", "................", "................", "................"],
    ["................", ".......54.......", "......5532......", ".....555322.....", "....45543221....",
     "....44443221....", "....44433221....", "....44433211....", "....34433211....", "....34432211....",
     "....33432211....", ".....333211.....", "......3321......", ".......32.......", "................", "................"],
]

_TOOLS = {
    "pickaxe": [
        "................", "................", "....55555444....", ".....44444333...", "...........332..",
        "..........cb32..", ".........cb.32..", "........cb..32..", ".......cb...32..", "......cb....32..",
        ".....cb.....21..", "....cb.......1..", "...cb...........", "..cb............", ".ba.............", "................"],
    "axe": [
        "................", ".......554......", "......55443.....", ".....55443332...", "....544433cb32..",
        "....44433cb.21..", "....4332cb......", "....32.cb.......", "......cb........", ".....cb.........",
        "....cb..........", "...cb...........", "..cb............", ".ba.............", "................", "................"],
    "sword": [
        "................", ".............54.", "............543.", "...........543..", "..........543...",
        ".........543....", "........543.....", ".......543......", "..3...432.......", "..43.432........",
        "...4332.........", "....33..........", "...c.32.........", "..cb..21........", ".ba.............", "................"],
    "shovel": [
        "................", "...........554..", "..........55443.", ".........554433.", "........5544332.",
        ".........544321.", "........cb321...", ".......cb..1....", "......cb........", ".....cb.........",
        "....cb..........", "...cb...........", "..cb............", ".ba.............", "................", "................"],
    "hoe": [
        "................", "................", ".....55544433...", ".....44333 3322..".replace(" ", ""), ".....32....c32..",
        ".....21...cb.1..", ".........cb.....", "........cb......", ".......cb.......", "......cb........",
        ".....cb.........", "....cb..........", "...cb...........", "..cb............", ".ba.............", "................"],
}

_FOODS = {
    "loaf": ["................", "................", "................", "................", "................",
             "....5545544433..", "...542454244333.", "..5444244424332.", "..4444344433321.", "..3333333322211.",
             "..2222222111111.", "...1111111111...", "................", "................", "................", "................"],
    "meat": ["................", "................", "................", "....4545........", "...544444 3.....".replace(" ", "4"),
             "..54444444 3....".replace(" ", "4"), "..4443344443....", "..44433334432...", "..34433334332...", "..3344443332cd..",
             "...33333322 cd..".replace(" ", "c"), "....222221.cdc..", "......21...bc...", "................", "................", "................"],
    "stew": ["................", "................", "................", "................", "......4554......",
             "....45544543....", "..dddddddccccb..", "..cccccbbbbbaa..", "...ccbbbbbbaa...", "....cbbbbbaa....",
             ".....bbbbaa.....", "......baaa......", "................", "................", "................", "................"],
    "cookie": ["................", "................", "................", ".....54444......", "....5444a433....",
               "...54a44443 3...".replace(" ", "3"), "...44444443a2...", "...4444a44332...", "...43444433 2...".replace(" ", "3"), "...3a3333322 ...".replace(" ", "2"),
               "....33a3322.....", ".....33222......", "................", "................", "................", "................"],
}


def ingot(color=(176, 176, 184), seed=0, size=SIZE):
    """A metal bar seen from above."""
    rng = _rng(seed, 20)
    return _sized(_sprite(_INGOTS[int(rng.integers(len(_INGOTS)))], _jitter(color, rng)), size)


def gem(color=(84, 200, 214), seed=0, size=SIZE, cut=None):
    """A cut stone. cut: 0 brilliant, 1 cushion, 2 shard. Picked by the seed if not given."""
    rng = _rng(seed, 21)
    i = int(rng.integers(len(_GEMS))) if cut is None else int(cut)
    return _sized(_sprite(_GEMS[i], _jitter(color, rng)), size)


def nugget(color=(240, 196, 70), seed=0, size=SIZE):
    """A small clump of two or three pebbles."""
    rng = _rng(seed, 22)
    x, y = rng.uniform(6.5, 8.5), rng.uniform(8.5, 9.5)
    lumps = [(x + 2.6, y - 2.8, 2.0), (x, y, 2.8)]
    if rng.random() < 0.6:
        lumps.insert(0, (x - 2.6, y + 1.8, 1.9))
    return _sized(_sprite(_lumps(rng, lumps), _jitter(color, rng)), size)


def raw_chunk(color=(190, 150, 110), seed=0, size=SIZE):
    """An unrefined lump with darker pockets."""
    rng = _rng(seed, 23)
    c = 7.5 + rng.uniform(-0.5, 0.5)
    lumps = [(c + rng.uniform(-2.5, -1.5), c + rng.uniform(1, 2), 3.8),
             (c + rng.uniform(1.5, 2.5), c + rng.uniform(1, 2), 3.5),
             (c + rng.uniform(-1, 1), c + rng.uniform(-2.5, -1.5), 3.9)]
    return _sized(_sprite(_lumps(rng, lumps, speckle=3), _jitter(color, rng)), size)


def dust(color=(190, 70, 60), seed=0, size=SIZE):
    """A low pile of powder with a few loose grains."""
    rng = _rng(seed, 24)
    tone = np.zeros((SIZE, SIZE), dtype=int)
    peak = 7.5 + rng.uniform(-1.5, 1.5)
    for x in range(2, 14):
        top = 12 - 6.2 * max(0.0, 1 - abs(x - peak) / 6.0) + rng.uniform(-0.8, 0.8)
        for y in range(int(round(top)), 13):
            shade = 4.3 - (x - peak) * 0.28 - (y - top) * 0.42
            tone[y, x] = int(np.clip(round(shade + rng.uniform(-0.5, 0.5)), 1, 5))
    grains = [(2, 7), (13, 6), (4, 4), (12, 3), (1, 10), (14, 9), (8, 3)]
    for i in rng.permutation(len(grains))[:4]:
        tone[grains[i][1], grains[i][0]] = 4
    return _sized(_sprite(["".join(str(v) if v else "." for v in r) for r in tone], _jitter(color, rng)), size)


def rod(color=(226, 170, 70), seed=0, size=SIZE):
    """A glowing or metal stick, held diagonally."""
    rng = _rng(seed, 25)
    rows = [["."] * SIZE for _ in range(SIZE)]
    for i in range(11):
        y, x = 13 - i, 2 + i
        tones = ("4", "2") if i % 3 else ("5", "3")
        rows[y][x], rows[y][x + 1] = tones
    rows[2][13], rows[3][13] = "5", "3"
    return _sized(_sprite(["".join(r) for r in rows], _jitter(color, rng)), size)


def seeds(color=(150, 170, 74), seed=0, size=SIZE):
    """A scatter of small seeds."""
    rng = _rng(seed, 26)
    rows = [["."] * SIZE for _ in range(SIZE)]
    slots = [(3, 3), (9, 2), (5, 7), (11, 7), (2, 11), (8, 11), (12, 12)]
    for i in sorted(rng.permutation(len(slots))[:5]):
        x, y = slots[i]
        x += int(rng.integers(0, 2))
        rows[y][x], rows[y][x + 1], rows[y + 1][x], rows[y + 1][x + 1] = "5", "3", "3", "2"
    return _sized(_sprite(["".join(r) for r in rows], _jitter(color, rng)), size)


def food(kind="fruit", color=(206, 62, 54), secondary=None, seed=0, size=SIZE):
    """Something to eat. kind: fruit, berries, loaf, meat, stew, cookie. `secondary` colours the leaf,
    bone, bowl or chips. Each has a sensible default."""
    rng = _rng(seed, 27)
    color = _jitter(color, rng)
    if kind == "fruit":
        rows = [list(r) for r in _lumps(rng, [(7.5, 9, 5.2)])]
        rows[3][7], rows[2][8], rows[3][8] = "a", "a", "a"
        rows[2][9], rows[2][10], rows[1][10], rows[1][11] = "b", "c", "c", "b"
        return _sized(_sprite(["".join(r) for r in rows], color, secondary or (80, 134, 50)), size)
    if kind == "berries":
        rows = [list(r) for r in _lumps(rng, [(5, 8, 2.6), (10.5, 8.5, 2.6), (8, 11.5, 2.8), (7.5, 6, 2.5)])]
        rows[3][8], rows[2][8], rows[2][9], rows[2][10] = "a", "a", "b", "c"
        return _sized(_sprite(["".join(r) for r in rows], color, secondary or (80, 134, 50)), size)
    defaults = {"meat": (238, 226, 200), "stew": (138, 96, 58), "cookie": (70, 44, 30), "loaf": color}
    return _sized(_sprite(_FOODS[kind], color, secondary or defaults[kind]), size)


def _tool(kind, color, handle, seed, size):
    rng = _rng(seed, 30)
    return _sized(_sprite(_TOOLS[kind], _jitter(color, rng), handle), size)


def pickaxe(color=(170, 170, 178), handle=(128, 94, 54), seed=0, size=SIZE):
    return _tool("pickaxe", color, handle, seed, size)


def axe(color=(170, 170, 178), handle=(128, 94, 54), seed=0, size=SIZE):
    return _tool("axe", color, handle, seed, size)


def sword(color=(170, 170, 178), handle=(128, 94, 54), seed=0, size=SIZE):
    return _tool("sword", color, handle, seed, size)


def shovel(color=(170, 170, 178), handle=(128, 94, 54), seed=0, size=SIZE):
    return _tool("shovel", color, handle, seed, size)


def hoe(color=(170, 170, 178), handle=(128, 94, 54), seed=0, size=SIZE):
    return _tool("hoe", color, handle, seed, size)


# ---------------------------------------------------------------- animation

def mcmeta(frametime=2, interpolate=False, order=None):
    """The contents of a .png.mcmeta. frametime is in ticks (20 per second)."""
    anim = {"frametime": int(frametime)}
    if interpolate:
        anim["interpolate"] = True
    if order:
        anim["frames"] = list(order)
    return {"animation": anim}


def save_animated(frames, path, frametime=2, interpolate=False, order=None):
    """Write frames as a vertical strip to `path`, with `path`.mcmeta beside it. Returns both paths."""
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    w, h = frames[0].size
    strip = Image.new("RGBA", (w, h * len(frames)))
    for i, frame in enumerate(frames):
        strip.paste(frame.convert("RGBA"), (0, h * i))
    strip.save(path)
    meta = path.with_name(path.name + ".mcmeta")
    meta.write_text(json.dumps(mcmeta(frametime, interpolate, order), indent=2) + "\n")
    return path, meta


def split_frames(img):
    """Cut a vertical animation strip back into its square frames."""
    w, h = img.size
    return [img.crop((0, i * w, w, (i + 1) * w)) for i in range(h // w)]


def scroll(img, frames=None, dx=0, dy=1):
    """Frames that slide a tiling texture along, as for lava or a conveyor. Loops seamlessly when
    frames times the step is the texture size, which is the default."""
    a = np.asarray(img.convert("RGBA"))
    frames = frames or a.shape[0] // max(abs(dx), abs(dy), 1)
    return [Image.fromarray(np.roll(a, (dy * i, dx * i), axis=(0, 1))) for i in range(frames)]


def pulse(img, frames=8, strength=0.22, only_bright=True):
    """Frames that breathe brightness. Dark pixels hold still when only_bright, so seams stay crisp."""
    a = np.asarray(img.convert("RGBA")).astype(float)
    lum = a[..., :3].mean(axis=2) / 255
    weight = np.clip((lum - 0.3) / 0.5, 0, 1) if only_bright else np.ones_like(lum)
    out = []
    for i in range(frames):
        k = np.sin(2 * np.pi * i / frames) * strength
        f = a.copy()
        target = 255.0 if k > 0 else 0.0
        for c in range(3):
            f[..., c] = a[..., c] + (target - a[..., c]) * abs(k) * weight
        out.append(Image.fromarray(np.round(f).astype(np.uint8)))
    return out


def glow_frames(color=(255, 196, 92), seed=0, size=SIZE, frames=8, style="crystal"):
    """An animated glow() block: it pulses gently instead of holding still."""
    return pulse(glow(color, seed, size, style), frames, 0.2)


def machine_frames(casing=(112, 112, 122), accent=(232, 142, 54), seed=0, size=SIZE, frames=6):
    """A running machine front: the fire behind the grate flickers. Each frame keeps the same casing."""
    base = machine("front", casing, accent, True, seed, size)
    return [base] + [_with_casing(machine("front", casing, accent, True, seed + i, size), base) for i in range(1, frames)]


def _with_casing(lit, base):
    """Take only the opening of `lit`, so the casing's blotches don't jump between frames."""
    a, b = np.asarray(lit).copy(), np.asarray(base)
    s = a.shape[0] // SIZE
    mask = np.ones(a.shape[:2], dtype=bool)
    mask[4 * s:13 * s, 4 * s:12 * s] = False
    a[mask] = b[mask]
    return Image.fromarray(a)


# ---------------------------------------------------------------- command line

GENERATORS = {f.__name__: f for f in (
    stone, ore, soil, planks, log_side, log_top, leaves, plant, metal, glow, machine,
    ingot, gem, nugget, raw_chunk, dust, rod, seeds, food, pickaxe, axe, sword, shovel, hoe,
    glow_frames, machine_frames)}


def _coerce(text):
    if text.startswith("#"):
        return rgb(text)
    if text.lower() in ("true", "false"):
        return text.lower() == "true"
    for kind in (int, float):
        try:
            return kind(text)
        except ValueError:
            pass
    return text


def main(argv=None):
    parser = argparse.ArgumentParser(description="Generate one Minecraft-style texture.",
                                     epilog="Run with 'list' to see every generator and its options.")
    parser.add_argument("generator", help="generator name, or 'list'")
    parser.add_argument("-o", "--out", help="output PNG (default <generator>.png)")
    parser.add_argument("--frametime", type=int, default=2, help="ticks per frame, for animated generators")
    args, rest = parser.parse_known_args(argv)
    if args.generator == "list":
        for name, fn in GENERATORS.items():
            print(f"{name}{inspect.signature(fn)}")
        return 0
    if args.generator not in GENERATORS:
        parser.error(f"unknown generator {args.generator!r}; try 'list'")
    if len(rest) % 2:
        parser.error("options must be --name value pairs")
    kwargs = {}
    for flag, value in zip(rest[::2], rest[1::2]):
        kwargs[flag.lstrip("-").replace("-", "_")] = _coerce(value)
    out = pathlib.Path(args.out or f"{args.generator}.png")
    result = GENERATORS[args.generator](**kwargs)
    if isinstance(result, list):
        png, meta = save_animated(result, out, args.frametime)
        print(f"{png} {meta}")
    else:
        out.parent.mkdir(parents=True, exist_ok=True)
        result.save(out)
        print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
