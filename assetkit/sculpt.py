#!/usr/bin/env python3
"""Model anything from nothing, in code. There are no body plans or parts to pick from: every creature is written for
itself, as a script with its own loops and maths, and the result is a normal .bbmodel.

    from assetkit import sculpt
    m = sculpt.Model("pebble_crab")
    body = m.part("body", pivot=(0, 5, 0))
    body.ball((0, 5, 0), (7, 4, 5), "#b4745a")
    body.decal(["ww..ww", "wk..wk"], {"w": "#f0ece0", "k": "#1c1826"}, at=(0, 6, 0), facing="front")
    m.animate("idle", 2.0, sculpt.bob(body, 0.3))
    m.animate("walk", 0.6, sculpt.bob(body, 0.5, cycles=2))
    m.finish("pebble_crab.bbmodel", preview="pebble_crab.png")   # read that image, then fix the script

Units are model units, 16 to a block, +Y up, the front is -Z, and +X is the creature's own right. All coordinates are
in the pose with every rotation at zero, so a part's rotation swings what you drew around its pivot.

Each part holds a grid of coloured voxels, and shapes write into it, later ones over earlier ones. On build the solid
voxels are merged into boxes by geometry alone, and each box's exposed faces are painted into one shared skin at a
texel per voxel face, so colour is free per texel while the box count stays low. assetkit/README.md teaches the loop.
"""
import bisect
import cmath
import inspect
import json
import math
import re
import uuid

import numpy as np

try:
    from . import bbmodel, textures as tx
except ImportError:  # run as a script
    import bbmodel
    import textures as tx

MAX_ATLAS = 512
MAX_BONES = 16  # bones with geometry, since each is one display entity in game
MAX_BONE_CUBES = 300
MAX_CUBES = 1600
THIN = 0.72  # no shape goes thinner than this many voxels across its radius, or a thin limb or a tip just vanishes

_AXES = {"x": 0, "y": 1, "z": 2}
_EPS = 1e-6
# Which way a viewer looks to see each side. The creature's own right is +X, so its left is -X.
_FACING = {"front": (0, 0, 1), "north": (0, 0, 1), "back": (0, 0, -1), "south": (0, 0, -1),
           "left": (1, 0, 0), "west": (1, 0, 0), "right": (-1, 0, 0), "east": (-1, 0, 0),
           "top": (0, -1, 0), "up": (0, -1, 0), "bottom": (0, 1, 0), "down": (0, 1, 0)}
_FACE_DIRS = {"west": (0, -1), "east": (0, 1), "down": (1, -1), "up": (1, 1), "north": (2, -1), "south": (2, 1)}
_SHADE_LIGHT = np.array((0.3, 0.8, -0.5)) / math.sqrt(0.09 + 0.64 + 0.25)
_TONES = 7
# Pulls against the game's own light on each face, which is strongest on top and weakest on the sides and underneath.
# Plain brightness rather than steps along the ramp, whose shifted hues would streak every terrace of a curved surface.
_FACE_GAIN = {"up": 0.8, "down": 1.2, "north": 1.0, "south": 1.0, "east": 1.18, "west": 1.18}


def _vec(value, size=3):
    a = np.asarray(value, dtype=float)
    return np.full(size, float(a)) if a.ndim == 0 else a


def _axis(axis):
    if axis not in _AXES:
        raise ValueError(f"axis must be x, y or z, not {axis!r}")
    return _AXES[axis]


def _name_of(part):
    return part.name if isinstance(part, Part) else part


def _names(parts):
    return [_name_of(p) for p in (parts if isinstance(parts, (list, tuple)) else [parts])]


# ---------------------------------------------------------------- shapes

class Shape:
    """A solid region: its bounds in model units, and a test of which points are inside. Combine them with
    a | b, a & b and a - b. Move them with moved(), rotated() and mirrored()."""

    def __init__(self, lo, hi, inside):
        self.lo, self.hi = np.asarray(lo, float), np.asarray(hi, float)
        self.inside = inside  # takes arrays x, y, z and the voxel size, and returns a boolean array

    def __or__(self, other):
        return Shape(np.minimum(self.lo, other.lo), np.maximum(self.hi, other.hi),
                     lambda x, y, z, g: self.inside(x, y, z, g) | other.inside(x, y, z, g))

    def __and__(self, other):
        return Shape(np.maximum(self.lo, other.lo), np.minimum(self.hi, other.hi),
                     lambda x, y, z, g: self.inside(x, y, z, g) & other.inside(x, y, z, g))

    def __sub__(self, other):
        return Shape(self.lo, self.hi, lambda x, y, z, g: self.inside(x, y, z, g) & ~other.inside(x, y, z, g))

    def moved(self, offset):
        o = _vec(offset)
        return Shape(self.lo + o, self.hi + o, lambda x, y, z, g: self.inside(x - o[0], y - o[1], z - o[2], g))

    def mirrored(self, axis="x", about=0.0):
        a = _axis(axis)
        lo, hi = self.lo.copy(), self.hi.copy()
        lo[a], hi[a] = 2 * about - self.hi[a], 2 * about - self.lo[a]

        def inside(x, y, z, g):
            p = [x, y, z]
            p[a] = 2 * about - p[a]
            return self.inside(p[0], p[1], p[2], g)

        return Shape(lo, hi, inside)

    def rotated(self, rotation, about=(0, 0, 0)):
        """Turn the shape in degrees, in the same order as a bone's rotation. The voxels stay on the grid, so this
        is how a flattened ball or a box gets to lean any way inside one part."""
        about = _vec(about)
        r = bbmodel._mat(*rotation)[:3, :3]
        corners = np.array([[(self.lo, self.hi)[i][0], (self.lo, self.hi)[j][1], (self.lo, self.hi)[k][2]]
                            for i in (0, 1) for j in (0, 1) for k in (0, 1)])
        turned = (corners - about) @ r.T + about

        def inside(x, y, z, g):
            dx, dy, dz = x - about[0], y - about[1], z - about[2]
            # The transpose undoes the turn, taking each point back to where the unturned shape can test it.
            return self.inside(r[0, 0] * dx + r[1, 0] * dy + r[2, 0] * dz + about[0],
                               r[0, 1] * dx + r[1, 1] * dy + r[2, 1] * dz + about[1],
                               r[0, 2] * dx + r[1, 2] * dy + r[2, 2] * dz + about[2], g)

        return Shape(turned.min(axis=0), turned.max(axis=0), inside)


def box(lo, hi):
    """Everything between two opposite corners."""
    a, b = _vec(lo), _vec(hi)
    lo, hi = np.minimum(a, b), np.maximum(a, b)
    return Shape(lo, hi, lambda x, y, z, g: ((x >= lo[0] - _EPS) & (x <= hi[0] + _EPS) & (y >= lo[1] - _EPS) & (y <= hi[1] + _EPS)
                                             & (z >= lo[2] - _EPS) & (z <= hi[2] + _EPS)))


def ball(center, radii, power=2.0):
    """An ellipsoid. radii is one number, or (x, y, z) for something chubby or squashed. A power above 2 boxes it up, with
    flatter sides and fewer steps: about 2.5 suits a cartoon head, where a flat face holds its features better, and it
    takes fewer cubes too."""
    c, r = _vec(center), _vec(radii)

    def inside(x, y, z, g):
        rx, ry, rz = np.maximum(r, THIN * g)
        return np.abs((x - c[0]) / rx) ** power + np.abs((y - c[1]) / ry) ** power + np.abs((z - c[2]) / rz) ** power <= 1 + _EPS

    return Shape(c - r - 1, c + r + 1, inside)


def _segment_gap(x, y, z, a, b, r0, r1, g, flat=False):
    """How far each point is outside a rounded cone from a to b. Zero or below is inside."""
    ab = b - a
    length2 = float(ab @ ab)
    t = ((x - a[0]) * ab[0] + (y - a[1]) * ab[1] + (z - a[2]) * ab[2]) / max(length2, 1e-9)
    clamped = np.clip(t, 0, 1)
    d = np.sqrt((x - a[0] - clamped * ab[0]) ** 2 + (y - a[1] - clamped * ab[1]) ** 2 + (z - a[2] - clamped * ab[2]) ** 2)
    gap = d - np.maximum(r0 + (r1 - r0) * clamped, THIN * g)
    if flat:
        gap = np.where((t < -_EPS) | (t > 1 + _EPS), np.inf, gap)
    return gap


def taper(a, b, r0, r1, flat=False):
    """A limb, tail, ear, horn or claw between two points, with a radius at each end. Round ends unless flat."""
    a, b, reach = _vec(a), _vec(b), max(r0, r1) + 1
    return Shape(np.minimum(a, b) - reach, np.maximum(a, b) + reach,
                 lambda x, y, z, g: _segment_gap(x, y, z, a, b, r0, r1, g, flat) <= _EPS)


def capsule(a, b, radius):
    """A round-ended rod between two points."""
    return taper(a, b, radius, radius)


def cylinder(a, b, radius):
    """A flat-ended rod between two points: axles, pistons, drums and discs."""
    return taper(a, b, radius, radius, flat=True)


def tube(points, radii):
    """A bent limb through a list of points, such as a tail from curve(). radii is one number or one per point."""
    points = [_vec(p) for p in points]
    radii = list(radii) if isinstance(radii, (list, tuple, np.ndarray)) else [radii] * len(points)
    if len(radii) != len(points):
        raise ValueError("tube needs one radius, or one for each point")
    reach = max(radii) + 1

    def inside(x, y, z, g):
        best = None
        for a, b, r0, r1 in zip(points, points[1:], radii, radii[1:]):
            gap = _segment_gap(x, y, z, a, b, r0, r1, g)
            best = gap if best is None else np.minimum(best, gap)
        return best <= _EPS

    return Shape(np.min(points, axis=0) - reach, np.max(points, axis=0) + reach, inside)


def curve(*points, n=10):
    """n + 1 points along a Bezier curve through control points, for tube()."""
    pts = np.array([_vec(p) for p in points])
    out = []
    for i in range(n + 1):
        t, row = i / n, pts
        while len(row) > 1:
            row = row[:-1] * (1 - t) + row[1:] * t
        out.append(tuple(float(v) for v in row[0]))
    return out


def polygon(points, facing="front", at=0.0, thick=1.0):
    """A flat outline with some thickness, for wing membranes, leaves, flames and bolts. Points are (x, y) for facing
    front, (z, y) for left or right, and (x, z) for top, and it runs from `at` to `at + thick` along the third axis."""
    d = _direction(facing)
    if abs(d[2]) > 0.5:
        u, v, w = 0, 1, 2
    elif abs(d[0]) > 0.5:
        u, v, w = 2, 1, 0
    else:
        u, v, w = 0, 2, 1
    pts = np.array(points, float)
    lo, hi = np.zeros(3), np.zeros(3)
    lo[u], lo[v], hi[u], hi[v] = pts[:, 0].min(), pts[:, 1].min(), pts[:, 0].max(), pts[:, 1].max()
    lo[w], hi[w] = min(at, at + thick), max(at, at + thick)
    ax, ay, bx, by = pts[:, 0], pts[:, 1], np.roll(pts[:, 0], -1), np.roll(pts[:, 1], -1)

    def inside(x, y, z, g):
        p = (x, y, z)
        pu, pv = p[u], p[v]
        odd = np.zeros(np.shape(pu), bool)
        for i in range(len(pts)):  # the even-odd rule
            if ay[i] == by[i]:
                continue
            crossing = (ay[i] > pv) != (by[i] > pv)
            odd ^= crossing & (pu < ax[i] + (pv - ay[i]) * (bx[i] - ax[i]) / (by[i] - ay[i]))
        low, high = lo[w], hi[w]
        if high - low < g:  # keep a thin sheet from falling between voxel centres
            mid = (low + high) / 2
            low, high = mid - 0.5 * g, mid + 0.5 * g
        return odd & (p[w] >= low - _EPS) & (p[w] <= high + _EPS)

    return Shape(lo - 1, hi + 1, inside)


def solid(fn, lo, hi):
    """Anything else: fn(x, y, z) says whether a point is inside, and lo and hi bound where to look. It gets numpy
    arrays, and a function written for single numbers works too, only slower."""
    def inside(x, y, z, g):
        try:
            out = np.asarray(fn(x, y, z), dtype=bool)
            if out.ndim and out.shape != x.shape:
                raise ValueError("wrong shape")
        except (TypeError, ValueError):
            out = np.array([bool(fn(float(a), float(b), float(c))) for a, b, c in zip(x.ravel(), y.ravel(), z.ravel())]).reshape(x.shape)
        return np.broadcast_to(out, x.shape)

    return Shape(_vec(lo), _vec(hi), inside)


_SHAPES = {f.__name__: f for f in (box, ball, taper, capsule, cylinder, tube, polygon, solid)}


def mirror(thing, axis="x", **options):
    """A mirrored copy of a Shape, or a new Part mirroring a Part (and its children), through the middle of the model."""
    if isinstance(thing, Shape):
        return thing.mirrored(axis, **options)
    if isinstance(thing, Part):
        return thing.model.mirror(thing, axis=axis, **options)
    raise TypeError("mirror takes a Shape or a Part")


# ---------------------------------------------------------------- colour

def _rgba(color):
    if isinstance(color, str):
        return tx.rgb(color) + (255,)
    a = tuple(int(v) for v in color)
    if len(a) == 3:
        return a + (255,)
    if len(a) == 4:
        return a
    raise ValueError(f"a colour is '#rrggbb', (r, g, b) or (r, g, b, a), not {color!r}")


def _colors(color, x, y, z):
    """Colours as an (n, 4) array of bytes, for 1D arrays of positions. A colour function may return one colour or
    one per point, and it may be written for single numbers."""
    n = x.size
    if color is None:
        raise ValueError("this shape needs a colour")
    if not callable(color):
        return np.tile(np.array(_rgba(color), dtype=np.uint8), (n, 1))
    try:
        out = color(x, y, z)
        if isinstance(out, str) or (np.ndim(out) == 1 and len(out) in (3, 4)):
            return np.tile(np.array(_rgba(out), dtype=np.uint8), (n, 1))
        out = np.asarray(out)
        if out.ndim != 2 or out.shape[0] != n or out.shape[1] not in (3, 4):
            raise ValueError(f"a colour function returned shape {out.shape}")
    except (TypeError, ValueError):
        return np.array([_rgba(color(float(a), float(b), float(c))) for a, b, c in zip(x, y, z)], dtype=np.uint8).reshape(n, 4)
    out = np.clip(np.rint(out), 0, 255).astype(np.uint8)
    if out.shape[1] == 3:
        out = np.concatenate([out, np.full((n, 1), 255, np.uint8)], axis=1)
    return out


