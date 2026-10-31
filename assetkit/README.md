# assetkit

Makes Minecraft assets that look at home next to vanilla. Run from the repository root, with Python, Pillow, numpy, and ffmpeg for sounds. Everything is seeded: the same seed gives the same file, and a different seed gives a sibling.

```python
from assetkit import textures as tx, sheet, sounds, bbmodel
```

Every generator also works from the command line, as `python3 assetkit/<tool>.py ...`. Run `textures.py list` or `sounds.py list` to see each one's options.

## The loop: generate, look, fix

**Never ship a texture you haven't looked at.** Write the PNGs, build a contact sheet, read that image, and regenerate what's wrong.

```
python3 assetkit/sheet.py /tmp/sheet.png mods/genesis/features/ember/assets/textures/
```

It shows each texture at 8x on a checkerboard, tiles each block 3x3, and lists its palette and colour count. Frames of an animation show as a strip. A cell with more than 10 colours gets an orange border and `TOO MANY` in its label.

## Blocks

Each returns a 16x16 RGBA image; pass `size=32` if you have a reason. Colours are `"#rrggbb"` or `(r, g, b)`.

| Family | Call |
|---|---|
| `stone` | `tx.stone(color, seed=1, style="stone")`, or `deepslate`, `cobble`, `bricks`, `smooth` |
| `ore` | `tx.ore("#e8742c", seed=1)` |
| `deep_ore` | `tx.ore("#e8742c", base="deepslate", seed=1)` |
| `metal` | `tx.metal(color, style="plate")`, or `rivets`, `gem` |
| `wood` | `tx.planks(color)`, `tx.log_side(color)`, `tx.log_top(wood, bark)` |
| `soil` | `tx.soil(color, style="dirt")`, or `gravel`, `sand`, `mud` |
| `glow` | `tx.glow(color, style="crystal")`, or `lamp` |
| `machine` | `tx.machine("front", casing, accent, on=True)`, with faces `front side top bottom back` |
| `cutout` | `tx.leaves(color)` |
| `plant` | `tx.plant("flower", color, stem)`, with kinds `flower tulip grass sapling mushroom crystal` |
| `tinted_plant` | The same with a grey `stem`, such as `(150, 150, 150)`, since the game multiplies by the biome colour |

Use one `casing` and `seed` on all faces of a machine so they match. `tx.ore` also takes `stone_color=`, or a finished image as `base=`, so an ore can sit in your own rock.

## Items

Transparent background with a dark outline, lit from the top left.

```python
tx.ingot(color)   tx.gem(color, cut=0)   tx.nugget(color)   tx.raw_chunk(color)
tx.dust(color)    tx.rod(color)          tx.seeds(color)
tx.food("fruit", color)     # fruit berries loaf meat stew cookie, with secondary= for leaf, bone or bowl
tx.pickaxe(head)  tx.axe(head)  tx.sword(head)  tx.shovel(head)  tx.hoe(head)   # handle= sets the wood
```

## Palettes

`tx.ramp("#e8742c", 5)` gives five colours, dark to light, with the base in the middle. Shadows drift cooler and more saturated, highlights warmer and paler. Use it for anything you draw yourself. `contrast=` scales the spread: about 0.6 for big block surfaces, 1.1 for items. Also here: `tx.mix(a, b, t)`, `tx.palette(img)`, `tx.tile_score(img)`, and `tx.recolor(img, base)` to put an image onto another colour.

## Animated textures

```python
tx.save_animated(tx.glow_frames(color, seed=1), "lamp.png", frametime=3)     # writes lamp.png and lamp.png.mcmeta
tx.save_animated(tx.machine_frames(casing, accent), "m_on.png", frametime=3)  # a flickering furnace
tx.save_animated(tx.scroll(tx.soil(color, style="mud")), "flow.png", frametime=2)
tx.save_animated(tx.pulse(any_block, frames=8), "pulse.png")
```

`frametime` is in ticks, 20 to a second. The file goes in `assets/textures/` with its `.mcmeta` beside it, as `feature-format.md` says.

## Sounds

Mono, under 2 seconds, Ogg Vorbis. `save` returns the path it actually wrote. Without ffmpeg that's a `.wav` plus a warning, and **the game can't play a `.wav`**, so check the suffix.

```python
sounds.save(sounds.block_hit("stone", seed=1), "hit.ogg")     # stone wood metal soil glass plant
sounds.save(sounds.block_break("wood", seed=1), "break.ogg")
sounds.save(sounds.machine_hum(pitch=70), "hum.ogg")          # loops without a click
sounds.save(sounds.machine_done(pitch=880), "done.ogg")
sounds.save(sounds.item_pickup(), "pickup.ogg")
sounds.mob_set("out/", "ember_husk", voice="growl", seed=3)   # writes _idle, _hurt and _death
```

Voices are `grunt growl squeak hollow gloop hiss`, and `pitch=` scales any of them. You can't hear these, so choose by what the sound should be: low and rough for something big, high and clean for something small. Vary with the seed, and never reuse one sound for two different things.

`feature-format.md` doesn't describe a place for sounds yet, so check how a feature should ship them before relying on it.

## Mobs

