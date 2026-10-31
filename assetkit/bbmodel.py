#!/usr/bin/env python3
"""Mobs as Blockbench .bbmodel files, for loading with Blockbench Import Library (BIL). Real creatures are modelled with
assetkit/sculpt.py, which builds on this file's document, check, animate, render and preview. The four simple kinds here
are stand-ins until someone does that.

    from assetkit import bbmodel
    mob = bbmodel.humanoid("ember_husk", primary="#8a5a48", secondary="#3c3440", eye="#ffb040", seed=3)
    bbmodel.save(mob, "ember_husk.bbmodel")
    bbmodel.preview(mob, "ember_husk_preview.png")   # look at this before using the model
    assert not bbmodel.check(mob)

Command line:  python3 assetkit/bbmodel.py humanoid ember_husk --primary "#8a5a48" --seed 3 -o ember_husk.bbmodel

Files use the Blockbench 5 layout ("format_version": "5.0", generic "free" format) with the skin embedded,
one root bone, a bone named "head" with its pivot at the neck, and animations named "idle" and "walk". The
reasons, checked against BIL's source, are in assetkit/README.md. check() enforces them.
"""
import argparse
import base64
import io
import json
import math
import pathlib
import re
import struct
import sys
import uuid

import numpy as np
from PIL import Image, ImageDraw, ImageFont

try:
    from . import textures as tx
except ImportError:  # run as a script
    import textures as tx

FORMAT_VERSION = "5.0"
FACES = ("north", "east", "south", "west", "up", "down")
RESERVED_BONES = ("hitbox", "seat", "driver")  # BIL gives bones starting with these a special meaning
_NAMESPACE = uuid.UUID("6f1d1c52-9a0b-4c55-8f6d-0f3a1b7c2e11")


# ---------------------------------------------------------------- building a mob

class _Mob:
    def __init__(self, name, seed):
        if not re.fullmatch(r"[a-z0-9_]+", name):
            raise ValueError(f"model name {name!r} must be lowercase letters, digits and underscores")
        self.name, self.seed = name, seed
        self.rng = tx._rng(seed, 40)
        self.bones, self.cubes = {}, []

    def id(self, *parts):
        """Stable UUIDs, so the same name and seed always give the same file."""
        return str(uuid.uuid5(_NAMESPACE, "/".join(map(str, (self.name, self.seed) + parts))))

    def bone(self, name, origin, parent=None):
        self.bones[name] = {"name": name, "origin": list(origin), "parent": parent, "uuid": self.id("bone", name),
                            "children": []}
        if parent:
            self.bones[parent]["children"].append(self.bones[name]["uuid"])
        return name

    def cube(self, bone, name, frm, to, material, paint=None, alpha=255, detail=1.0):
        cube = {"bone": bone, "name": name, "from": list(frm), "to": list(to), "material": material, "paint": paint,
                "alpha": alpha, "detail": detail, "uuid": self.id("cube", bone, name)}
        self.cubes.append(cube)
        self.bones[bone]["children"].append(cube["uuid"])
        return cube

    def _pack(self):
        """Shelf-pack every cube's unwrap into the smallest power-of-two square skin."""
        order = sorted(self.cubes, key=lambda c: -(c["to"][2] - c["from"][2] + c["to"][1] - c["from"][1]))
        for side in (32, 64, 128, 256):
            x = y = shelf = 0
            spots = {}
            for c in order:
                w, h, d = (int(math.ceil(c["to"][i] - c["from"][i])) for i in range(3))
                bw, bh = 2 * (w + d), d + h
                if x + bw > side:
                    x, y, shelf = 0, y + shelf, 0
                if bw > side or y + bh > side:
                    break
                spots[c["uuid"]] = (x, y, w, h, d)
                x, shelf = x + bw, max(shelf, bh)
            else:
                return side, spots
        raise ValueError("mob is too big for a 256x256 skin")

    def finish(self, materials):
        """Paint the skin and produce the .bbmodel dictionary."""
        side, spots = self._pack()
        skin = np.zeros((side, side, 4), dtype=np.uint8)
        elements = []
        for c in self.cubes:
            u, v, w, h, d = spots[c["uuid"]]
            rects = {"east": (u, v + d, u + d, v + d + h), "north": (u + d, v + d, u + d + w, v + d + h),
                     "west": (u + d + w, v + d, u + d + w + d, v + d + h),
                     "south": (u + d + w + d, v + d, u + 2 * d + 2 * w, v + d + h),
                     "up": (u + d, v, u + d + w, v + d), "down": (u + d + w, v, u + d + 2 * w, v + d)}
            pal = materials[c["material"]]
            for face, (x0, y0, x1, y1) in rects.items():
                if x1 > x0 and y1 > y0:
                    px = skin[y0:y1, x0:x1]
                    _base_face(px, face, pal, self.rng, c["alpha"], c["detail"])
                    if c["paint"]:
                        c["paint"](face, px)
            elements.append({"name": c["name"], "box_uv": False, "rescale": False, "locked": False,
                             "render_order": "default", "allow_mirror_modeling": True, "from": c["from"], "to": c["to"],
                             "autouv": 0, "color": 0, "origin": self.bones[c["bone"]]["origin"],
                             "faces": {f: {"uv": list(r), "texture": 0} for f, r in rects.items()},
                             "type": "cube", "uuid": c["uuid"]})
        groups = [{"name": b["name"], "origin": b["origin"], "rotation": [0, 0, 0], "scale": 1, "color": 0,
                   "uuid": b["uuid"], "export": True, "mirror_uv": False, "isOpen": True, "locked": False,
                   "visibility": True, "autouv": 0} for b in self.bones.values()]
        by_uuid = {b["uuid"]: b for b in self.bones.values()}

        def outline(bone):
            kids = [outline(by_uuid[k]) if k in by_uuid else k for k in bone["children"]]
            return {"uuid": bone["uuid"], "isOpen": True, "children": kids}

        return document(self.name, elements, groups, [outline(self.bones[next(iter(self.bones))])], skin, self.id("texture"))


def document(name, elements, groups, outliner, skin_array, texture_uuid):
    """The .bbmodel dictionary around finished bones and cubes, with a square RGBA array embedded as its one skin."""
    side = skin_array.shape[0]
    png = io.BytesIO()
    Image.fromarray(skin_array).save(png, "PNG")
    texture = {"path": "", "name": "skin.png", "folder": "", "namespace": "", "id": "0", "group": "",
               "width": side, "height": side, "uv_width": side, "uv_height": side, "particle": False,
               "use_as_default": False, "layers_enabled": False, "render_mode": "default", "render_sides": "auto",
               "pbr_channel": "color", "frame_time": 1, "frame_order_type": "loop", "frame_order": "",
               "frame_interpolate": False, "visible": True, "internal": True, "saved": True,
               "uuid": texture_uuid, "relative_path": "",
               "source": "data:image/png;base64," + base64.b64encode(png.getvalue()).decode()}
    return {"meta": {"format_version": FORMAT_VERSION, "model_format": "free", "box_uv": False},
            "name": name, "model_identifier": name, "visible_box": [1, 1, 0],
            "variable_placeholders": "", "variable_placeholder_buttons": [], "bedrock_animation_mode": "entity",
            "timeline_setups": [], "unhandled_root_fields": {}, "resolution": {"width": side, "height": side},
            "elements": elements, "groups": groups, "outliner": outliner,
            "textures": [texture], "animations": []}


def _materials(*colors, contrast=0.72):
    return [tx.ramp(c, 5, contrast) for c in colors]


def _base_face(px, face, pal, rng, alpha=255, detail=1.0):
    """Fill one face of a cube: flat tone by direction, soft edge shading, and a few clusters."""
    h, w = px.shape[:2]
    base = {"up": 3, "down": 1}.get(face, 2)
    idx = np.full((h, w), base)
    if face not in ("up", "down"):
        if h >= 3:
            idx[0, :] = 3
            idx[-1, :] = 1
    if w * h >= 16:
        for _ in range(int(w * h / 16 * detail)):
            x, y = int(rng.integers(w)), int(rng.integers(h))
            tone = base + int(rng.choice((-1, 1)))
            for dx, dy in tx._grow(rng, int(rng.integers(2, 5)), hbias=1.0):
                if 0 <= y + dy < h and 0 <= x + dx < w:
                    idx[y + dy, x + dx] = tone
    lut = np.array([p + (alpha,) for p in pal], dtype=np.uint8)
    px[:] = lut[np.clip(idx, 0, 4)]


def _set(px, y, x, color):
    h, w = px.shape[:2]
    if 0 <= y < h and 0 <= x < w:
        px[y, x] = tuple(tx.rgb(color)) + (255,)


