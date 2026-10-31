"""An orange upright dragon with a cream belly, blue-green membrane wings and a flame at the tail tip. It walks with weight,
knees bending, with its wings beating as it goes and its tail dragging behind."""
import time

from assetkit import sculpt
from common import report

start = time.time()

ORANGE = "#ee8a2e"
CREAM = "#f4e0a4"
WING = "#2f8f9c"
WING_DARK = "#1f6a78"
HORN = "#e8d8b0"
DARK = "#2a1a18"
WHITE = "#f8f4e8"

m = sculpt.Model("ember_wyrm")

# Upright: the body is an egg standing on its legs, with a long neck that belongs to the head bone.
body = m.part("body", pivot=(0, 16, 1))
skin = sculpt.patch(ORANGE, CREAM, (0, 15, -7), (7.5, 11, 6))
body.ball((0, 16, 1), (9, 11, 8), skin)
body.ball((0, 26, -1), (6.5, 6.5, 6), skin)

head = m.part("head", parent=body, pivot=(0, 31, -2))
head.taper((0, 28, -2), (0, 35, -4), 5, 4.2, sculpt.patch(ORANGE, CREAM, (0, 30, -7), (3.6, 6, 3)))
# A broad skull with a brow, and a muzzle that narrows.
head.ball((0, 38, -5), (7.5, 5.5, 6.5), ORANGE, power=2.4)
head.taper((0, 37, -9), (0, 36, -16), 5.0, 3.6, ORANGE)
# The lower jaw is separate from the snout, with a dark line between, so it reads as a mouth from any side.
head.taper((0, 33.2, -8), (0, 33.6, -15), 3.6, 2.6, CREAM)
head.paint.box((-7, 34.0, -20), (7, 34.8, -8), "#5a2a18")
for x in (5, -5):
    head.tube(sculpt.curve((x, 41, -3), (x * 1.3, 44, 2), (x * 1.3, 46, 8), n=5), [2.2, 1.7, 1.3, 1.0, 0.8, 0.6], HORN)
eye = ["bbbbb",
       "wwkkw",
       "wwkkw"]
head.decal(eye, {"w": WHITE, "k": DARK, "b": "#a85a1c"}, at=(4.5, 39.5, 0), depth=2, mirror="x")
head.decal(["k......k"], {"k": DARK}, at=(0, 36.5, 0))

arm = m.part("arm_r", parent=body, pivot=(8.5, 24, -1), rotation=(-20, 0, 8))
arm.taper((8.5, 24, -1), (10.5, 15, -2), 2.4, 2.0, ORANGE)
arm.ball((10.5, 14, -3), (2.4, 2.2, 2.6), ORANGE)
arm.decal(["w.w"], {"w": WHITE}, at=(10.5, 13, 0))
m.mirror(arm)

# Stubby legs on separate feet, which stay flat as the leg rocks over them. Legs this short have no room to bend at a knee.
leg = m.part("leg_r", parent=body, pivot=(5.5, 11, 2))
leg.ball((6, 8.5, 2), (4.6, 5.5, 5.5), ORANGE)
leg.taper((6, 6, 2), (6, 4, 1), 3.4, 3.2, ORANGE)
foot = m.part("foot_r", parent=leg, pivot=(6, 3.5, 1))
foot.ball((6, 2, -2), (4, 2, 6), ORANGE)
foot.decal(["ww.ww.ww"], {"w": WHITE}, at=(6, 1, 0), depth=2)
m.mirror(leg)

# Wings are a membrane between finger bones, an outline seen from behind, swept a little backward. Each folds at the wrist.
wing = m.part("wing_r", parent=body, pivot=(5, 26, 6), rotation=(0, 18, 0))
inner = sculpt.gradient([WING_DARK, WING], (5, 26, 0), (34, 40, 0), steps=4)
wing.polygon([(5, 27), (15, 46), (19, 43), (19, 18), (14, 21), (6, 20)], inner, facing="front", at=6.4, thick=1)
for tip in ((15, 46), (19, 30), (19, 18)):
    wing.taper((5, 26, 7), (tip[0], tip[1], 7), 1.3, 0.8, ORANGE)