Model every creature and machine for itself, from nothing, in a script of its own. There are no body plans or parts to pick from, because anything premade makes everything look like a recolour. `assetkit/sculpt.py` gives you shapes that fill a grid of coloured voxels, and you make whatever the thing is out of those, with loops and maths where they help.

### The loop: write a script, read the preview, fix it

**Never ship a model you haven't looked at, and the first version is never the last.** Write the script, run it, read the preview images, and change the script. It takes a second or two, so go round as many times as it needs.

```python
from assetkit import sculpt

m = sculpt.Model("pebble_crab")

shell = sculpt.spots("#b4745a", "#8a4e3c", size=1.5, spacing=5, seed=2)
body = m.part("body", pivot=(0, 5, 0))
body.ball((0, 6, 0), (8, 4.5, 6), shell, power=2.4)
body.taper((5, 8, -5), (6, 12, -6), 0.8, 0.8, "#b4745a", mirror="x")     # eye stalks
body.ball((6, 13, -6), 1.6, "#f0ece0", mirror="x", shade=False)
body.decal(["kk", "kk"], {"k": "#1c1826"}, at=(6, 13, 0), mirror="x")
body.decal(["d......d", ".dddddd."], {"d": "#5a2c24"}, at=(0, 5, 0))

claw = m.part("claw_r", parent=body, pivot=(7, 5, -3))
claw.taper((7, 5, -3), (12, 4, -8), 1.6, 2.6, "#b4745a")
claw.ball((12, 4, -9), (3.2, 2.2, 3), "#c8826a")
claw.cut.box((10, 3.6, -13), (15, 4.6, -9))                              # the pincers' gap
m.mirror(claw)

leg = m.part("leg_r", parent=body, pivot=(7, 4, 2))
leg.taper((7, 4, 2), (12, 0.8, 3), 1.3, 0.8, "#8a4e3c")
m.mirror(leg)

LEGS = ["leg_r", "leg_l"]
CLAWS = ["claw_r", "claw_l"]
fidget = sculpt.keyed(CLAWS, rotation=[(0, (0, 0, 0)), (0.2, (-8, 0, 0), "out"), (0.3, (-8, 0, 0)), (0.42, (0, 0, 0)), (1, (0, 0, 0))], lag=0.06)

m.animate("idle", 3.0, sculpt.bob(body, 0.3, skew=0.3), fidget, sculpt.plant(LEGS))
m.animate("walk", 0.5, sculpt.gait(LEGS, stride=5, lift=2.2, heading=(1, 0), body=body, drop=0.5, roll=4), sculpt.pose(CLAWS, rotation=(14, 0, 0)), sculpt.follow(CLAWS, stiffness=3))
m.animate("attack", 0.6, sculpt.strike("claw_r", (50, 0, 0), back=0.1), sculpt.strike("claw_l", (20, 0, 0), back=0.1), sculpt.lunge(body, (0, 0, -3)), sculpt.plant(LEGS), loop="once")
m.animate("hurt", 0.45, sculpt.flinch(body), sculpt.flinch(CLAWS, move=(0, 0, 0), degrees=(25, 0, 0)), sculpt.plant(LEGS), loop="once")
m.animate("death", 1.4, sculpt.collapse(body, direction="back", degrees=75, limbs={"leg_r": (0, 0, 30), "leg_l": (0, 0, -30), "claw_r": (-40, 0, 20), "claw_l": (-40, 0, -20)}), loop="hold")

m.finish("pebble_crab.bbmodel", preview="pebble_crab.png")               # prints the numbers and any problems
```

Then read both `pebble_crab.png` and `pebble_crab_motion.png`, and judge them like a stranger would:

- **Could someone name it from its outline alone?** Look at the eight angles. Proportions do most of the work. Cartoon creatures have big heads; huge things have tiny ones.
- **Does its face have character?** The close views show it. Small changes to eyes are what change it most. Dark pupils with one light pixel look alive.
- **Is it the right size?** The panel stands it beside a player and a block, with a ruler in blocks.
- **Does it stand on the floor?** Lines a block apart mark the ground, and `check` reports anything through it.
- **Does it look alive when it moves, and does the motion suit what it is?** That's the second image. Say out loud what each row should feel like (quick and light, slow and enormous), then see whether it does. Motion nobody looked at is always a smooth sine wave with no weight in it. See [Animation](#animation) for what to look for.

`m.finish` runs `sculpt.check(m)`. Fix everything it reports. A mob's `width` and `height` come from `sculpt.stats(m)`.

### Parts

`m.part(name, parent=None, pivot=(x, y, z), rotation=(rx, ry, rz))` makes a bone, and every bone with voxels is one display entity in game, which is the real cost. Aim for 5 to 12. A bone with no voxels costs nothing, so use one as a joint.

Units are model units, 16 to a block, +Y up, feet at Y 0. **The front is -Z, so +X is the creature's own right, and on the viewer's left when you look at its face.**

**All coordinates are in the pose with every rotation at zero.** A part's rotation swings what you drew around its pivot, which is how a long body gets simple: draw it in one straight line, then lay it in curves with the joints' rotations (with X rotation, positive lifts whatever is ahead of the joint toward -Z). Work out which side of a part ends up facing front once its chain is posed. The belly of a snake's reared-up neck ends up there.

