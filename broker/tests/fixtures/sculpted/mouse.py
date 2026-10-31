"""A chubby yellow electric mouse: long black-tipped ears, red cheeks, stripes on its back, a lightning-bolt tail. It's small
and light, so everything it does is quick, and its ears and tail arrive a moment after the rest of it."""
import time

from assetkit import sculpt
from common import report

start = time.time()

YELLOW = "#f7d22d"
DARK = "#2a2118"
RED = "#e8402c"
BROWN = "#8c5a24"

m = sculpt.Model("volt_mouse")

body = m.part("body", pivot=(0, 11, 0))
fur = sculpt.stripes(YELLOW, BROWN, along="y", every=5, width=2, start=8, stop=19, where=lambda x, y, z: z > 2.5)
body.ball((0, 11.5, 0), (8, 9.5, 7), fur)

# A big flat-faced head wider than the body, because the head is most of what makes it cute.
head = m.part("head", parent=body, pivot=(0, 18, -1))
head.ball((0, 25, -1), (10, 8, 8), YELLOW, power=2.5)

# Eyes, cheeks, nose and mouth, as pixel art on the face.
head.decal(["kkkk", "kwwk", "kkwk", "kkkk"], {"k": DARK, "w": "#fbfbf0"}, at=(4.5, 27, 0), mirror="x")
head.decal([".rrr.", "rrrrr", "rrrrr", ".rrr."], {"r": RED}, at=(7, 23, 0), depth=3, mirror="x")
head.decal(["kk"], {"k": DARK}, at=(0, 25, 0))
head.decal(["k....k", ".kkkk."], {"k": DARK}, at=(0, 22.5, 0))

# Long ears are flattened ellipsoids, leaning out, on bones of their own so they can flop. The black tips are just a
# condition on height.
ear = m.part("head_ear_r", parent=head, pivot=(6.5, 30, -1))
ear.add(sculpt.ball((7.5, 38, -1), (3.2, 9.5, 1.7)).rotated((0, 0, -14), about=(7.5, 30, -1)), sculpt.where(lambda x, y, z: y > 40, DARK, YELLOW))
m.mirror(ear, name="head_ear_l")

leg = m.part("leg_r", parent=body, pivot=(4, 5, -1))
leg.ball((4.5, 2.5, -2.5), (3.6, 2.5, 5), YELLOW)
leg.decal(["k.k"], {"k": BROWN}, at=(4.5, 1, 0))
m.mirror(leg)

arm = m.part("arm_r", parent=body, pivot=(6, 15, -3))
arm.taper((6, 15, -3), (7, 10, -7.5), 2.4, 2.0, YELLOW)
m.mirror(arm)

# The bolt is flat, seen from the side, stepping up and back from the rump, and it comes in two pieces so that it can whip.
tail = m.part("tail", parent=body, pivot=(0, 7, 6))
tail.polygon([(4, 3), (13, 7), (10.5, 11), (19, 13), (17, 16.5), (5, 16), (7.5, 11), (4, 9)], sculpt.where(lambda x, y, z: z < 9, BROWN, YELLOW), facing="left", at=-1, thick=2)
tip = m.part("tail_tip", parent=tail, pivot=(0, 16, 12))
tip.polygon([(5, 15.5), (17, 16), (16, 19), (27, 29), (11, 23), (13, 18.5), (5, 17)], YELLOW, facing="left", at=-1, thick=2)

EARS = ["head_ear_r", "head_ear_l"]
ARMS = ["arm_r", "arm_l"]
LEGS = ["leg_r", "leg_l"]
TAIL = ["tail", "tail_tip"]


def loose_bits(amount=1.0):
    """Whatever hangs off it answers to how the body moves, a little later."""
    return [sculpt.follow(["head_ear_r"], stiffness=4.5, damping=0.22, amount=amount, limit=28), sculpt.follow(["head_ear_l"], stiffness=4.5, damping=0.22, amount=amount, limit=28),
            sculpt.follow(TAIL, stiffness=3.0, damping=0.25, amount=amount, limit=32)]


