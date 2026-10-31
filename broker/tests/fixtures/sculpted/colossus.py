"""A boss about 6 blocks tall: a stone-and-brass colossus with a glowing eye, at a coarser grain. It has to feel enormous, so
everything takes a long time: each step is slow, the weight comes down late and hard, and nothing starts or stops at once."""
import time

from assetkit import sculpt
from common import report

start = time.time()

STONE = "#8d8c86"
STONE_DARK = "#6e6d68"
MOSS = "#6c7458"
BRASS = "#c79a3e"
BRASS_DARK = "#8d6a26"
EYE = "#7ff0ff"
EYE_CORE = "#e8ffff"
CORE = "#ffb648"

rock = sculpt.mottle(sculpt.mottle(STONE, STONE_DARK, size=8, amount=0.35, seed=2), MOSS, size=10, amount=0.05, seed=5)

m = sculpt.Model("brass_colossus", grain=2)

# Heavy from the waist up, with a tiny head, so it reads as huge.
pelvis = m.part("pelvis", pivot=(0, 38, 0))
pelvis.box((-14, 32, -9), (14, 44, 9), rock)
pelvis.box((-16, 36, -11), (16, 40, 11), sculpt.bands([BRASS, BRASS_DARK], along="x", width=4))

torso = m.part("torso", parent=pelvis, pivot=(0, 44, 0))
torso.ball((0, 60, 0), (25, 19, 16), rock, power=2.6)
torso.box((-12, 42, -10), (12, 52, 10), rock)
# A brass disc with the core burning inside it, and a yoke across the shoulders.
torso.cylinder((0, 60, -18), (0, 60, -13), 10, BRASS)
torso.cylinder((0, 60, -19), (0, 60, -13), 7, BRASS_DARK)
torso.cylinder((0, 60, -20), (0, 60, -14), 5, CORE, glow=15)
torso.box((-20, 74, -14), (20, 78, 14), BRASS)
for x in (-16, 16):
    torso.ball((x, 58, -15), (2.5, 2.5, 2.5), BRASS_DARK)

head = m.part("head", parent=torso, pivot=(0, 76, -2))
head.ball((0, 85, -3), (13, 11, 12), rock, power=3.2)
head.box((-14, 79, -16), (14, 81, 10), BRASS_DARK)
head.box((-14, 93, -16), (14, 95, 10), BRASS)
head.taper((0, 95, -3), (0, 98, -3), 3, 1, BRASS)
# One great round eye: a socket cut into the face, then the light in it, so it sits back in its brass rim.
head.cylinder((0, 86, -17), (0, 86, -11), 8, BRASS)
head.cut.cylinder((0, 86, -17), (0, 86, -14), 6.4)
head.cylinder((0, 86, -14), (0, 86, -11), 6.4, EYE, glow=15)
head.cylinder((0, 86, -15), (0, 86, -11), 3, EYE_CORE, glow=15)

arm = m.part("arm_r", parent=torso, pivot=(25, 68, 0))
arm.ball((29, 70, 0), (11, 11, 11), sculpt.bands([BRASS, BRASS_DARK], along="y", width=4))
arm.taper((30, 66, 0), (32, 46, 0), 9, 8, rock)
fore = m.part("fore_r", parent=arm, pivot=(32, 46, 0))
fore.ball((32, 46, 0), (8, 8, 8), BRASS)
fore.taper((32, 44, 0), (34, 28, -2), 8, 10, rock)
# A fist of stone, with a brass knuckle guard.
fore.ball((34, 22, -2), (11, 10, 11), rock, power=3.5)
fore.box((24, 18, -14), (44, 24, -11), BRASS)
m.mirror(arm)

# Each leg bends at the knee and has a separate foot, a great slab that stays flat on the ground.
leg = m.part("leg_r", parent=pelvis, pivot=(9, 34, 0))
leg.taper((9, 36, 0), (11, 20, 0), 10, 8, rock)
shin = m.part("shin_r", parent=leg, pivot=(11, 20, 0))
shin.ball((11, 20, 0), (8, 8, 8), BRASS)
shin.taper((11, 18, 0), (12, 9, 0), 8, 9, rock, flat=True)
foot = m.part("foot_r", parent=shin, pivot=(12, 8, 0))
foot.box((1, 0, -14), (23, 8, 10), rock)
foot.box((1, 6, -15), (23, 8, 10), BRASS_DARK)
m.mirror(leg)