hand = m.part("hand_r", parent=wing, pivot=(19, 30, 7))
hand.polygon([(19, 43), (24, 40), (36, 44), (31, 32), (37, 24), (26, 24), (24, 15), (19, 18)], inner, facing="front", at=6.4, thick=1)
for tip in ((36, 44), (37, 24), (24, 15)):
    hand.taper((19, 30, 7), (tip[0], tip[1], 7), 1.0, 0.5, ORANGE)
m.mirror(wing)

# The tail curls out behind and up, in two parts, with the flame on the end as its own part.
tail = m.part("tail1", parent=body, pivot=(0, 9, 8))
tail.tube([(0, 9, 7), (0, 7, 14), (0, 7, 20)], [6, 4.4, 3.4], ORANGE)
tail2 = m.part("tail2", parent=tail, pivot=(0, 7, 20))
tail2.tube(sculpt.curve((0, 7, 20), (0, 7, 27), (0, 13, 30), n=5), [3.4, 3, 2.6, 2.2, 2, 1.8], ORANGE)

flame = m.part("flame", parent=tail2, pivot=(0, 14, 30))
tongue = sculpt.gradient(["#ffe668", "#ffb02e", "#ff5a1e", "#e0301a"], (0, 14, 30), (0, 28, 30), steps=4)
flame.ball((0, 17, 30), (3.6, 4.2, 3.6), tongue, glow=15)
flame.taper((0, 18, 30), (0, 28, 30), 3.2, 0.3, tongue, glow=15)
flame.taper((1.5, 17, 30), (3.4, 23, 29.5), 1.8, 0.2, tongue, glow=15)
flame.taper((-1.5, 17, 30), (-3.2, 22, 30.5), 1.8, 0.2, tongue, glow=15)

ARMS = ["arm_r", "arm_l"]
LEGS = [["leg_r", "foot_r"], ["leg_l", "foot_l"]]
TAIL = ["tail1", "tail2", "flame"]
burning = sculpt.flicker(flame, scale=0.13, rotation=5, rate=9, seed=3)


def trailing_wings(amount=1.0):
    return [sculpt.follow("hand_r", stiffness=2.4, damping=0.22, amount=amount, limit=30), sculpt.follow("hand_l", stiffness=2.4, damping=0.22, amount=amount, limit=30)]


# Idle: it breathes, half-opening its wings on each breath, and the flame never stops.
m.animate("idle", 3.6,
          sculpt.keyed(body, position=[(0, (0, 0, 0)), (0.42, (0, 0.5, 0), "in_out"), (0.55, (0, 0.5, 0), "linear"), (1, (0, 0, 0), "in_out")]),
          sculpt.flap("wing_r", "wing_l", 7, axis="y", skew=0.3),
          sculpt.wave(["tail1", "tail2"], 6, axis="y", waves=0.5),
          sculpt.glance("head", (0.2, -24, 4), (0.5, 8, -4), (0.78, 20, 0)),
          sculpt.swing(ARMS, 4, offset=0.0),
          sculpt.plant(LEGS, level=True), burning, *trailing_wings(), sculpt.follow("flame", stiffness=3, damping=0.25))

# Walk: a heavy tread with the knees bending and the hips rolling. The wings beat for balance, driving forward quickly and
# recovering slowly, with the outer wing dragging behind, and the long tail swings late, behind the hips.
m.animate("walk", 1.0,
          sculpt.gait(LEGS, level=True, stride=10, lift=4.5, duty=0.62, pattern="trot", body=body, drop=1.2, sway=1.4, roll=4, twist=6, arms=ARMS, arm_swing=20),
          sculpt.pose(body, rotation=(-6, 0, 0)),
          sculpt.flap("wing_r", "wing_l", 16, axis="y", cycles=1, skew=0.45),
          sculpt.steady("head", amount=0.75, level=0.4),
          sculpt.wave(["tail1", "tail2"], 8, axis="y", waves=0.4, phase=0.2),
          burning, *trailing_wings(), sculpt.follow(["tail1", "tail2", "flame"], stiffness=1.5, damping=0.3, limit=22))