def _face_paint(eye, pupil, mood="calm", mouth=None, eye_row=None):
    """Eyes and mouth on the front (north) face. BIL mobs look along -Z, which is Blockbench's north."""
    def paint(face, px):
        if face != "north":
            return
        h, w = px.shape[:2]
        row = eye_row if eye_row is not None else h * 3 // 8
        big = w >= 12  # a big flat face, as on a slime, needs big eyes to read at a distance
        ew = 3 if big else 2 if w >= 6 else 1
        left = max(0, w // 2 - ew - max(1, w // 8))
        right = w - left - ew
        for x0, inner in ((left, ew - 1), (right, 0)):
            for i in range(ew):
                for j in range(ew if big else 1):
                    _set(px, row + j, x0 + i, pupil if i == inner else eye)
            if big:
                _set(px, row, x0, tx.mix(eye, (255, 255, 255), 0.55))
        if big:
            if mouth is not None:
                for x in range(w // 2 - 1, w // 2 + 1):
                    _set(px, row + ew + 1, x, mouth)
            return
        if mood == "angry":
            for x0, step in ((left, 1), (right, -1)):
                for i in range(ew):
                    _set(px, row - 1 + (i if step > 0 else ew - 1 - i), x0 + i, tx.mix(pupil, px[0, 0][:3], 0.25))
                    if (i if step > 0 else ew - 1 - i) == 1:
                        _set(px, row, x0 + i, pupil)
        elif mood == "calm" and h >= 6:
            for x0 in (left, right):
                for i in range(ew):
                    px[row - 1, x0 + i, :3] = tx.mix(px[row - 1, x0 + i, :3], (0, 0, 0), 0.18)
        if mouth is not None and h >= 6:
            my = min(h - 2, row + 2)
            for x in range(w // 2 - 1, w // 2 + 1):
                _set(px, my, x, mouth)
    return paint


def _chain(*painters):
    def paint(face, px):
        for p in painters:
            p(face, px)
    return paint


def _rows(rows, ramp, faces=("north", "east", "south", "west")):
    """Recolour some rows of the side faces, as for a belt or boots. rows maps row number to ramp tone."""
    def paint(face, px):
        if face in faces:
            h = px.shape[0]
            for r, tone in rows.items():
                y = r if r >= 0 else h + r
                if 0 <= y < h:
                    px[y, :, :3] = ramp[tone]
    return paint


def _whole(ramp, faces, base=2):
    """Repaint whole faces in another material, keeping their light and dark pattern."""
    def paint(face, px):
        if face in faces:
            lum = px[..., :3].astype(float).mean(axis=2)
            order = np.argsort(np.argsort(lum.ravel())).reshape(lum.shape) / max(lum.size - 1, 1)
            px[..., :3] = np.array(ramp, dtype=np.uint8)[np.clip(np.round(base - 1 + order * 2).astype(int), 0, 4)]
    return paint


def _patches(ramp, rng, count=3):
    """Cow-like clusters in a second colour on the side and top faces."""
    def paint(face, px):
        if face == "down":
            return
        h, w = px.shape[:2]
        ys, xs = np.mgrid[0:h, 0:w]
        for _ in range(max(1, count * w * h // 96)):
            cx, cy = rng.uniform(0, w), rng.uniform(0, h)
            rx, ry = rng.uniform(1.8, 3.8), rng.uniform(1.4, 2.8)
            blob = ((xs - cx) / rx) ** 2 + ((ys - cy) / ry) ** 2 < 1
            px[..., :3] = np.where(blob[..., None], ramp[2], px[..., :3])
            edge = blob & (((xs - cx + 1) / rx) ** 2 + ((ys - cy + 1) / ry) ** 2 >= 1)  # lit top-left rim
            px[..., :3] = np.where(edge[..., None], ramp[3], px[..., :3])
    return paint


# ---------------------------------------------------------------- animation

TICK = 0.05  # BIL bakes every animation to one frame a tick
# How far a keyframe may be left out and still land this close: degrees, model units, and a scale factor.
_KEY_TOLERANCE = {"rotation": 0.4, "position": 0.03, "scale": 0.004}


def _simplified(values, tolerance):
    """Indexes of the rows to keep so that straight lines between them stay within tolerance of every row."""
    keep = {0, len(values) - 1}
    stack = [(0, len(values) - 1)]
    while stack:
        a, b = stack.pop()
        if b - a < 2:
            continue
        along = (np.arange(a + 1, b) - a)[:, None] / (b - a)
        error = np.abs(values[a + 1:b] - (values[a] + (values[b] - values[a]) * along)).max(axis=1)
        worst = int(np.argmax(error))
        if error[worst] > tolerance:
            keep.add(a + 1 + worst)
            stack += [(a, a + 1 + worst), (a + 1 + worst, b)]
    return sorted(keep)


def _plain(value, places=2):
    value = round(float(value), places)
    return int(value) if value == int(value) else value


def animate_ticks(model, name, ticks, tracks, loop="loop"):
    """Add an animation lasting this many ticks, keeping only the keyframes it needs. BIL plays a frame a tick, ending
    on the frame at the animation's length and then going back to the first. So a loop of n ticks is written n - 1 ticks
    long, its last frame one step before its first, and it never holds for a tick at the seam. Channels that don't
    move are left out, and straight runs become two keyframes, so the file pays only for what moves. Keyframes go
    without the uuid and colour Blockbench adds, which BIL doesn't read, to save a third of their size."""
    ids = {g["name"]: g["uuid"] for g in model["groups"]}
    ticks = max(int(ticks), 2)
    frames = ticks if loop == "loop" else ticks + 1
    phases = np.arange(frames) / ticks
    animators = {}
    for bone, channels in tracks.items():
        keys = []
        for channel, fn in channels.items():
            values = np.array([fn(float(p)) for p in phases], float)
            tolerance = _KEY_TOLERANCE[channel]
            if np.abs(values - (1.0 if channel == "scale" else 0.0)).max() < tolerance:
                continue
            places = 2 if channel == "rotation" else 3
            for i in _simplified(values, tolerance):
                x, y, z = values[i]
                keys.append({"channel": channel, "data_points": [{"x": _plain(x, places), "y": _plain(y, places), "z": _plain(z, places)}],
                             "time": round(i * TICK, 2), "interpolation": "linear"})
        if keys:
            animators[ids[bone]] = {"name": bone, "type": "bone", "keyframes": keys}
    model["animations"] = [a for a in model["animations"] if a["name"] != name] + [{
        "uuid": str(uuid.uuid5(_NAMESPACE, f"{model['name']}/{name}")), "name": name, "loop": loop, "override": False,
        "length": round((frames - 1) * TICK, 2), "snapping": 20, "selected": False, "saved": False, "path": "", "anim_time_update": "",
        "blend_weight": "", "start_delay": "", "loop_delay": "", "animators": animators}]
    return model


def animate(model, name, length, tracks, loop="loop", samples=None):
    """Add an animation. tracks maps bone name to {"rotation"|"position"|"scale": fn}, where fn takes the
    phase 0..1 and returns (x, y, z). Rotation is in degrees around the bone's pivot, position in model
    units (16 = one block), scale is a multiplier. BIL bakes animations at 20 frames a second."""
    ids = {g["name"]: g["uuid"] for g in model["groups"]}
    samples = samples or max(4, int(round(length * 12)))
    times = [round(round(length * i / samples / 0.05) * 0.05, 4) for i in range(samples + 1)]
    animators = {}
    for bone, channels in tracks.items():
        keys = []
        for channel, fn in channels.items():
            for t in sorted(set(times)):
                x, y, z = fn(t / length)
                keys.append({"channel": channel, "data_points": [{"x": round(float(x), 3), "y": round(float(y), 3), "z": round(float(z), 3)}],
                             "uuid": str(uuid.uuid5(_NAMESPACE, f"{model['name']}/{name}/{bone}/{channel}/{t}")),
                             "time": t, "color": -1, "interpolation": "linear"})
        animators[ids[bone]] = {"name": bone, "type": "bone", "keyframes": keys}
    model["animations"] = [a for a in model["animations"] if a["name"] != name] + [{
        "uuid": str(uuid.uuid5(_NAMESPACE, f"{model['name']}/{name}")), "name": name, "loop": loop, "override": False,
        "length": length, "snapping": 20, "selected": False, "saved": False, "path": "", "anim_time_update": "",
        "blend_weight": "", "start_delay": "", "loop_delay": "", "animators": animators}]
    return model


def _sin(p, cycles=1, phase=0.0):
    return math.sin(2 * math.pi * (cycles * p + phase))


def _rx(amount, cycles=1, phase=0.0):
    return lambda p: (amount * _sin(p, cycles, phase), 0, 0)


def _ry(amount, cycles=1, phase=0.0):
    return lambda p: (0, amount * _sin(p, cycles, phase), 0)


def _rz(amount, cycles=1, phase=0.0):
    return lambda p: (0, 0, amount * _sin(p, cycles, phase))


def _py(amount, cycles=1, phase=0.0):
    return lambda p: (0, amount * _sin(p, cycles, phase), 0)


# ---------------------------------------------------------------- the mob kinds

def humanoid(name, primary="#b58e6e", secondary="#4f6a8c", eye="#e8e4d8", pupil="#1c1826", mood="calm", horns=False, seed=0):
    """Two legs, two arms and a head, about two blocks tall. primary is skin, secondary is clothing."""
    m = _Mob(name, seed)
    P, S = _materials(primary, secondary)
    D = tx.ramp(tx.mix(secondary, (24, 20, 28), 0.55), 5, 0.6)
    root = m.bone("root", (0, 0, 0))
    body = m.bone("body", (0, 12, 0), root)
    head = m.bone("head", (0, 24, 0), body)
    hair = _whole(S, ("up", "south"))
    m.cube(head, "head", (-4, 24, -4), (4, 32, 4), 0,
           _chain(hair, _rows({0: 1}, S), _face_paint(eye, pupil, mood, tx.mix(primary, pupil, 0.7))))
    if horns:
        m.cube(head, "horn_a", (-5, 30, -1), (-3, 34, 1), 1)
        m.cube(head, "horn_b", (3, 30, -1), (5, 34, 1), 1)
    m.cube(body, "torso", (-4, 12, -2), (4, 24, 2), 1,
           _chain(_rows({-3: 0, -4: 3}, D), _rows({0: 3}, S)))
    for side, x0, x1, pivot in (("right", 4, 8, 6), ("left", -8, -4, -6)):
        arm = m.bone(f"arm_{side}", (pivot, 22, 0), body)
        m.cube(arm, f"arm_{side}", (x0, 12, -2), (x1, 24, 2), 0, _rows({0: 3, 1: 2, 2: 2, 3: 1}, S))
        lx0, lx1 = (0, 4) if side == "right" else (-4, 0)
        leg = m.bone(f"leg_{side}", ((lx0 + lx1) / 2, 12, 0), root)
        m.cube(leg, f"leg_{side}", (lx0, 0, -2), (lx1, 12, 2), 1,
               _chain(_whole(D, ("north", "east", "south", "west", "down"), base=2), _rows({-1: 0, -2: 1}, D)))
    model = m.finish([P, S])
    animate(model, "idle", 4.0, {
        "body": {"position": _py(0.2, 2)},
        "head": {"rotation": lambda p: (1.5 * _sin(p, 2), 3 * _sin(p, 1), 0)},
        "arm_right": {"rotation": lambda p: (2 * _sin(p, 2, 0.1), 0, 2.5 + 1.5 * _sin(p, 2))},
        "arm_left": {"rotation": lambda p: (-2 * _sin(p, 2, 0.1), 0, -2.5 - 1.5 * _sin(p, 2))},
    })
    animate(model, "walk", 1.0, {
        "body": {"position": lambda p: (0, 0.5 * abs(_sin(p)), 0)},
        "head": {"rotation": _rx(1.5, 2)},
        "leg_right": {"rotation": _rx(32)}, "leg_left": {"rotation": _rx(-32)},
        "arm_right": {"rotation": _rx(-26)}, "arm_left": {"rotation": _rx(26)},
    })
    return model


def quadruped(name, primary="#9a7a58", secondary="#d8cdb8", eye="#1c1826", pupil="#1c1826", mood="calm", spots=True, horns=False, seed=0):
    """Four legs, a horizontal body and a head at the front, about a block tall."""
    m = _Mob(name, seed)
    P, S, M = _materials(primary, secondary, tx.mix(primary, secondary, 0.45))
    D = tx.ramp(tx.mix(primary, (24, 20, 28), 0.6), 5, 0.55)
    root = m.bone("root", (0, 0, 0))
    body = m.bone("body", (0, 12, 0), root)
    head = m.bone("head", (0, 14, -8), body)
    m.cube(head, "head", (-4, 10, -14), (4, 18, -7), 0, _face_paint(eye, pupil, mood, eye_row=2))

    def nostrils(face, px):
        if face == "north":
            _set(px, 1, 0, tx.mix(pupil, M[2], 0.25))
            _set(px, 1, px.shape[1] - 1, tx.mix(pupil, M[2], 0.25))

    m.cube(head, "snout", (-3, 10, -15), (3, 14, -14), 2, nostrils)
    m.cube(head, "ear_a", (-6, 16, -10), (-4, 18, -9), 0)
    m.cube(head, "ear_b", (4, 16, -10), (6, 18, -9), 0)
    if horns:
        m.cube(head, "horn_a", (-4, 18, -10), (-2, 21, -8), 1)
        m.cube(head, "horn_b", (2, 18, -10), (4, 21, -8), 1)
    m.cube(body, "torso", (-5, 8, -8), (5, 17, 9), 0, _patches(S, m.rng) if spots else None)
    tail = m.bone("tail", (0, 15, 9), body)
    m.cube(tail, "tail", (-1, 8, 9), (1, 15, 11), 0, _rows({-1: 1, -2: 2, -3: 2}, S))
    for leg_name, x, z in (("leg_front_right", 3, -6), ("leg_front_left", -3, -6), ("leg_back_right", 3, 7), ("leg_back_left", -3, 7)):
        leg = m.bone(leg_name, (x, 8, z), root)
        m.cube(leg, leg_name, (x - 2, 0, z - 2), (x + 2, 8, z + 2), 0, _rows({-1: 0, -2: 1}, D))
    model = m.finish([P, S, M])
    animate(model, "idle", 4.0, {
        "body": {"position": _py(0.15, 2)},
        "head": {"rotation": lambda p: (2 * _sin(p, 1), 4 * _sin(p, 1, 0.2), 0)},
        "tail": {"rotation": _rz(6, 2)},
    })
    animate(model, "walk", 0.8, {
        "body": {"position": lambda p: (0, 0.35 * abs(_sin(p)), 0)},
        "head": {"rotation": _rx(2.5, 2)},
        "tail": {"rotation": _rz(9, 2)},
        "leg_front_right": {"rotation": _rx(26)}, "leg_back_left": {"rotation": _rx(26)},
        "leg_front_left": {"rotation": _rx(-26)}, "leg_back_right": {"rotation": _rx(-26)},
    })
    return model


def slime(name, primary="#74c25e", secondary="#3f8a4a", eye="#16301e", pupil="#16301e", mood="calm", size=16, seed=0, translucent=True):
    """A bouncing cube with a darker core inside, all in one bone. walk is a hop."""
    m = _Mob(name, seed)
    P, S = _materials(primary, secondary)
    root = m.bone("root", (0, 0, 0))
    body = m.bone("body", (0, 0, 0), root)
    half, core = size // 2, max(2, size // 4)
    # The core comes first: BIL keeps element order, and a translucent shell must draw over what's inside.
    m.cube(body, "core", (-core, core // 2, -core), (core, core // 2 + 2 * core, core), 1, detail=0.5)
    face = _face_paint(eye, pupil, mood, tx.mix(primary, pupil, 0.7), eye_row=size // 4)
    m.cube(body, "shell", (-half, 0, -half), (half, size, half), 0, face, alpha=178 if translucent else 255, detail=0.18)
    model = m.finish([P, S])
    squash = lambda s: (1 + (1 - s) * 0.5, s, 1 + (1 - s) * 0.5)
    animate(model, "idle", 2.0, {"body": {"scale": lambda p: squash(1 - 0.05 * (0.5 + 0.5 * _sin(p, 1, -0.25)))}})
    hop_t = [0.0, 0.18, 0.32, 0.55, 0.72, 0.85, 1.0]
    hop_s = [1.0, 0.78, 1.14, 1.04, 0.76, 1.05, 1.0]
    hop_y = [0.0, 0.0, 2.0, 7.0, 0.0, 0.0, 0.0]
    animate(model, "walk", 1.0, {"body": {
        "scale": lambda p: squash(float(np.interp(p, hop_t, hop_s))),
        "position": lambda p: (0, float(np.interp(p, hop_t, hop_y)), 0)}}, samples=20)
    return model


def flying(name, primary="#5a6478", secondary="#a8b0bc", eye="#f0e8c0", pupil="#14121e", mood="calm", seed=0):
    """A small body hanging between two flat wings, with a head and tail. walk is flapping flight.
    primary is the back and the wing tops, secondary the belly, beak and wing undersides."""
    m = _Mob(name, seed)
    P, S = _materials(primary, secondary)
    root = m.bone("root", (0, 0, 0))
    body = m.bone("body", (0, 12, 0), root)
    head = m.bone("head", (0, 15, -5), body)
    m.cube(body, "torso", (-4, 10, -5), (4, 17, 6), 0, _whole(S, ("down",), base=2))
    m.cube(head, "head", (-3, 12, -11), (3, 18, -5), 0, _face_paint(eye, pupil, mood, eye_row=2))
    m.cube(head, "beak", (-1, 13, -12), (1, 15, -11), 1)
    tail = m.bone("tail", (0, 15, 6), body)
    m.cube(tail, "tail", (-2, 14, 6), (2, 15, 12), 0, _rows({0: 1}, S, ("south",)))

    def feathers(face, px):
        h, w = px.shape[:2]
        if face == "up":  # darker feather tips along the trailing edge
            px[-1, ::2, :3] = P[0]
            px[-2, ::3, :3] = P[1]
        elif face == "down":
            px[:, :, :3] = np.array(S, dtype=np.uint8)[np.clip(2 + (np.indices((h, w)).sum(axis=0) % 5 == 0).astype(int) * -1, 0, 4)]

    for side, x0, x1, pivot in (("right", 4, 15, 4), ("left", -15, -4, -4)):
        wing = m.bone(f"wing_{side}", (pivot, 16, 0), body)
        m.cube(wing, f"wing_{side}", (x0, 16, -3), (x1, 17, 4), 0, feathers)
    model = m.finish([P, S])
    animate(model, "idle", 2.0, {
        "body": {"position": _py(1.0, 1)},
        "wing_right": {"rotation": _rz(14, 2)}, "wing_left": {"rotation": _rz(-14, 2)},
        "tail": {"rotation": _rx(4, 1)}, "head": {"rotation": _rx(2, 1)},
    })
    animate(model, "walk", 1.0, {
        "body": {"position": _py(0.8, 2), "rotation": lambda p: (-8, 0, 0)},
        "wing_right": {"rotation": _rz(38, 2)}, "wing_left": {"rotation": _rz(-38, 2)},
        "tail": {"rotation": _rx(6, 2)},
    })
    return model


KINDS = {"humanoid": humanoid, "quadruped": quadruped, "slime": slime, "flying": flying}


# ---------------------------------------------------------------- files

def save(model, path):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(model, separators=(",", ":")))
    return path


def load(path):
    return json.loads(pathlib.Path(path).read_text())


def skin(model, index=0):
    """The embedded skin as a PIL image."""
    data = model["textures"][index]["source"].split(",", 1)[1]
    return Image.open(io.BytesIO(base64.b64decode(data))).convert("RGBA")


def check(model, machine=False):
    """Everything BIL's importer needs from a file, as a list of problems. Empty means it should load. A machine stays
    put, so unlike a mob it doesn't need to be able to walk.
    The rules are taken from BIL's source; see assetkit/README.md."""
    problems = []
    meta = model.get("meta") or {}
    version = str(meta.get("format_version", ""))
    if not re.fullmatch(r"\d+(\.\d+)*(-.*)?", version):
        problems.append("meta.format_version is missing or not a version number")
    elif int(version.split(".")[0]) < 5:
        problems.append("this checker expects the Blockbench 5 layout, with format_version 5.0 or newer")
    if not re.fullmatch(r"[a-z0-9_/.-]+", str(model.get("model_identifier") or model.get("name") or "")):
        problems.append("name is not usable in a resource location")

    textures = model.get("textures") or []
    if not textures:
        problems.append("no textures")
    for i, t in enumerate(textures):
        source = t.get("source", "")
        if not source.startswith("data:image/png;base64,"):
            problems.append(f"texture {i}: source must be an embedded PNG data URL")
            continue
        png = base64.b64decode(source.split(",", 1)[1])
        w, h = struct.unpack(">II", png[16:24])
        if (t.get("width"), t.get("height")) != (w, h):
            problems.append(f"texture {i}: width and height don't match the PNG")
        if not (t.get("uv_width") and t.get("uv_height")):
            problems.append(f"texture {i}: needs uv_width and uv_height, or BIL rescales UVs wrongly")
        if not t.get("frame_time", 0) >= 1:
            problems.append(f"texture {i}: frame_time must be at least 1, since BIL writes it into an .mcmeta")
        if h % w == 0 and h != w:
            problems.append(f"texture {i}: a height that's a multiple of the width makes BIL treat it as an animation")
        if w & (w - 1) or h & (h - 1):
            problems.append(f"texture {i}: use power-of-two sizes, or the atlas loses mipmap levels")
        if not re.fullmatch(r"[a-z0-9_.-]+", str(t.get("name", ""))):
            problems.append(f"texture {i}: name must be lowercase, it becomes a pack path")

    elements = {e.get("uuid"): e for e in model.get("elements", [])}
    for e in model.get("elements", []):
        label = f"cube {e.get('name')!r}"
        if e.get("type") != "cube":
            problems.append(f"{label}: type must be 'cube', or BIL skips its processing")
        for key in ("from", "to", "origin"):
            if len(e.get(key) or []) != 3:
                problems.append(f"{label}: {key} must be three numbers")
        if e.get("rotation") and any(e["rotation"]):
            problems.append(f"{label}: keep cubes unrotated and rotate bones instead")
        if not 0 <= e.get("light_emission", 0) <= 15:
            problems.append(f"{label}: light_emission must be 0 to 15")
        faces = e.get("faces") or {}
        if not faces:
            problems.append(f"{label}: has no faces")
        for name, face in faces.items():
            tex = face.get("texture")
            uv = face.get("uv") or []
            if not isinstance(tex, int) or not 0 <= tex < len(textures):
                problems.append(f"{label} {name}: texture must be an index into textures")
            elif len(uv) != 4 or not all(0 <= uv[j] <= textures[tex].get("uv_width" if j % 2 == 0 else "uv_height", 0) for j in range(4)):
                problems.append(f"{label} {name}: uv must be four numbers inside the texture")

    groups = {}
    for g in model.get("groups", []):
        label = f"bone {g.get('name')!r}"
        groups[g.get("uuid")] = g
        for key in ("origin", "rotation"):
            if len(g.get(key) or []) != 3:
                problems.append(f"{label}: {key} must be three numbers, or BIL crashes on import")
        if not g.get("export"):
            problems.append(f"{label}: export must be true, or its cubes are dropped")
        if not g.get("name"):
            problems.append("a bone has no name")
        if str(g.get("name", "")).startswith(RESERVED_BONES):
            problems.append(f"{label}: names starting with {RESERVED_BONES} have a special meaning in BIL")
    if len({g.get("name") for g in groups.values()}) != len(groups):
        problems.append("bone names must be unique")

    roots = model.get("outliner") or []
    if len(roots) != 1 or not isinstance(roots[0], dict):
        problems.append("use one root bone: BIL rebuilds every bone once per root node")
    seen = set()

    def walk(node, under_head):
        name = groups.get(node.get("uuid"), {}).get("name", "")
        if node.get("uuid") not in groups:
            problems.append(f"outliner node {node.get('uuid')} isn't in groups")
        # BIL tags a head's children and turns them with the look, so ears and antennae can be bones. Naming them for the
        # head keeps that deliberate, because anything else under a head has usually been put there by mistake.
        if under_head and not name.startswith("head"):
            problems.append(f"bone {name!r} is inside a head bone: name it head_{name} if it's meant to turn with the look, such as an ear")
        seen.add(node.get("uuid"))
        for child in node.get("children") or []:
            if isinstance(child, dict):
                walk(child, under_head or name.startswith("head"))
            elif child in elements:
                seen.add(child)
            else:
                problems.append(f"outliner child {child} isn't an element")

    for node in roots:
        if isinstance(node, dict):
            walk(node, False)
        else:
            problems.append("a cube sits at the root of the outliner, put it in a bone")
    missing = (set(elements) | set(groups)) - seen
    if missing:
        problems.append(f"{len(missing)} elements or bones aren't in the outliner")

    for a in model.get("animations", []):
        label = f"animation {a.get('name')!r}"
        if a.get("loop") not in ("once", "hold", "loop"):
            problems.append(f"{label}: loop must be once, hold or loop, or BIL crashes")
        if not a.get("length", 0) > 0:
            problems.append(f"{label}: length must be positive")
        for key, animator in (a.get("animators") or {}).items():
            if key not in groups and key != "effects":
                problems.append(f"{label}: animator {key} isn't a bone")
            for k in animator.get("keyframes", []):
                if k.get("interpolation") not in ("linear", "catmullrom", "step", "bezier"):
                    problems.append(f"{label}: keyframe needs an interpolation, or BIL crashes")
                if k.get("channel") not in ("position", "rotation", "scale"):
                    problems.append(f"{label}: unsupported channel {k.get('channel')!r}")
                if any(v not in (k.get("data_points") or [{}])[0] for v in "xyz"):
                    problems.append(f"{label}: keyframe needs x, y and z")
    names = {a.get("name") for a in model.get("animations", [])}
    for wanted in () if machine else ("idle", "walk"):
        if wanted not in names:
            problems.append(f"no animation named {wanted!r}, which BIL's walk helper plays")
    return problems


# ---------------------------------------------------------------- preview

def _mat(rx=0.0, ry=0.0, rz=0.0, pos=(0, 0, 0), scale=(1, 1, 1)):
    """Same order as BIL's Utils.createQuaternion: Z * Y * X, in degrees."""
    x, y, z = math.radians(rx), math.radians(ry), math.radians(rz)
    cx, sx, cy, sy, cz, sz = math.cos(x), math.sin(x), math.cos(y), math.sin(y), math.cos(z), math.sin(z)
    m = np.eye(4)
    m[:3, :3] = (np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]]) @ np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
                 @ np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]]) @ np.diag(scale))
    m[:3, 3] = pos
    return m


def _matrices(rot, pos, scale):
    """What _mat makes, for arrays of rotations in degrees, positions and scales, as (n, 4, 4)."""
    x, y, z = np.radians(rot[:, 0]), np.radians(rot[:, 1]), np.radians(rot[:, 2])
    cx, sx, cy, sy, cz, sz = np.cos(x), np.sin(x), np.cos(y), np.sin(y), np.cos(z), np.sin(z)
    m = np.zeros((len(rot), 4, 4))
    m[:, 0, 0], m[:, 0, 1], m[:, 0, 2] = cz * cy, cz * sy * sx - sz * cx, cz * sy * cx + sz * sx
    m[:, 1, 0], m[:, 1, 1], m[:, 1, 2] = sz * cy, sz * sy * sx + cz * cx, sz * sy * cx - cz * sx
    m[:, 2, 0], m[:, 2, 1], m[:, 2, 2] = -sy, cy * sx, cy * cx
    m[:, :3, :3] *= scale[:, None, :]
    m[:, :3, 3] = pos
    m[:, 3, 3] = 1.0
    return m


def _sample(keys, t, channel, default):
    keys = sorted((k for k in keys if k["channel"] == channel), key=lambda k: k["time"])
    if not keys:
        return default
    ts = [k["time"] for k in keys]
    return tuple(float(np.interp(t, ts, [k["data_points"][0][a] for k in keys])) for a in "xyz")


def _pose(model, anim_name=None, t=0.0):
    """Bone matrices at a moment of an animation, the way BIL's 5.x importer composes them: it adds the animation's
    rotation to the bone's own before making a quaternion, and a bone's size scale doesn't pass to its children."""
    groups = {g["uuid"]: g for g in model["groups"]}
    anim = next((a for a in model["animations"] if a["name"] == anim_name), None)
    animators = anim["animators"] if anim else {}
    out = {}

    def walk(node, parent_m, parent_origin):
        g = groups[node["uuid"]]
        keys = animators.get(g["uuid"], {}).get("keyframes", [])
        pos = _sample(keys, t, "position", (0, 0, 0))
        rot = _sample(keys, t, "rotation", (0, 0, 0))
        scl = _sample(keys, t, "scale", (1, 1, 1))
        rest = g.get("rotation") or (0, 0, 0)
        local = np.array(g["origin"], float) - parent_origin + np.array(pos)
        m = parent_m @ _mat(rot[0] + rest[0], rot[1] + rest[1], rot[2] + rest[2], local, scl)
        out[g["uuid"]] = m
        for child in node["children"]:
            if isinstance(child, dict):
                walk(child, m, np.array(g["origin"], float))
            else:
                out[child] = (m, np.array(g["origin"], float))

    for root in model["outliner"]:
        walk(root, np.eye(4), np.zeros(3))
    return out


def _corners(a, b):
    """Corners of each face in the order top-left, top-right, bottom-right, bottom-left of its texture,
    as the game maps them: side faces look right from outside, up has north at the top."""
    (x0, y0, z0), (x1, y1, z1) = a, b
    return {"north": [(x1, y1, z0), (x0, y1, z0), (x0, y0, z0), (x1, y0, z0)],
            "south": [(x0, y1, z1), (x1, y1, z1), (x1, y0, z1), (x0, y0, z1)],
            "east": [(x1, y1, z1), (x1, y1, z0), (x1, y0, z0), (x1, y0, z1)],
            "west": [(x0, y1, z0), (x0, y1, z1), (x0, y0, z1), (x0, y0, z0)],
            "up": [(x0, y1, z0), (x1, y1, z0), (x1, y1, z1), (x0, y1, z1)],
            "down": [(x0, y0, z1), (x1, y0, z1), (x1, y0, z0), (x0, y0, z0)]}


_NORMALS = {"north": (0, 0, -1), "south": (0, 0, 1), "east": (1, 0, 0), "west": (-1, 0, 0), "up": (0, 1, 0), "down": (0, -1, 0)}
# The two fixed lights the game shades entities with (Lighting.DIFFUSE_LIGHT_0 and _1), so what a model looks like here
# is what it looks like there. BIL's half turn just swaps them.
_LIGHTS = np.array([(0.2, 1.0, -0.7), (-0.2, 1.0, 0.7)]) / math.sqrt(0.04 + 1.0 + 0.49)
_BACKDROP = (84, 96, 110)
_GRID, _INK, _DIM = (100, 113, 128), (235, 235, 235), (186, 194, 204)


class _Scene:
    """A model's faces as flat arrays, so another view of it costs little."""

    def __init__(self, model):
        self.model = model
        self.textures = [np.asarray(skin(model, i)) for i in range(len(model["textures"]))]
        self.bones = [g["uuid"] for g in model["groups"]]
        index = {uuid: i for i, uuid in enumerate(self.bones)}
        origins = {g["uuid"]: g["origin"] for g in model["groups"]}
        owner = {}

        def walk(node):
            for child in node["children"]:
                if isinstance(child, dict):
                    walk(child)
                else:
                    owner[child] = node["uuid"]

        for root in model["outliner"]:
            walk(root)
        corners, uvs, bones, normals, emission, tex = [], [], [], [], [], []
        for e in model["elements"]:
            bone = owner[e["uuid"]]
            for face, points in _corners(e["from"], e["to"]).items():
                data = e["faces"].get(face)
                if data is None:
                    continue
                corners.append(np.array(points, float) - np.array(origins[bone], float))
                uvs.append(data["uv"])
                bones.append(index[bone])
                normals.append(_NORMALS[face])
                emission.append(e.get("light_emission", 0))
                tex.append(data["texture"])
        self.corners = np.array(corners, float).reshape(-1, 4, 3)
        self.uvs = np.array(uvs, float).reshape(-1, 4)
        self.bone_of = np.array(bones, int)
        self.normals = np.array(normals, float).reshape(-1, 3)
        self.emission = np.array(emission, float)
        self.tex = np.array(tex, int)

    def pose(self, anim=None, t=0.0):
        return self.series(anim, [t])[0]

    def tracks(self, anim, times):
        """What an animation asks of each bone at these times: rotation, position and scale as (times, bones, 3)."""
        times = np.asarray(times, float)
        rot, pos, scl = (np.zeros((len(times), len(self.bones), 3)) for _ in range(3))
        scl += 1.0
        found = next((a for a in self.model["animations"] if a["name"] == anim), None)
        animators = found["animators"] if found else {}
        for b, uuid_ in enumerate(self.bones):
            keys = animators.get(uuid_, {}).get("keyframes", ())
            for channel, target in (("rotation", rot), ("position", pos), ("scale", scl)):
                chosen = sorted((k for k in keys if k["channel"] == channel), key=lambda k: k["time"])
                if chosen:
                    ts = [k["time"] for k in chosen]
                    for i, axis in enumerate("xyz"):
                        target[:, b, i] = np.interp(times, ts, [k["data_points"][0][axis] for k in chosen])
        return rot, pos, scl

    def series(self, anim, times):
        """Bone matrices at many moments at once, as (times, bones, 4, 4), the same as _pose gives for one."""
        rot, pos, scl = self.tracks(anim, times)
        out = np.zeros(rot.shape[:2] + (4, 4))
        origins = {g["uuid"]: np.array(g["origin"], float) for g in self.model["groups"]}
        rests = {g["uuid"]: np.array(g.get("rotation") or (0, 0, 0), float) for g in self.model["groups"]}
        index = {uuid_: i for i, uuid_ in enumerate(self.bones)}

        def walk(node, parent, parent_origin):
            uuid_ = node["uuid"]
            b = index[uuid_]
            local = _matrices(rot[:, b] + rests[uuid_], pos[:, b] + origins[uuid_] - parent_origin, scl[:, b])
            out[:, b] = local if parent is None else parent @ local
            for child in node["children"]:
                if isinstance(child, dict):
                    walk(child, out[:, b], origins[uuid_])

        for root in self.model["outliner"]:
            walk(root, None, np.zeros(3))
        return out

    def points(self, matrices, view=None):
        """Every face's corners under a pose and a view, as (faces, 4, 3)."""
        m = matrices if view is None else view @ matrices
        m = m[self.bone_of]
        return np.einsum("fij,fkj->fki", m[:, :3, :3], self.corners) + m[:, None, :3, 3]

    def faces_of(self, names):
        """A mask of the faces that belong to bones with these names."""
        wanted = {g["uuid"] for g in self.model["groups"] if g["name"] in names}
        return np.isin(self.bone_of, [i for i, uuid in enumerate(self.bones) if uuid in wanted])


def _view(yaw, pitch):
    return _mat(rx=pitch) @ _mat(ry=180 + yaw)


def _tidy_scale(scale):
    """Whole or half pixels per unit when there's room, so that texels on the sheet come out nearly the same size."""
    return math.floor(scale * 2) / 2 if scale >= 2 else scale


def _fit(points, size, margin=6, limit=None):
    """The scale and screen position that fit view-space points into a cell."""
    lo, hi = points[..., :2].reshape(-1, 2).min(axis=0), points[..., :2].reshape(-1, 2).max(axis=0)
    span = np.maximum(hi - lo, 1.0)
    scale = min((size[0] - 2 * margin) / span[0], (size[1] - 2 * margin) / span[1])
    scale = min(scale, limit) if limit else scale
    scale = _tidy_scale(scale)
    return scale, size[0] / 2 - scale * (lo[0] + hi[0]) / 2, size[1] / 2 + scale * (lo[1] + hi[1]) / 2


def _raster(scene, matrices, view, scale, cx, cy, size, night=False):
    """Draw the model into an RGBA array with a real depth buffer. The view is orthographic, so each face maps to the
    screen by one affine transform, and all the candidate pixels of all faces can be tested in one go."""
    width, height = size
    image = np.zeros((height, width, 4), dtype=np.uint8)
    if not len(scene.corners):
        return image
    p = scene.points(matrices, view)
    sx, sy = cx + p[:, :, 0] * scale, cy - p[:, :, 1] * scale
    # Corners run left to right and top to bottom as seen from outside, which is a clockwise
    # turn on screen, so a face toward the viewer has a normal pointing away along z.
    # The margin drops faces exactly edge on, which have no area and would otherwise leave a stray line.
    facing = np.cross(p[:, 1] - p[:, 0], p[:, 3] - p[:, 0])[:, 2] < -1e-6
    x0, x1 = np.floor(sx.min(axis=1)).astype(int), np.ceil(sx.max(axis=1)).astype(int)
    y0, y1 = np.floor(sy.min(axis=1)).astype(int), np.ceil(sy.max(axis=1)).astype(int)
    x0, y0, x1, y1 = np.maximum(x0, 0), np.maximum(y0, 0), np.minimum(x1, width), np.minimum(y1, height)
    span_x, span_y = x1 - x0, y1 - y0
    keep = np.nonzero(facing & (span_x > 0) & (span_y > 0))[0]
    if not len(keep):
        return image
    counts = span_x[keep] * span_y[keep]
    face = np.repeat(keep, counts)
    # Each face contributes the pixels of its bounding box, numbered row by row.
    offset = np.arange(counts.sum()) - np.repeat(np.cumsum(counts) - counts, counts)
    px = x0[face] + offset % span_x[face]
    py = y0[face] + offset // span_x[face]
    ax, ay = sx[face, 1] - sx[face, 0], sy[face, 1] - sy[face, 0]
    bx, by = sx[face, 3] - sx[face, 0], sy[face, 3] - sy[face, 0]
    det = ax * by - ay * bx
    det[np.abs(det) < 1e-9] = 1e-9
    dx, dy = px + 0.5 - sx[face, 0], py + 0.5 - sy[face, 0]
    fu, fv = (dx * by - dy * bx) / det, (ax * dy - ay * dx) / det
    inside = (fu >= -1e-6) & (fu <= 1 + 1e-6) & (fv >= -1e-6) & (fv <= 1 + 1e-6)
    face, px, py, fu, fv = face[inside], px[inside], py[inside], fu[inside], fv[inside]
    depth = p[face, 0, 2] + fu * (p[face, 1, 2] - p[face, 0, 2]) + fv * (p[face, 3, 2] - p[face, 0, 2])
    uv = scene.uvs[face]
    tu = np.floor(uv[:, 0] + np.clip(fu, 0, 0.999999) * (uv[:, 2] - uv[:, 0])).astype(int)
    tv = np.floor(uv[:, 1] + np.clip(fv, 0, 0.999999) * (uv[:, 3] - uv[:, 1])).astype(int)
    colors = np.zeros((len(face), 4), dtype=np.uint8)
    for i, tex in enumerate(scene.textures):
        which = scene.tex[face] == i
        colors[which] = tex[np.clip(tv[which], 0, tex.shape[0] - 1), np.clip(tu[which], 0, tex.shape[1] - 1)]
    normals = np.einsum("fij,fj->fi", matrices[scene.bone_of][:, :3, :3], scene.normals)
    normals /= np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-9)
    light = np.minimum(1.0, 0.4 + 0.6 * np.maximum(normals @ _LIGHTS.T, 0).sum(axis=1))
    if night:
        light = light * 0.22
    light = np.maximum(light, scene.emission / 15.0)
    rgb = colors[:, :3] * light[face, None]
    alpha = colors[:, 3]
    best = np.full((height, width), -np.inf)
    solid = np.nonzero(alpha == 255)[0]
    if len(solid):
        # Assigning in depth order leaves the nearest fragment on top, since the last write to an index wins.
        solid = solid[np.argsort(depth[solid], kind="stable")]
        image[py[solid], px[solid], :3] = rgb[solid].astype(np.uint8)
        image[py[solid], px[solid], 3] = 255
        best[py[solid], px[solid]] = depth[solid]
    glass = np.nonzero((alpha > 0) & (alpha < 255))[0]
    glass = glass[depth[glass] > best[py[glass], px[glass]]]
    if len(glass):
        # Translucent fragments blend far to near, one pixel layer at a time. Ties keep element order, as the game does.
        order = np.lexsort((np.arange(len(glass)), depth[glass], py[glass], px[glass]))
        glass = glass[order]
        where = px[glass] * height + py[glass]
        rank = np.arange(len(glass)) - np.searchsorted(where, where)
        out = image.astype(float)
        for layer in range(int(rank.max()) + 1):
            g = glass[rank == layer]
            a = alpha[g, None] / 255.0
            below = out[py[g], px[g]]
            below_a = below[:, 3:] / 255.0
            total = a + below_a * (1 - a)
            out[py[g], px[g], :3] = (rgb[g] * a + below[:, :3] * below_a * (1 - a)) / np.maximum(total, 1e-6)
            out[py[g], px[g], 3] = total[:, 0] * 255.0
        image = out.astype(np.uint8)
    return image