Name the bone that should turn to look at things starting with `head`, and put its pivot at the neck. Ears and horns are voxels in the head bone, or, if they have to move, bones under it whose names start with `head` too (`head_ear_r`), which turn with the look. Any other child of a head gets reported. Names starting with `hitbox`, `seat` or `driver` are reserved. Several bones without a parent get a joint added above them, so there's one root bone in the file.

`m.part(..., still=True)` says a part with no motion of its own is meant that way, so the motion check doesn't ask about it.

### Shapes

Each part method takes these arguments, then a colour, then options. Later shapes overwrite earlier ones.

| Call | What it is |
|---|---|
| `part.box(lo, hi, color)` | Everything between two corners |
| `part.ball(center, radii, color, power=2)` | An ellipsoid. Radii are one number or `(x, y, z)`. A power of about 2.5 flattens its sides, which suits a cartoon head, holds a face better, and takes fewer cubes |
| `part.capsule(a, b, r, color)` | A round-ended rod between two points |
| `part.taper(a, b, r0, r1, color)` | A rod with a radius at each end, for limbs, tails, ears, horns and claws. `flat=True` squares the ends |
| `part.cylinder(a, b, r, color)` | A flat-ended rod: axles, pistons, discs |
| `part.tube(points, radii, color)` | A bent limb through points, usually from `sculpt.curve(p0, p1, p2, n=10)` |
| `part.polygon(points, color, facing="front", at=0, thick=1)` | A flat outline, for wing membranes, leaves, flames and bolts. Points are `(x, y)` from the front, `(z, y)` from the side, `(x, z)` from the top. Keep its necks at least two wide, or they fall between voxels |
| `part.solid(fn, lo, hi, color)` | Anything else: `fn(x, y, z)` says what's inside, between two corners |
| `part.add(shape, color)` | A shape you've combined or turned yourself |

The options are `mirror="x"` to also draw it reflected through the model's middle, `shade=False` to keep a colour exact, and `glow=15` to make it emit light in game, which suits eyes, flames and fires (the whole cube glows, so its voxels get cubes of their own).

The same names at module level make `Shape` objects: `sculpt.ball(...)`. Combine them with `a | b`, `a & b` and `a - b`, and move them with `.moved(offset)`, `.mirrored("x")` and `.rotated((rx, ry, rz), about=point)`. That last one is how something flat leans any way inside one part: `sculpt.ball(c, (3, 9, 1.5)).rotated((0, 0, -14), about=c)` is an ear.

- **`part.cut`** removes voxels, for mouths, sockets and holes: `head.cut.box(...)`, or `head.cut(shape)`.
- **`part.paint`** recolours what's already there without changing the shape: `body.paint.ball(c, r, color)`.
- **`part.mirror("x")`** copies what's in a part across the middle. **`m.mirror(part)`** makes a new part from one, with its pivot, rotation and children, and `leg_r` becomes `leg_l`.

### Colour

A colour is `"#rrggbb"`, `(r, g, b)` or `(r, g, b, a)`, or a function of position that takes arrays `x, y, z` and returns colours. One written for single numbers works too, only slower. These helpers make such functions, and each takes a colour or another helper as its base, so they stack. They're paint, not parts.

```python
sculpt.gradient(["#ffe668", "#e0301a"], a, b, steps=6)     # from point a to point b, in flat steps
sculpt.bands([c1, c2], along="y", width=2)                 # along an axis, a direction, or a function of position
sculpt.stripes(base, color, along="z", every=6, width=2, start=0, stop=30, where=lambda x, y, z: z > 2)
sculpt.spots(base, color, size=1.5, spacing=6, seed=0)
sculpt.patch(base, color, center, radii, rim=None)         # a belly
sculpt.mottle(base, color, size=3, amount=0.3, seed=0)     # soft clusters, for stone and hide
sculpt.where(lambda x, y, z: y > 40, a, b)                 # one paint here, another there
```

Surfaces are shaded for you along each colour's `tx.ramp`, using a smoothed normal, so any shape reads as round and creases go dark. Each face direction also pulls against the game's own light, or every step of a curved surface would read as a bright and dark stripe. `sculpt.Model(name, shade=0.4)` softens that, which suits flat machine parts, and `part.shading = 0` turns it off for one part.

Translucent colours work. They draw after the opaque voxels in their bone, and opaque voxels inside them show through, so a solid glass shape with a glowing core needs no hollowing out.

### Faces and fine detail

Faces are what make a creature recognisable, so art goes on exactly where you aim it.

```python
head.decal(["kkkk",
            "kwwk",
            "kkwk",
            "kkkk"], {"k": "#2a2118", "w": "#fbfbf0"}, at=(4.5, 27, 0), mirror="x")
```

