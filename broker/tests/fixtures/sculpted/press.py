"""A machine: a small brass press with a turning gear and a moving piston. It's heavy brass doing work, so the piston hangs and
then slams, the gear labours through the stroke and hurries after it, and the frame takes the blow."""
import math
import time

from assetkit import sculpt
from common import report

start = time.time()

BRASS = "#c9a040"
BRASS_DARK = "#8a6a28"
IRON = "#5a5f68"
IRON_DARK = "#3a3e46"
STEEL = "#b8bcc4"
GLOW = "#ff9a38"

m = sculpt.Model("brass_press", shade=0.4)

# It fits inside one block, as a block's model would, with the gear on its right side.
frame = m.part("frame", pivot=(0, 0, 0))
frame.box((-8, 0, -8), (8, 2, 8), IRON)               # the bed
frame.box((-8, 2, -8), (8, 3, 8), BRASS_DARK)
frame.box((-7, 3, 3), (-4, 13, 7), BRASS)             # two uprights at the back
frame.box((1, 3, 3), (4, 13, 7), BRASS)
frame.box((-7, 12, -5), (4, 15, 7), BRASS)            # the crown
frame.box((-7, 15, -5), (4, 16, 7), BRASS_DARK)
frame.box((-5, 3, -5), (2, 4, 2), IRON_DARK)          # the die it presses on
frame.box((-4, 4, -4), (1, 5, 1), GLOW, glow=10)
frame.cut.box((-3.5, 12, -3), (0.5, 16, 1))           # the bore the piston rides in
frame.decal(["w.........w"], {"w": "#ecd88a"}, at=(-1.5, 13.5, 0))

piston = m.part("piston", parent=frame, pivot=(-1.5, 11, -1))
piston.cylinder((-1.5, 9, -1), (-1.5, 17, -1), 1.8, STEEL)
piston.box((-4, 8, -3.5), (1, 10, 1.5), IRON)


def gear_shape(center, radius, teeth, width):
    """A toothed wheel on an X axle: a disc, with one box per tooth."""
    x, y, z = center
    wheel = sculpt.cylinder((x, y, z), (x + width, y, z), radius)
    for i in range(teeth):
        tooth = sculpt.box((x, y + radius - 0.6, z - 0.9), (x + width, y + radius + 1.6, z + 0.9))
        wheel = wheel | tooth.rotated((360 * i / teeth, 0, 0), about=(0, y, z))
    return wheel


# One big wheel, its face marked with a darker cross, so the spin shows from a distance.
center = (5, 9, 1)
gear = m.part("gear", parent=frame, pivot=center)
gear.add(gear_shape(center, 5, 8, 2), BRASS)
gear.paint.box((6, 8.5, -3.5), (7, 9.5, 5.5), BRASS_DARK)
gear.paint.box((6, 4.5, 0.5), (7, 13.5, 1.5), BRASS_DARK)
gear.cylinder((4, 9, 1), (7.4, 9, 1), 1.2, IRON_DARK)
frame.box((4, 8, 0), (5, 10, 4), IRON_DARK)           # the axle's bracket


def ratchet(p, teeth=8):
    """A clockwork tick: a quick step a tooth at a time with a small bounce, and a rest between."""
    at = p * teeth
    i = math.floor(at)
    return (i + sculpt.ease("back", min((at - i) / 0.3, 1.0))) / teeth


# The stroke: it lifts, hangs, comes down hard, dwells under load, and rises slowly. It stops just on the glowing die.
DOWN = (0, -2.95, 0)
stroke =sculpt.beats((0, 0.0), (0.32, -0.3, "in_out"), (0.4, -0.3, "linear"), (0.5, 1.0, "hard_in"), (0.54, 0.95, "out"), (0.58, 1.0, "in"), (0.7, 1.0, "linear"), (1, 0.0, "in_out"))
# The gear gives its turn to the piston: it labours as the blow lands, then hurries to catch up.
labour = sculpt.beats((0, 0.0), (0.4, 0.42, "in_out"), (0.5, 0.46, "out"), (0.7, 0.5, "linear"), (1, 1.0, "in"))
jolt = sculpt.beats((0, 0.0), (0.49, 0.0, "linear"), (0.52, 1.0, "hard_out"), (0.56, -0.5, "in_out"), (0.61, 0.2, "in_out"), (0.66, 0.0, "in_out"), (1, 0.0, "linear"))

# Idle: running down, just ticking over. The piston is parked, and the gear clicks round.
m.animate("idle", 4.0,
          sculpt.spin(gear, axis="x", turns=1, timing=ratchet),
          sculpt.keyed(piston, position=[(0, (0, 0, 0)), (0.5, (0, 0.15, 0)), (1, (0, 0, 0))]))

# Working, under the name walk, which a module plays with machine.play("walk").
m.animate("walk", 2.0,
          sculpt.spin(gear, axis="x", turns=2, timing=labour),
          sculpt.lunge(piston, DOWN, timing=stroke),
          sculpt.move(frame, position=(0, -0.3, 0), timing=jolt))

# A single stamp, for a module to play once per craft.
m.animate("stamp", 1.2,
          sculpt.spin(gear, axis="x", turns=1, timing=labour),
          sculpt.lunge(piston, DOWN, timing=stroke),
          sculpt.move(frame, position=(0, -0.3, 0), timing=jolt), loop="once")

# Jammed: the piston comes down part way and sticks, shuddering, and the gear strains back and forth, then gives up.
m.animate("jam", 1.5,
          sculpt.lunge(piston, (0, -2.2, 0), timing=sculpt.beats((0, 0.0), (0.15, 1.0, "hard_in"), (0.75, 1.0, "linear"), (1, 0.0, "in_out"))),
          sculpt.fade(sculpt.flicker([frame, piston], position=0.14, rate=17, seed=2, axes="xy"), out=0.3, into=0.1),
          sculpt.keyed(gear, rotation=[(0, (0, 0, 0)), (0.15, (20, 0, 0), "out"), (0.3, (6, 0, 0)), (0.42, (24, 0, 0), "out"), (0.56, (10, 0, 0)), (0.68, (22, 0, 0), "out"), (1, (0, 0, 0), "in_out")]), loop="once")

report(m, "press", start, machine=True)