def render(model, anim=None, t=0.0, yaw=-35.0, pitch=22.0, scale=5, size=None, fit=True):
    """Draw the model with a simple orthographic view. yaw=0 looks straight at its face. Something too big for the
    picture is drawn smaller rather than cut off, unless fit is False."""
    scene = _Scene(model)
    size = size or (56 * scale, 56 * scale)
    view, matrices = _view(yaw, pitch), scene.pose(anim, t)
    cx, cy = size[0] / 2, size[1] * 0.72
    if fit and len(scene.corners):
        p = scene.points(matrices, view)
        sx, sy = cx + p[..., 0] * scale, cy - p[..., 1] * scale
        if sx.min() < 0 or sy.min() < 0 or sx.max() > size[0] or sy.max() > size[1]:
            scale, cx, cy = _fit(p, size, margin=3)
    return Image.fromarray(_raster(scene, matrices, view, scale, cx, cy, size))


def _floor(cell, view, scale, cx, cy, reach):
    """Lines a block apart on the ground, so the sheet shows how big a model is and whether it stands on anything."""
    draw = ImageDraw.Draw(cell)
    n = max(1, math.ceil(reach / 16))
    for i in range(-n, n + 1):
        for a, b in (((i * 16, 0, -n * 16), (i * 16, 0, n * 16)), ((-n * 16, 0, i * 16), (n * 16, 0, i * 16))):
            pa, pb = view[:3, :3] @ np.array(a, float), view[:3, :3] @ np.array(b, float)
            draw.line((cx + pa[0] * scale, cy - pa[1] * scale, cx + pb[0] * scale, cy - pb[1] * scale), fill=_GRID)