- It's drawn as seen from `facing`, so what you type is what you see: `front`, `back`, `left`, `right`, `top`, `bottom` or a direction to look along. `at` is where the art's centre is aimed, and on a straight view only the two coordinates across it matter.
- A pixel is one voxel on the first surface it meets, and `.` and space are gaps. Its colours stay exact through shading.
- `depth=3` paints that many voxels in, so a cheek wraps around a curve instead of breaking into stripes from the side.
- With a direction instead of a side's name, `at` has to be a point on the surface.
- `near=0` starts looking from `at` itself rather than from outside the model, to reach past something in the way.

A pattern on a steep or round surface breaks up from an angle, because it lies across steps. For eyes that have to read from every side, make them shapes (`head.ball(eye, r, "#f4f0e4", shade=False)`) and put the iris on them as a decal. A flatter face from `power=2.5` helps too.

`part.layers(rows, palette, at, facing="front")` places exact voxels from pixel art, for fine shapes. Each layer is a list of strings, and more layers go on away from the viewer.

An odd width can't be centred on `x=0`, since voxels lie either side of it, so it lands half a voxel off. Use even widths on the centre line.

### Animation

A mob needs `idle` and `walk`, `hurt` and `death`, and `attack` if it fights. The engine plays `attack` when it lands a hit and `hurt` when it takes damage, and when it dies it plays `death` and keeps the body in the world until that finishes, for 5 seconds at most. A machine needs only `idle` and `walk`, with its working cycle under `walk`, and anything else you name for it: pass `machine=True` to `check` and `finish`.

`m.animate(name, seconds, *tracks, loop="loop")` combines tracks, which add up where they meet. Use `loop="once"` for `attack` and `hurt`, and `loop="hold"` for `death`, so that it stays down. Seconds round to whole ticks, of which there are 20 a second.

#### What makes motion look alive

The same smooth sine wave on everything looks like a thing floating in syrup. Here's what fixes that, and the helpers below do the sums.

- **Timing is where weight comes from, more than anything else.** Small things are quick, and snap between holds: a mouse's whole stride cycle is 0.4 seconds. Enormous things take ages to start and stop: a colossus 6 blocks tall takes 3 seconds over its cycle and 2.6 over a blow. Choose the lengths first, and choose them by asking how heavy it is.
- **Uneven beats even.** Real motion drives hard and recovers slowly, or darts and holds. Hardly anything alive moves at one speed the whole way through (`skew`, `beats`, `glance`). A moment of stillness is what makes the next move read.
- **Anticipation.** Go back before going forward. The wind-up is what the eye catches, and it's what makes a blow land (`snap`, `windup`).
- **Overshoot and settle.** Go past the target and come back onto it (`over`, the `back` and `settle` eases).
- **Weight in the body.** The body sinks just after a foot lands, not as it lands, then rises over the planted leg. It shifts toward the foot that's down, and the hips and shoulders turn against each other. Squash on landing, stretch on take-off (`gait`, `weight`, `hop`, `squash`).
- **Feet stay planted.** A leg that swings like a pendulum drags its foot along the ground. A real foot stays where it was put, then lifts and comes through, and legs bend to let it (`gait`, `plant`). This shows on every animation: a lunge with sliding feet is an ornament on a stick.
- **Follow-through.** Anything that hangs doesn't move with the body. It reacts late, swings on after the body stops, and settles (`follow`). Tails, ears, wing tips, hands, antennae, hair.
- **Nothing starts at once.** Hips, then shoulders, then arm, then hand (`lag`).
- **A steady head.** A creature keeps its eyes on things, so its head moves less than whatever carries it (`steady`).
- **Secondary motion.** A flick of the ear, a flicker in the flame, a look to one side. These are what stop it looking like a machine that's running.
- **Arcs.** Hands and heads travel in curves. Rotations give you this for free, and for a thrust, add a rotation to the position.

Machines are the exception: an even cycle looks right for an even engine, and they get their character from lurches and impacts instead (`spin(timing=...)`, `keyed`).

**One animation plays at a time, and it owns the whole model.** BIL doesn't blend. The moment `attack` starts, every bone it doesn't move snaps to rest, tails mid-swing included, and when it ends the next one starts from its first frame. So a one-shot should move the whole body rather than one arm, hold the feet with `plant`, and start and end at rest. `check` reports one that doesn't. Anything that never stops, like a flame, goes in through `fade`, so it doesn't jump when the animation ends.

**How fast is too fast.** A tick is the smallest step. Display entities smooth over 2 ticks, so a move under about 0.1 seconds barely registers, and a blow has to take at least 2 or 3 ticks. More than 90 degrees in a tick can go the wrong way round, and `check` reports it.

#### Timing

A timing is any function of phase, from 0 to 1 over the animation. These make them.

```python
sculpt.ease("out", t)      # linear, in, hard_in, out, hard_out, in_out, back, anticipate, settle, bounce, or your own function
sculpt.beats((0, 0.0), (0.3, 1.0, "out"), (0.5, 1.0), (1, 0.0, "in_out"))    # through stops. Each ease is how it gets there from the stop before
sculpt.snap(windup=0.25, hit=0.45, back=0.25, over=0.12, hold=0.1)           # back by this share until windup, past 1 by over at hit, onto 1, a hold, home
```

A value in `beats` can be a number or `(x, y, z)`. Two stops with one value are a hold.

#### Moving parts

These work on whatever parts you name. In a list, `lag` starts each part that much of the phase after the one before.

