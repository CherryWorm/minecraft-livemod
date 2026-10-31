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

```python
mob = bbmodel.humanoid("ember_husk", primary="#8a5a48", secondary="#3c4a5a", eye="#ffb040", mood="angry", seed=3)
bbmodel.save(mob, "ember_husk.bbmodel")
bbmodel.preview(mob, "ember_husk_preview.png")     # read this image
assert not bbmodel.check(mob)
```

Kinds are `humanoid`, `quadruped`, `slime` and `flying`. Each comes with a matching skin embedded in the file, and `idle` and `walk` animations. `walk` is a hop on a slime and flapping flight on a flyer. Options include `horns=True` and `spots=False`, and `mood` is `calm` or `angry`.

To add a custom animation, pass functions of the loop's phase, from 0 to 1. Rotation is in degrees and position in model units, 16 to the block:

```python
bbmodel.animate(mob, "attack", 0.5, {"arm_right": {"rotation": lambda p: (-90 * math.sin(math.pi * p), 0, 0)}}, loop="once")
```

The preview shows four angles, poses from each animation, and the skin. Look for a face on the front, limbs swinging from the shoulder or hip rather than their middle, and nothing cutting through the floor.

Playing these in the game needs BIL on the server and a way for a feature to declare a mob. `infra/mods.lock` has no BIL yet and `feature-format.md` has no mobs, so check that both exist before designing around one.

### What Blockbench Import Library needs

Checked by reading the source of [BIL](https://github.com/tomalbrc/blockbench-import-library) at `main`, tag `v2.2.0+26.3-rc-3` (September 2026, listed on Modrinth for game version 26.3), through the GitHub API, along with Blockbench's own save code. `bbmodel.check()` enforces these. **No file has been loaded by a real server yet**, so treat that as still to be proven.

Format:
- **Layout:** `meta.format_version` of 5.0 or more selects `BbModel5Importer`, which reads bones from a top-level `groups` list. We write `5.0`, as current Blockbench does, in the generic `free` format.
- **Sign of keyframes:** the 5.x importer uses rotation and position as written. Blockbench flipped X and Y rotation and X position between 4.x and 5.0, so don't paste keyframes from an older file.
- **Fields that crash or silently drop things if missing:** a bone's `origin` and `rotation` (crash) and `export: true` (no model made); a cube's `type: "cube"` (skipped) and `origin` (crash); an animation's `loop` (crash); a keyframe's `interpolation` (crash).
- **Numbers:** vectors must be arrays of exactly three numbers. Molang strings work in keyframes, but only `q.anim_time` and `q.life_time`. We write plain numbers, sampled at 12 per second.

Textures:
- **Embedded PNG:** `source` must be a `data:image/png;base64,` URL. BIL never reads a file path.
- **UVs:** BIL divides by the texture's `uv_width` and `uv_height` and reads each face's `uv` directly, whatever `box_uv` says. Each face's `texture` is an index into `textures`.
- **Sizes:** BIL writes an animation `.mcmeta` for any texture whose height is a multiple of its width, using `frame_time` as the frame time. So a square skin gets one with a single frame, which should be harmless, but `frame_time` must be at least 1, and a skin twice as tall as wide would turn into two frames. We write power-of-two squares.

Bones and animation:
- **Head:** a bone whose name starts with `head` turns to follow the entity's look, pivoting at the bone's `origin`, so that goes at the neck. BIL's docs warn that child bones under a head don't move correctly, so we have none.
- **Reserved names:** bones starting with `hitbox`, `seat` or `driver` get special treatment. Don't use those for body parts.
- **One root bone:** BIL rebuilds every bone once per root entry, so more roots only waste load time.
- **Facing:** BIL turns models 180 degrees, so the front is -Z, which is `north` in Blockbench. Faces go on `north`.
- **Animation names:** BIL requires none. It stores them by exact name. Its documented walk helper plays `walk` and `idle`, so we use those, and not Blockbench's `animation.x.walk` style.
- **Baking:** animations are baked to 20 frames a second on load, and a loop's last frame repeats its first, so it holds for one tick.
- **Cost:** every bone with cubes becomes one item display entity. Our mobs have 1 to 7. Keep it low.
- **Size:** a bone spanning over 24 units gets scaled down in its model and scaled back up in the animation, so big bones work. Ours all fit.

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
python3 -m unittest assetkit.test_assetkit
```