def _shot(scene, matrices, view, scale, cx, cy, size, reach, night=False):
    cell = Image.new("RGBA", size, (34, 38, 52, 255) if night else _BACKDROP + (255,))
    if not night:
        _floor(cell, view, scale, cx, cy, reach)
    cell.alpha_composite(Image.fromarray(_raster(scene, matrices, view, scale, cx, cy, size, night)))
    return cell


def _size_panel(scene, rest, size, font):
    """The model beside a player-sized figure and a block, standing on the same floor, with a ruler in blocks."""
    width, height = size
    view = _view(-35, 0)
    p = scene.points(rest, view) if len(scene.corners) else np.zeros((1, 4, 3))
    lo, hi = p[..., :2].reshape(-1, 2).min(axis=0), p[..., :2].reshape(-1, 2).max(axis=0)
    cube_width = 16 * (math.cos(math.radians(35)) + math.sin(math.radians(35)))
    wide = 8 + 16 + 5 + cube_width + 6 + (hi[0] - lo[0]) + 3
    tall = max(32.0, hi[1]) + 3 + max(0.0, -lo[1])
    scale = min((width - 12) / wide, (height - 20) / tall)
    panel = Image.new("RGBA", size, _BACKDROP + (255,))
    draw = ImageDraw.Draw(panel)
    floor = height - 16 - max(0.0, -lo[1]) * scale
    draw.line((0, floor, width, floor), fill=_GRID)
    block = 16 * scale
    x = 8 + 6 * scale
    step = 1 if block >= 16 else 2 if block >= 9 else 4 if block >= 4 else 8
    for i in range(0, int((floor - 2) / block) + 1, step):
        y = floor - i * block
        draw.line((x - 6, y, x - 1, y), fill=_INK)
        if i:
            draw.text((1, y - 6), str(i), fill=_INK, font=font)
    draw.line((x - 1, floor, x - 1, floor - int((floor - 2) / block) * block), fill=_INK)
    person = x + 2
    for (a, b, c, d) in ((4, 24, 12, 32), (4, 12, 12, 24), (0, 12, 4, 24), (12, 12, 16, 24), (4, 0, 8, 12), (8, 0, 12, 12)):
        draw.rectangle((person + a * scale, floor - d * scale, person + c * scale, floor - b * scale), fill=(205, 212, 222, 255), outline=(60, 66, 78, 255))
    draw.text((person, floor + 2), "player", fill=_DIM, font=font)
    cube = person + (16 + 5) * scale
    a, b = 16 * math.cos(math.radians(35)) * scale, 16 * math.sin(math.radians(35)) * scale
    draw.rectangle((cube, floor - block, cube + a, floor), fill=(150, 158, 170, 255), outline=(60, 66, 78, 255))
    draw.rectangle((cube + a, floor - block, cube + a + b, floor), fill=(122, 130, 142, 255), outline=(60, 66, 78, 255))
    draw.text((cube, floor + 2), "block", fill=_DIM, font=font)
    start = cube + a + b + 6 * scale
    raster = _raster(scene, rest, view, scale, start - lo[0] * scale, floor, size)
    panel.alpha_composite(Image.fromarray(raster))
    return panel