```python
sculpt.move(arm, rotation=(-70, 0, 0), position=(0, 1, -2), scale=(1, 1.2, 1), timing=sculpt.snap(), lag=0.03)   # how far it goes at an amount of 1
sculpt.keyed(arm, rotation=[(0, (0, 0, 0)), (0.3, (25, 0, 0), "out"), (0.45, (-80, 0, 0), "hard_in"), (1, (0, 0, 0))])   # poses you choose. Also position= and scale=
sculpt.pose(body, rotation=(-6, 0, 0), position=(0, -1, 0))                  # held for the whole animation, like a lean into a walk
sculpt.strike(arm, degrees=(-70, 0, 0), windup=0.25, hit=0.45, over=0.12)    # draw back, swing past, settle, return. Or any timing=
sculpt.lunge(head, distance=(0, 0, -6), windup=0.25, hit=0.45, over=0.12)    # the same as a thrust
sculpt.swing(["leg_r", "leg_l"], degrees=30, axis="x", cycles=1, offset=0.5, center=0, skew=0.3)   # each part a phase after the last
sculpt.flap(right=["wing_r", "tip_r"], left=["wing_l", "tip_l"], degrees=35, axis="z", lag=0.06, skew=-0.35)
sculpt.wave(["tail1", "tail2", "tail3"], degrees=15, axis="y", waves=1.0, grow=0.0)   # travels down the chain
sculpt.bob(body, amount=0.5, cycles=1, bounce=False, skew=0.3)
sculpt.breathe(body, amount=0.03, axes="xyz", skew=0.3)
sculpt.squash(body, amount=-0.15, at=(0.0, 0.5), width=0.2)                  # keeps the volume, at these moments or to a timing=
sculpt.hop(body, height=4, air=0.5, squash=0.14, stretch=0.1)                # a real arc, stretching off the ground and squashing on landing
sculpt.glance(head, (0.2, -24, 4), (0.5, 8, -4), speed=0.05)                 # darts to each (phase, yaw, pitch), holds it, and comes home
sculpt.flicker(flame, scale=0.13, rotation=5, rate=9, seed=3)                # restless and uneven, but it loops
sculpt.fade(track, out=0.2, into=0.0)                                        # any track, faded to rest at the ends
sculpt.spin({gear: 1, pinion: -2}, axis="x", timing=None)                    # whole turns, so that it loops. timing bends the speed
sculpt.weight(body, at=(0.0, 0.5), sides=(-1, 1), drop=1.0, sway=0.5, roll=3, twist=4, nod=2, duty=0.6)      # a body carried by feet landing at these phases
```

`skew` bends a cycle's time without breaking the loop, up to about 0.8: positive makes it rise through zero quickly and fall slowly. A track is only `{part: {"rotation"|"position"|"scale": fn}}`, with `fn` taking the phase and returning `(x, y, z)`, so anything else is a lambda away. Rotation is in degrees and position in model units.

BIL adds an animation's rotation to the bone's own before making a quaternion, so a tilted bone doesn't spin around its own axis. Put the tilt on an empty joint above it and spin the bone inside. The same goes for a joint you mean to turn a long way, or whose axes you want to think about plainly: lay it out with an empty joint, and animate the bone inside.

#### Walking

```python
sculpt.gait(["leg_r", "leg_l"], stride=6, lift=2.5, body=body)                                  # one-part legs, any number
sculpt.gait([["thigh_r", "shin_r"], ["thigh_l", "shin_l"]], knee="front", crouch=0.1, body=body)    # bends at the knee
sculpt.gait([["thigh_r", "shin_r", "foot_r"], ["thigh_l", "shin_l", "foot_l"]], body=body)          # and keeps a flat foot level
sculpt.gait([["leg_r", "foot_r"], ["leg_l", "foot_l"]], level=True, body=body)                      # a rigid stub of a leg on a separate foot
sculpt.plant(LEGS)                                                                              # the same legs, knee= and level= in everything but the walk
```

`gait` takes any number of legs in any arrangement, and works out each leg's rotation so that its foot really is on the ground, whatever else moves the body. The ground is wherever the foot is at rest, so model it standing there. Each list goes from the hip.

- **`stride`** is how far a foot travels while it's down, in units, and **`lift`** how high it goes.
- **`duty`** is the share of the cycle a foot spends down. Higher is slower and heavier. The default depends on the pattern.
- **`pattern`**: `walk` is one foot at a time, in the order animals use. `trot` moves every other foot together: a running biped, a horse's trot, an ant's tripod. `bound` is the front pair, then the back pair. A dict of part to phase is whatever you like.
- **`heading=(x, z)`** is the direction of travel, so `(1, 0)` walks a crab sideways. **`cycles`** fits more than one cycle in the animation.
- **`knee`** is `front`, `back`, `out`, `up` or a direction, and a leg modelled bent already knows. **`crouch`** lowers the body for the whole walk, as a share of the legs' length, because a straight leg has no room to bend.
- **`body`** takes the weight: `drop` is how far it sinks at each landing, `sway` how far it shifts over the foot that's down, `roll` how far it tilts over it, `nod` its pitch at each landing, and `twist` turns the hips. Those are sensible for the legs' size unless you say otherwise. **`shoulders`** names a part to turn against the hips, and **`arms`** swing against the opposite leg by `arm_swing` degrees.
- **`tilt`** is how far a rigid one-part leg leans before it moves bodily in its socket instead, and **`peel`** tips a separate foot's toe down in the air.

