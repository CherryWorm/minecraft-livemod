#!/usr/bin/env python3
"""Simple mobs as Blockbench .bbmodel files, for loading with Blockbench Import Library (BIL).

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

        png = io.BytesIO()
        Image.fromarray(skin).save(png, "PNG")
        texture = {"path": "", "name": "skin.png", "folder": "", "namespace": "", "id": "0", "group": "",
                   "width": side, "height": side, "uv_width": side, "uv_height": side, "particle": False,
                   "use_as_default": False, "layers_enabled": False, "render_mode": "default", "render_sides": "auto",
                   "pbr_channel": "color", "frame_time": 1, "frame_order_type": "loop", "frame_order": "",
                   "frame_interpolate": False, "visible": True, "internal": True, "saved": True,
                   "uuid": self.id("texture"), "relative_path": "",
                   "source": "data:image/png;base64," + base64.b64encode(png.getvalue()).decode()}
        return {"meta": {"format_version": FORMAT_VERSION, "model_format": "free", "box_uv": False},
                "name": self.name, "model_identifier": self.name, "visible_box": [1, 1, 0],
                "variable_placeholders": "", "variable_placeholder_buttons": [], "bedrock_animation_mode": "entity",
                "timeline_setups": [], "unhandled_root_fields": {}, "resolution": {"width": side, "height": side},
                "elements": elements, "groups": groups, "outliner": [outline(self.bones[next(iter(self.bones))])],
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


def check(model):
    """Everything BIL's importer needs from a file, as a list of problems. Empty means it should load.
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
        if under_head:
            problems.append(f"bone {name!r} is inside a head bone, which BIL's docs say doesn't animate properly")
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
    for wanted in ("idle", "walk"):
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


def _sample(keys, t, channel, default):
    keys = sorted((k for k in keys if k["channel"] == channel), key=lambda k: k["time"])
    if not keys:
        return default
    ts = [k["time"] for k in keys]
    return tuple(float(np.interp(t, ts, [k["data_points"][0][a] for k in keys])) for a in "xyz")


def _pose(model, anim_name=None, t=0.0):
    """Bone matrices at a moment of an animation, the way BIL's 5.x importer composes them."""
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
        local = np.array(g["origin"], float) - parent_origin + np.array(pos)
        m = parent_m @ _mat(rot[0], rot[1], rot[2], local, scl)
        out[g["uuid"]] = m
        for child in node["children"]:
            if isinstance(child, dict):
                walk(child, m, np.array(g["origin"], float))
            else:
                out[child] = (m, np.array(g["origin"], float))

    for root in model["outliner"]:
        walk(root, np.eye(4), np.zeros(3))
    return out


_FACE_SHADE = {"up": 1.0, "north": 0.82, "south": 0.82, "east": 0.62, "west": 0.62, "down": 0.5}


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


def render(model, anim=None, t=0.0, yaw=-35.0, pitch=22.0, scale=5, size=None):
    """Draw the model with a simple orthographic view. yaw=0 looks straight at its face."""
    tex = np.asarray(skin(model))
    pose = _pose(model, anim, t)
    view = _mat(rx=pitch) @ _mat(ry=180 + yaw)
    size = size or (56 * scale, 56 * scale)
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img, "RGBA")
    cx, cy = size[0] / 2, size[1] * 0.72
    polys = []
    for order, e in enumerate(model["elements"]):
        m, origin = pose[e["uuid"]]
        world = view @ m
        for face, corners in _corners(e["from"], e["to"]).items():
            pts = np.array([list(np.array(c, float) - origin) + [1.0] for c in corners]).T
            p = (world @ pts)[:3].T
            # Corners run left to right and top to bottom as seen from outside, which is a clockwise
            # turn on screen, so a face toward the viewer has a normal pointing away along z.
            if np.cross(p[1] - p[0], p[3] - p[0])[2] >= 0:
                continue
            u0, v0, u1, v1 = (int(v) for v in e["faces"][face]["uv"])
            polys.append((float(p[:, 2].mean()), order, p, (u0, v0, u1, v1), _FACE_SHADE[face]))
    for _, _, p, (u0, v0, u1, v1), shade in sorted(polys, key=lambda q: (q[0], q[1])):
        w, h = max(u1 - u0, 1), max(v1 - v0, 1)
        for j in range(h):
            for i in range(w):
                c = tex[v0 + j, u0 + i]
                if c[3] == 0:
                    continue
                quad = []
                for fu, fv in ((i / w, j / h), ((i + 1) / w, j / h), ((i + 1) / w, (j + 1) / h), (i / w, (j + 1) / h)):
                    top = p[0] + (p[1] - p[0]) * fu
                    bottom = p[3] + (p[2] - p[3]) * fu
                    q = top + (bottom - top) * fv
                    quad.append((cx + q[0] * scale, cy - q[1] * scale))
                draw.polygon(quad, fill=tuple(int(v * shade) for v in c[:3]) + (int(c[3]),))
    return img


def preview(model, out=None, scale=4):
    """A sheet the builder reads to critique a mob: four angles, idle and walk poses, and the skin."""
    views = [("front", None, 0, 0), ("3/4", None, 0, -35), ("side", None, 0, -90), ("back", None, 0, 180)]
    names = {a["name"] for a in model["animations"]}
    for anim, label in (("idle", "idle"), ("walk", "walk")):
        if anim in names:  # these phases catch both once-per-loop and twice-per-loop motion at its extremes
            views += [(f"{label} {p:.3f}", anim, p, -55) for p in (0.125, 0.25, 0.375, 0.75)]
    cell = 56 * scale
    font = ImageFont.load_default()
    tex = skin(model)
    tex_big = tex.resize((192, 192), Image.NEAREST)
    width, rows = cell * 4 + 212, (len(views) + 3) // 4
    sheet = Image.new("RGBA", (width, rows * (cell + 16)), (84, 96, 110, 255))
    draw = ImageDraw.Draw(sheet)
    lengths = {a["name"]: a["length"] for a in model["animations"]}
    for i, (label, anim, phase, yaw) in enumerate(views):
        x, y = (i % 4) * cell, (i // 4) * (cell + 16)
        t = phase * lengths.get(anim, 1)
        sheet.alpha_composite(render(model, anim, t, yaw=yaw, scale=scale), (x, y))
        draw.text((x + 4, y + cell), label, fill=(235, 235, 235), font=font)
    sheet.alpha_composite(tex_big, (cell * 4 + 10, 10))
    draw.text((cell * 4 + 10, 206), f"skin {tex.width}x{tex.height}", fill=(235, 235, 235), font=font)
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