def _facts(model, scene, rest):
    """The numbers an author budgets against."""
    bones_with_cubes = len(set(scene.bone_of.tolist()))
    tex = model["textures"][0]
    lines = [f"bones {len(model['groups'])}, drawn {bones_with_cubes}", f"cubes {len(model['elements'])}, faces {len(scene.corners)}",
             f"skin {tex['width']}x{tex['height']}"]
    if len(scene.corners):
        p = scene.points(rest).reshape(-1, 3)
        lo, hi = p.min(axis=0), p.max(axis=0)
        lines.append("size in blocks")
        lines.append(f"  x {(hi[0] - lo[0]) / 16:.2f}  y {(hi[1] - lo[1]) / 16:.2f}  z {(hi[2] - lo[2]) / 16:.2f}")
        lines.append(f"lowest point y {lo[1]:.1f} units")
    for a in model["animations"]:
        lines.append(f"{a['name']} {a['length']}s {a['loop']}")
    return lines


def motion_path(out):
    """Where the motion sheet goes for a preview written to this path."""
    out = pathlib.Path(out)
    return out.with_name(f"{out.stem}_motion{out.suffix}")


def preview(model, out=None, scale=4, focus=None, feet=None, still=(), machine=False):
    """A sheet the author reads to fix a model: eight angles, a close view of the face, the model beside a player and a
    block, and the skin. Given a path, it also writes the motion sheet beside it, as <name>_motion.png, which is the one
    to read for how it moves. focus names the bones to look at closely; by default that's the head. feet, still and
    machine go to motion_notes. scale is only here for older callers, since the sheet sizes itself to the model."""
    scene = _Scene(model)
    rest = scene.pose()
    font = ImageFont.load_default(12)
    has_faces = len(scene.corners) > 0
    width, cell, close_w = 1280, 230, 320
    pitch = 14
    label_h = 15

    def caption(sheet, x, y, text):
        ImageDraw.Draw(sheet).text((x + 3, y), text, fill=_INK, font=font)

    angles = (("front", 0), ("front left", -45), ("left", -90), ("back left", -135),
              ("back", 180), ("back right", 135), ("right", 90), ("front right", 45))
    # One scale for all eight, and it has to fit the widest view and the floor beneath the model.
    views = [_view(yaw, pitch) for _, yaw in angles]
    reference = np.vstack([scene.points(rest, v).reshape(-1, 3) for v in views] + [np.array([[0.0, 0, 0]])]) if has_faces else np.zeros((1, 3))
    # Each cell is framed around its own centre, and the scale comes from the largest extent in any view.
    spans = [scene.points(rest, v) if has_faces else np.zeros((1, 4, 3)) for v in views]
    base = max(np.ptp(s[..., 0]) for s in spans), max(np.ptp(s[..., 1]) for s in spans)
    shared = min((cell - 14) / max(base[0], 1), (cell - 14) / max(base[1], 1))
    shared = _tidy_scale(shared)
    reach = max(16.0, float(np.abs(reference[:, 0]).max()))

    row_top = 2 * (cell + label_h) + 8
    info_h = 230
    height = row_top + info_h + label_h + 8
    sheet = Image.new("RGBA", (width, height), (58, 66, 78, 255))

    for i, ((label, yaw), view, span) in enumerate(zip(angles, views, spans)):
        x, y = (i % 4) * cell, (i // 4) * (cell + label_h)
        lo, hi = span[..., :2].reshape(-1, 2).min(axis=0), span[..., :2].reshape(-1, 2).max(axis=0)
        cx, cy = cell / 2 - shared * (lo[0] + hi[0]) / 2, cell / 2 + shared * (lo[1] + hi[1]) / 2
        sheet.alpha_composite(_shot(scene, rest, view, shared, cx, cy, (cell, cell), reach), (x, y))
        caption(sheet, x, y + cell + 1, label)

    # Close views of the head, or of the whole front if there's nothing called a head.
    names = [focus] if isinstance(focus, str) else list(focus) if focus else [g["name"] for g in model["groups"] if g["name"].startswith("head")]
    mask = scene.faces_of(names) if names else np.ones(len(scene.corners), bool)
    if has_faces and not mask.any():
        mask = np.ones(len(scene.corners), bool)
    close_x = 4 * cell + 6
    close_size = (width - close_x, cell)
    for i, (label, yaw, tilt) in enumerate((("face on", 0, 0), ("three quarters", -40, 10))):
        view = _view(yaw, tilt)
        p = scene.points(rest, view)[mask] if has_faces else np.zeros((1, 4, 3))
        s, cx, cy = _fit(p, close_size, margin=10, limit=40)
        y = i * (cell + label_h)
        sheet.alpha_composite(_shot(scene, rest, view, s, cx, cy, close_size, reach), (close_x, y))
        caption(sheet, close_x, y + cell + 1, f"{label}, {s:.3g} px per unit")

    # What it's beside, the skin, the numbers, and how it looks in the dark if anything on it glows.
    x = 0
    size_w = 610
    sheet.alpha_composite(_size_panel(scene, rest, (size_w, info_h), font), (0, row_top))
    caption(sheet, 0, row_top + info_h + 1, "size: a player is 2 blocks tall")
    x = size_w + 6
    side = model["textures"][0]["width"]
    tex_view = Image.new("RGBA", (info_h, info_h), (40, 44, 52, 255))
    tex_view.alpha_composite(skin(model).resize((info_h, info_h), Image.NEAREST))
    sheet.alpha_composite(tex_view, (x, row_top))
    caption(sheet, x, row_top + info_h + 1, f"skin {side}x{side}")
    x += info_h + 6
    if has_faces and scene.emission.any():
        # Seen from the side the light is on, which may not be the front.
        world = scene.points(rest)
        glowing = world[scene.emission > 0].reshape(-1, 3).mean(axis=0) - world.reshape(-1, 3).mean(axis=0)
        yaw = math.degrees(math.atan2(glowing[0], -glowing[2])) if np.hypot(glowing[0], glowing[2]) > 4 else -35
        view = _view(yaw, pitch)
        s, cx, cy = _fit(scene.points(rest, view), (info_h, info_h), margin=8)
        sheet.alpha_composite(_shot(scene, rest, view, s, cx, cy, (info_h, info_h), reach, night=True), (x, row_top))
        caption(sheet, x, row_top + info_h + 1, "in the dark")
        x += info_h + 6
    for i, line in enumerate(_facts(model, scene, rest)):
        ImageDraw.Draw(sheet).text((x + 2, row_top + 2 + i * 15), line, fill=_INK, font=font)

    if out:
        pathlib.Path(out).parent.mkdir(parents=True, exist_ok=True)
        sheet.convert("RGB").save(out)
        if model["animations"]:
            motion_sheet(model, motion_path(out), feet, still, machine, scene)
    return sheet


# ---------------------------------------------------------------- motion

_FOOT_NAME = re.compile(r"(^|_)(leg|foot|feet|shin|paw|hoof|toe)s?(_|\d|$)")
_ORDER = {"idle": 0, "walk": 1, "attack": 2, "hurt": 3, "death": 4}
_TRAIL_COLORS = ((255, 214, 90), (120, 220, 255), (255, 130, 130), (160, 240, 150), (220, 160, 255), (255, 170, 80), (130, 170, 255), (240, 240, 240))


def _cyclic_runs(mask):
    """Runs of True in a loop of frames, as lists of frame numbers, joined across the seam."""
    n = len(mask)
    if mask.all():
        return [list(range(n))]
    start = int(np.argmin(mask))
    runs, run = [], []
    for k in range(n):
        i = (start + k) % n
        if mask[i]:
            run.append(i)
        elif run:
            runs.append(run)
            run = []
    if run:
        runs.append(run)
    return runs


class _Motion:
    """Measures animations as BIL plays them, frame by frame at 20 a second, in the model's own frame of reference."""

    def __init__(self, model, scene=None, feet=None, still=()):
        self.model = model
        self.scene = scene or _Scene(model)
        self.names = [next(g["name"] for g in model["groups"] if g["uuid"] == u) for u in self.scene.bones]
        self.index = {n: i for i, n in enumerate(self.names)}
        self.still = set(still)
        self.rest = self.scene.pose()
        self.frames_cache = {}
        self.children = {n: [] for n in self.names}

        def walk(node, parent):
            name = self.names[self.scene.bones.index(node["uuid"])]
            if parent:
                self.children[parent].append(name)
            for child in node["children"]:
                if isinstance(child, dict):
                    walk(child, name)

        for root in model["outliner"]:
            walk(root, None)
        self.corners = {}
        for b, name in enumerate(self.names):
            faces = self.scene.corners[self.scene.bone_of == b]
            if len(faces):
                self.corners[name] = np.unique(faces.reshape(-1, 3), axis=0)
        self.feet = self._find_feet(feet)

    def _world(self, matrices, name):
        c = self.corners[name]
        return c @ matrices[..., self.index[name], :3, :3].swapaxes(-1, -2) + matrices[..., self.index[name], None, :3, 3]

    def _find_feet(self, named):
        """Bones that reach the ground at rest and are named or declared as feet, with the point on each that takes the
        weight: the middle of its lowest surface."""
        if isinstance(named, dict) and named:
            return {name: np.asarray(point, float) for name, point in named.items() if name in self.corners}
        out = {}
        for name in named or [n for n in self.names if _FOOT_NAME.search(n)]:
            if name not in self.corners:
                continue
            world = self._world(self.rest, name)
            low = world[:, 1].min()
            if low > 1.5 and not named:
                continue
            sole = self.corners[name][world[:, 1] <= low + 0.75]
            out[name] = sole.mean(axis=0)
        return out

    def frames(self, a):
        """Times and bone matrices of every frame of an animation."""
        if a["name"] not in self.frames_cache:
            times = np.arange(int(round(a["length"] / TICK)) + 1) * TICK
            self.frames_cache[a["name"]] = times, self.scene.series(a["name"], times)
        return self.frames_cache[a["name"]]

    def foot_paths(self, a):
        """For each foot: where its sole is and how low it gets in every frame, and when it's on the ground."""
        _, m = self.frames(a)
        out = {}
        for name, sole in self.feet.items():
            b = self.index[name]
            path = sole @ m[:, b, :3, :3].swapaxes(-1, -2) + m[:, b, :3, 3]
            low = self._world(m, name)[..., 1].min(axis=-1)
            resting = self._world(self.rest, name)[:, 1].min()
            contact = low <= resting + 0.8
            info = {"path": path, "low": low, "contact": contact, "lift": float(low.max() - resting), "slide": 0.0, "velocity": None}
            looped = a["loop"] == "loop"
            runs = _cyclic_runs(contact) if looped else []
            velocities, weights = [], []
            for run in runs:
                if len(run) < 3:
                    continue
                steps = np.arange(len(run)) * TICK
                fit = np.polyfit(steps, path[run][:, [0, 2]], 1)
                error = path[run][:, [0, 2]] - (steps[:, None] * fit[0] + fit[1])
                info["slide"] = max(info["slide"], float(np.linalg.norm(error, axis=1).max()))
                velocities.append(fit[0])
                weights.append(len(run))
            if velocities:
                info["velocity"] = np.average(velocities, axis=0, weights=weights)
            out[name] = info
        return out

    def ground_speed(self):
        """How fast the feet go past on the ground in walk, in blocks a second, which is how fast the mob has to move for
        them to look planted. None if nothing measurable touches the ground."""
        walk = next((a for a in self.model["animations"] if a["name"] == "walk"), None)
        if walk is None or not self.feet:
            return None
        speeds = [np.linalg.norm(f["velocity"]) for f in self.foot_paths(walk).values() if f["velocity"] is not None and not f["contact"].all()]
        return round(float(np.median(speeds)) / 16, 2) if speeds else None

    def notes(self, machine=False):
        """Plain measurements of motion that looks dead or wrong, as sentences."""
        out = []
        anims = self.model["animations"]
        if not anims:
            return out
        moved = dict.fromkeys(self.names, 0.0)
        for a in anims:
            times, m = self.frames(a)
            rot, pos, scl = self.scene.tracks(a["name"], times)
            for b, name in enumerate(self.names):
                moved[name] = max(moved[name], float(np.ptp(rot[:, b], axis=0).max()), 8 * float(np.ptp(pos[:, b], axis=0).max()), 60 * float(np.ptp(scl[:, b], axis=0).max()))
            looped = a["loop"] == "loop"
            label = f"{a['name']}:"
            step = np.abs(np.diff(rot, axis=0)).max(axis=(0, 2)) if len(times) > 1 else np.zeros(len(self.names))
            fast = [self.names[b] for b in np.nonzero(step > 90)[0]]
            if fast:
                out.append(f"{label} {fast[0]} turns over 90 degrees in a tick, which the game can show going the wrong way. Slow it down")
            if looped and len(times) > 2:
                moves = np.linalg.norm(m[1:, :, :3, 3] - m[:-1, :, :3, 3], axis=2).max(axis=0)
                seam = np.linalg.norm(m[0, :, :3, 3] - m[-1, :, :3, 3], axis=1)
                turns = np.abs(np.diff(rot, axis=0)).max(axis=(0, 2))
                wrapped = np.abs((rot[0] - rot[-1] + 180) % 360 - 180).max(axis=1)
                bad = [self.names[b] for b in range(len(self.names)) if seam[b] > max(2 * moves[b], 0.25) or wrapped[b] > max(2 * turns[b], 2.0)]
                if bad:
                    out.append(f"{label} the loop's last frame doesn't meet its first: {bad[0]} jumps at the seam. Use whole cycles")
            elif a["name"] != "death" and a["loop"] == "once" and len(times) > 1:
                off = np.maximum(np.abs((rot[-1] + 180) % 360 - 180).max(axis=1), 8 * np.abs(pos[-1]).max(axis=1))
                if off.max() > 3.0:
                    out.append(f"{label} it ends away from rest, with {self.names[int(np.argmax(off))]} still out, so the model jumps when it finishes. Bring everything back by the end")
            if self.corners:
                lowest = min(float(self._world(m, name)[..., 1].min()) for name in self.corners)
                rest_low = min(float(self._world(self.rest, name)[:, 1].min()) for name in self.corners)
                if lowest < min(rest_low, 0.0) - 1.0:
                    deepest = min(self.corners, key=lambda name: float(self._world(m, name)[..., 1].min()))
                    frame = int(np.argmin(self._world(m, deepest)[..., 1].min(axis=-1)))
                    out.append(f"{label} {deepest} sinks {-lowest:.1f} units through the floor at {times[frame]:.2f}s")
        walk = next((a for a in anims if a["name"] == "walk"), None)
        if walk is not None and not machine:
            times, m = self.frames(walk)
            feet = self.foot_paths(walk)
            plain = [n for n in self.corners if n not in feet]
            if plain:
                body = max(plain, key=lambda n: (self.scene.bone_of == self.index[n]).sum())
                b = self.index[body]
                turned = np.abs(np.diff(m[:, b, :3, :3], axis=0)).max() if len(times) > 1 else 0.0
                if np.ptp(m[:, b, :3, 3], axis=0).max() < 0.15 and turned < 0.01:
                    out.append(f"walk: the body ({body}) doesn't move at all, which reads as a model on rails. Give it a rise and fall at each step")
            velocities = [f["velocity"] for f in feet.values() if f["velocity"] is not None and not f["contact"].all()]
            typical = np.median(velocities, axis=0) if velocities else None
            for name, f in feet.items():
                if not f["contact"].any():
                    continue
                if f["contact"].all():
                    out.append(f"walk: {name} never lifts, it stays within a unit of the ground for the whole cycle, so it skates. Lift it")
                    continue
                allowed = max(0.75, 0.15 * float(np.ptp(f["path"][:, [0, 2]], axis=0).max()))
                if f["slide"] > allowed:
                    out.append(f"walk: {name} slides {f['slide']:.1f} units while it's on the ground. A planted foot moves in a straight line at a steady speed")
                elif typical is not None and f["velocity"] is not None and np.linalg.norm(typical) > 2:
                    if np.linalg.norm(f["velocity"] - typical) > max(2.0, 0.4 * np.linalg.norm(typical)):
                        out.append(f"walk: {name} moves on the ground at a different speed from the other feet, so one of them is skating")
        for name in self.names:
            if moved[name] >= 0.5 or name in self.still:
                continue
            has_children = bool(self.children[name])
            if name not in self.corners and not has_children:
                continue
            if machine and not has_children:
                continue
            if machine and name == self.names[0]:
                continue
            kind = "though it has parts hanging off it" if has_children else "though it's a limb"
            out.append(f"part {name!r} never moves in any animation, {kind}. Move it, or pass still=True if it's meant to stay put")
        return out


def motion_notes(model, feet=None, still=(), machine=False, scene=None):
    """Measured problems with a model's motion, as a list of sentences. feet names the bones that walk, and otherwise
    bones named leg, foot, shin, paw, hoof or toe that reach the ground count. still names bones meant not to move."""
    return _Motion(model, scene, feet, still).notes(machine)


def _pick_view(motion, a):
    """Side on for a walk, where footfalls are clearest. Something long with no feet slithers, and that shows from above."""
    if a["name"] != "walk":
        return "three quarters", _view(-55, 10)
    going = [f["velocity"] for f in motion.foot_paths(a).values() if f["velocity"] is not None]
    if going and abs(np.median(going, axis=0)[0]) > abs(np.median(going, axis=0)[1]):
        return "from the front, since it walks sideways", _view(0, 4)
    if not motion.feet and len(motion.scene.corners):
        rest = motion.scene.points(motion.rest).reshape(-1, 3)
        size = np.ptp(rest, axis=0)
        if max(size[0], size[2]) > 1.5 * size[1]:
            return "from above", _view(-90, 72)
    return "side on", _view(-90, 4)


def _trails(motion, m):
    """The points that travel furthest, as (name, path through the frames): the far end of each outermost bone, and the
    middle of the biggest."""
    drawn = list(motion.corners)
    tips = {}
    for name in drawn:
        if any(c in drawn for c in _descendants(motion, name)):
            continue
        c = motion.corners[name]
        tips[name] = c[int(np.argmax(np.linalg.norm(c, axis=1)))]
    if drawn:
        biggest = max(drawn, key=lambda n: (motion.scene.bone_of == motion.index[n]).sum())
        tips.setdefault(biggest, motion.corners[biggest].mean(axis=0))
    paths = []
    for name, point in tips.items():
        b = motion.index[name]
        path = point @ m[:, b, :3, :3].swapaxes(-1, -2) + m[:, b, :3, 3]
        travel = float(np.linalg.norm(np.diff(path, axis=0), axis=1).sum())
        paths.append((travel, name, path))
    paths.sort(key=lambda t: -t[0])
    return [(name, path) for travel, name, path in paths[:8] if travel > 0.5]


def _descendants(motion, name):
    found = []
    for child in motion.children[name]:
        found += [child] + _descendants(motion, child)
    return found


def _onion(rasters, backdrop):
    """A whole cycle laid over itself, each frame tinted from cool at the start to warm at the end, so that the extremes
    of a movement show where the colours spread out."""
    out = np.asarray(backdrop.convert("RGB"), float).copy()
    n = len(rasters)
    for i, raster in enumerate(rasters):
        t = i / max(n - 1, 1)
        tint = np.array((90 + 165 * t, 170 - 40 * t, 255 - 215 * t))
        a = (raster[..., 3:] / 255.0) * (0.34 if i else 0.5)
        out = out * (1 - a) + (raster[..., :3] * 0.45 + tint * 0.55) * a
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8)).convert("RGBA")