LEGS = [["leg_r", "shin_r", "foot_r"], ["leg_l", "shin_l", "foot_l"]]
ARMS = ["arm_r", "arm_l"]
FOREARMS = ["fore_r", "fore_l"]
heavy_hands = [sculpt.follow("fore_r", stiffness=0.8, damping=0.4, limit=18), sculpt.follow("fore_l", stiffness=0.8, damping=0.4, limit=18)]

# Idle: a very slow breath, and a head that scans the distance and takes its time about it.
m.animate("idle", 7.0,
          sculpt.keyed(torso, position=[(0, (0, 0, 0)), (0.45, (0, 0.8, 0), "in_out"), (0.6, (0, 0.8, 0), "linear"), (1, (0, 0, 0), "in_out")]),
          sculpt.keyed(pelvis, position=[(0, (0, 0, 0)), (0.45, (0, -0.5, 0), "in_out"), (0.6, (0, -0.5, 0), "linear"), (1, (0, 0, 0), "in_out")]),
          sculpt.glance("head", (0.2, -22, 2), (0.5, 0, -3), (0.8, 20, 2), speed=0.12),
          sculpt.keyed(ARMS, rotation=[(0, (0, 0, 0)), (0.5, (2, 0, 0)), (1, (0, 0, 0))]),
          sculpt.plant(LEGS), *heavy_hands)

# Walk: a long stride, nearly always a foot down, the hips rolling over it and the shoulders turning against them. The
# body sinks late and hard at each landing, and the fists swing like the weights they are.
m.animate("walk", 3.0,
          sculpt.gait(LEGS, stride=22, lift=7, duty=0.7, pattern="walk", knee="front", crouch=0.1, peel=8, body=pelvis, drop=2.4, sway=3, roll=2.5, twist=5, shoulders=torso, arms=ARMS, arm_swing=13),
          sculpt.steady("head", amount=0.85, level=0.5),
          *heavy_hands)

# Attack: both fists go up over a long moment, hang there, and come down all at once, the whole body following them,
# and it takes its time to recover.
raise_slam = [(0, (0, 0, 0)), (0.38, (150, 0, 0), "in_out"), (0.46, (156, 0, 0), "out"), (0.56, (62, 0, 0), "hard_in"), (0.62, (72, 0, 0), "out"), (0.72, (66, 0, 0)), (1, (0, 0, 0), "in_out")]
m.animate("attack", 2.6,
          sculpt.keyed(ARMS, rotation=raise_slam),
          sculpt.keyed(torso, rotation=[(0, (0, 0, 0)), (0.4, (12, 0, 0), "in_out"), (0.46, (13, 0, 0), "out"), (0.56, (-24, 0, 0), "hard_in"), (0.64, (-20, 0, 0), "out"), (1, (0, 0, 0), "in_out")]),
          sculpt.keyed(pelvis, position=[(0, (0, 0, 0)), (0.42, (0, 1.5, 2), "in_out"), (0.56, (0, -5, -3), "hard_in"), (0.66, (0, -4, -3), "out"), (1, (0, 0, 0), "in_out")]),
          sculpt.steady("head", amount=0.6, level=0.0),
          sculpt.plant(LEGS), *heavy_hands, loop="once")

# Hurt: it hardly notices. A small lurch that takes a while to come back, and the head turning toward the blow.
m.animate("hurt", 0.9,
          sculpt.flinch(torso, move=(0, 0.5, 2), degrees=(5, 0, 2), shake=1.0),
          sculpt.flinch("head", move=(0, 0, 0), degrees=(9, 10, 0), shake=1.0),
          sculpt.plant(LEGS), *heavy_hands, loop="once")

# Death: its knees go first, it hangs there a moment, and then the whole mass goes over forward and the ground takes it.
m.animate("death", 4.8,
          sculpt.collapse(pelvis, direction="forward", degrees=84, fall=0.62, stagger=0.05, bounce=0.05, slide=0.4,
                          limbs={"leg_r": (46, 0, 6), "leg_l": (38, 0, -6), "shin_r": (-52, 0, 0), "shin_l": (-44, 0, 0), "foot_r": (24, 0, 0), "foot_l": (18, 0, 0),
                                 "arm_r": (100, 0, 26), "arm_l": (116, 0, -30), "fore_r": (24, 0, 0), "fore_l": (34, 0, 0), "head": (30, -14, 0)}),
          loop="hold")

report(m, "colossus", start)