# Attack: it rears back with its wings thrown wide, then slams its head and claws forward as the wings drive down.
rear = sculpt.snap(windup=0.36, hit=0.5, back=0.55, over=0.14)
m.animate("attack", 0.85,
          sculpt.move(body, position=(0, -0.6, -4), rotation=(-16, 0, 0), timing=rear),
          sculpt.move("head", position=(0, -1, -4), rotation=(-26, 0, 0), timing=sculpt.snap(windup=0.38, hit=0.52, back=0.7, over=0.2)),
          sculpt.strike(ARMS, (75, 0, 0), windup=0.36, hit=0.5, back=0.5, lag=0.015),
          sculpt.keyed("wing_r", rotation=[(0, (0, 0, 0)), (0.36, (0, -34, 0), "out"), (0.5, (0, 42, 0), "hard_in"), (0.62, (0, 34, 0), "out"), (1, (0, 0, 0), "in_out")]),
          sculpt.keyed("wing_l", rotation=[(0, (0, 0, 0)), (0.36, (0, 34, 0), "out"), (0.5, (0, -42, 0), "hard_in"), (0.62, (0, -34, 0), "out"), (1, (0, 0, 0), "in_out")]),
          sculpt.move("tail1", rotation=(16, 0, 0), timing=rear),
          sculpt.plant(LEGS, level=True), sculpt.fade(burning), *trailing_wings(1.2), sculpt.follow(["tail2", "flame"], stiffness=2, damping=0.25, limit=24), loop="once")

# Hurt: thrown back on its heels with its wings snatched open, and the tail lashes after it.
m.animate("hurt", 0.55,
          sculpt.flinch(body, move=(0, 0.5, 3), degrees=(11, 0, 4), shake=2.0),
          sculpt.flinch("head", move=(0, 0, 0), degrees=(22, 10, 0), shake=2.0),
          sculpt.flinch("wing_r", move=(0, 0, 0), degrees=(0, -30, 0), shake=1.0),
          sculpt.flinch("wing_l", move=(0, 0, 0), degrees=(0, 30, 0), shake=1.0),
          sculpt.flinch("tail1", move=(0, 0, 0), degrees=(-14, 0, 0), shake=1.0),
          sculpt.plant(LEGS, level=True), sculpt.fade(burning), *trailing_wings(1.3), sculpt.follow(["tail2", "flame"], stiffness=2.2, damping=0.2, limit=24), loop="once")

# Death: it sags, topples forward, its wings folding over it, and the flame on its tail shrinks and goes out.
m.animate("death", 2.6,
          sculpt.collapse(body, direction="forward", degrees=82, fall=0.44, stagger=0.1, bounce=0.08,
                          limbs={"head": (28, -18, 0), "arm_r": (40, 0, 30), "arm_l": (46, 0, -30), "leg_r": (40, 0, 8), "leg_l": (34, 0, -8), "foot_r": (30, 0, 0), "foot_l": (26, 0, 0),
                                 "wing_r": (10, 46, -24), "wing_l": (10, -46, 24), "hand_r": (0, 48, 0), "hand_l": (0, -48, 0), "tail1": (30, 12, 0), "tail2": (24, 18, 0)}),
          sculpt.keyed("flame", scale=[(0, (1, 1, 1)), (0.3, (1.1, 1.25, 1.1), "out"), (0.5, (0.85, 0.7, 0.85), "in_out"), (0.8, (0.4, 0.3, 0.4), "in_out"), (1, (0.08, 0.05, 0.08), "in")]),
          loop="hold")

report(m, "dragon", start)