Legs too short to bend read better as a rigid leg with `level=True`, or as one part. Long legs with knees and a low `duty` read as heavy. Lots of quick small legs want `trot`.

`stats(m)["walk_speed"]` is how fast the feet go past, in blocks a second. **A mob moving at about that speed looks planted, and anything else looks like skating**, so change `stride` or the animation's length until it matches the speed you want.

#### What's worked out from the model

`gait`, `plant`, `follow`, `steady` and `collapse` read the other tracks in the animation, so they work whatever order you pass them in.

```python
sculpt.follow(["tail1", "tail2", "tip"], stiffness=2.0, damping=0.3, amount=1.0, limit=45)
sculpt.steady(head, amount=0.7, level=0.4)
```

- **`follow`** treats each part as a damped spring, driven by how the part above it really moves in this animation, so it comes from the motion rather than from a rule. A chain passes it down, later and further each time. Give the list from the root outward. `stiffness` is how fast it swings back, in cycles a second: low is heavy and floppy, high is short and springy. `damping` of 0.1 keeps wobbling, and 0.7 barely overshoots. A still carrier moves nothing, so give the body some motion for it to answer. A loop of it stays a perfect loop.
- **`steady`** takes out this share of the turning of whatever carries a part, and `level` is the share of its movement to take out.

#### Hurt and death

```python
sculpt.flinch(body, move=(0, 0.6, 3), degrees=(12, 0, 0), hit=0.14, shake=2.0, lag=0.03)
sculpt.collapse(body, direction="forward", degrees=85, limbs={"head": (28, 0, 0), "arm_r": (40, 0, 30)}, fall=0.55, stagger=0.06, bounce=0.1, slide=0.5)
```

- **`flinch`** throws a part back all at once and wobbles it home, so the first instant reads as the blow. Keep the whole thing short, about 0.4 seconds for something small and 0.9 for something huge, with `plant` for the feet, and the head and limbs reacting too, each with its own `degrees`.
- **`collapse`** is a stagger, a fall that goes faster and faster, a small rebound off the floor, then stillness. `root` is the part everything hangs from, `direction` is `forward`, `back`, `left` or `right`, and `fall` is the phase of the impact. `limbs` maps parts to the rotation they end at, and they go slack late and flop on impact. The lowest point stays on the floor all the way. Things without a body to fall over can deflate instead, with `keyed` and `scale`. Fall forward or back rather than sideways, for the reason under Dying, below.

#### Keyframes

The build samples each track at every tick and keeps only the keyframes it needs to stay within 0.4 degrees, 0.03 units and 0.4% of scale, and a channel that doesn't move costs nothing. `stats(m)["keyframes"]` counts them, at about 110 bytes each. Those are usually well under the voxels' share of the file, so don't scrimp on them. What costs more in game is the length of an animation, because BIL bakes every bone in it to one matrix per tick when it loads. `m.animate(..., samples=12)` samples evenly instead, which you shouldn't need.

### Checks and numbers

`sculpt.check(m, machine=False)` returns a list of problems, and it's what `m.finish` prints. It runs `bbmodel.check`, then looks for voxels floating apart from the rest of a part (`part(..., loose=True)` says separate pieces are on purpose), parts that don't touch their parent as posed at rest, too many bones (over 16 with voxels), too many cubes (over 300 in a bone or 1600 in all), a skin over 512x512, anything through the floor, a decal that missed or a paint that landed on nothing, and a front that's one plain colour.

It measures the motion too, and these are also printed across the top of the motion sheet:

- a part with children, or a limb, that never moves in any animation
- a foot in the walk that never lifts, slides while it's down, or goes at a different speed from the others
- a walk where the body doesn't move at all
- a loop whose last frame doesn't meet its first
- a one-shot that doesn't end at rest
- a part that sinks through the floor in any animation, by more than a unit
- more than 90 degrees in a tick
- no `hurt` or `death`, unless `machine=True`

A foot is a bone with a `gait` or `plant` on it, or one whose name has leg, foot, shin, paw, hoof or toe in it and that reaches the ground. Passing these says nothing's obviously dead, not that it looks good. Only the image can tell you that.

`sculpt.stats(m)` returns:

| Key | What it is |
|---|---|
| `height`, `width` | What to declare for a mob, in blocks. `width` goes by where the bulk is, so wings and tails don't make the hitbox huge |
| `size` | The whole bounding box in blocks, as `(x, y, z)` |
| `bones`, `drawn_bones` | All bones, and the ones with voxels that cost an entity |
| `elements`, `faces` | Cubes and quads. Hidden faces are left out |
| `atlas`, `bytes` | The skin's side and the file's size |
| `keyframes` | How many are in the file |
| `walk_speed` | How fast the feet go past in the walk, in blocks a second, or `None` |