# Idle: alert. It breathes, looks about in quick darts, and flicks its ears and tail now and then.
m.animate("idle", 4.0,
          sculpt.breathe(body, 0.02, cycles=2, skew=0.4),
          sculpt.bob(body, 0.2, cycles=2),
          sculpt.glance("head", (0.14, 22, 3), (0.42, -16, -4), (0.62, 0, 8), (0.8, 10, 0)),
          sculpt.keyed(EARS, rotation=[(0.5, (0, 0, 0)), (0.53, (-16, 0, 0), "out"), (0.58, (0, 0, 0), "settle")]),
          sculpt.keyed("head_ear_l", rotation=[(0.84, (0, 0, 0)), (0.87, (-14, 0, 0), "out"), (0.93, (0, 0, 0), "settle")]),
          sculpt.keyed(TAIL, rotation=[(0.25, (0, 0, 0)), (0.28, (0, 14, 0), "out"), (0.31, (0, -12, 0), "in_out"), (0.36, (0, 0, 0), "settle")], lag=0.012),
          sculpt.swing(ARMS, 4, cycles=2, offset=0.2))

# Walk: a scamper, up on its toes, leaning into it, with a flight between steps, so it spends most of the time bouncing.
m.animate("walk", 0.4,
          sculpt.gait(LEGS, stride=9, lift=4, duty=0.42, pattern="trot", body=body, drop=1.3, sway=0.7, roll=7, twist=8, arms=ARMS, arm_swing=34, tilt=24),
          sculpt.pose(body, rotation=(-8, 0, 0)),
          sculpt.steady("head", amount=0.65, level=0.35),
          sculpt.pose("tail", rotation=(10, 0, 0)),
          *loose_bits())

# Attack: it crouches and draws back, then throws itself forward and swats, with a real stretch, and lands with a bounce.
leap = sculpt.snap(windup=0.3, hit=0.48, back=0.45, over=0.15)
m.animate("attack", 0.6,
          sculpt.move(body, position=(0, 1.6, -7), rotation=(-16, 0, 0), timing=leap),
          sculpt.squash(body, amount=0.14, timing=sculpt.beats((0, 0.0), (0.26, -1.0), (0.42, 1.0, "hard_in"), (0.6, 0.0), (1, 0.0))),
          sculpt.strike(ARMS, (80, 0, 0), windup=0.3, hit=0.46, back=0.4, lag=0.02),
          sculpt.lunge("head", (0, 0, -2), windup=0.3, hit=0.5),
          sculpt.plant(LEGS), *loose_bits(1.2), loop="once")

# Hurt: knocked back and up at once, arms flung out, everything loose going a beat later.
m.animate("hurt", 0.45,
          sculpt.plant(LEGS),
          sculpt.flinch([body, "head"], move=(0, 1.2, 4), degrees=(20, 0, 0), shake=2.0),
          sculpt.flinch(ARMS, move=(0, 0, 0), degrees=(-50, 0, 0), shake=1.0),
          sculpt.flinch("tail", move=(0, 0, 0), degrees=(-26, 0, 0), shake=1.0),
          *loose_bits(1.4), loop="once")

# Death: it staggers and goes over backward, and everything that was held up goes slack.
m.animate("death", 1.8,
          sculpt.collapse(body, direction="back", degrees=78, fall=0.42,
                          limbs={"arm_r": (50, 0, 30), "arm_l": (50, 0, -30), "leg_r": (-30, 0, 14), "leg_l": (-24, 0, -14), "head": (-14, 8, 0), "head_ear_r": (30, 0, -20), "head_ear_l": (34, 0, 22), "tail": (-30, 0, 0), "tail_tip": (-20, 0, 0)}),
          *loose_bits(0.8), loop="hold")

report(m, "mouse", start)