def _reflected(color, axis, about=0.0):
    if not callable(color):
        return color
    a = _axis(axis)

    def fn(x, y, z):
        p = [x, y, z]
        p[a] = 2 * about - p[a]
        return color(*p)

    return fn


def _along(along, x, y, z):
    """A distance along an axis name, a direction, or any function of position."""
    if callable(along):
        return np.asarray(along(x, y, z), float)
    if isinstance(along, str):
        return (x, y, z)[_axis(along)]
    d = _vec(along)
    return (x * d[0] + y * d[1] + z * d[2]) / max(np.linalg.norm(d), 1e-9)


def gradient(colors, a, b, steps=6):
    """Colour from a list of stops, running from point a to point b. It moves in `steps` flat bands, because a smooth
    blend looks out of place beside vanilla. Pass steps=None for a smooth one."""
    stops = np.array([_rgba(c) for c in colors], float)
    a, b = _vec(a), _vec(b)
    ab = b - a
    length2 = max(float(ab @ ab), 1e-9)

    def fn(x, y, z):
        t = np.clip(((x - a[0]) * ab[0] + (y - a[1]) * ab[1] + (z - a[2]) * ab[2]) / length2, 0, 1)
        if steps:
            t = np.minimum(np.floor(t * steps), steps - 1) / max(steps - 1, 1)
        at = t * (len(stops) - 1)
        i = np.minimum(at.astype(int), len(stops) - 2)
        return stops[i] + (stops[i + 1] - stops[i]) * (at - i)[:, None]

    return fn


def bands(colors, along="y", width=2, start=0.0):
    """Repeating flat bands in a list of colours, along an axis, a direction, or a function of position."""
    stops = np.array([_rgba(c) for c in colors], np.uint8)

    def fn(x, y, z):
        return stops[np.floor((_along(along, x, y, z) - start) / width).astype(int) % len(stops)]

    return fn


def stripes(base, color, along="z", every=6, width=2, start=0.0, stop=None, where=None):
    """Stripes over another paint, every so often along an axis from start to stop. where(x, y, z) can limit them
    to some region, say the back."""
    def fn(x, y, z):
        out = _colors(base, x, y, z)
        s = _along(along, x, y, z)
        on = (np.mod(s - start, every) < width) & (s >= start)
        if stop is not None:
            on &= s <= stop
        if where is not None:
            on &= np.asarray(where(x, y, z), bool)
        if on.any():
            out[on] = _colors(color, x[on], y[on], z[on])
        return out

    return fn


def _hash01(ix, iy, iz, seed, salt):
    v = (ix * 73856093) ^ (iy * 19349663) ^ (iz * 83492791) ^ ((seed + 1) * 2654435) ^ (salt * 40503)
    v = (v ^ (v >> 13)) * 1274126177
    v = v ^ (v >> 16)
    return (v & 0xFFFFFF) / 0xFFFFFF


def spots(base, color, size=1.5, spacing=6.0, seed=0, stretch=(1, 1, 1)):
    """Round spots of about this radius over another paint, roughly `spacing` apart, in three dimensions."""
    sx, sy, sz = _vec(stretch)

    def fn(x, y, z):
        out = _colors(base, x, y, z)
        px, py, pz = x / (spacing * sx), y / (spacing * sy), z / (spacing * sz)
        cx, cy, cz = np.floor(px).astype(np.int64), np.floor(py).astype(np.int64), np.floor(pz).astype(np.int64)
        best = np.full(x.shape, np.inf)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    ix, iy, iz = cx + dx, cy + dy, cz + dz
                    fx = ix + 0.15 + 0.7 * _hash01(ix, iy, iz, seed, 1)
                    fy = iy + 0.15 + 0.7 * _hash01(ix, iy, iz, seed, 2)
                    fz = iz + 0.15 + 0.7 * _hash01(ix, iy, iz, seed, 3)
                    d = ((px - fx) * spacing * sx) ** 2 + ((py - fy) * spacing * sy) ** 2 + ((pz - fz) * spacing * sz) ** 2
                    best = np.minimum(best, d)
        on = best <= size * size
        if on.any():
            out[on] = _colors(color, x[on], y[on], z[on])
        return out

    return fn


def patch(base, color, center, radii, rim=None):
    """A patch of another colour over a paint, such as a belly, in the shape of an ellipsoid. rim edges it in a third."""
    c, r = _vec(center), _vec(radii)

    def fn(x, y, z):
        out = _colors(base, x, y, z)
        d = ((x - c[0]) / r[0]) ** 2 + ((y - c[1]) / r[1]) ** 2 + ((z - c[2]) / r[2]) ** 2
        on = d <= 1
        if rim is not None:
            ring = (d > 1) & (d <= 1.0 + 2.2 / r.max())
            if ring.any():
                out[ring] = _colors(rim, x[ring], y[ring], z[ring])
        if on.any():
            out[on] = _colors(color, x[on], y[on], z[on])
        return out

    return fn


def mottle(base, color, size=3.0, amount=0.3, seed=0):
    """Soft clusters of another colour over a paint, for stone and hide. Clusters instead of per-voxel noise, because
    noise per texel always looks bad. amount is about the share it covers."""
    def fn(x, y, z):
        out = _colors(base, x, y, z)
        px, py, pz = x / size, y / size, z / size
        ix, iy, iz = np.floor(px).astype(np.int64), np.floor(py).astype(np.int64), np.floor(pz).astype(np.int64)
        fx, fy, fz = px - ix, py - iy, pz - iz
        fx, fy, fz = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy), fz * fz * (3 - 2 * fz)
        n = 0.0
        for dx in (0, 1):
            for dy in (0, 1):
                for dz in (0, 1):
                    w = (fx if dx else 1 - fx) * (fy if dy else 1 - fy) * (fz if dz else 1 - fz)
                    n = n + w * _hash01(ix + dx, iy + dy, iz + dz, seed, 4)
        # Blended noise bunches around 0.5, so this keeps the threshold near what `amount` asks for.
        on = n > 0.5 + (0.5 - amount) * 0.4
        if on.any():
            out[on] = _colors(color, x[on], y[on], z[on])
        return out

    return fn


def where(test, a, b):
    """One paint where test(x, y, z) is true, and another elsewhere."""
    def fn(x, y, z):
        out = _colors(b, x, y, z)
        on = np.asarray(test(x, y, z), bool)
        if on.any():
            out[on] = _colors(a, x[on], y[on], z[on])
        return out

    return fn


# ---------------------------------------------------------------- pixel art

def _rows(rows):
    rows = [rows] if isinstance(rows, str) else list(rows)
    if len({len(r) for r in rows}) != 1:
        raise ValueError("every row of pixel art has to be the same length")
    return rows


def _direction(facing):
    if isinstance(facing, str):
        if facing not in _FACING:
            raise ValueError(f"facing must be one of {sorted(_FACING)}, or a direction, not {facing!r}")
        return np.array(_FACING[facing], float)
    d = _vec(facing)
    return d / max(np.linalg.norm(d), 1e-9)


def _image_axes(d):
    """For a viewer looking along d: the directions of image right and image down, as they see it."""
    up = np.array((0, 0, -1.0) if d[1] < -0.9 else (0, 0, 1.0) if d[1] > 0.9 else (0, 1.0, 0))
    right = np.cross(d, up)
    right /= np.linalg.norm(right)
    return right, -np.cross(right, d)


def _palette_lut(palette):
    return {k: (None if v is None else _rgba(v)) for k, v in palette.items()}


# ---------------------------------------------------------------- parts

class _Brush:
    """part.cut and part.paint. Call one with a Shape, or use a shape's name: head.cut.ball((0, 20, -6), (2, 1, 2))."""

    def __init__(self, part, mode):
        self.part, self.mode = part, mode

    def __call__(self, shape, color=None, **options):
        return self.part._apply(shape, color, mode=self.mode, **options)

    def __getattr__(self, kind):
        if kind not in _SHAPES:
            raise AttributeError(kind)
        return lambda *args, **kw: self.part._draw(_SHAPES[kind], args, kw, self.mode)


