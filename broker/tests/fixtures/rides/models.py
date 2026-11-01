"""Models for the rides fixture, made the way a builder would make them. Each has a bright front, because which way a thing points is one of the things being tested.

Usage: python3 models.py <folder to write them in>
"""
import pathlib
import sys

from assetkit import sculpt

BRIGHT = "#ffe040"
HULL = "#a06a38"
HULL_DARK = "#6a4422"
STEEL = "#7a828e"
RED = "#c8402c"
BLUE = "#3c64c8"


def bolt():
    m = sculpt.Model("rides_bolt", shade=0.4)
    shaft = m.part("shaft", pivot=(0, 3, 0))
    shaft.box((-1, 2, -2), (1, 4, 6), BLUE)
    shaft.box((-2, 1, -6), (2, 5, -2), BRIGHT)
    m.animate("idle", 0.6, sculpt.spin(shaft, axis="z", turns=1))
    return m


def skiff():
    m = sculpt.Model("rides_skiff", shade=0.4)
    hull = m.part("hull", pivot=(0, 0, 0))
    hull.box((-11, 0, -16), (11, 8, 16), HULL)
    hull.cut.box((-9, 3, -13), (9, 8, 13))
    hull.box((-11, 8, -18), (11, 12, -14), BRIGHT)
    hull.box((-2, 3, -2), (2, 8, 2), HULL_DARK)
    sail = m.part("sail", parent=hull, pivot=(0, 8, 8))
    sail.box((-1, 8, 7), (1, 34, 9), HULL_DARK)
    sail.box((-1, 14, 2), (0, 32, 7), RED)
    m.animate("idle", 3.0, sculpt.bob(hull, 0.4))
    m.animate("walk", 1.0, sculpt.bob(hull, 0.8, cycles=2))
    return m


def rover():
    m = sculpt.Model("rides_rover", shade=0.4)
    body = m.part("body", pivot=(0, 6, 0))
    body.box((-10, 5, -14), (10, 13, 14), RED)
    body.cut.box((-8, 8, -4), (8, 13, 10))
    body.box((-10, 13, -14), (10, 16, -10), BRIGHT)
    for name, x, z in (("wheel_a", -11, -9), ("wheel_b", 11, -9), ("wheel_c", -11, 9), ("wheel_d", 11, 9)):
        wheel = m.part(name, parent=body, pivot=(x, 4, z))
        wheel.box((x - 2, 0, z - 4), (x + 2, 8, z + 4), STEEL)
    m.animate("idle", 2.0, sculpt.bob(body, 0.15))
    m.animate("walk", 0.5, *(sculpt.spin(m.parts[name], axis="x", turns=1) for name in ("wheel_a", "wheel_b", "wheel_c", "wheel_d")))
    return m


def glider():
    m = sculpt.Model("rides_glider", shade=0.4)
    body = m.part("body", pivot=(0, 6, 0))
    body.box((-5, 3, -14), (5, 10, 12), BLUE)
    body.box((-5, 10, -14), (5, 12, -10), BRIGHT)
    body.box((-22, 8, -4), (22, 10, 6), STEEL)
    m.animate("idle", 3.0, sculpt.bob(body, 0.6))
    return m


def totem():
    m = sculpt.Model("rides_totem", shade=0.4)
    base = m.part("base", pivot=(0, 0, 0))
    base.box((-6, 0, -6), (6, 8, 6), HULL_DARK)
    head = m.part("head", parent=base, pivot=(0, 16, 0))
    head.box((-5, 8, -5), (5, 30, 5), STEEL)
    head.box((-6, 22, -7), (6, 26, -5), BRIGHT)
    m.animate("idle", 4.0, sculpt.bob(head, 0.8))
    m.animate("spin", 1.0, sculpt.spin(head, axis="y", turns=1), loop="once")
    return m


def main(folder):
    target = pathlib.Path(folder)
    target.mkdir(parents=True, exist_ok=True)
    for name, make in (("bolt", bolt), ("skiff", skiff), ("rover", rover), ("glider", glider), ("totem", totem)):
        # These print what the model kit makes of them. Some of what it says is for creatures, like having a face, so it does not stop the test.
        make().finish(str(target / f"{name}.bbmodel"), preview=str(target / f"{name}.png"), machine=True)


if __name__ == "__main__":
    main(sys.argv[1])