def _curves(draw, box, motion, a, times, font):
    """The bones that move most, as a line each across the animation, so overshoot, snaps and holds show as shapes."""
    x0, y0, x1, y1 = box
    rot, pos, scl = motion.scene.tracks(a["name"], times)
    amounts = []
    for b, name in enumerate(motion.names):
        grown = np.abs(scl[:, b] - 1).max(axis=1)
        for value, unit, weight in ((rot[:, b, int(np.argmax(np.ptp(rot[:, b], axis=0)))], "deg", 1.0),
                                    (pos[:, b, int(np.argmax(np.ptp(pos[:, b], axis=0)))], "u", 8.0),
                                    (grown, "x", 60.0)):
            span = float(np.ptp(value))
            if span > 0.01:
                amounts.append((span * weight, name, value, unit, span))
    amounts.sort(key=lambda t: -t[0])
    draw.rectangle(box, fill=(46, 52, 62))
    if len(times) < 2:
        return
    for i, (_, name, value, unit, span) in enumerate(amounts[:3]):
        scale = (y1 - y0 - 4) / max(span, 1e-6)
        low = float(value.min())
        points = [(x0 + (x1 - x0) * k / (len(times) - 1), y1 - 2 - (float(v) - low) * scale) for k, v in enumerate(value)]
        draw.line(points, fill=_TRAIL_COLORS[i], width=1)
        draw.text((x0 + 3 + i * 150, y0), f"{name} {span:.3g}{unit}", fill=_TRAIL_COLORS[i], font=font)