class Part:
    """A bone and its voxels. Make one with Model.part. Each shape method takes the shape's arguments, then a colour
    or a colour function of (x, y, z), and these options:

        mirror="x"    also draw it reflected through the model's middle
        shade=False   keep this colour exact, with no ramp shading on it
        glow=15       make it emit light in game (0 to 15), which also keeps its colour exact
    """

    def __init__(self, model, name, parent, pivot, rotation, grain, loose):
        self.model, self.name, self.parent = model, name, parent
        self.pivot, self.rotation, self.grain = tuple(float(v) for v in pivot), tuple(float(v) for v in rotation), grain
        self.loose = loose  # separate pieces are meant, so don't call them floating
        self.shading = None
        self.lo = None
        self.solid_grid = self.rgba = self.flat = self.glow = None

    # The grid only grows, so a part can hold anything without saying its size up front.
    def _ensure(self, lo, hi):
        lo, hi = np.asarray(lo, int), np.asarray(hi, int)
        if self.solid_grid is None:
            self.lo = lo - 2
            shape = tuple(hi - lo + 4)
            self.solid_grid, self.flat = np.zeros(shape, bool), np.zeros(shape, bool)
            self.rgba, self.glow = np.zeros(shape + (4,), np.uint8), np.zeros(shape, np.uint8)
            return
        old_hi = self.lo + self.solid_grid.shape
        if (lo >= self.lo).all() and (hi <= old_hi).all():
            return
        new_lo, new_hi = np.minimum(lo - 4, self.lo), np.maximum(hi + 4, old_hi)
        shape = tuple(new_hi - new_lo)
        at = tuple(slice(a, a + n) for a, n in zip(self.lo - new_lo, self.solid_grid.shape))
        for field in ("solid_grid", "flat", "rgba", "glow"):
            old = getattr(self, field)
            new = np.zeros(shape + old.shape[3:], old.dtype)
            new[at] = old
            setattr(self, field, new)
        self.lo = new_lo

    def _draw(self, make, args, kw, mode):
        names = inspect.signature(make).parameters
        required = sum(1 for p in names.values() if p.default is p.empty)
        shape = make(*args[:required], **{k: kw.pop(k) for k in list(kw) if k in names})
        color = args[required] if len(args) > required else kw.pop("color", None)
        return self._apply(shape, color, mode=mode, **kw)

    def add(self, shape, color, **options):
        """Draw a Shape you've combined or turned yourself, such as (ball(...) - box(...)).rotated(...)."""
        return self._apply(shape, color, **options)

    def _apply(self, shape, color=None, mode="add", mirror=None, shade=True, glow=0):
        if mode != "cut" and color is None:
            raise ValueError(f"{self.name}: this shape needs a colour")
        self._stamp(shape, color, mode, shade, glow)
        if mirror:
            done = [(shape, color)]
            for axis in mirror:
                done += [(s.mirrored(axis), _reflected(c, axis)) for s, c in done]
            for s, c in done[1:]:
                self._stamp(s, c, mode, shade, glow)
        self.model._changed()
        return self

    def _stamp(self, shape, color, mode, shade, glow):
        g = self.grain
        lo = np.ceil(shape.lo / g - 0.5 - _EPS).astype(int)
        hi = np.floor(shape.hi / g - 0.5 + _EPS).astype(int) + 1
        if mode != "add":
            if self.solid_grid is None:
                hi = lo
            else:
                lo = np.maximum(lo, self.lo)
                hi = np.minimum(hi, self.lo + self.solid_grid.shape)
        if (hi <= lo).any():
            if mode == "paint":
                self.model._notes.append(f"part {self.name!r}: a paint landed on nothing")
            return 0
        if np.prod(hi - lo, dtype=float) > 3e7:
            raise ValueError(f"part {self.name!r}: a shape spans {(hi - lo).tolist()} voxels, which is more than any model needs. Check its coordinates, or use a coarser grain")
        x, y, z = np.meshgrid(*[(np.arange(lo[i], hi[i]) + 0.5) * g for i in range(3)], indexing="ij")
        inside = np.asarray(shape.inside(x, y, z, g), bool)
        if not inside.any():
            if mode == "paint":
                self.model._notes.append(f"part {self.name!r}: a paint landed on nothing")
            return 0
        if mode == "add":
            self._ensure(lo, hi)
        at = tuple(slice(a, b) for a, b in zip(lo - self.lo, hi - self.lo))
        if mode == "cut":
            self.solid_grid[at] &= ~inside
            return int(inside.sum())
        if mode == "paint":
            inside = inside & self.solid_grid[at]
            if not inside.any():
                self.model._notes.append(f"part {self.name!r}: a paint landed on nothing")
                return 0
        colors = _colors(color, x[inside], y[inside], z[inside])
        self.rgba[at][inside] = colors
        self.flat[at][inside] = (not shade) or glow > 0
        self.glow[at][inside] = glow
        if mode == "add":
            self.solid_grid[at][inside] = True
        return int(inside.sum())

    @property
    def cut(self):
        return _Brush(self, "cut")

    @property
    def paint(self):
        return _Brush(self, "paint")

    def mirror(self, axis="x"):
        """Copy what's in this part across the model's middle, as when you've drawn one half of something."""
        if self.solid_grid is None:
            return self
        a = _axis(axis)
        snapshot = {f: np.flip(getattr(self, f), axis=a) for f in ("solid_grid", "flat", "rgba", "glow")}
        n = np.array(self.solid_grid.shape)
        lo = self.lo.copy()
        lo[a] = -(self.lo[a] + n[a])
        self._ensure(lo, lo + n)
        at = tuple(slice(i, i + c) for i, c in zip(lo - self.lo, n))
        on = snapshot["solid_grid"]
        for field, data in snapshot.items():
            getattr(self, field)[at][on] = data[on]
        self.model._changed()
        return self

    def _pixels(self, x, y, z, colors, shade, glow):
        i = np.floor(np.stack([x, y, z], axis=1) / self.grain + _EPS).astype(int)
        self._ensure(i.min(axis=0), i.max(axis=0) + 1)
        i = i - self.lo
        self.solid_grid[i[:, 0], i[:, 1], i[:, 2]] = True
        self.rgba[i[:, 0], i[:, 1], i[:, 2]] = colors
        self.flat[i[:, 0], i[:, 1], i[:, 2]] = (not shade) or glow > 0
        self.glow[i[:, 0], i[:, 1], i[:, 2]] = glow

    def layers(self, layers, palette, at, facing="front", mirror=None, shade=False, glow=0):
        """Exact voxels from pixel art. Each layer is a list of equal strings, drawn as seen from `facing`, and a key
        missing from the palette or mapped to None leaves a gap. '.' and ' ' are always gaps. One list of strings is one
        layer. `at` is where the art's centre goes, and where its first layer begins going away from the viewer.
        An odd width can't be centred on x=0, since voxels lie either side of it, so that lands half a voxel off."""
        if layers and isinstance(layers[0], str):
            layers = [layers]
        lut = _palette_lut(palette)
        d = _direction(facing)
        if np.abs(d).max() < 0.999:
            raise ValueError("layers only go along the axes. Use a decal for anything at an angle.")
        right, down = _image_axes(d)
        at = _vec(at)
        g = self.grain
        coords, colors = [], []
        for k, rows in enumerate(layers):
            rows = _rows(rows)
            h, w = len(rows), len(rows[0])
            for r, row in enumerate(rows):
                for c, ch in enumerate(row):
                    color = lut.get(ch)
                    if ch in ". " or color is None:
                        continue
                    coords.append(at + (c - (w - 1) / 2) * g * right + (r - (h - 1) / 2) * g * down + (k + 0.5) * g * d)
                    colors.append(color)
        if not coords:
            return self
        p = np.array(coords)
        self._pixels(p[:, 0], p[:, 1], p[:, 2], np.array(colors, np.uint8), shade, glow)
        if mirror:
            for axis in mirror:
                a = _axis(axis)
                q = p.copy()
                # A voxel's index mirrors to -i - 1, whichever side of a voxel boundary the art landed on.
                i = np.floor(q[:, a] / g + _EPS)
                q[:, a] = (-i - 1 + 0.5) * g
                self._pixels(q[:, 0], q[:, 1], q[:, 2], np.array(colors, np.uint8), shade, glow)
        self.model._changed()
        return self

    def decal(self, rows, palette, at, facing="front", scale=1, mirror=None, depth=1, shade=False, glow=0, near=None):
        """Pixel art projected onto this part's surface: eyes, mouths, cheeks and markings. It's drawn as seen from
        `facing`, which is a side's name or a direction to look along, and a pixel is one voxel unless scale says more.
        `at` is where the art's centre is aimed, and on a straight view only the two coordinates across it matter, unless
        `near` says to start looking this far along the view from `at`, to reach past something in the way. depth paints
        this many voxels in. From an angle, `at` has to be a point on the surface."""
        self._decal(_rows(rows), _palette_lut(palette), _vec(at), _direction(facing), scale, depth, shade, glow, near)
        if mirror:
            for axis in mirror:
                flip = np.ones(3)
                flip[_axis(axis)] = -1
                self._decal(_rows(rows), _palette_lut(palette), _vec(at), _direction(facing), scale, depth, shade, glow, near, flip)
        self.model._changed()
        return self

    def _decal(self, rows, lut, at, d, scale, depth, shade, glow, near, flip=None):
        h, w = len(rows), len(rows[0])
        right, down = _image_axes(d)
        if flip is not None:
            # Reflect the whole projection, so the art reads mirrored and lands voxel for voxel opposite.
            at, d, right, down = at * flip, d * flip, right * flip, down * flip
        art = [[lut.get(ch) if ch not in ". " else None for ch in row] for row in rows]
        wanted = sum(c is not None for row in art for c in row)
        label = f"part {self.name!r}: a decal at {tuple(float(v) for v in at)}"
        if self.solid_grid is None or not self.solid_grid.any():
            self.model._notes.append(f"{label} has nothing to land on")
            return
        g = self.grain
        idx = np.argwhere(self.solid_grid)
        p = (idx + self.lo + 0.5) * g
        size = g * scale
        u = (p - at) @ right / size + w / 2
        v = (p - at) @ down / size + h / 2
        col, row = np.floor(u + _EPS).astype(int), np.floor(v + _EPS).astype(int)
        along = p @ d
        keep = (col >= 0) & (col < w) & (row >= 0) & (row < h)
        if near is not None:
            keep &= along >= (at @ d) + near
        idx, col, row, along = idx[keep], col[keep], row[keep], along[keep]
        cell = row * w + col
        nearest = np.full(w * h, np.inf)
        np.minimum.at(nearest, cell, along)
        straight = np.abs(d).max() > 0.999
        tolerance = (depth - 1) * g + (0.0 if straight else 0.9 * g) + 1e-3
        hit = along <= nearest[cell] + tolerance
        table = np.zeros((h, w, 4), np.uint8)
        painted = np.zeros((h, w), bool)
        for r in range(h):
            for c in range(w):
                if art[r][c] is not None:
                    table[r, c] = art[r][c]
                    painted[r, c] = True
        hit &= painted[row, col]
        i = idx[hit]
        self.rgba[i[:, 0], i[:, 1], i[:, 2]] = table[row[hit], col[hit]]
        self.flat[i[:, 0], i[:, 1], i[:, 2]] = (not shade) or glow > 0
        self.glow[i[:, 0], i[:, 1], i[:, 2]] = glow
        missed = int((painted & ~np.isfinite(nearest.reshape(h, w))).sum())
        if missed:
            self.model._notes.append(f"{label}: {missed} of its {wanted} pixels missed the surface")

    # ------------------------------------------------------------ meshing

    def _trimmed(self):
        """Index ranges of the solid voxels, or None if there aren't any."""
        if self.solid_grid is None or not self.solid_grid.any():
            return None
        which = np.nonzero(self.solid_grid)
        return tuple(slice(int(w.min()), int(w.max()) + 1) for w in which)

    def final_colors(self):
        """The grid's colours after ramp shading, so a surface reads as round instead of flat, as a dict of face direction
        to an array. A face gets its own tone because the game lights each direction differently, and without
        pulling against that, every step of a curved surface reads as a bright and dark stripe."""
        strength = self.model.shade if self.shading is None else self.shading
        at = self.solid_grid & ~self.flat
        if not strength or not at.any():
            return {face: self.rgba for face in _FACE_DIRS}
        tones, ramps = _shading(self.solid_grid, self.rgba, at, strength)
        index = np.clip(np.rint(_TONES // 2 + tones), 0, _TONES - 1).astype(int)
        shaded = ramps[np.arange(len(index)), index].astype(float)
        out = {}
        for face in _FACE_DIRS:
            colors = self.rgba.copy()
            gain = 1 + min(strength, 1.0) * (_FACE_GAIN[face] - 1)
            colors[at, :3] = np.clip(np.rint(shaded * gain), 0, 255).astype(np.uint8)
            out[face] = colors
        return out

    def mesh(self):
        """The boxes to draw, as dicts of voxel index ranges, the faces that show, and what they're made of."""
        trim = self._trimmed()
        if trim is None:
            return []
        solid = self.solid_grid[trim]
        alpha = self.rgba[trim][..., 3]
        glow = self.glow[trim]
        opaque = solid & (alpha == 255)
        glass = solid & (alpha < 255)
        exposed = _exposed(solid, opaque)
        out = []
        offset = np.array([s.start for s in trim])
        keys = sorted({(int(v), False) for v in np.unique(glow[opaque])} | {(int(v), True) for v in np.unique(glow[glass])},
                      key=lambda k: (k[1], k[0]))
        for level, is_glass in keys:
            mask = (glass if is_glass else opaque) & (glow == level)
            for lo, hi in greedy_boxes(mask):
                faces = [name for name in _FACE_DIRS if _face_slice_any(exposed[name], lo, hi, name)]
                if faces:  # a box with nothing showing would be an empty element, which the game refuses
                    out.append({"lo": np.array(lo) + offset, "hi": np.array(hi) + offset, "faces": faces, "glow": level, "glass": is_glass})
        return out


def _face_layer(lo, hi, name):
    axis, sign = _FACE_DIRS[name]
    at = [slice(lo[i], hi[i]) for i in range(3)]
    at[axis] = slice(hi[axis] - 1, hi[axis]) if sign > 0 else slice(lo[axis], lo[axis] + 1)
    return tuple(at)


def _face_slice_any(array, lo, hi, name):
    return bool(array[_face_layer(lo, hi, name)].any())


def _exposed(solid, opaque):
    """For each face direction, the voxels whose face in that direction can be seen. An opaque voxel shows behind
    something translucent, but translucent voxels don't draw the walls between themselves."""
    out = {}
    padded_solid, padded_opaque = np.pad(solid, 1), np.pad(opaque, 1)
    for name, (axis, sign) in _FACE_DIRS.items():
        next_solid = np.roll(padded_solid, -sign, axis=axis)[1:-1, 1:-1, 1:-1]
        next_opaque = np.roll(padded_opaque, -sign, axis=axis)[1:-1, 1:-1, 1:-1]
        out[name] = (opaque & ~next_opaque) | (solid & ~opaque & ~next_solid)
    return out


def _span_boxes(mask, axis, across_first):
    """Boxes from runs along one axis: columns with the very same run merge into rectangles. Going right through a shape
    makes one box show on both sides, which is why round things come out in fewer boxes this way than scanning from a
    corner."""
    m = np.moveaxis(mask, axis, -1)
    pad = np.zeros(m.shape[:2] + (1,), bool)
    d = np.diff(np.concatenate([pad, m, pad], axis=2).astype(np.int8), axis=2)
    starts, ends = np.argwhere(d == 1), np.argwhere(d == -1)
    groups = {}
    for (u, v, s), e in zip(starts.tolist(), ends[:, 2].tolist()):
        groups.setdefault((s, e), []).append((u, v))
    others = [i for i in range(3) if i != axis]
    boxes = []
    for (s, e), cells in groups.items():
        grid = np.zeros(m.shape[:2], bool)
        cells = sorted(cells) if across_first else sorted(cells, key=lambda c: (c[1], c[0]))
        for u, v in cells:
            grid[u, v] = True
        for u, v in cells:
            if not grid[u, v]:
                continue
            hu, hv = u + 1, v + 1
            if across_first:
                while hv < grid.shape[1] and grid[u, hv]:
                    hv += 1
                while hu < grid.shape[0] and grid[hu, v:hv].all():
                    hu += 1
            else:
                while hu < grid.shape[0] and grid[hu, v]:
                    hu += 1
                while hv < grid.shape[1] and grid[u:hu, hv].all():
                    hv += 1
            grid[u:hu, v:hv] = False
            lo, hi = [0, 0, 0], [0, 0, 0]
            lo[others[0]], hi[others[0]], lo[others[1]], hi[others[1]], lo[axis], hi[axis] = u, hu, v, hv, s, e
            boxes.append((tuple(lo), tuple(hi)))
    return boxes


def greedy_boxes(mask):
    """Boxes that cover exactly the true cells of a boolean grid, without overlapping. It tries every axis and keeps the
    split with the fewest boxes. It looks only at geometry, since colour comes from the skin."""
    if not mask.any():
        return []
    best = None
    for axis in range(3):
        for across_first in (True, False):
            boxes = _span_boxes(mask, axis, across_first)
            if best is None or len(boxes) < len(best):
                best = boxes
    return sorted(best)


def _blur(a, passes):
    for _ in range(passes):
        for axis in range(3):
            a = (np.roll(a, 2, axis) + 4 * np.roll(a, 1, axis) + 6 * a + 4 * np.roll(a, -1, axis) + np.roll(a, -2, axis)) / 16
    return a


def _shading(solid, rgba, at, strength):
    """How the voxels in `at` move along the ramp of their own colour: by how they face the light and how deep in a
    crease they sit. Normals come from a blurred copy of the solid, so any shape, or a union of shapes, reads as one
    smooth form. Returns each voxel's tone and its ramp."""
    passes, pad = 3, 7
    blurred = _blur(np.pad(solid, pad).astype(np.float32), passes)
    gx, gy, gz = np.gradient(blurred)
    trim = (slice(pad, -pad),) * 3
    gx, gy, gz, blurred = gx[trim][at], gy[trim][at], gz[trim][at], blurred[trim][at]
    length = np.maximum(np.sqrt(gx * gx + gy * gy + gz * gz), 1e-6)
    facing = -(gx * _SHADE_LIGHT[0] + gy * _SHADE_LIGHT[1] + gz * _SHADE_LIGHT[2]) / length
    crease = np.maximum(blurred - 0.42, 0)
    tones = strength * (2.0 * facing - 4.0 * crease)
    colors = rgba[at][:, :3].astype(np.int64)
    packed = colors[:, 0] << 16 | colors[:, 1] << 8 | colors[:, 2]
    unique, inverse = np.unique(packed, return_inverse=True)
    ramps = np.array([tx.ramp((int(c) >> 16 & 255, int(c) >> 8 & 255, int(c) & 255), _TONES, 0.45) for c in unique], np.uint8)
    return tones, ramps[inverse.ravel()]


def _pack(sizes):
    """First-fit shelves, tallest first, in the smallest power-of-two square that holds them. Returns the side and each
    rectangle's corner. It goes past the 512 limit if it has to, so check() can report by how much."""
    if not sizes:
        return 16, []
    area = sum(w * h for w, h in sizes)
    side = 16
    while side * side < area or side < max(max(s) for s in sizes):
        side *= 2
    order = sorted(range(len(sizes)), key=lambda i: (-sizes[i][1], -sizes[i][0], i))
    while True:
        spots_out, shelves, top = [None] * len(sizes), [], 0
        for i in order:
            w, h = sizes[i]
            for shelf in shelves:
                if h <= shelf[1] and shelf[2] + w <= side:
                    spots_out[i] = (shelf[2], shelf[0])
                    shelf[2] += w
                    break
            else:
                if top + h > side:
                    side *= 2
                    break
                shelves.append([top, h, w])
                spots_out[i] = (0, top)
                top += h
        else:
            return side, spots_out


def _face_pixels(colors, lo, hi, name):
    """A box face's colours as (rows, columns, 4), laid out the way the game maps a face onto its uv rectangle."""
    x0, y0, z0 = lo
    x1, y1, z1 = hi
    if name == "north":
        return colors[x0:x1, y0:y1, z0].transpose(1, 0, 2)[::-1, ::-1]
    if name == "south":
        return colors[x0:x1, y0:y1, z1 - 1].transpose(1, 0, 2)[::-1, :]
    if name == "east":
        return colors[x1 - 1, y0:y1, z0:z1][::-1, ::-1]
    if name == "west":
        return colors[x0, y0:y1, z0:z1][::-1, :]
    if name == "up":
        return colors[x0:x1, y1 - 1, z0:z1].transpose(1, 0, 2)
    return colors[x0:x1, y0, z0:z1].transpose(1, 0, 2)[::-1, :]


# ---------------------------------------------------------------- the model

class Model:
    """A creature or machine. grain sets the voxel size in units for every part (2 or 4 for huge bosses), and shade how
    strongly surfaces are shaded along each colour's ramp (0 for none)."""

    def __init__(self, name, grain=1, shade=1.0):
        if not re.fullmatch(r"[a-z0-9_]+", name):
            raise ValueError(f"model name {name!r} must be lowercase letters, digits and underscores")
        self.name, self.grain, self.shade = name, grain, shade
        self.parts = {}
        self.anims = []
        self._notes = []
        self._built = None

    def _changed(self):
        self._built = None

    def part(self, name, parent=None, pivot=(0, 0, 0), rotation=(0, 0, 0), grain=None, loose=False, still=False):
        """Make a bone. pivot is what it rotates around, and rotation in degrees is how it's posed at rest. Every part
        with voxels is one display entity in game, so a creature wants about 5 to 12. A part with no voxels costs
        nothing, and is useful as a joint. loose says that separate pieces in this part are on purpose, and still that
        it's meant to stay put in every animation."""
        if not re.fullmatch(r"[a-z0-9_]+", name):
            raise ValueError(f"part name {name!r} must be lowercase letters, digits and underscores")
        if name in self.parts:
            raise ValueError(f"there's already a part called {name!r}")
        if parent is not None:
            parent = _name_of(parent)
            if parent not in self.parts:
                raise ValueError(f"part {name!r} has parent {parent!r}, which doesn't exist yet")
        part = Part(self, name, parent, pivot, rotation, grain or self.grain, loose)
        part.still = still
        self.parts[name] = part
        self._changed()
        return part

    def _rest_world(self, name):
        """A part's matrix at rest, which takes pivot-relative points to the model's."""
        part = self.parts[name]
        above = self.parts.get(part.parent)
        m = bbmodel._mat(*part.rotation, pos=np.array(part.pivot) - (np.array(above.pivot) if above else 0))
        return self._rest_world(part.parent) @ m if part.parent else m

    def mirror(self, part, name=None, axis="x", parent=None, children=True):
        """A new part reflecting this one through the model's middle, with its pivot, rotation and voxels, and
        its children too. The name swaps _r and _l, or right and left, unless you give one."""
        source = self.parts[_name_of(part)]
        a = _axis(axis)
        name = name or _swapped(source.name)
        if name in self.parts:
            raise ValueError(f"mirroring {source.name!r} needs a new name, and {name!r} is taken")
        pivot = list(source.pivot)
        pivot[a] = -pivot[a]
        rotation = [(r if i == a else -r) for i, r in enumerate(source.rotation)]
        made = self.part(name, parent if parent is not None else source.parent, pivot, rotation, source.grain, source.loose, source.still)
        made.shading = source.shading
        if source.solid_grid is not None:
            made.lo = source.lo.copy()
            made.lo[a] = -(source.lo[a] + source.solid_grid.shape[a])
            for field in ("solid_grid", "flat", "rgba", "glow"):
                setattr(made, field, np.flip(getattr(source, field), axis=a).copy())
        if children:
            for child in [p for p in self.parts.values() if p.parent == source.name]:
                self.mirror(child, axis=axis, parent=made, children=True)
        return made

    def animate(self, name, length, *tracks, loop="loop", samples=None):
        """Add an animation made of helpers' tracks, such as gait(), follow() and strike(). Tracks on the same part and
        channel add up. A track is {part: {"rotation"|"position"|"scale": fn}} with fn taking the phase 0..1, so anything
        goes alongside the helpers. Time goes in whole ticks, as BIL plays it, so length is rounded to the nearest 0.05
        seconds. Use loop="once" for something that plays and ends, and loop="hold" for a death, which stays on its last
        frame. Mobs need idle and walk, attack if they fight, and hurt and death to react."""
        for track in tracks:
            for part in (track.names() if isinstance(track, _Later) else track):
                if _name_of(part) not in self.parts:
                    raise ValueError(f"animation {name!r} moves part {_name_of(part)!r}, which doesn't exist")
        ticks = max(int(round(length / bbmodel.TICK)), 2)
        self.anims = [a for a in self.anims if a[0] != name] + [(name, ticks, tracks, loop, samples)]
        self._changed()
        return self

    def _feet(self):
        """The ends of the legs that any gait() in this model stands on, each with the point on it that takes the weight."""
        feet = {}
        for _, _, tracks, _, _ in self.anims:
            for track in tracks:
                if isinstance(track, _Gait):
                    for name in track.feet():
                        part = self.parts[name]
                        if name not in feet and part.solid_grid is not None and part.solid_grid.any():
                            feet[name] = _sole(part)[1]
        return feet

    def _still(self):
        return [p.name for p in self.parts.values() if p.still]

    def _tracks_for(self, ticks, tracks, loop):
        rig = _Rig(self, ticks, loop, {})
        for track in tracks:
            if not isinstance(track, _Later):
                rig.add(track)
        for track in sorted((t for t in tracks if isinstance(t, _Later)), key=lambda t: t.order):
            track.work_out(rig)
        return rig.tracks

    def build(self):
        """The .bbmodel dictionary. Building again costs nothing unless something has changed."""
        if self._built is None:
            self._built = self._build()
        return self._built

    def _id(self, *parts):
        return str(uuid.uuid5(bbmodel._NAMESPACE, "/".join(map(str, (self.name, "sculpt") + parts))))

    def _build(self):
        meshes = {p.name: p.mesh() for p in self.parts.values()}
        grids = {p.name: p.final_colors() for p in self.parts.values() if p.solid_grid is not None}
        sizes, slots = [], []
        for part in self.parts.values():
            for i, b in enumerate(meshes[part.name]):
                for face in b["faces"]:
                    axis = _FACE_DIRS[face][0]
                    span = b["hi"] - b["lo"]
                    across = [span[j] for j in range(3) if j != axis]
                    # Texture rectangles run width by height the way _face_pixels lays them out.
                    w, h = (int(across[1]), int(across[0])) if axis == 0 else (int(across[0]), int(across[1]))
                    sizes.append((w, h))
                    slots.append((part.name, i, face))
        side, corners = _pack(sizes)
        atlas = np.zeros((side, side, 4), np.uint8)
        uvs = {}
        seen = {}
        for (part_name, i, face), (u, v), (w, h) in zip(slots, corners, sizes):
            part, b = self.parts[part_name], meshes[part_name][i]
            pixels = _face_pixels(grids[part_name][face], b["lo"], b["hi"], face).copy()
            if b["glass"]:
                # Any translucent face hidden against a neighbour has to vanish, or it would show through.
                if part_name not in seen:
                    seen[part_name] = _exposed(part.solid_grid, part.solid_grid & (part.rgba[..., 3] == 255))
                pixels[~_face_pixels(seen[part_name][face][..., None], b["lo"], b["hi"], face)[..., 0]] = 0
            atlas[v:v + h, u:u + w] = pixels
            uvs[(part_name, i, face)] = [u, v, u + w, v + h]

        elements, children = [], {name: [] for name in self.parts}
        for part in self.parts.values():
            g = part.grain
            for i, b in enumerate(meshes[part.name]):
                low = (b["lo"] + part.lo) * g
                high = (b["hi"] + part.lo) * g
                el = {"name": f"{part.name}_{i}", "from": [_num(v) for v in low], "to": [_num(v) for v in high],
                      "autouv": 0, "color": 0, "origin": [_num(v) for v in part.pivot],
                      "faces": {face: {"uv": uvs[(part.name, i, face)], "texture": 0} for face in b["faces"]},
                      "type": "cube", "uuid": self._id("cube", part.name, i)}
                if b["glow"]:
                    el["light_emission"] = int(b["glow"])
                elements.append(el)
                children[part.name].append(el["uuid"])

        roots = [p for p in self.parts.values() if p.parent is None]
        groups = []
        # One root bone: BIL rebuilds every bone once per root, so several get a joint with no voxels above them.
        extra = None
        if len(roots) != 1:
            extra = {"name": _free_name("root", self.parts), "origin": [0, 0, 0], "rotation": [0, 0, 0], "uuid": self._id("bone", "root")}
        ids = {p.name: self._id("bone", p.name) for p in self.parts.values()}

        def group(name, origin, rotation, uid):
            return {"name": name, "origin": list(origin), "rotation": list(rotation), "scale": 1, "color": 0, "uuid": uid,
                    "export": True, "mirror_uv": False, "isOpen": True, "locked": False, "visibility": True, "autouv": 0}

        if extra:
            groups.append(group(extra["name"], extra["origin"], extra["rotation"], extra["uuid"]))
        for p in self.parts.values():
            groups.append(group(p.name, [_num(v) for v in p.pivot], [_num(v) for v in p.rotation], ids[p.name]))

        def outline(name):
            kids = children[name] + [outline(p.name) for p in self.parts.values() if p.parent == name]
            return {"uuid": ids[name], "isOpen": True, "children": kids}

        if extra:
            outliner = [{"uuid": extra["uuid"], "isOpen": True, "children": [outline(p.name) for p in roots]}]
        else:
            outliner = [outline(roots[0].name)] if roots else []
        doc = bbmodel.document(self.name, elements, groups, outliner, atlas, self._id("texture"))
        for name, ticks, tracks, loop, samples in self.anims:
            worked_out = self._tracks_for(ticks, tracks, loop)
            if samples:
                bbmodel.animate(doc, name, ticks * bbmodel.TICK, worked_out, loop=loop, samples=samples)
            else:
                bbmodel.animate_ticks(doc, name, ticks, worked_out, loop=loop)
        return doc

    def save(self, path):
        return bbmodel.save(self.build(), path)

    def preview(self, out=None, machine=False, **options):
        """Draws the model and how it moves. Given a path, the second sheet goes beside it as <name>_motion.png."""
        return bbmodel.preview(self.build(), out, feet=self._feet(), still=self._still(), machine=machine, **options)

    def finish(self, path=None, preview=None, machine=False):
        """The end of a script: write the file and the two preview sheets, and print the numbers and the problems. Returns
        the problems. Pass machine=True for a block's model, which doesn't need a walk or hurt or death."""
        problems = check(self, machine)
        if path:
            print(self.save(path))
        if preview:
            self.preview(preview, machine=machine)
            print(preview)
            print(bbmodel.motion_path(preview))
        numbers = stats(self)
        print(f"{self.name}: {numbers['height']} blocks tall, {numbers['width']} wide, {numbers['bones']} bones, "
              f"{numbers['elements']} cubes, {numbers['faces']} faces, skin {numbers['atlas']}, {numbers['keyframes']} keyframes, {numbers['bytes'] // 1024} KB")
        for problem in problems:
            print(f"PROBLEM: {problem}")
        return problems


def _num(v):
    v = float(v)
    return int(v) if v == int(v) else v


def _free_name(name, taken):
    while name in taken:
        name += "_"
    return name


def _swapped(name):
    swap = {"right": "left", "left": "right", "r": "l", "l": "r"}
    out, count = re.subn(r"(?:(?<=_)|^)(right|left|r|l)(?=_|$)", lambda m: swap[m.group(1)], name)
    return out if count else name + "_mirror"


def _combine(channel, a, b):
    if channel == "scale":
        return lambda p: tuple(u * v for u, v in zip(a(p), b(p)))
    return lambda p: tuple(u + v for u, v in zip(a(p), b(p)))


# ---------------------------------------------------------------- timing

def _smooth(t):
    return t * t * (3 - 2 * t)


def _back_out(t, over=1.70158):
    t -= 1
    return 1 + t * t * ((over + 1) * t + over)


def _settle(t):
    # A spring let go: past the target, back, and still by the end.
    return 1 - math.exp(-5.5 * t) * math.cos(3.0 * math.pi * t) * (1 - t) ** 0.5


def _bounce(t):
    n, d = 7.5625, 2.75
    if t < 1 / d:
        return n * t * t
    if t < 2 / d:
        t -= 1.5 / d
        return n * t * t + 0.75
    if t < 2.5 / d:
        t -= 2.25 / d
        return n * t * t + 0.9375
    t -= 2.625 / d
    return n * t * t + 0.984375


EASES = {
    "linear": lambda t: t,
    "in": lambda t: t * t,
    "hard_in": lambda t: t * t * t,
    "out": lambda t: 1 - (1 - t) * (1 - t),
    "hard_out": lambda t: 1 - (1 - t) ** 3,
    "in_out": _smooth,
    "back": _back_out,
    "anticipate": lambda t: 1 - _back_out(1 - t),
    "settle": _settle,
    "bounce": _bounce,
}


def ease(kind, t):
    """A shaped 0 to 1, for t from 0 to 1: linear, in (starts slowly and arrives hard), hard_in, out (leaves hard and arrives
    gently), hard_out, in_out, back (goes past the end and returns), anticipate (backs up, then goes), settle (a spring
    coming to rest) or bounce. Or pass your own function of t."""
    fn = kind if callable(kind) else EASES.get(kind)
    if fn is None:
        raise ValueError(f"no ease called {kind!r}. There's {', '.join(EASES)}")
    return fn(min(max(t, 0.0), 1.0))


def beats(*stops):
    """A curve through values at chosen moments, which is the most direct way to shape timing: each stop is (phase, value)
    or (phase, value, ease), and the ease says how it gets there from the stop before, in_out if not given. Values can be
    numbers or (x, y, z). Holding is two stops with one value. Between loops, make the last stop's value the first's."""
    parsed = [(float(s[0]), np.asarray(s[1], float), s[2] if len(s) > 2 else "in_out") for s in stops]
    phases = [s[0] for s in parsed]
    if phases != sorted(phases):
        raise ValueError("beats have to go in order of phase")
    vector = parsed[0][1].ndim > 0

    def fn(p):
        i = bisect.bisect_right(phases, p)
        if i <= 0:
            value = parsed[0][1]
        elif i >= len(parsed):
            value = parsed[-1][1]
        else:
            a, b = parsed[i - 1], parsed[i]
            value = a[1] + (b[1] - a[1]) * ease(b[2], (p - a[0]) / max(b[0] - a[0], 1e-9))
        return tuple(float(v) for v in value) if vector else float(value)

    return fn


def snap(windup=0.25, hit=0.45, back=0.25, over=0.12, hold=0.1):
    """The timing of a blow, as an amount over the phase: back a little until windup, out hard to past the target by hit,
    settling onto it, holding a moment, and home by the end. Use it as timing= on strike, lunge and the like."""
    settle_at = hit + (1 - hit) * 0.2
    hold_to = min(settle_at + (1 - hit) * hold, 0.98)
    return beats((0, 0.0), (windup, -back, "in_out"), (hit, 1 + over, "in"), (settle_at, 1.0, "out"), (hold_to, 1.0, "linear"), (1, 0.0, "in_out"))


def _cycle_phase(p, cycles, phase, skew):
    """Where in a repeating cycle a phase falls. skew bends time without breaking the loop: positive makes the rise
    through zero quicker and the fall slower, negative the reverse, up to about 0.8."""
    u = (cycles * p + phase) % 1.0
    return u + skew * math.sin(2 * math.pi * u) / (2 * math.pi) if skew else u


def _wave_value(p, cycles, phase, skew=0.0):
    return math.sin(2 * math.pi * _cycle_phase(p, cycles, phase, skew))


def _on_axis(axis, amount):
    a = _axis(axis)
    return tuple(amount if i == a else 0.0 for i in range(3))


def _phased(parts, offset, phase=0.0):
    """Parts and their phases, from a dict of part to phase, or a list stepped along by offset."""
    if isinstance(parts, dict):
        return [(_name_of(k), v + phase) for k, v in parts.items()]
    return [(name, i * offset + phase) for i, name in enumerate(_names(parts))]


# ---------------------------------------------------------------- moving parts

def pose(parts, rotation=(0, 0, 0), position=(0, 0, 0)):
    """Hold parts away from rest for a whole animation: a lean into a walk, a raised tail."""
    rotation, position = tuple(float(v) for v in _vec(rotation)), tuple(float(v) for v in _vec(position))
    channels = {}
    if any(rotation):
        channels["rotation"] = lambda p: rotation
    if any(position):
        channels["position"] = lambda p: position
    return {name: dict(channels) for name in _names(parts)}


def swing(parts, degrees=30, axis="x", cycles=1, offset=0.5, center=0.0, phase=0.0, skew=0.0):
    """Limbs swinging to and fro around their pivots. Give any number of them, with each one offset in phase from the
    last (a half by default, so every other leg is opposite), or a dict of part to phase for a rhythm of your own. phase
    moves them all, and skew makes one way quicker than the other."""
    return {name: {"rotation": (lambda ph: lambda p: _on_axis(axis, center + degrees * _wave_value(p, cycles, ph, skew)))(ph)}
            for name, ph in _phased(parts, offset, phase)}


def flap(right, left, degrees=35, axis="z", cycles=1, lag=0.06, center=0.0, skew=-0.35):
    """Wings on each side beating in opposite directions, so both rise together. A list on each side is the wing's
    joints from shoulder to tip, and lag lets each joint follow the one before. By default the downstroke is quicker than
    the upstroke, since that's the one doing the work."""
    tracks = {}
    for side, sign in ((right, 1), (left, -1)):
        for i, name in enumerate(_names(side)):
            tracks[name] = {"rotation": (lambda s, ph: lambda p: _on_axis(axis, s * (center + degrees * _wave_value(p, cycles, ph, skew))))(sign, -i * lag)}
    return tracks


def wave(chain, degrees=15, axis="y", cycles=1, waves=1.0, grow=0.0, phase=0.0, skew=0.0):
    """A wave travelling down a chain of parts, from first to last, for tails, snakes and tentacles. waves is how many fit
    along the chain, and grow makes the last joint move that much more than the first (1.0 is twice as much). A negative
    number of degrees turns the other way, for a chain running the other way from where it's rooted."""
    names = _names(chain)
    n = max(len(names), 1)
    tracks = {}
    for i, name in enumerate(names):
        size = degrees * (1 + grow * i / max(n - 1, 1))
        tracks[name] = {"rotation": (lambda s, ph: lambda p: _on_axis(axis, s * _wave_value(p, cycles, ph, skew)))(size, phase - waves * i / n)}
    return tracks


def bob(parts, amount=0.5, axis="y", cycles=1, phase=0.0, bounce=False, skew=0.0):
    """Parts rising and falling by this many units. bounce makes it the hop of a step, always up from rest."""
    def fn(p):
        value = _wave_value(p, cycles, phase, skew)
        return _on_axis(axis, amount * (abs(value) if bounce else value))
    return {name: {"position": fn} for name in _names(parts)}


def breathe(parts, amount=0.03, cycles=1, phase=0.0, axes="xyz", skew=0.0):
    """Parts gently swelling and shrinking by this fraction."""
    on = [a in axes for a in "xyz"]

    def fn(p):
        v = 1 + amount * _wave_value(p, cycles, phase, skew)
        return tuple(v if flag else 1.0 for flag in on)

    return {name: {"scale": fn} for name in _names(parts)}


def _delayed(fn, delay):
    return (lambda p: fn(max(p - delay, 0.0))) if delay else fn


def move(parts, rotation=None, position=None, scale=None, timing=None, lag=0.0):
    """Parts going through a move: at an amount of 1 they're this far from rest, at 0 at rest, and timing says how much at
    each phase, from snap(), beats() or any function. In a list, lag starts each part that bit after the one before, which
    is what makes a body move as a whole rather than all at once: hips, then shoulders, then arm."""
    timing = timing or snap()
    tracks = {}
    for i, name in enumerate(_names(parts)):
        channels = {}
        if rotation is not None:
            turn = _vec(rotation)
            channels["rotation"] = _delayed((lambda v: lambda p: tuple(v * timing(p)))(turn), i * lag)
        if position is not None:
            shift = _vec(position)
            channels["position"] = _delayed((lambda v: lambda p: tuple(v * timing(p)))(shift), i * lag)
        if scale is not None:
            grow = _vec(scale)
            channels["scale"] = _delayed((lambda v: lambda p: tuple(1 + (v - 1) * timing(p)))(grow), i * lag)
        tracks[name] = channels
    return tracks


def keyed(parts, rotation=None, position=None, scale=None, lag=0.0):
    """Parts going through poses you choose. Each channel is a list of beats() stops with (x, y, z) values, such as
    rotation=[(0, (0, 0, 0)), (0.3, (25, 0, 0), "out"), (0.45, (-80, 0, 0), "hard_in"), (1, (0, 0, 0), "in_out")]."""
    tracks = {}
    for i, name in enumerate(_names(parts)):
        channels = {}
        for channel, stops in (("rotation", rotation), ("position", position), ("scale", scale)):
            if stops is not None:
                channels[channel] = _delayed(beats(*stops), i * lag)
        tracks[name] = channels
    return tracks


def lunge(parts, distance=(0, 0, -6), windup=0.25, hit=0.45, back=0.25, over=0.12, lag=0.0, timing=None):
    """Parts drawing back, then thrusting by this many units past the target and settling, and returning: a bite, a
    charge or a piston. back and over are the share to draw back and to overshoot."""
    return move(parts, position=distance, timing=timing or snap(windup, hit, back, over), lag=lag)


def strike(parts, degrees=(-70, 0, 0), windup=0.25, hit=0.45, back=0.25, over=0.12, lag=0.0, timing=None):
    """Parts drawing back, then swinging through this rotation past the target and settling, and returning: a claw, a tail
    or a hammer."""
    return move(parts, rotation=degrees, timing=timing or snap(windup, hit, back, over), lag=lag)


def spin(parts, axis="y", turns=1, timing=None):
    """Parts turning and looping, for gears and rotors. A dict of part to turns lets one gear drive another backwards.
    Turns have to be whole, or the loop jumps. timing bends the speed, as a function from 0 to 1 of the phase, for a wheel
    that lurches. A bone with its own rest rotation doesn't spin around its own axis, because BIL adds the rotations
    together, so put the rest rotation on an empty joint above it and spin the bone inside."""
    items = parts.items() if isinstance(parts, dict) else [(p, turns) for p in _names(parts)]
    timing = timing or (lambda p: p)
    return {_name_of(name): {"rotation": (lambda t: lambda p: _on_axis(axis, 360.0 * t * timing(p)))(t)} for name, t in items}


def _pulses(at, width, p, cycles=1):
    """A bump around each of these phases, reaching 1 quickly, falling away slowly, and wrapping around the loop."""
    u, total = (cycles * p) % 1.0, 0.0
    for a in at:
        d = (u - a + 0.5) % 1.0 - 0.5
        if -0.3 * width < d < width:
            total = max(total, _smooth((d + 0.3 * width) / (0.3 * width)) if d < 0 else (1 - _smooth(d / width)))
    return total


def squash(parts, amount=-0.15, at=None, width=0.2, timing=None, cycles=1, phase=0.0):
    """Squash and stretch, keeping the volume: taller means thinner. A negative amount squashes and a positive one
    stretches. Give the moments it happens as at=(phases), such as landings, or any timing function."""
    def fn(p):
        if timing is not None:
            k = timing(p)
        elif at is not None:
            k = _pulses(at, width, p, cycles)
        else:
            k = _wave_value(p, cycles, phase)
        y = 1 + amount * k
        side = 1 / math.sqrt(max(y, 0.05))
        return (side, y, side)

    return {name: {"scale": fn} for name in _names(parts)}


def hop(parts, height=4.0, cycles=1, air=0.5, squash=0.14, stretch=0.1, phase=0.0):
    """Hopping up from rest: crouch, stretch on take-off, a real arc through the air, stretch coming down, squash on landing.
    air is the share of each cycle off the ground."""
    shape = beats((0, stretch), (air * 0.5, 0.0), (air, stretch * 0.6), (air + (1 - air) * 0.25, -squash, "out"),
                  (air + (1 - air) * 0.6, -squash * 0.3), (air + (1 - air) * 0.85, -squash * 0.8), (1, stretch, "in"))

    def height_at(p):
        u = (cycles * p + phase) % 1.0
        return _on_axis("y", height * 4 * (u / air) * (1 - u / air) if u < air else 0.0)

    def scale_at(p):
        y = 1 + shape((cycles * p + phase) % 1.0)
        side = 1 / math.sqrt(max(y, 0.05))
        return (side, y, side)

    return {name: {"position": height_at, "scale": scale_at} for name in _names(parts)}


def flicker(parts, scale=0.0, rotation=0.0, position=0.0, rate=5, seed=0, axes="xyz"):
    """Restless, uneven motion instead of a smooth wave, for flames, a shudder or a nervous tremble. It's a few unrelated
    whole-number rhythms added up, so it still loops. rate is the quickest of them, in cycles per loop."""
    rng = np.random.default_rng([abs(int(seed)), 77])
    rhythms = [max(1, rate // 3), max(1, rate // 2) + 1, rate]
    phases = rng.random((3, 3))

    def noise(p, axis):
        return sum(math.sin(2 * math.pi * (r * p + phases[i][axis])) for i, r in enumerate(rhythms)) / 2.2

    on = [a in axes for a in "xyz"]
    channels = {}
    if scale:
        channels["scale"] = lambda p: tuple(1 + scale * noise(p, i) if on[i] else 1.0 for i in range(3))
    if rotation:
        channels["rotation"] = lambda p: tuple(rotation * noise(p, i) if on[i] else 0.0 for i in range(3))
    if position:
        channels["position"] = lambda p: tuple(position * noise(p, i) if on[i] else 0.0 for i in range(3))
    return {name: dict(channels) for name in _names(parts)}


def fade(track, out=0.2, into=0.0):
    """Any track, faded out over the last part of the phase and in over the first, so that something that doesn't end at rest
    by itself, such as a flicker in a one-shot, doesn't jump when the animation stops."""
    def envelope(p):
        k = 1.0
        if out and p > 1 - out:
            k = min(k, _smooth((1 - p) / out))
        if into and p < into:
            k = min(k, _smooth(p / into))
        return k

    faded = {}
    for name, channels in track.items():
        faded[name] = {}
        for channel, fn in channels.items():
            if channel == "scale":
                faded[name][channel] = (lambda f: lambda p: tuple(1 + (v - 1) * envelope(p) for v in f(p)))(fn)
            else:
                faded[name][channel] = (lambda f: lambda p: tuple(v * envelope(p) for v in f(p)))(fn)
    return faded


def glance(parts, *looks, speed=0.05):
    """A head looking around the way a head does: darting to each look, holding it, and home at the end, rather than
    drifting. Each look is (phase, yaw, pitch) in degrees, and speed is the share of the cycle a dart takes."""
    stops = [(0, (0.0, 0.0, 0.0))]
    for phase, yaw, pitch in looks:
        last = stops[-1][1]
        stops.append((max(phase - speed, stops[-1][0]), last, "linear"))
        stops.append((phase, (float(pitch), float(yaw), 0.0), "out"))
    stops.append((max(1 - speed * 1.5, stops[-1][0]), stops[-1][1], "linear"))
    stops.append((1, (0.0, 0.0, 0.0), "in_out"))
    fn = beats(*stops)
    return {name: {"rotation": fn} for name in _names(parts)}


def weight(parts, at=(0.0, 0.5), sides=None, drop=1.0, sway=0.0, roll=0.0, twist=0.0, nod=0.0, duty=0.6, cycles=1, lag=0.05):
    """A body carried by its feet. at is when each foot lands, as phases. drop is how far the body sinks just after each
    landing, sharply, before rising again. Given sides, a list of -1 for the creature's left and 1 for its right, one per
    foot, then sway shifts it toward whichever foot is down, roll tilts it over that foot in degrees, and twist turns the
    hips with the leg swinging forward. nod pitches it down at each landing."""
    at = list(at)
    width = min(0.5, 0.8 / max(len(at), 1))
    support = 0j
    forward = 0j
    if sides:
        for phase, side in zip(at, sides):
            support += side * cmath.exp(-2j * math.pi * (phase + duty / 2))
            forward += side * cmath.exp(-2j * math.pi * phase)
    shifted = [(a + lag) % 1.0 for a in at]

    def wave_of(p, c):
        return (c * cmath.exp(2j * math.pi * cycles * p)).real / abs(c) if abs(c) > 0.2 else 0.0

    def where(p):
        side = wave_of(p, support)
        return (sway * side, -drop * _pulses(shifted, width, p, cycles), 0.0)

    def turn(p):
        side = wave_of(p, support)
        return (nod * _pulses(shifted, width, p, cycles), twist * wave_of(p, forward), -roll * side)

    return {name: {"position": where, "rotation": turn} for name in _names(parts)}


def flinch(parts, move=(0, 0.6, 3), degrees=(12, 0, 0), hit=0.14, shake=2.0, lag=0.03):
    """A hurt: thrown back all at once, then shaken and recovering, so the first instant reads as the blow. move is in
    units and degrees the tilt, and the default goes up and backward, away from something in front. shake is how many
    times it wobbles on the way back. In a list, each part reacts just after the one before."""
    shift, turn = _vec(move), _vec(degrees)

    def k(p):
        if p < hit:
            return ease("hard_out", p / hit)
        s = (p - hit) / (1 - hit)
        return math.exp(-3.5 * s) * math.cos(2 * math.pi * shake * s) * (1 - s)

    tracks = {}
    for i, name in enumerate(_names(parts)):
        weaker = 1 / (1 + 0.15 * i)
        tracks[name] = {"position": _delayed((lambda w: lambda p: tuple(shift * k(p) * w))(weaker), i * lag),
                        "rotation": _delayed((lambda w: lambda p: tuple(turn * k(p) * w))(1.0), i * lag)}
    return tracks


# ---------------------------------------------------------------- motion worked out from the model

class _Rig:
    """One animation being worked out: its tracks so far, and the bones' positions over the cycle under them."""

    def __init__(self, model, ticks, loop, tracks):
        self.model, self.ticks, self.loop, self.tracks = model, ticks, loop, tracks
        self.seconds = ticks * bbmodel.TICK
        self.count = max(ticks * 3, 48) // ticks * ticks
        self.phases = np.arange(self.count) / self.count if loop == "loop" else np.linspace(0, 1, self.count + 1)
        self.cache = {}

    def add(self, tracks):
        for name, channels in tracks.items():
            name = _name_of(name)
            slot = self.tracks.setdefault(name, {})
            for channel, fn in channels.items():
                slot[channel] = _combine(channel, slot[channel], fn) if channel in slot else fn
        self.cache.clear()

    def table(self, name, channel, values):
        """Add a channel worked out for every one of this rig's phases."""
        values = np.asarray(values, float)
        count, looped = self.count, self.loop == "loop"

        def fn(p):
            at = (p % 1.0 if looped else min(max(p, 0.0), 1.0)) * count
            i = int(at)
            f = at - i
            a = values[i % len(values)]
            b = values[(i + 1) % len(values)] if looped else values[min(i + 1, len(values) - 1)]
            return tuple(float(v) for v in a + (b - a) * f)

        self.add({name: {channel: fn}})

    def own(self, name):
        """A bone's own rotation, position and scale over the cycle, from its tracks and its rest pose."""
        part = self.model.parts[name]
        channels = self.tracks.get(name, {})
        n = len(self.phases)

        def series(channel, rest):
            fn = channels.get(channel)
            return np.array([fn(float(p)) for p in self.phases], float) if fn else np.full((n, 3), rest, float)

        return series("rotation", 0.0) + np.array(part.rotation), series("position", 0.0), series("scale", 1.0)

    def local(self, name):
        part = self.model.parts[name]
        rot, pos, scl = self.own(name)
        above = self.model.parts.get(part.parent)
        origin = np.array(part.pivot) - (np.array(above.pivot) if above else 0)
        return bbmodel._matrices(rot, pos + origin, scl)

    def world(self, name):
        """A bone's matrix over the cycle, which takes pivot-relative points to the model's."""
        if name not in self.cache:
            part = self.model.parts[name]
            local = self.local(name)
            self.cache[name] = self.world(part.parent) @ local if part.parent else local
        return self.cache[name]

    def carrier(self, name):
        """The matrix over the cycle of the joint a bone hangs from: everything above it, but none of its own motion."""
        part = self.model.parts[name]
        n = len(self.phases)
        above = self.model.parts.get(part.parent)
        origin = np.array(part.pivot) - (np.array(above.pivot) if above else 0)
        fixed = bbmodel._matrices(np.tile(np.array(part.rotation), (n, 1)), np.tile(origin, (n, 1)), np.ones((n, 3)))
        return self.world(part.parent) @ fixed if part.parent else fixed


class _Later:
    """A track that has to be worked out from the model and the rest of its animation, when the model is built. Lower
    orders go first, so that legs can plant themselves under a body that has already moved, and tails can follow both."""
    order = 1

    def names(self):
        return []

    def work_out(self, rig):
        raise NotImplementedError


def _rotations_to(a, b, limit=None):
    """The least rotation taking directions a to directions b, as (n, 3, 3). With a limit in radians, it eases off and goes
    no further than that."""
    a = a / np.maximum(np.linalg.norm(a, axis=-1, keepdims=True), 1e-9)
    b = b / np.maximum(np.linalg.norm(b, axis=-1, keepdims=True), 1e-9)
    v = np.cross(a, b)
    c = np.clip((a * b).sum(axis=-1), -0.999999, 1.0)
    s = np.linalg.norm(v, axis=-1)
    unit = v / np.maximum(s[..., None], 1e-9)
    angle = np.arctan2(s, c)
    if limit is not None:
        angle = limit * np.tanh(angle / limit)
    k = np.zeros(v.shape[:-1] + (3, 3))
    k[..., 0, 1], k[..., 0, 2], k[..., 1, 0], k[..., 1, 2], k[..., 2, 0], k[..., 2, 1] = -unit[..., 2], unit[..., 1], unit[..., 2], -unit[..., 0], -unit[..., 1], unit[..., 0]
    return np.eye(3) + np.sin(angle)[..., None, None] * k + (1 - np.cos(angle))[..., None, None] * (k @ k)


def _euler(r):
    """Degrees that make these rotations in BIL's Z * Y * X order, unwrapped so that they run on smoothly."""
    x = np.arctan2(r[..., 2, 1], r[..., 2, 2])
    y = np.arctan2(-r[..., 2, 0], np.hypot(r[..., 0, 0], r[..., 1, 0]))
    z = np.arctan2(r[..., 1, 0], r[..., 0, 0])
    return np.degrees(np.unwrap(np.stack([x, y, z], axis=-1), axis=0))


def _sole(part):
    """The bottom of a part, relative to its pivot: the points that could touch the ground, and the one that takes the
    weight, which is the middle of the very lowest layer."""
    idx = np.argwhere(part.solid_grid)
    low = idx[:, 1].min()
    near = (idx[idx[:, 1] <= low + 1] + part.lo + np.array((0.5, 0.0, 0.5))) * part.grain
    lowest = (idx[idx[:, 1] == low] + part.lo + np.array((0.5, 0.0, 0.5))) * part.grain
    return near - np.array(part.pivot), lowest.mean(axis=0) - np.array(part.pivot)


def _gait_phases(legs, pattern):
    """When each foot lands, from where the feet are. Sides alternate. In a walk the landings run evenly from the back of
    one side to its front and then the other side, which holds up any number of legs. In a trot, every other foot along
    a side lands together with its opposite neighbour, as a trotting horse or a running ant does."""
    if isinstance(pattern, dict):
        return [pattern.get(leg["name"], 0.0) for leg in legs]
    left = sorted((leg for leg in legs if leg["x"] < 0), key=lambda leg: -leg["z"])
    right = sorted((leg for leg in legs if leg["x"] >= 0), key=lambda leg: -leg["z"])
    phases = {}
    if pattern == "walk":
        for k, leg in enumerate(left + right):
            phases[leg["name"]] = k / len(legs)
    elif pattern == "trot":
        for side, group in enumerate((left, right)):
            for k, leg in enumerate(sorted(group, key=lambda leg: leg["z"])):
                phases[leg["name"]] = ((k + side) % 2) / 2
    elif pattern == "bound":
        middle = sum(leg["z"] for leg in legs) / len(legs)
        for leg in legs:
            phases[leg["name"]] = (0.0 if leg["z"] < middle else 0.5) + (0.04 if leg["x"] >= 0 else 0.0)
    else:
        raise ValueError(f"pattern must be walk, trot, bound or a dict of part to phase, not {pattern!r}")
    return [phases[leg["name"]] for leg in legs]


class _Gait(_Later):
    order = 1

    def __init__(self, legs, stride, lift, duty, pattern, cycles, knee, heading, body, drop, sway, roll, twist, nod, crouch, shoulders, arms, arm_swing, peel, tilt, level):
        self.tilt, self.level = tilt, level
        self.legs =[[_name_of(p) for p in (leg if isinstance(leg, (list, tuple)) else [leg])] for leg in legs]
        self.stride, self.lift, self.duty, self.pattern, self.cycles = stride, lift, duty, pattern, cycles
        self.knee, self.heading = knee, np.array(heading, float) / max(np.linalg.norm(heading), 1e-9)
        self.body, self.drop, self.sway, self.roll, self.twist, self.nod = _name_of(body) if body is not None else None, drop, sway, roll, twist, nod
        self.crouch, self.shoulders, self.arms, self.arm_swing, self.peel = crouch, shoulders, arms, arm_swing, peel

    def names(self):
        found = [p for leg in self.legs for p in leg]
        return found + ([self.body] if self.body else [])

    def feet(self):
        return [leg[-1] for leg in self.legs]

    def work_out(self, rig):
        model = rig.model
        legs = [self._describe(rig, chain) for chain in self.legs]
        if self.duty is None:
            self.duty = {"walk": 0.65, "trot": 0.52, "bound": 0.4}.get(self.pattern, 0.6) if not isinstance(self.pattern, dict) else 0.6
        phases = _gait_phases(legs, self.pattern)
        sides = [1 if leg["x"] >= 0 else -1 for leg in legs]
        if self.body:
            length = float(np.mean([leg["height"] for leg in legs]))
            stride = self.stride
            amounts = dict(drop=0.1 * stride if self.drop is None else self.drop, sway=0.08 * stride if self.sway is None else self.sway,
                           roll=2.0 if self.roll is None else self.roll, twist=0.0 if self.twist is None else self.twist, nod=0.0 if self.nod is None else self.nod)
            rig.add(weight(self.body, at=phases, sides=sides, duty=self.duty, cycles=self.cycles, **amounts))
            if self.crouch:
                rig.add(pose(self.body, position=(0, -self.crouch * length, 0)))
            if self.shoulders:
                forward = sum(side * cmath.exp(-2j * math.pi * phase) for side, phase in zip(sides, phases))
                if abs(forward) > 0.2:
                    size = 1.8 * (amounts["twist"] or 3.0)
                    rig.add({_name_of(self.shoulders): {"rotation": lambda p: (0.0, -size * (forward * cmath.exp(2j * math.pi * self.cycles * p)).real / abs(forward), 0.0)}})
        if self.arms:
            arms = _names(self.arms)
            for arm in arms:
                x = model.parts[arm].pivot[0]
                opposite = [ph for ph, leg in zip(phases, legs) if (leg["x"] >= 0) != (x >= 0)] or phases
                # At its peak a swing is at a quarter of its cycle, and a hanging limb goes forward as X rotation grows.
                rig.add(swing({arm: 0.25 - opposite[0]}, self.arm_swing, cycles=self.cycles))
        for leg, phase in zip(legs, phases):
            self._solve(rig, leg, phase)

    def _describe(self, rig, chain):
        model = rig.model
        parts = [model.parts[n] for n in chain]
        last = parts[-1]
        if last.solid_grid is None or not last.solid_grid.any():
            raise ValueError(f"gait: {last.name!r} is the end of a leg, and it has no voxels to stand on")
        sole, center = _sole(last)
        rest = rig.model._rest_world(last.name)
        world_sole = (rest[:3, :3] @ center) + rest[:3, 3]
        hip = model._rest_world(parts[0].name)[:3, 3]
        floor = float((sole @ rest[:3, :3].T + rest[:3, 3])[:, 1].min())
        return {"name": chain[0], "parts": parts, "sole": sole, "center": center, "ground": world_sole.copy(), "floor": floor, "x": float(world_sole[0]),
                "z": float(world_sole[2]), "height": float(np.linalg.norm(hip - world_sole))}

    def _targets(self, rig, leg, phase):
        """Where the foot should be, in the model's frame, at each moment of the cycle: going back in a straight line at a
        steady speed while it's down, and forward through an arc while it's up."""
        n = len(rig.phases)
        out = np.tile(leg["ground"], (n, 1))
        swinging = np.zeros(n)
        for k, p in enumerate(rig.phases):
            u = (self.cycles * p - phase) % 1.0
            if u < self.duty:
                travel = -0.5 + u / self.duty
                up = 0.0
            else:
                s = (u - self.duty) / (1 - self.duty)
                travel = 0.5 - _smooth(s)
                up = self.lift * math.sin(math.pi * s ** 0.8) ** 1.2
                swinging[k] = math.sin(math.pi * s)
            # A foot on the ground goes the opposite way to the creature, and travel runs from ahead to behind.
            out[k, 0] += travel * self.stride * -self.heading[0]
            out[k, 2] += travel * self.stride * -self.heading[1]
            out[k, 1] += up
        return out, swinging

    def _solve(self, rig, leg, phase):
        parts = leg["parts"]
        target, swinging = self._targets(rig, leg, phase)
        carrier = rig.carrier(parts[0].name)
        rest1 = bbmodel._mat(*parts[0].rotation)[:3, :3]
        # The carrier includes the bone's own rest rotation, so take that off to work in the frame its parent gives.
        frame = carrier.copy()
        frame[:, :3, :3] = carrier[:, :3, :3] @ rest1.T
        inverse = np.linalg.inv(frame)
        local = (inverse[:, :3, :3] @ target[..., None])[..., 0] + inverse[:, :3, 3]
        if len(parts) == 1 or (len(parts) == 2 and self.level):
            grounded = target.copy()
            grounded[:, 1] = leg["ground"][1]
            flat = (inverse[:, :3, :3] @ grounded[..., None])[..., 0] + inverse[:, :3, 3]
            self._solve_one(rig, leg, parts, local, flat, frame, rest1, swinging)
        else:
            self._solve_two(rig, leg, parts, local, frame, rest1, swinging)

    def _keep_level(self, rig, foot, above, swinging, flat):
        """Turn a foot so it stays as level as it is at rest, whatever the leg above is doing, and points its toe down while
        it's in the air."""
        level = np.linalg.inv(above) @ rig.model._rest_world(foot.name)[:3, :3]
        toe = bbmodel._matrices(np.stack([self.peel * swinging, swinging * 0, swinging * 0], axis=1), np.zeros((len(swinging), 3)), np.ones((len(swinging), 3)))[:, :3, :3]
        rig.table(foot.name, "rotation", _euler(level @ toe) - _euler(flat))

    def _solve_one(self, rig, leg, parts, local, flat, frame, rest, swinging):
        part = parts[0]
        if len(parts) == 2:
            # A rigid leg on a separate foot: it reaches for the ankle rather than the sole.
            reach = np.array(parts[1].pivot) - np.array(part.pivot)
            local, flat = local - leg["center"], flat - leg["center"]
        else:
            reach = leg["center"]
        # It leans toward where the foot goes along the ground, as far as a leg that short can without looking wrong, and
        # the rest of the way, including the lift, it moves bodily.
        turned = _rotations_to(np.tile(rest @ reach, (len(local), 1)), flat, math.radians(self.tilt))
        total = turned @ rest
        shift = local - total @ reach
        if len(parts) == 2:
            flat_at_rest = np.linalg.inv(rig.model._rest_world(part.name)[:3, :3]) @ rig.model._rest_world(parts[1].name)[:3, :3]
            self._keep_level(rig, parts[1], frame[:, :3, :3] @ total, swinging, flat_at_rest[None, ...])
        else:
            # A rigid foot tilts as the leg swings, so lift it by however far its lowest corner would dip below the ground.
            points = np.einsum("nij,sj->nsi", frame[:, :3, :3] @ total, leg["sole"]) + (frame[:, :3, :3] @ shift[..., None])[:, None, :, 0] + frame[:, None, :3, 3]
            dip = np.maximum(leg["floor"] - points[..., 1].min(axis=1), 0.0)
            shift = shift + (np.linalg.inv(frame[:, :3, :3]) @ np.array((0.0, 1.0, 0.0))) * dip[:, None]
        rig.table(part.name, "rotation", _euler(total) - np.array(part.rotation))
        rig.table(part.name, "position", shift)

    def _pole(self, leg, parts):
        """Which way the knee points: as modelled if it's modelled bent, and otherwise as asked."""
        knee = np.array(parts[1].pivot) - np.array(parts[0].pivot)
        foot = (np.array(parts[-1].pivot) + leg["center"]) - np.array(parts[0].pivot)
        unit = foot / max(np.linalg.norm(foot), 1e-9)
        bent = knee - (knee @ unit) * unit
        if self.knee is None and np.linalg.norm(bent) > 0.75:
            return bent / np.linalg.norm(bent)
        named = {None: (0, 0, -1), "front": (0, 0, -1), "back": (0, 0, 1), "out": (np.sign(leg["x"]) or 1, 0, 0), "up": (0, 1, 0)}
        return np.array(named[self.knee] if self.knee in named else self.knee, float)

    def _solve_two(self, rig, leg, parts, local, frame, rest1, swinging):
        upper, lower = parts[0], parts[1]
        foot_part = parts[2] if len(parts) > 2 else None
        rest2 = bbmodel._mat(*lower.rotation)[:3, :3]
        v1 = np.array(lower.pivot) - np.array(upper.pivot)
        end = (np.array(foot_part.pivot) if foot_part else np.array(lower.pivot) + leg["center"])
        v2 = end - np.array(lower.pivot)
        pole = self._pole(leg, parts)
        # With a separate foot part, the leg reaches for the ankle, which stays this far above the sole.
        offset = (np.array(foot_part.pivot) - (np.array(foot_part.pivot) + leg["center"])) if foot_part else np.zeros(3)
        wanted = local + offset
        up = np.linalg.inv(frame[:, :3, :3]) @ np.array((0.0, 1.0, 0.0))
        cap = 0.3 * (np.linalg.norm(v1) + np.linalg.norm(v2))
        lift = np.zeros(len(wanted))
        for _ in range(4):
            total1, total2 = self._two_bone(wanted + up * lift[:, None], v1, v2, rest1, rest2, pole)
            if foot_part:
                break
            # A shin carrying its own foot tilts it as it swings, so the foot rocks: reach a little higher by however far
            # the sole would dip, working it out again each time because reaching higher changes the tilt.
            knee = total1 @ v1
            turn = frame[:, :3, :3] @ total1 @ total2
            points = np.einsum("nij,sj->nsi", turn, leg["sole"]) + ((frame[:, :3, :3] @ knee[..., None])[..., 0] + frame[:, :3, 3])[:, None, :]
            dip = leg["floor"] - points[..., 1].min(axis=1)
            if np.abs(np.clip(lift + dip, 0.0, cap) - lift).max() < 0.02:
                break
            lift = np.clip(lift + dip, 0.0, cap)
        # Measured from what the solver makes of the leg at rest, so that a leg modelled nearly straight, or bent some other
        # way than the knee is asked to bend, is exactly at rest when its foot is.
        at_rest = rig.model._rest_world(upper.name).copy()
        at_rest[:3, :3] = at_rest[:3, :3] @ rest1.T
        home = (np.linalg.inv(at_rest) @ np.append(leg["ground"], 1.0))[:3] + offset
        zero1, zero2 = self._two_bone(home[None, :], v1, v2, rest1, rest2, pole)
        rig.table(upper.name, "rotation", _euler(total1) - _euler(zero1))
        rig.table(lower.name, "rotation", _euler(total2) - _euler(zero2))
        if foot_part:
            flat = np.linalg.inv(at_rest[:3, :3] @ zero1 @ zero2) @ rig.model._rest_world(foot_part.name)[:3, :3]
            self._keep_level(rig, foot_part, frame[:, :3, :3] @ total1 @ total2, swinging, flat)

    def _two_bone(self, wanted, v1, v2, rest1, rest2, pole):
        l1, l2 = float(np.linalg.norm(v1)), float(np.linalg.norm(v2))
        dist = np.linalg.norm(wanted, axis=1)
        reach = np.clip(dist, abs(l1 - l2) + 0.01, (l1 + l2) * 0.9995)
        unit = wanted / np.maximum(dist[:, None], 1e-9)
        along = (l1 * l1 - l2 * l2 + reach * reach) / (2 * reach)
        out = np.sqrt(np.maximum(l1 * l1 - along * along, 0.0))
        side = pole - (unit @ pole)[:, None] * unit
        side /= np.maximum(np.linalg.norm(side, axis=1, keepdims=True), 1e-6)
        knee = unit * along[:, None] + side * out[:, None]
        foot = unit * reach[:, None]
        n = len(wanted)
        total1 = _rotations_to(np.tile(rest1 @ v1, (n, 1)), knee) @ rest1
        inner = (np.linalg.inv(total1) @ (foot - knee)[..., None])[..., 0]
        total2 = _rotations_to(np.tile(rest2 @ v2, (n, 1)), inner) @ rest2
        return total1, total2


def plant(legs, knee=None, peel=0.0, tilt=35.0, level=False):
    """Feet that stay exactly where they are on the ground while the body above them moves, for a crouch, a lunge, a blow
    or a flinch. It solves the legs the way gait() does, so a body that dips really does bend its knees."""
    return _Gait(legs, 0.0, 0.0, 1.0, "walk", 1, knee, (0, -1), None, None, None, None, None, None, 0.0, None, None, 0.0, peel, tilt, level)


def gait(legs, stride=6.0, lift=2.5, duty=None, pattern="walk", cycles=1, knee=None, heading=(0, -1), body=None, drop=None, sway=None, roll=None,
         twist=None, nod=None, crouch=0.0, shoulders=None, arms=None, arm_swing=18.0, peel=20.0, tilt=35.0, level=False):
    """Walking on any number of legs in any arrangement. Feet land in an order worked out from where they are, plant on
    the ground, go back at a steady speed under a body that moves over them, then lift and swing through. It solves
    each leg so that its foot really is there, whatever the body is doing.

    legs is a list of parts, and a leg in several parts is a list of its own, from the hip: ["thigh_r", "shin_r"] bends
    at the knee, and ["thigh_r", "shin_r", "foot_r"] also keeps the foot level. level=True says a two-part leg is a rigid
    leg on a separate foot instead, which suits stubby legs too short to bend well. A rigid one-part leg leans by up to tilt
    degrees and otherwise moves bodily, sliding in its socket, to stay on the ground.

    stride is how far a foot travels while it's down, in units. lift is how high it goes. duty is the share of the cycle a
    foot spends down, and higher is slower and heavier. pattern is walk (one foot at a time, in order), trot (every other
    foot together: a running biped, a horse's trot, an ant's tripod), bound (front pair then back pair), or a dict of
    part to phase. heading is the (x, z) direction of travel, so (1, 0) walks a crab sideways. knee is front, back, out, up
    or a direction, and a leg modelled bent already knows.

    body takes the weight: it's the part that sinks at each landing, by drop, and shifts over the foot that's down, by
    sway and roll. crouch lowers it for the whole walk, as a share of the legs' length, and gives straight legs room to
    bend. twist turns the hips, and shoulders names a part that turns the other way. arms swing against the opposite leg
    by arm_swing degrees. The first foot on the left lands at phase 0."""
    return _Gait(legs, stride, lift, duty, pattern, cycles, knee, heading, body, drop, sway, roll, twist, nod, crouch, shoulders, arms, arm_swing, peel, tilt, level)


class _Follow(_Later):
    order = 3

    def __init__(self, chain, stiffness, damping, amount, axes, limit):
        self.chain = _names(chain)
        self.stiffness, self.damping, self.amount, self.axes, self.limit = stiffness, damping, amount, axes, limit

    def names(self):
        return self.chain

    def work_out(self, rig):
        for i, name in enumerate(self.chain):
            self._link(rig, name, self.stiffness / (1 + 0.15 * i))

    def _lever(self, rig, name):
        """From a bone's pivot to the middle of everything it carries, in its own unposed frame."""
        part = rig.model.parts[name]
        points = []
        stack = [part]
        while stack:
            p = stack.pop()
            if p.solid_grid is not None and p.solid_grid.any():
                points.append(_voxel_centers(p))
            stack += [c for c in rig.model.parts.values() if c.parent == p.name]
        if not points:
            return np.array((0.0, -part.grain * 2.0, 0.0))
        return np.vstack(points).mean(axis=0) - np.array(part.pivot)

    def _link(self, rig, name, stiffness):
        carrier = rig.carrier(name)
        n = len(rig.phases)
        dt = rig.seconds / rig.count
        rotation, joint = carrier[:, :3, :3].copy(), carrier[:, :3, 3]
        rotation /= np.maximum(np.linalg.norm(rotation, axis=1, keepdims=True), 1e-9)
        lever = self._lever(rig, name)
        length = max(float(np.linalg.norm(lever)), 1.0)
        looped = rig.loop == "loop"
        if looped:
            speed = (np.roll(joint, -1, axis=0) - joint) / dt
            accel = (speed - np.roll(speed, 1, axis=0)) / dt
            delta = rotation.swapaxes(1, 2) @ np.roll(rotation, -1, axis=0)
            spin_rate = _vee(delta) / dt
            spin_accel = (spin_rate - np.roll(spin_rate, 1, axis=0)) / dt
        else:
            speed = np.gradient(joint, dt, axis=0)
            accel = np.gradient(speed, dt, axis=0)
            delta = rotation[:-1].swapaxes(1, 2) @ rotation[1:]
            spin_rate = np.vstack([_vee(delta) / dt, np.zeros((1, 3))])
            spin_accel = np.gradient(spin_rate, dt, axis=0)
        # Standing on the carrier, the joint's acceleration feels like a push the other way on whatever hangs from it.
        felt = (rotation.swapaxes(1, 2) @ -accel[..., None])[..., 0]
        drive = np.cross(lever, felt) / (length * length) - spin_accel
        axes = self.axes
        if axes is None:
            axes = [i for i in range(3) if abs(lever[i]) < 0.8 * length]
        else:
            axes = [_axis(a) for a in axes]
        w0 = 2 * math.pi * stiffness
        z = self.damping
        angles = np.zeros((n, 3))
        for axis in axes:
            if looped:
                spectrum = np.fft.rfft(drive[:, axis])
                w = 2 * math.pi * np.fft.rfftfreq(n, dt)
                response = spectrum / (w0 * w0 - w * w + 2j * z * w0 * w)
                response[0] = 0.0
                angles[:, axis] = np.fft.irfft(response, n)
            else:
                angle, rate = 0.0, 0.0
                substeps = max(1, int(math.ceil(dt * w0 / 0.5)))
                h = dt / substeps
                for k in range(n):
                    for _ in range(substeps):
                        rate += h * (drive[k, axis] - w0 * w0 * angle - 2 * z * w0 * rate)
                        angle += h * rate
                    angles[k, axis] = angle
        degrees = np.degrees(angles) * self.amount
        if not looped:
            # It has to end somewhere still, whatever it was doing, or the model would jump as the animation stops.
            fade = np.minimum(1.0, (1 - rig.phases) / 0.15)
            degrees = degrees * fade[:, None]
        degrees = self.limit * np.tanh(degrees / self.limit)
        rig.table(name, "rotation", degrees)


def _vee(delta):
    """The small rotation in each of these rotation matrices, as a vector in radians."""
    return np.stack([delta[..., 2, 1] - delta[..., 1, 2], delta[..., 0, 2] - delta[..., 2, 0], delta[..., 1, 0] - delta[..., 0, 1]], axis=-1) / 2


def follow(chain, stiffness=2.0, damping=0.3, amount=1.0, axes=None, limit=45.0):
    """Follow-through: parts that lag behind what carries them, swing on after it stops, and settle, because they have
    weight. Each one behaves as a damped spring driven by how the part above it actually moves in this animation, so it
    goes for tails, ears, antennae, wings, tentacles and hair alike, and a chain passes the motion down, later
    and further each time. Give a list from the root outward.

    stiffness is how fast it swings back in cycles a second: low is heavy and floppy, high is short and springy. damping
    of 0.1 keeps wobbling, and 0.7 barely overshoots. amount scales the swing, and limit keeps it within this many degrees.
    A still carrier moves nothing, so give the body some motion for it to answer."""
    return _Follow(chain, stiffness, damping, amount, axes, limit)


class _Steady(_Later):
    order = 2

    def __init__(self, parts, amount, level):
        self.parts, self.amount, self.level = _names(parts), amount, level

    def names(self):
        return self.parts

    def work_out(self, rig):
        for name in self.parts:
            carrier = rig.carrier(name)
            rotation = carrier[:, :3, :3].copy()
            rotation /= np.maximum(np.linalg.norm(rotation, axis=1, keepdims=True), 1e-9)
            usual = rig.model._rest_world(name)[:3, :3]
            # How far the carrier has turned from how it sits at rest, seen from the bone.
            euler = _euler(usual.T @ rotation)
            if rig.loop == "loop":
                euler = euler - euler.mean(axis=0)
            rig.table(name, "rotation", -self.amount * euler)
            if self.level:
                away = carrier[:, :3, 3] - rig.model._rest_world(name)[:3, 3]
                if rig.loop == "loop":
                    away = away - away.mean(axis=0)
                own = bbmodel._mat(*rig.model.parts[name].rotation)[:3, :3]
                parent = np.linalg.inv(rotation @ own.T)
                rig.table(name, "position", -self.level * (parent @ away[..., None])[..., 0])


def steady(parts, amount=0.7, level=0.4):
    """A head that stays steadier than the body under it, as heads do, because a creature keeps its eyes on things. It takes
    out this share of the turning of whatever carries it, and level is the share of its movement to take out."""
    return _Steady(parts, amount, level)


class _Collapse(_Later):
    order = 4

    def __init__(self, root, direction, degrees, limbs, fall, stagger, bounce, ground, slide):
        self.root, self.direction, self.degrees, self.limbs = _name_of(root), direction, degrees, limbs or {}
        self.fall, self.stagger, self.bounce, self.ground, self.slide = fall, stagger, bounce, ground, slide

    def names(self):
        return [self.root] + [_name_of(k) for k in self.limbs]

    def timing(self):
        f = self.fall
        s = self.stagger
        return beats((0, 0.0), (f * 0.25, -s, "out"), (f * 0.45, s * 0.5, "in_out"), (f, 1.0, "hard_in"), (f + (1 - f) * 0.14, 1 - self.bounce, "out"),
                     (f + (1 - f) * 0.3, 1.0, "in"), (f + (1 - f) * 0.4, 1 - self.bounce * 0.25, "out"), (f + (1 - f) * 0.5, 1.0, "in"), (1, 1.0, "linear"))

    def work_out(self, rig):
        axis, sign = {"forward": (0, -1), "back": (0, 1), "left": (2, 1), "right": (2, -1)}[self.direction]
        turn = np.zeros(3)
        turn[axis] = sign * self.degrees
        k = self.timing()
        rig.add({self.root: {"rotation": lambda p: tuple(turn * k(p))}})
        f = self.fall
        for limb, target in self.limbs.items():
            final = _vec(target)
            limp = beats((0, 0.0), (f * 0.9, 0.35, "in"), (f + (1 - f) * 0.12, 1.15, "hard_in"), (f + (1 - f) * 0.3, 0.95, "out"), (f + (1 - f) * 0.45, 1.0, "in_out"), (1, 1.0, "linear"))
            rig.add({limb: {"rotation": (lambda v: lambda p: tuple(v * limp(p)))(final)}})
        pivot = np.array(rig.model.parts[self.root].pivot)
        height = float(pivot[1])
        along = np.zeros(3)
        # As it tips over, a body comes down in the direction it falls, rather than turning around its own middle.
        if self.direction in ("forward", "back"):
            along[2] = -1 if self.direction == "forward" else 1
        else:
            along[0] = -1 if self.direction == "left" else 1
        rig.add({self.root: {"position": lambda p: tuple(along * self.slide * height * math.sin(math.radians(self.degrees) * min(max(k(p), 0.0), 1.0)))}})
        if self.ground:
            self._keep_on_floor(rig)

    def _keep_on_floor(self, rig):
        """Lift or lower the whole body so that its lowest point stays on the floor through the fall."""
        lowest = np.full(len(rig.phases), np.inf)
        for part in rig.model.parts.values():
            if part.solid_grid is None or not part.solid_grid.any():
                continue
            points = _voxel_centers(part) - np.array(part.pivot)
            if len(points) > 1500:
                points = points[np.linspace(0, len(points) - 1, 1500).astype(int)]
            world = rig.world(part.name)
            ys = (world[:, 1:2, :3] @ points.T)[:, 0, :] + world[:, 1:2, 3]
            # A voxel's corner is this much further from its centre than anything else on it.
            lowest = np.minimum(lowest, ys.min(axis=1) - part.grain * 0.87)
        start = lowest[0]
        rig.table(self.root, "position", np.stack([np.zeros_like(lowest), start - lowest, np.zeros_like(lowest)], axis=1))


def collapse(root, direction="forward", degrees=85.0, limbs=None, fall=0.55, stagger=0.06, bounce=0.1, ground=True, slide=0.5):
    """Dying: a stagger, the body going over faster and faster, hitting the ground with a small rebound, and lying still.
    root is the part everything hangs from, direction is forward, back, left or right, and degrees is how far over it ends.
    limbs maps parts to the rotation they end at, and they go slack late and flop on impact. The lowest point stays
    on the floor the whole way. fall is the phase of the impact. Play it with loop="hold", so that it stays down."""
    return _Collapse(root, direction, degrees, limbs, fall, stagger, bounce, ground, slide)


# ---------------------------------------------------------------- checks and numbers

def _rest_transforms(model):
    """Each part's rest matrix, which takes pivot-relative coordinates to the model's."""
    doc = model.build()
    posed = bbmodel._pose(doc)
    by_name = {g["name"]: g["uuid"] for g in doc["groups"]}
    return {name: posed[uuid_] for name, uuid_ in by_name.items()}


def _voxel_centers(part, mask=None):
    idx = np.argwhere(part.solid_grid if mask is None else mask)
    return (idx + part.lo + 0.5) * part.grain


def _posed_centers(part, transforms):
    p = _voxel_centers(part)
    m = transforms[part.name]
    return (p - np.array(part.pivot)) @ m[:3, :3].T + m[:3, 3]


def _components(mask):
    """Connected groups of voxels, counting corners as touching, largest first, as index arrays. Dilating from a seed is
    fine at this size, and it needs no extra library."""
    out = []
    left = mask.copy()
    while left.any():
        seed = np.unravel_index(int(np.argmax(left)), left.shape)
        grown = np.zeros(left.shape, bool)
        grown[seed] = True
        while True:
            wider = grown.copy()
            for axis in range(3):
                wider[tuple(slice(1, None) if i == axis else slice(None) for i in range(3))] |= wider[tuple(slice(None, -1) if i == axis else slice(None) for i in range(3))]
                wider[tuple(slice(None, -1) if i == axis else slice(None) for i in range(3))] |= wider[tuple(slice(1, None) if i == axis else slice(None) for i in range(3))]
            wider &= left
            if wider.sum() == grown.sum():
                break
            grown = wider
        out.append(np.argwhere(grown))
        left &= ~grown
    return sorted(out, key=len, reverse=True)


def _touches(part, other, transforms):
    """Whether any of part's voxels, as posed at rest, comes within a voxel of other's."""
    m = transforms[other.name]
    world = _posed_centers(part, transforms)
    # Back into the other part's unposed space, where its voxel grid lives.
    local = (world - m[:3, 3]) @ m[:3, :3] + np.array(other.pivot)
    near = np.floor(local / other.grain).astype(int) - other.lo
    grid = other.solid_grid
    wide = grid.copy()
    for axis in range(3):
        wide[tuple(slice(1, None) if i == axis else slice(None) for i in range(3))] |= wide[tuple(slice(None, -1) if i == axis else slice(None) for i in range(3))]
        wide[tuple(slice(None, -1) if i == axis else slice(None) for i in range(3))] |= wide[tuple(slice(1, None) if i == axis else slice(None) for i in range(3))]
    ok =((near >= 0) & (near < np.array(grid.shape))).all(axis=1)
    near = near[ok]
    return bool(wide[near[:, 0], near[:, 1], near[:, 2]].any())


def _front_detail(parts, transforms, sign):
    """How much on the surface seen from one end of the Z axis differs from its main colour. Uses colours as painted,
    before shading, so roundness doesn't count as detail."""
    points, colors = [], []
    for part in parts:
        if part.solid_grid is None or not part.solid_grid.any():
            continue
        points.append(_posed_centers(part, transforms))
        colors.append(part.rgba[part.solid_grid][:, :3])
    if not points:
        return 0
    p, c = np.vstack(points), np.vstack(colors).astype(int)
    cell = np.floor(p[:, 0]).astype(np.int64) * 100000 + np.floor(p[:, 1]).astype(np.int64)
    order = np.lexsort((sign * p[:, 2], cell))
    first = np.concatenate(([True], cell[order][1:] != cell[order][:-1]))
    seen = c[order][first]
    packed = (seen[:, 0] // 16) << 8 | (seen[:, 1] // 16) << 4 | (seen[:, 2] // 16)
    values, counts = np.unique(packed, return_counts=True)
    main = seen[packed == values[np.argmax(counts)]].mean(axis=0)
    return int((np.linalg.norm(seen - main, axis=1) > 60).sum())


def check(model, machine=False):
    """Everything that makes a model fail or look wrong, as a list of problems. Empty means it's fine to load and has
    nothing obviously broken, in how it looks or how it moves. Takes a Model, or a built dictionary, which gets only the
    checks that don't need the voxels. Pass machine=True for a block's model, which doesn't need a walk, hurt or death."""
    built = model.build() if isinstance(model, Model) else model
    problems = list(bbmodel.check(built, machine))
    feet, still = (model._feet(), model._still()) if isinstance(model, Model) else (None, ())
    if built.get("textures") and built.get("outliner"):
        problems += bbmodel.motion_notes(built, feet, still, machine)
    if not machine:
        names = {a["name"] for a in built.get("animations", [])}
        problems += [f"no animation named {wanted!r}, which the game plays when the mob {why}" for wanted, why in (("hurt", "takes damage"), ("death", "dies")) if wanted not in names]
    per_bone = {}
    owners = {}

    def walk(node, name_of):
        for child in node["children"]:
            if isinstance(child, dict):
                walk(child, name_of)
            else:
                owners[child] = name_of[node["uuid"]]

    name_of = {g["uuid"]: g["name"] for g in built["groups"]}
    for root in built["outliner"]:
        walk(root, name_of)
    for e in built["elements"]:
        per_bone[owners.get(e["uuid"])] = per_bone.get(owners.get(e["uuid"]), 0) + 1
    if len(per_bone) > MAX_BONES:
        problems.append(f"too many bones: {len(per_bone)} have voxels, and each is one display entity in game. Aim for 5 to 12, at most {MAX_BONES}")
    for name, count in per_bone.items():
        if count > MAX_BONE_CUBES:
            problems.append(f"part {name!r} has {count} cubes, over the budget of {MAX_BONE_CUBES}. Make it smaller or use a coarser grain")
    if len(built["elements"]) > MAX_CUBES:
        problems.append(f"{len(built['elements'])} cubes in all, over the budget of {MAX_CUBES}. Use fewer parts or a coarser grain")
    side = built["textures"][0]["width"] if built.get("textures") else 0
    if side > MAX_ATLAS:
        problems.append(f"the skin needs {side}x{side}, over the limit of {MAX_ATLAS}. Use a coarser grain")
    if not isinstance(model, Model):
        return problems

    problems.extend(dict.fromkeys(model._notes))
    transforms = _rest_transforms(model)
    drawn = [p for p in model.parts.values() if p.solid_grid is not None and p.solid_grid.any()]
    for part in model.parts.values():
        if part not in drawn and not any(p.parent == part.name for p in model.parts.values()):
            problems.append(f"part {part.name!r} has no voxels and no children, so it does nothing")
    for part in drawn:
        if not part.loose:
            pieces = _components(part.solid_grid)
            for piece in pieces[1:]:
                where_ = ((piece.mean(axis=0) + part.lo + 0.5) * part.grain).round(1).tolist()
                problems.append(f"part {part.name!r}: {len(piece)} voxels float apart from the rest, around {where_}. Join them, or pass loose=True if they're meant to be separate")
        above = model.parts.get(part.parent)
        while above is not None and (above.solid_grid is None or not above.solid_grid.any()):
            above = model.parts.get(above.parent)
        if above is not None and not _touches(part, above, transforms):
            problems.append(f"part {part.name!r} doesn't touch its parent {above.name!r}, so it hangs in the air")
    if drawn:
        lowest = min(float(_posed_centers(p, transforms)[:, 1].min()) - p.grain / 2 for p in drawn)
        if lowest < -0.5:
            problems.append(f"the lowest point is at y {lowest:.1f}, through the floor. Feet go at y 0")
        heads = [p for p in drawn if p.name.startswith("head")] or drawn
        if not _front_detail(heads, transforms, 1):
            where_ = "the back" if _front_detail(heads, transforms, -1) else "either end"
            problems.append(f"nothing on the front: seen from -Z it's one colour, with no eyes or markings, and there's detail on {where_}. The front is -Z")
    return problems


def _hitbox_width(built):
    """A sensible width for a mob's square hitbox, in blocks. It goes by where the bulk is, so that wings and tails don't
    count for much: the span holding the middle 80% of the volume along X and along Z, scaled to what a solid box of
    that span would measure, then the geometric mean of the two, since vanilla sizes long bodies between their width and
    length. That comes out close to vanilla's own zombies, cows and horses."""
    posed = bbmodel._pose(built)
    boxes = []
    for e in built["elements"]:
        m, origin = posed[e["uuid"]]
        corners = np.array([(a, b, c) for a in (e["from"][0], e["to"][0]) for b in (e["from"][1], e["to"][1]) for c in (e["from"][2], e["to"][2])], float)
        p = (corners - origin) @ m[:3, :3].T + m[:3, 3]
        boxes.append((p.min(axis=0), p.max(axis=0), float(np.prod(np.subtract(e["to"], e["from"])))))
    if not boxes:
        return 0.0
    spans = []
    for axis in (0, 2):
        low = math.floor(min(b[0][axis] for b in boxes))
        high = math.ceil(max(b[1][axis] for b in boxes))
        mass = np.zeros(max(high - low, 1))
        for lo, hi, volume in boxes:
            i, j = int(lo[axis] - low), max(int(math.ceil(hi[axis] - low)), int(lo[axis] - low) + 1)
            mass[i:j] += volume / (j - i)
        cumulative = np.cumsum(mass) / mass.sum()
        a, b = np.searchsorted(cumulative, 0.1), np.searchsorted(cumulative, 0.9)
        spans.append((b - a + 1) / 0.8)
    return math.sqrt(spans[0] * spans[1]) / 16


def stats(model):
    """The numbers a model is judged by. size is the whole bounding box in blocks, as (x, y, z). height is its top and
    width a sensible hitbox width, which are what a mob declares. walk_speed is how fast its feet go past on the ground in
    blocks a second, which is how fast it has to move to look planted, or None if nothing walks."""
    built = model.build() if isinstance(model, Model) else model
    scene = bbmodel._Scene(built)
    motion = bbmodel._Motion(built, scene, model._feet() if isinstance(model, Model) else None)
    posed = scene.points(scene.pose()).reshape(-1, 3) if len(scene.corners) else np.zeros((1, 3))
    lo, hi = posed.min(axis=0), posed.max(axis=0)
    size = (hi - lo) / 16
    return {"size": tuple(round(float(v), 2) for v in size), "height": round(float(hi[1]) / 16, 2),
            "width": round(_hitbox_width(built), 2), "lowest": round(float(lo[1]), 2),
            "bones": len(built["groups"]), "drawn_bones": len(set(scene.bone_of.tolist())), "elements": len(built["elements"]),
            "faces": len(scene.corners), "atlas": built["textures"][0]["width"] if built.get("textures") else 0,
            "keyframes": sum(len(animator["keyframes"]) for a in built["animations"] for animator in a["animators"].values()),
            "walk_speed": motion.ground_speed(), "bytes": len(json.dumps(built, separators=(",", ":")))}


def _shape_method(make):
    def method(self, *args, **kw):
        return self._draw(make, args, kw, "add")
    method.__name__, method.__doc__ = make.__name__, make.__doc__
    return method


for _shape_name, _make in _SHAPES.items():
    setattr(Part, _shape_name, _shape_method(_make))
