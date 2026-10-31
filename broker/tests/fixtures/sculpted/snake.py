"""A long purple snake with a hood and yellow bands, as a chain of parts. It slithers with a wave that runs from head to tail,
the way a real one pushes itself along, and it strikes with a long draw back and a fast lunge."""
import time

from assetkit import sculpt
from common import report

start = time.time()

PURPLE = "#7a4aa0"
BELLY = "#e0d094"
YELLOW = "#f0cf3a"
DARK = "#2c1838"
RED = "#d83a3a"

m = sculpt.Model("hooded_serpent")

# Everything is drawn in one straight line along Z, with the front toward -Z. The rest rotations then lay it in an S on
# the floor and rear the front end up, so the geometry stays simple and the curve lives in the pose.
COUNT = 9
STEP = 8
Y = 4.0
RADII = [1.4, 2.2, 2.9, 3.4, 3.7, 3.9, 3.8, 3.6, 3.4, 3.2]
ROOT = 4
# Rotations at each joint. Positive X lifts what's ahead of the joint, and Y swings it sideways.
BENDS = {0: (0, -30, 0), 1: (0, -32, 0), 2: (0, 28, 0), 3: (0, 36, 0), 4: (0, 0, 0),
         5: (0, -26, 0), 6: (24, 8, 0), 7: (36, 10, 0), 8: (32, 8, 0)}


def banded(x, y, z):
    return sculpt.where(lambda x, y, z: y < Y - 2.6, BELLY, sculpt.stripes(PURPLE, YELLOW, along="z", every=8, width=2.5, start=-44))(x, y, z)


parts = {}
for i in list(range(ROOT, COUNT)) + list(range(ROOT - 1, -1, -1)):
    near = (ROOT - i) * STEP + STEP / 2  # the end toward the tail
    far = near - STEP                    # the end toward the head
    parent = None if i == ROOT else parts[i - 1] if i > ROOT else parts[i + 1]
    # A joint sits where a segment meets its parent, so the tail half hinges at its far end.
    pivot_z = near if i >= ROOT else far
    seg = m.part(f"seg{i}", parent=parent, pivot=(0, Y, pivot_z), rotation=BENDS[i])
    seg.taper((0, Y, near), (0, Y, far), RADII[i], RADII[i + 1], banded)
    parts[i] = seg

# The hood fans out of the neck. Its broad side has to face front once the neck is reared up, which is the belly side
# of the unposed segment, so that's where its marking goes.
top = parts[COUNT - 1]
neck = (ROOT - (COUNT - 1)) * STEP - STEP / 2
hood = sculpt.ball((0, Y, neck + 5), (10.5, 2.6, 11))
top.add(hood, sculpt.where(lambda x, y, z: y < Y - 1, sculpt.patch(BELLY, YELLOW, (0, Y, neck + 3), (5, 5, 5), rim=DARK), PURPLE))

# The head has a net rotation of nearly nothing, so it looks forward along -Z, and it's drawn in its own frame.
head = m.part("head", parent=top, pivot=(0, Y, neck), rotation=(-92, 0, 0))
skull = sculpt.where(lambda x, y, z: y < Y - 1.4, BELLY, PURPLE)
head.ball((0, Y + 1, neck - 4), (5.4, 3.6, 6), skull, power=2.4)
head.taper((0, Y + 0.5, neck - 7), (0, Y, neck - 13), 3.6, 2.4, skull)
eye = ["yyy", "ykk"]
head.decal(eye, {"y": YELLOW, "k": DARK}, at=(0, Y + 1.5, neck - 8), facing="right", depth=2)
head.decal(eye, {"y": YELLOW, "k": DARK}, at=(0, Y + 1.5, neck - 8), facing="left", depth=2)
head.decal(["k.k"], {"k": DARK}, at=(0, Y + 1, 0))
head.decal(["ddddddd"], {"d": DARK}, at=(0, Y - 1.5, 0), depth=2)
# A forked tongue, because nothing else says snake so fast.
head.layers(["r...r", ".r.r.", "..r..", "..r.."], {"r": RED}, at=(0, Y - 0.5, neck - 14), facing="top")

NECK = [f"seg{i}" for i in range(COUNT - 1, ROOT, -1)]