def motion_sheet(model, out=None, feet=None, still=(), machine=False, scene=None):
    """A second sheet just for how a model moves. For each animation: a strip of curves for the bones that move most,
    evenly spaced frames, and the whole cycle laid over itself with trails whose dots are one tick apart, so close dots
    are slow and far ones fast. A walk also gets a side view and a chart of when each foot is down. Measured problems go
    at the top."""
    scene = scene or _Scene(model)
    motion = _Motion(model, scene, feet, still)
    font = ImageFont.load_default(11)
    title_font = ImageFont.load_default(13)
    notes = motion.notes(machine)
    anims = sorted(model["animations"], key=lambda a: (_ORDER.get(a["name"], 9), a["name"]))
    width, onion_w, shots = 1400, 260, 6
    top = 22 + 13 * max(1, min(len(notes), 7))
    rows = []
    for a in anims:
        label, view = _pick_view(motion, a)
        rows.append((a, label, view))
        if a["name"] == "walk":
            rows.append((a, "three quarters", _view(-55, 10)))
    chart_h = 22 + 12 * len(motion.feet) if motion.feet and any(a["name"] == "walk" for a in anims) else 0
    label_h, curve_h = 15, 26
    cell = (width - onion_w) // shots
    frame_h = cell
    if rows:
        frame_h = int(min(cell, max(110, (1490 - top - chart_h) / len(rows) - label_h - curve_h - 12)))
    fits = int((1490 - top - chart_h) // (frame_h + label_h + curve_h + 12)) if rows else 0
    hidden = rows[fits:]
    rows = rows[:fits]
    height = top + chart_h + len(rows) * (frame_h + label_h + curve_h + 12) + 4
    sheet = Image.new("RGBA", (width, height), (58, 66, 78, 255))
    draw = ImageDraw.Draw(sheet)
    draw.text((6, 4), f"{model['name']}: how it moves", fill=_INK, font=title_font)
    if notes:
        for i, note in enumerate(notes[:7]):
            draw.text((6, 22 + 13 * i), note, fill=(255, 170, 130), font=font)
    else:
        draw.text((6, 22), "No problems measured in its motion. That doesn't make it good: read the shapes below.", fill=(170, 230, 170), font=font)
    y = top
    has_faces = len(scene.corners) > 0
    reach = 16.0
    if has_faces:
        reach = max(16.0, float(np.abs(scene.points(motion.rest).reshape(-1, 3)[:, [0, 2]]).max()))
    size = (cell, frame_h)
    onion_size = (onion_w, frame_h)
    for a, label, view in rows:
        times, m = motion.frames(a)
        looped = a["loop"] == "loop"
        count = 12
        cycle = a["length"] + TICK if looped else a["length"]
        phases = np.arange(count) / count if looped else np.linspace(0, 1, count)
        poses = scene.series(a["name"], phases * cycle)
        cover = np.concatenate([scene.points(pose, view) for pose in poses[::2]]) if has_faces else np.zeros((1, 4, 3))
        scale, cx, cy = _fit(cover, size, margin=6)
        rasters = [_raster(scene, pose, view, scale, cx, cy, size) if has_faces else np.zeros(size[::-1] + (4,), np.uint8) for pose in poses]
        shown = np.round(np.linspace(0, count - 1, shots)).astype(int) if not looped else np.arange(shots) * count // shots
        draw.text((4, y + 1), f"{a['name']}  {cycle:.2f}s {a['loop']}, {label}", fill=_INK, font=title_font)
        y += label_h
        _curves(draw, (2, y, shots * cell - 2, y + curve_h - 2), motion, a, times, font)
        for i, k in enumerate(shown):
            x = i * cell
            backdrop = Image.new("RGBA", size, _BACKDROP + (255,))
            _floor(backdrop, view, scale, cx, cy, reach)
            backdrop.alpha_composite(Image.fromarray(rasters[k]))
            sheet.alpha_composite(backdrop, (x, y + curve_h))
            draw.text((x + 3, y + curve_h + frame_h - 13), f"{phases[k] * cycle:.2f}s", fill=_INK, font=font)
        # The overlay uses the same picture a little wider, with the floor and trails drawn over it.
        ox = shots * cell
        centered = cx + (onion_w - cell) / 2
        ghost_rasters = [np.pad(r, ((0, 0), (int((onion_w - cell) / 2), onion_w - cell - int((onion_w - cell) / 2)), (0, 0))) for r in rasters]
        backdrop = Image.new("RGBA", onion_size, _BACKDROP + (255,))
        _floor(backdrop, view, scale, centered, cy, reach)
        composite = _onion(ghost_rasters, backdrop)
        ghost_draw = ImageDraw.Draw(composite)
        for t, (name, path) in enumerate(_trails(motion, m)):
            color = _TRAIL_COLORS[t % len(_TRAIL_COLORS)]
            screen = (view[:3, :3] @ path.T).T + view[:3, 3]
            xy = [(centered + p[0] * scale, cy - p[1] * scale) for p in screen]
            ghost_draw.line(xy + (xy[:1] if looped else []), fill=color, width=1)
            for px, py in xy:
                ghost_draw.rectangle((px - 1, py - 1, px + 1, py + 1), fill=color)
            ghost_draw.text((xy[0][0] + 3, xy[0][1] - 11), name, fill=color, font=font)
        sheet.alpha_composite(composite, (ox, y + curve_h))
        y += curve_h + frame_h + 12
        if a["name"] == "walk" and chart_h and label != "three quarters":
            feet_info = motion.foot_paths(a)
            draw.text((4, y - 11), "when each foot is down, across one cycle:", fill=_DIM, font=font)
            speed = motion.ground_speed()
            if speed:
                draw.text((330, y - 11), f"feet pass at {speed} blocks a second, so a mob moving that fast looks planted", fill=_DIM, font=font)
            y += 4
            bar_x0, bar_x1 = 230, width - 8
            for i, (name, f) in enumerate(feet_info.items()):
                row_y = y + i * 12
                draw.text((4, row_y - 1), f"{name}  lifts {f['lift']:.1f}, slides {f['slide']:.1f}", fill=_INK, font=font)
                n = len(f["contact"])
                draw.rectangle((bar_x0, row_y + 1, bar_x1, row_y + 9), fill=(46, 52, 62))
                for k, on in enumerate(f["contact"]):
                    if on:
                        a0 = bar_x0 + (bar_x1 - bar_x0) * k / n
                        a1 = bar_x0 + (bar_x1 - bar_x0) * (k + 1) / n
                        draw.rectangle((a0, row_y + 1, a1, row_y + 9), fill=(190, 200, 215))
            y += chart_h - 8
    if hidden:
        draw.text((width - 300, 4), "no room to show: " + ", ".join(sorted({r[0]["name"] for r in hidden})), fill=(255, 170, 130), font=font)
    if out:
        pathlib.Path(out).parent.mkdir(parents=True, exist_ok=True)
        sheet.convert("RGB").save(out)
    return sheet


# ---------------------------------------------------------------- command line

def main(argv=None):
    parser = argparse.ArgumentParser(description="Generate a mob as a .bbmodel with idle and walk animations.")
    parser.add_argument("kind", choices=sorted(KINDS))
    parser.add_argument("name", help="lowercase letters, digits and underscores")
    parser.add_argument("-o", "--out", help="output file (default <name>.bbmodel)")
    parser.add_argument("--preview", help="also write a preview sheet to this PNG")
    args, rest = parser.parse_known_args(argv)
    if len(rest) % 2:
        parser.error("options must be --name value pairs")
    kwargs = {}
    for flag, value in zip(rest[::2], rest[1::2]):
        value = value.lower() == "true" if value.lower() in ("true", "false") else value
        kwargs[flag.lstrip("-").replace("-", "_")] = int(value) if isinstance(value, str) and value.isdigit() else value
    model = KINDS[args.kind](args.name, **kwargs)
    for problem in check(model):
        print(f"PROBLEM: {problem}", file=sys.stderr)
    print(save(model, args.out or f"{args.name}.bbmodel"))
    if args.preview:
        preview(model, args.preview)
        print(args.preview)
    return 0


if __name__ == "__main__":
    sys.exit(main())