A round part takes more cubes than a square one: a plain ball of radius 8 is about 110, and 12 is about 180. `power` above 2 cuts that. If a big creature goes over budget, or for anything several blocks tall, use `grain`: `sculpt.Model(name, grain=2)` makes voxels 2 units across, and a decal's pixels with them. One part can have its own with `m.part(..., grain=2)`.

Building takes 0.1 to 0.2 seconds for a 40-unit creature or a boss 6 blocks tall at grain 2, with a `gait`, `follow` and `collapse` in its animations. The two preview images take 1 to 2 seconds together.

### The preview

`m.preview("name.png")`, or `m.finish(path, preview="name.png")`, writes two images: `name.png` is how it looks, and `name_motion.png` is how it moves. **Read both, every time.** The second one isn't written if there's no animation.

The first sheet comes from `bbmodel.preview(model, out, focus=None)`, with a real depth buffer, the skin at one texel per texel, and the two fixed lights the game shades entities with, so a model looks here as it does there. That's why the sides of a mob look darker than its front. `focus` names the bones for the close views, which is the head by default. Anything with `glow` also gets a view in the dark.

The motion sheet is about 1400 pixels wide, one band to an animation, all at one scale. Measured problems are in orange across the top.

- **Six frames, evenly spaced in time,** so that how far things move between them is how fast they're going. A walk gets a second row: side on, or from the front if it walks sideways, or from above if it's long with no feet. Everything else is from three quarters.
- **An onion skin,** on the right. Twelve ghost frames are laid over each other, with a dotted trail for the parts that travel furthest, one dot a tick. Read the dots: bunched is slow and far apart is fast, so a blow should be a cluster, then a gap, then a cluster. Even dots mean it has no timing. The trail's shape shows whether it travels on an arc.
- **Curves,** along the top of the band, for what moves the most. A clean sine wave here is a warning sign. A hit should have a sharp corner in it.
- **A chart of when each foot is down,** under a walk, with how far each lifts and slides, and the walk speed. The bars should show an even pattern, and at least one foot down at nearly any moment unless it's meant to leap.

`bbmodel.render(model, anim=None, t=0.0, yaw=-35.0, pitch=22.0, scale=5, size=None)` draws one view of any moment, and yaw 0 looks at the face. `bbmodel.motion_sheet(model, out)` and `bbmodel.motion_notes(model)` give you the second image and the notes alone.

`bbmodel.humanoid`, `quadruped`, `slime` and `flying` are still here for the stand-ins a template makes until someone sculpts the real thing. Never ship one.

### What Blockbench Import Library needs