def slither(size, cycles=1, waves=1.2, neck=0.25):
    """The body's curve as a wave running from head to tail. A joint's rotation is the bend there, and it has the opposite
    sign in the half whose chain runs toward the head. The neck takes only a share of it, so the raised part stays steady."""
    tracks = []
    for i in range(COUNT):
        along = (COUNT - 1 - i) / COUNT          # 0 at the neck, nearly 1 at the tail tip
        if i == ROOT:
            continue
        sign = -1 if i > ROOT else 1
        amount = size * (neck + (1 - neck) * min(along * 2.2, 1.0))
        tracks.append(sculpt.swing(f"seg{i}", sign * amount, axis="y", cycles=cycles, phase=-waves * along))
    return tracks


# Idle: coiled and watching. The neck sways slowly, the tail shifts, and the tongue would flicker if it had a bone of its own.
m.animate("idle", 4.0,
          *slither(4, waves=0.8, neck=0.35),
          sculpt.keyed(f"seg{COUNT - 1}", rotation=[(0, (0, 0, 0)), (0.5, (3, 0, 0)), (1, (0, 0, 0))], scale=[(0, (1, 1, 1)), (0.5, (1.03, 1, 1)), (1, (1, 1, 1))]),
          sculpt.glance("head", (0.2, 16, 0), (0.45, -14, 3), (0.7, 6, -4), speed=0.03))

# Walk: real slither. The wave runs from head to tail and grows, with the head held still on top of it all.
m.animate("walk", 1.3,
          *slither(17),
          sculpt.steady("head", amount=0.85, level=0.5),
          sculpt.swing(f"seg{COUNT - 1}", 3, axis="z", phase=0.1))

# Attack: it draws its neck back into a tight S and spreads its hood, then the whole front strikes at once and recoils.
lash = sculpt.snap(windup=0.5, hit=0.6, back=0.7, over=0.1, hold=0.05)
m.animate("attack", 0.9,
          sculpt.move(NECK[:-1], rotation=(-11, 0, 0), timing=lash, lag=0.008),
          sculpt.move(parts[COUNT - 1], scale=(1.22, 1, 1), timing=sculpt.beats((0, 0.0), (0.45, 1.0, "out"), (0.8, 1.0, "linear"), (1, 0.0))),
          sculpt.move("head", position=(0, -6, 1), rotation=(36, 0, 0), timing=sculpt.snap(windup=0.5, hit=0.6, back=0.5, over=0.15, hold=0.05)),
          sculpt.swing("seg3", 6, axis="y", cycles=1), sculpt.fade(sculpt.swing("seg1", 8, axis="y", cycles=1, phase=0.3)),
          sculpt.follow(["seg3", "seg2", "seg1", "seg0"], stiffness=1.6, damping=0.3, limit=18), loop="once")

# Hurt: the neck whips back, and a kink runs down the body after it.
m.animate("hurt", 0.6,
          sculpt.flinch(list(reversed(NECK)), move=(0, 0, 0), degrees=(7, 0, 0), shake=1.5, lag=0.02),
          sculpt.flinch("head", move=(0, 0, 0), degrees=(14, 16, 0), shake=2.0),
          *[sculpt.flinch(f"seg{i}", move=(0, 0, 0), degrees=(0, (-1) ** i * (13 - 2 * i), 0), shake=1.5, lag=0.0) for i in range(ROOT)], loop="once")

# Death: the neck loses its strength and lays itself along the ground in stages, and the body goes slack behind it.
m.animate("death", 2.8,
          sculpt.collapse(parts[ROOT], direction="left", degrees=0, fall=0.5, stagger=0.0, bounce=0.04, slide=0.0,
                          limbs={"seg5": (-2, 14, 0), "seg6": (-24, -14, 0), "seg7": (-36, -18, 0), "seg8": (-32, 12, 0), "head": (92 - 4, 26, 0)}),
          sculpt.keyed("seg8", scale=[(0, (1, 1, 1)), (0.4, (1.05, 1, 1)), (0.75, (0.88, 1, 1)), (1, (0.85, 1, 1))]),
          sculpt.keyed(["seg3", "seg2", "seg1", "seg0"], rotation=[(0, (0, 0, 0)), (0.2, (0, 0, 0), "linear"), (0.7, (0, 10, 0)), (1, (0, 12, 0), "out")], lag=0.05),
          loop="hold")

report(m, "snake", start)
