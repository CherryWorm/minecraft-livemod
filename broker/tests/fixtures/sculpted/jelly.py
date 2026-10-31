"""A jellyfish-like thing, to show the tool isn't limited to creatures with legs. It swims the way a jellyfish does: a quick
squeeze of the bell that shoots it upward, then a slow glide while the bell opens, with its tentacles trailing behind."""
import math
import time

from assetkit import sculpt
from common import report

start = time.time()

BELL = (150, 110, 220, 185)
BELL_DARK = (118, 84, 196, 185)
RIM = (214, 176, 244, 210)
GLOW = "#ffd8f4"
TENTACLE = (176, 128, 232, 230)
LIFT = 7  # it hovers

m = sculpt.Model("drift_jelly")

bell = m.part("bell", pivot=(0, 24 + LIFT, 0))
# A dome: a ball with a scoop out of its underside. Glass voxels draw no walls between themselves, so the core shows through a solid bell.
dome = sculpt.ball((0, 22 + LIFT, 0), (10, 10, 10), power=2.2) - sculpt.ball((0, 11 + LIFT, 0), (8, 8, 8))
ribs = sculpt.bands([BELL, BELL_DARK], along=lambda x, y, z: (math.atan2(x, z) + math.pi) * 8 / math.pi, width=1)
bell.add(dome, ribs, shade=False)
bell.ball((0, 26 + LIFT, 0), (4.5, 4, 4.5), GLOW, glow=12)
bell.ball((0, 22.5 + LIFT, 0), (2.6, 1.8, 2.6), "#ffb0e0", glow=8)
# A frilled rim, in a loop, because it's only trigonometry.
for i in range(8):
    a = 2 * math.pi * i / 8
    bell.ball((9 * math.cos(a), 15.5 + LIFT, 9 * math.sin(a)), (2.2, 1.5, 2.2), RIM, shade=False)
# Two sleepy eyes on the front of the bell.
bell.decal(["kk", "kk"], {"k": "#2a1840"}, at=(3.5, 21 + LIFT, 0), mirror="x")

# Four tentacles, each a chain of two parts, each wandering in its own curve.
chains = []
for i, (x, z) in enumerate(((5.5, 5.5), (-5.5, 5.5), (5.5, -5.5), (-5.5, -5.5))):
    upper = m.part(f"t{i}a", parent=bell, pivot=(x, 16 + LIFT, z))
    upper.tube(sculpt.curve((x, 17 + LIFT, z), (x * 1.2, 11 + LIFT, z * 1.2), (x, 8 + LIFT, z), n=4), [1.8, 1.6, 1.5, 1.4, 1.3], TENTACLE, shade=False)
    lower = m.part(f"t{i}b", parent=upper, pivot=(x, 8 + LIFT, z))
    lower.tube(sculpt.curve((x, 8 + LIFT, z), (x * 0.7, 4 + LIFT, z * 0.7), (x * 1.0, LIFT, z * 1.0), n=4), [1.3, 1.2, 1.0, 0.8, 0.6], TENTACLE, shade=False)
    chains.append([upper.name, lower.name])


def stroke(squeeze=0.2, height=3.0, cycles=1):
    """One swimming stroke. The bell closes fast and throws itself up, then opens slowly as it glides and sinks."""
    close = sculpt.beats((0, 0.0), (0.2, 1.0, "hard_out"), (0.32, 0.9), (1, 0.0, "in_out"))
    rise = sculpt.beats((0, 0.0), (0.12, 0.05, "in"), (0.4, 1.0, "out"), (1, 0.0, "in_out"))

    def timed(fn):
        return lambda p: fn((cycles * p) % 1.0)

    return [sculpt.squash(bell, amount=squeeze, timing=timed(close)), sculpt.move(bell, position=(0, height, 0), timing=timed(rise))]


def trailing(stiffness=1.3, amount=1.0, limit=30, sway=0.0):
    tracks = [sculpt.follow(chain, stiffness=stiffness, damping=0.22, amount=amount, limit=limit) for chain in chains]
    if sway:
        tracks += [sculpt.wave(chain, sway, axis="z" if i % 2 else "x", waves=0.4, phase=i * 0.25) for i, chain in enumerate(chains)]
    return tracks


# Idle: slow strokes, a long glide between them, and the tentacles waving in water that isn't there.
m.animate("idle", 4.0, *stroke(0.13, 2.0), *trailing(1.0, 1.0, 26, sway=7),
          sculpt.keyed(bell, rotation=[(0, (0, 0, 0)), (0.5, (3, 0, 2)), (1, (0, 0, 0))]))

# Walk: the same swimming stroke, but quick and hard, tipped forward into the direction of travel.
m.animate("walk", 1.4, *stroke(0.26, 3.5, cycles=2), sculpt.pose(bell, rotation=(-14, 0, 0)), *trailing(1.2, 1.2, 34, sway=4))

# Attack: the bell rears, then darts down and forward, and the tentacles lash out ahead of it.
m.animate("attack", 0.8,
          sculpt.lunge(bell, (0, -0.5, -7), windup=0.35, hit=0.5, back=0.6, over=0.15),
          sculpt.strike(bell, (-20, 0, 0), windup=0.35, hit=0.5, back=0.6),
          sculpt.squash(bell, amount=0.22, timing=sculpt.beats((0, 0.0), (0.33, -0.7), (0.5, 1.0, "hard_in"), (0.7, 0.2), (1, 0.0))),
          *[sculpt.strike(chain, (34, 0, 0), windup=0.4, hit=0.56, back=0.3, lag=0.03) for chain in chains], loop="once")

# Hurt: it jolts away and clenches, and its tentacles fly after it.
m.animate("hurt", 0.6,
          sculpt.flinch(bell, move=(0, 2, 3), degrees=(16, 0, 8), shake=1.5),
          sculpt.squash(bell, amount=-0.25, timing=sculpt.beats((0, 0.0), (0.12, 1.0, "hard_out"), (0.3, -0.4), (0.55, 0.2), (1, 0.0))),
          *trailing(2.2, 0.7, 26), loop="once")

# Death: its bell gives out and sags, it sinks to the ground, and the tentacles spread out flat around it.
limp = {}
for i, (upper_name, lower_name) in enumerate(chains):
    sx, sz = (1 if i in (0, 2) else -1), (1 if i in (0, 1) else -1)
    limp[upper_name] = (sz * 58, 0, -sx * 58)
    limp[lower_name] = (sz * 20, 0, -sx * 20)
m.animate("death", 3.2,
          sculpt.collapse(bell, direction="forward", degrees=4, fall=0.62, stagger=0.0, bounce=0.05, slide=0.0, limbs=limp),
          sculpt.keyed(bell, scale=[(0, (1, 1, 1)), (0.14, (0.8, 1.18, 0.8), "out"), (0.5, (1.05, 0.8, 1.05), "in_out"), (0.66, (1.32, 0.52, 1.32), "hard_in"), (0.76, (1.26, 0.58, 1.26), "out"), (1, (1.28, 0.55, 1.28), "in_out")]),
          loop="hold")

report(m, "jelly", start)