Checked by reading the source of [BIL](https://github.com/tomalbrc/blockbench-import-library) at `main`, tag `v2.2.0+26.3-rc-3` (September 2026, listed on Modrinth for game version 26.3), through the GitHub API and then its bytecode, along with Blockbench's own save code. `bbmodel.check()` enforces these. Sculpted models also go through BIL's real `BbModelLoader` and the game's own client model parser (`CuboidModel.fromStream`) without complaint, and the bone matrices BIL bakes for every frame match what the preview draws. They've been rendered standing still on a real client as well. Their animations have only been checked this far.

Format:
- **Layout:** `meta.format_version` of 5.0 or more selects `BbModel5Importer`, which reads bones from a top-level `groups` list. We write `5.0`, as current Blockbench does, in the generic `free` format.
- **Sign of keyframes:** the 5.x importer uses rotation and position as written. Blockbench flipped X and Y rotation and X position between 4.x and 5.0, so don't paste keyframes from an older file.
- **Fields that crash or silently drop things if missing:** a bone's `origin` and `rotation` (crash) and `export: true` (no model made); a cube's `type: "cube"` (skipped) and `origin` (crash); an animation's `loop` (crash); a keyframe's `interpolation` (crash).
- **Numbers:** vectors must be arrays of exactly three numbers. Molang strings work in keyframes, but only `q.anim_time` and `q.life_time`. We write plain numbers, with linear interpolation, and keyframes need no `uuid` or `color`.
- **Faces:** a cube can leave out any face. BIL passes on whichever are there, and the game wants 1 to 6, so a cube with none has to go. That's why sculpted models leave out hidden faces and drop cubes with nothing showing.
- **Light:** `light_emission` on a cube, from 0 to 15, reaches the item model and the game reads it. It applies to the whole cube.

Textures:
- **Embedded PNG:** `source` must be a `data:image/png;base64,` URL. BIL never reads a file path.
- **UVs:** BIL divides by the texture's `uv_width` and `uv_height` and reads each face's `uv` directly, whatever `box_uv` says. Each face's `texture` is an index into `textures`.
- **Sizes:** BIL writes an animation `.mcmeta` for any texture whose height is a multiple of its width, using `frame_time` as the frame time. So a square skin gets one with a single frame, which should be harmless, but `frame_time` must be at least 1, and a skin twice as tall as wide would turn into two frames. We write power-of-two squares.

Bones and animation:
- **Head:** a bone whose name starts with `head` turns to follow the entity's look, pivoting at the bone's `origin`, so that goes at the neck. BIL's docs warn that child bones under a head don't move correctly, but its code (`LivingEntityHolder.applyPose`, tag `HEAD_CHILD`) turns them with the look about the head's current origin. So `check` allows them if their names start with `head` as well. Read from the bytecode, and not yet seen on a client.
- **Reserved names:** bones starting with `hitbox`, `seat` or `driver` get special treatment. Don't use those for body parts.
- **One root bone:** BIL rebuilds every bone once per root entry, so more roots only waste load time.
- **Facing:** BIL turns models 180 degrees, so the front is -Z, which is `north` in Blockbench. Faces go on `north`.
- **Animation names:** BIL requires none. It stores them by exact name. Its documented walk helper plays `walk` and `idle`, so we use those, and not Blockbench's `animation.x.walk` style.
- **Baking:** animations are baked to one frame a tick, 20 a second, on load. A loop plays its frames and goes straight back to the first, so a last frame equal to the first would hold for a tick, and `m.animate` makes a loop of N ticks N-1 long, its last frame one step short of its first, so it runs evenly. An animation's rotation is added to the bone's own rotation before the quaternion is made. Display entities interpolate over 2 ticks, and interpolating a quaternion takes the short way round, which is why over 90 degrees in a tick can go wrong.
- **No blending:** an animation with an empty `affectedBones` affects every bone, so the top priority of whatever's playing owns the whole model, and nothing mixes. The engine's priorities are idle 1, walk 5, hurt 8, attack 10, death 20.
- **Dying:** while an entity's `deathTime` is above 0, BIL's `LivingEntityHolder` rolls the whole model over toward its left about the origin, up to 90 degrees within about 0.6 seconds, and stops the head following the look. That comes on top of any `death` animation, for any engine that counts up `deathTime`, so don't count on the floor being where the preview shows it in a death, and fall forward or back rather than sideways.
- **Cost:** every bone with cubes becomes one item display entity. Keep them to about 12.
- **Size:** BIL measures a bone from its pivot to its furthest cube. If that spans over 24 units, it shrinks the bone's cubes in the item model and scales that entity back up, which only affects that bone, not its children. So big bones work and always fit the -16 to 32 a model can hold.
- **Culling:** BIL gives each display entity a culling box of twice the mob's hitbox width and its height plus one. Parts reaching well beyond that can vanish once the mob's middle is off the edge of the screen.

Loading:
- **Where files go:** the docs say `/resources/model/<namespace>/<path>.json`, but `BbModelLoader` opens `/model/<namespace>/<path>.bbmodel`. `BbModelLoader.load("some/path.bbmodel")` also works and doesn't care about location.
- **Timing:** BIL adds its files whenever Polymer builds the pack (`RESOURCE_PACK_AFTER_INITIAL_CREATION_EVENT`, the event `LiveAssets` uses too). A model loaded while the server runs reaches players at the next `polymer generate-pack`, not before.
- **Trying one in game:** `/bil model create <namespace>:<path>` spawns a model at permission level 2, and `/bil model <targets> animation ...` plays its animations. The code only takes a resource ID here, although BIL's README also mentions file paths.
- **Names leak:** BIL writes into the pack under `assets/bil/`, in folders named after the model file. A file called `ember_husk.bbmodel` puts `ember_husk` in the pack for anyone to read, so give the file a meaningless name if the mob should stay a surprise. Bone names don't reach the pack, since BIL uses UUIDs for those files.

## What good looks like

- **Few colours.** 4 to 6 per block surface. Ores run to about 9 with their flecks; a tool head and handle to about 10.
- **Soft contrast.** Stone's tones sit close together. High contrast reads as noise at a distance.
- **Clusters.** Shapes of 3 or more pixels, not salt and pepper. If a block looks like TV static on the sheet, regenerate or lower the contrast.
- **Tiling.** Look at the 3x3 view. Stripes or a grid you didn't intend mean a problem; try another seed. Metal and machines show their frame on purpose.
- **Readable ore.** You should spot the ore in the tiled view in a moment, and the rock should still look like rock.
- **Clean silhouettes.** Cover an item's insides in your mind: the outline alone should say what it is.

## Common mistakes

- **Pure black or white.** Ramps avoid these. If you draw by hand, use the ramp too.
- **Darkening instead of shifting.** `tx.mix(c, (0, 0, 0))` gives muddy shadows. Use `tx.ramp`.
- **Hand-drawn noise.** `np.random` per pixel always looks bad. Use the generators, or `tx._stamp` for clusters.
- **Bright saturated stone.** Rock should be close to grey, even when magical. Put the colour in the flecks.
- **Too many ores in one colour family.** Players tell ores apart by hue. Check the theme's other ores first.
- **Oversized textures.** A 64x64 block next to 16x16 vanilla looks wrong whatever it shows.
- **A `tinted_plant` with coloured leaves.** The biome tint multiplies over it and it turns muddy.
- **Forgetting the `.mcmeta`.** Without it an animation strip shows up as one squashed texture.
- **Spending plant slots.** Only 5 exist, forever.
- **Skipping `check()` after editing a `.bbmodel` by hand.** A missing field fails only when the server loads the model.

## Testing

```
python3 -m unittest assetkit.test_assetkit assetkit.test_sculpt
```
