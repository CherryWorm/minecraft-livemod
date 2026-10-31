"""A squat blue-green four-legged toad with a big green bulb on its back and red eyes. It's heavy and low, so it waddles,
one foot at a time, with its weight rolling over each foot and the bulb wobbling after it."""
import time

from assetkit import sculpt
from common import report

start = time.time()

SKIN = "#6cc4ae"
PATCH = "#3a8a80"
PALE = "#93dcc6"
BULB = "#4e9e45"
BULB_DARK = "#2f7a3a"
BULB_PALE = "#74c060"
RED = "#c8242c"
WHITE = "#f4f0e4"
DARK = "#1e2a2c"

m = sculpt.Model("bulb_toad")

body = m.part("body", pivot=(0, 8, 2))
hide = sculpt.spots(SKIN, PATCH, size=3.0, spacing=8.5, seed=4)
hide = sculpt.patch(hide, PALE, (0, 2, -2), (7, 5, 8))
body.ball((0, 9.5, 3), (10, 7, 11), hide)

# A wide flat head, nearly as wide as the body. Its face is flat enough to hold a long mouth.
head = m.part("head", parent=body, pivot=(0, 12, -6))
face = sculpt.spots(SKIN, PATCH, size=2.2, spacing=8, seed=11)
head.ball((0, 14, -11), (10.5, 7.5, 7.5), face, power=2.6)
# Two small pointed ears up on the skull.
head.taper((6.5, 20, -9), (8.5, 25, -9), 2.8, 0.8, SKIN, mirror="x")
# Round eyes that really bulge, so they read from the side as well, painted with big red irises.
head.ball((6, 16.5, -17), (3.4, 3.4, 2.2), WHITE, mirror="x", shade=False)
head.decal(["..rr..",
            ".rrrr.",
            "rrkkrr",
            "rrkkrr",
            ".rhrr.",
            "..rr.."], {"r": RED, "k": "#3a0810", "h": "#ff8078"}, at=(6, 16.5, 0), mirror="x")
head.decal(["kk.kk"], {"k": DARK}, at=(0, 13.5, 0))
# A long curved mouth, wrapping onto the sides of the head.
head.decal(["d.................d",
            ".dd.............dd.",
            "...ddddddddddddd..."], {"d": "#23524c"}, at=(0, 10.5, 0), depth=2)

# The bulb is a fat onion with a tip, made of swept leaves, and it's its own part so that it can breathe and wobble.
bulb = m.part("bulb", parent=body, pivot=(0, 15, 5))
petals = sculpt.bands([BULB, BULB_DARK], along=lambda x, y, z: (y - 14) * 0.5 + ((x * x + (z - 5) ** 2) ** 0.5) * 0.8, width=2.2)
bulb.ball((0, 22, 5), (9.5, 9, 9.5), petals)
bulb.taper((0, 28, 5), (0, 36, 6), 4.5, 0.8, BULB_PALE)
bulb.paint.ball((0, 26, -2), (4, 7, 3), BULB_PALE)

for name, x, z in (("leg_fr", 8, -6), ("leg_br", 8, 10)):
    leg = m.part(name, parent=body, pivot=(x, 7, z))
    leg.taper((x, 7, z), (x + 1, 4, z - 1), 4.4, 3.8, SKIN)
    leg.ball((x + 1, 2.5, z - 2), (4.6, 2.5, 5.2), SKIN)
    leg.decal(["ww.ww.ww"], {"w": WHITE}, at=(x + 1, 1, 0), depth=2)
    m.mirror(leg, name=name[:-1] + "l")

LEGS = ["leg_fr", "leg_fl", "leg_br", "leg_bl"]
wobble = sculpt.follow(bulb, stiffness=1.7, damping=0.2, limit=16)

# Idle: slow, heavy breaths through the throat and the bulb, and an occasional look.
m.animate("idle", 5.0,
          sculpt.keyed(body, position=[(0, (0, 0, 0)), (0.3, (0, 0.5, 0), "in_out"), (0.5, (0, 0.5, 0), "linear"), (1, (0, 0, 0), "in_out")]),
          sculpt.squash(body, amount=0.025, timing=sculpt.beats((0, 0.0), (0.3, 1.0), (0.5, 1.0, "linear"), (1, 0.0))),
          sculpt.squash(bulb, amount=0.04, timing=sculpt.beats((0, 0.0), (0.28, -1.0), (0.45, -1.0, "linear"), (1, 0.0))),
          sculpt.glance("head", (0.22, -18, 2), (0.42, 0, 0), (0.7, 14, -3)),
          sculpt.plant(LEGS))

# Walk: a waddle, one foot at a time, slow enough that each foot takes its share of the weight.
m.animate("walk", 1.3,
          sculpt.gait(LEGS, stride=7, lift=3, duty=0.72, pattern="walk", body=body, drop=0.8, sway=1.3, roll=5, twist=5, tilt=26),
          sculpt.steady("head", amount=0.7, level=0.3),
          sculpt.swing("head", 2, axis="z", cycles=1, phase=0.3),
          wobble)

# Attack: it sinks back on its haunches, then throws its whole front forward in a snap of the head.
snap = sculpt.snap(windup=0.36, hit=0.5, back=0.5, over=0.15)
m.animate("attack", 0.8,
          sculpt.move(body, position=(0, -1.2, -4), rotation=(-9, 0, 0), timing=snap),
          sculpt.move("head", position=(0, 1, -3), rotation=(-14, 0, 0), timing=sculpt.snap(windup=0.38, hit=0.52, back=0.8, over=0.2)),
          sculpt.plant(LEGS), sculpt.follow(bulb, stiffness=2, damping=0.2, amount=1.3, limit=22), loop="once")

# Hurt: the whole bulk jolts back on planted feet, and the bulb swings over and takes a moment to recover.
m.animate("hurt", 0.55,
          sculpt.flinch(body, move=(0, 1.0, 2.5), degrees=(6, 0, 3), shake=2.0),
          sculpt.flinch("head", move=(0, 0, 0), degrees=(14, 8, 0), shake=2.0),
          sculpt.plant(LEGS), sculpt.follow(bulb, stiffness=2.5, damping=0.15, amount=1.0, limit=14), loop="once")

# Death: the legs give out and it spreads flat on its belly, head down, the bulb wilting over it.
m.animate("death", 2.0,
          sculpt.collapse(body, direction="forward", degrees=5, fall=0.42, bounce=0.06,
                          limbs={"leg_fr": (20, 0, 62), "leg_fl": (20, 0, -62), "leg_br": (-20, 0, 62), "leg_bl": (-20, 0, -62), "head": (-16, 12, 6)}),
          sculpt.keyed(bulb, rotation=[(0, (0, 0, 0)), (0.42, (0, 0, 0), "linear"), (0.75, (22, 0, -10), "in_out"), (1, (24, 0, -11), "out")],
                       scale=[(0, (1, 1, 1)), (0.42, (1, 1, 1), "linear"), (0.8, (1.07, 0.82, 1.07), "in_out"), (1, (1.08, 0.8, 1.08), "out")]),
          loop="hold")

report(m, "toad", start)
