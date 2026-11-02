# Feature bundle format

Knowledge, machine recipes, mobs, projectiles, vehicles, props, beams, plants, ruins, biomes, dimensions and sounds are in `docs/content-types.md`.

Each feature is one folder, `mods/genesis/features/<id>/`, where `<id>` is lowercase letters, digits and underscores.

```
<id>/
  feature.json
  assets/
    textures/<name>.png        16x16 unless you have reason otherwise
    textures/<name>.png.mcmeta only for animation
    models/<block_name>.json   optional custom block model
    lang.json                  rarely needed. Use "texts" in feature.json instead
  raw/                         optional vanilla data and resource pack files. See 'Raw files' in docs/content-types.md
    data/gm/..., data/minecraft/tags/...
    assets/gm/...
  server/                      optional Java module, on the server
    src/main/java/...
    src/main/resources/module.properties   contains entry=<class>
  client/                      optional Java module, on players' clients
    src/main/java/...
    src/main/resources/module.properties
  mixins/                      optional patches to the game's own code, on the server, only when no hook will do. See Mixins
    src/main/java/gm/feature/<id>/mixin/...
    src/main/java/gm/feature/<id>/shared/...
```

## feature.json

```json
{
  "id": "ember",
  "phase": 1,
  "summary": "What this is, for other builders. Players never see it.",
  "blocks": {
    "ember_ore": {
      "family": "ore",
      "display": "Ember Ore",
      "texture": "ember_ore",
      "tool": "pickaxe",
      "tool_level": "stone",
      "drops": {"item": "ember", "count": [1, 2]}
    }
  },
  "items": {
    "ember": {"display": "Ember", "texture": "ember"}
  },
  "ores": [
    {"id": "ember_ore_v1", "block": "ember_ore", "replaces": ["minecraft:stone", "minecraft:deepslate"],
     "veinsPerChunk": 3, "veinSize": 7, "minY": -40, "maxY": 48}
  ],
  "recipes": {
    "ember_block": {
      "mode": "open",
      "json": {
        "type": "minecraft:crafting_shaped",
        "pattern": ["XX", "XX"],
        "key": {"X": "$item:ember"},
        "result": {"id": "$block:ember_block", "count": 1}
      }
    }
  }
}
```

## Where a feature sits in the world

`bible/progression.json` is this world's progression, a graph of nodes where each lists the nodes that come before it. Every feature belongs to one, named as `"node"` in `feature.json`. You're told which node when you're given a feature. These are checked when it's released:

- **Recipes follow the graph.** A recipe can only use your content from its own node or from nodes that come before it.
- **Later things have to be earned.** Past the first nodes, any recipe for tiered gear or a machine has to need a material from a node directly before it in the graph, either itself or through something else you make from it. So endgame gear needs what the step before it makes, not just the first ore anyone found. If there are several recipes for one thing, all of them do, so a cheap one can't get around it.
- **Each stage has limits.**

| Stage | Strongest tier | Strongest mob (health, damage) | What can run by itself |
|---|---|---|---|
| `early` | `iron` | 30, 6 | Nothing |
| `mid` | `beyond` | 150, 15 | Limited, as listed below |
| `end` | `mythic` | No limit | No limit |

**What runs by itself.** Anything that works without a player being there is declared, with what it does and how fast, and a reviewer compares that with your code:

```json
"automation": [{"what": "mining", "per_minute": 6}]
```

The most the mid game allows, per minute: `mining` 6, `mob_killing` 1, `crafting` 20, `machining` 20, `farming` 20, `sorting` 150, `transport` 150.

**What players already have stays as it is.** Once anyone has held or killed something, a release that changes it (its numbers, recipes, art or where it's found) is refused, unless you give a reason for that thing, and a reviewer judges whether it's a good one. `world_index` marks what players have.

```json
"changes_reached": {"tin_pick": "Three players said it breaks too quickly to be worth making"}
```

## Changing another feature

This mod is one codebase. If your work needs another feature to change, because its recipe is in the wrong place, say, or a machine should take what you've added, then change it yourself. Don't work around it, or wait for it, or leave a note for someone. There are two ways.

**Adding to its data, from your own folder.** This is the one to reach for if all you need is another line in one of its lists, because nothing you add here can collide with anyone. It's put together when a release is made, so it never touches the other feature's files.

```json
"adds_to": {
  "alloy_kiln": {
    "why": "A tablet found in the new ruins should be another way to learn this",
    "knowledge.alloying.routes": [{"type": "read", "id": "$item:worn_tablet"}],
    "knowledge.alloying.text": "A paragraph more for its page in the Codex.",
    "ruins.old_kiln.loot.pools.0.entries": [{"type": "minecraft:item", "name": "$item:worn_tablet"}]
  }
}
```

Each key is a place in that feature's `feature.json`, with dots between the names and numbers for places in a list. It has to be inside `knowledge`, `blocks`, `items`, `mobs`, `ruins` or `recipes`, or be `changes_reached`, and it can only add: what you give goes on the end of a list, new names go in an object, and a paragraph goes on the end of a page's `text` or a mind's `character`. If the last name isn't there yet, it's created. `$item:name` means your own, wherever it ends up, and anything else that names something, like `requires`, is read as if that feature had written it, so give yours as `your_feature/name`. All the gates see the other feature with your additions in it. If you change a thing players already have this way, the `changes_reached` reason goes in here too.

**Changing its files.** For anything else, edit that feature's folder directly, in your own tree, and say so in your own `feature.json`:

```json
"changes_features": {"alloy_kiln": "Its bronze recipe was on the wrong machine, so players never found it"}
```

Only what's listed here goes out with your work, and a check tells you straight away if you've changed a feature you haven't listed. It has to be a feature that's out, because one still being built belongs to its own builder, and anything new goes in your own folder. A reviewer reads your reason beside exactly what changed, so make it specific, and keep it up to date if you change that feature again later. If you change something players already have, the `changes_reached` reason goes in the `feature.json` of the feature that declares it. Everything you've changed is checked with everything else, by all the same gates.

Other builders may be changing the same feature right now, and neither of you can see the other's work until it's out. So edit the lines you mean to, and never rewrite or reformat a whole file, because that collides with everybody. Work that changes different lines just comes together by itself.

**If something that's gone out changes the same lines as you,** a check will stop and say which files, and it doesn't cost you a try. Those files now have both versions in them, marked the way git marks them, with yours first and what's out second:

```
yours
what's out
```

Keep what both need and take out the marker lines. Nothing can go any further until you have. `git log main -- <file>` says who changed it, and `git show main:<file>` shows what's out. Art can't show both, so a picture you both changed is left as what's out, and the answer tells you how to get yours back.

## Block families

A family fixes what can't change on a live block. `stone`, `ore`, `deep_ore`, `metal` and `machine` need the right tool to drop anything, so give them a `tool` and usually a `tool_level` (`stone`, `iron` or `diamond`).

| Family | Good for |
|---|---|
| `stone` | Building blocks and rock |
| `ore` | Ores, hardness like iron ore |
| `deep_ore` | Harder ores for deep levels |
| `metal` | Refined storage blocks |
| `wood` | Wood-like blocks |
| `soil` | Soft blocks like dirt and gravel |
| `glow` | Light-giving blocks |
| `machine` | Blocks that hold data and run every tick |
| `cutout` | Leaves-like blocks with see-through pixels |
| `plant` | Small plants, cross-shaped, no collision. Only 5 exist, so use them sparingly |
| `glow_plant` | The same, giving light at level 10. Only 2 exist |
| `tinted_plant` | The same, tinted by biome |
| `model` | Drawn by a 3D model with moving parts instead of a texture. See below |
| `glow_ore` | A deep ore that gives off a little light, level 4, so it can be spotted across a cave. Only 20 exist |
| `crop` | One crop with all four growth stages in one block. See below. Only 7 exist |
| `connected` | A thin line that grows arms toward its neighbours, like a cable. See below. Only 2 exist |
| `ladder` | Something to climb, on a wall. See below. Only 10 exist |
| `facing` | A cube with a front or a top, turned the way it's placed, like a log. It breaks in about a second and always drops. See "Which way it faces" |
| `facing_machine` | A `machine` with a front, turned the way it's placed, like a furnace |

Families are limited, and a name stays assigned to its slot forever, so don't create blocks casually. A block's family can never change once it's been released.

A cube block can have different textures on its faces. `side` covers any side you don't name, and a face with nothing named uses `texture`. A block in any family but the two below always faces the same way once placed, so `front` is always north.

```json
"press": {"family": "machine", "display": "Press", "texture": "press_side",
          "faces": {"front": "press_front", "side": "press_side", "top": "press_top", "bottom": "press_top"}}
```

A `model` block is any shape you can model, with moving parts, for machines that should look like machines. It works like a `machine` block for modules and saving data, and its hitbox is always one full block, though the model can reach beyond that. Its `texture` is what it looks like in an inventory, drawn flat like an item, so make it a picture of the block with nothing around it. Make the model the way you'd make a mob's, as described in `assetkit/README.md`, with its feet on the block's floor at Y 0 and its centre over X 0, Z 0.

```json
"great_press": {"family": "model", "display": "Great Press", "texture": "great_press_icon", "model": "great_press", "tool": "pickaxe"}
```

An animation called `idle` plays by itself. Start and stop others from a module with `machine.play("stamp")` and `machine.stop("stamp")`. Every moving part is an entity for players' computers to draw, so this suits things that matter. Use a cube for anything players will place by the hundred.

To show a value on it, like a gauge, make one animation that sweeps from empty to full and hold it at the right point with `machine.show("fill", 0.75)`. Call it whenever the value changes. It stays there, even through a restart, until `machine.stop("fill")`. Several can be held at once, as long as they don't move the same parts.

A module can also change one part by its name in the model, which goes on top of whatever an animation is doing to it and stays through a restart, so call these whenever the value changes:

```java
machine.movePart("piston", 0, level * 0.5F, 0);  // in blocks
machine.turnPart("needle", 0, 0, pressure * 180); // in degrees: pitch, yaw, roll
machine.scalePart("tank", 1, fill, 1);            // times its size
machine.tintPart("tank", 0x55CCFF);               // multiplies its colours, so paint it in light greys
machine.glowPart("core", 15);                     // gives it its own light, from 0 to 15, whatever's around it
machine.resetPart("piston");                      // back to how its model says
```

Each returns false if the model has no part of that name. Parts that should always glow go in the block: `"glowing": ["core"]`.

### Which way it faces

```json
"kiln": {"family": "facing_machine", "display": "Kiln", "texture": "kiln_side", "tool": "pickaxe",
         "faces": {"front": "kiln_front", "side": "kiln_side", "top": "kiln_top"}, "facing": "horizontal"},
"statue": {"family": "model", "display": "Statue", "texture": "statue_icon", "model": "statue", "facing": "all"}
```

`"facing": "horizontal"` turns its front towards whoever places it, which is what a `facing` or `facing_machine` block does if you leave it out. `"facing": "all"` does that up and down as well, for something that points at what it's placed on, like a dispenser. A `model` block doesn't turn at all unless it says, and its front is the side of the model towards north, which is Z going negative. Only these three families can do this, and each `facing` or `facing_machine` block costs six of a limited kind of client block, so there are only 40 of each.

A module reads it with `machine.facing()`, or `state.getValue(BlockStateProperties.FACING)` for a block with no machine in it, and turns one with `level.setBlockAndUpdate(pos, state.setValue(BlockStateProperties.FACING, Direction.EAST))`.

### Crops

```json
"weald_wheat": {"family": "crop", "display": "Weald Wheat", "texture": "wheat_ripe",
                "stages": ["wheat_0", "wheat_1", "wheat_2", "wheat_ripe"],
                "drops": [{"item": "weald_grain", "count": [1, 3]}, {"item": "weald_seeds", "count": [1, 2]}],
                "young_drops": {"item": "weald_seeds"},
                "growth": 0.2}
```

`stages` is four textures, from just planted to ripe. It grows by itself in enough light, one stage at a time, and `growth` is how likely it is each time the game picks it, which is 0.2 if you leave it out, or about 5 minutes a stage. Bone meal grows it a stage. `drops` is what it gives when ripe, and `young_drops` is what it gives before then, which is nothing if you leave it out. Silk touch makes no difference.

Plant it with an item that has `"places": {"block": "$block:weald_wheat", "on": ["minecraft:farmland"]}`, and that item is then a source of the block. It stands on farmland, and keeps it wet, unless it says `"on": [...]` for what else it can stand on. It goes if what's under it does. A crop's stages are a little like a plant's, so don't spend them on something that isn't really a crop: there are only 7.

### Connected blocks

```json
"charge_cable": {"family": "connected", "display": "Charge Cable", "texture": "cable", "connects": ["minecraft:hopper", "$block:battery"]}
```

It's a small cube with an arm toward each neighbour that's the same block, any machine or `model` block, or anything in `connects`, and that keeps up by itself as things around it change. Players can place these by the hundred, because it's an ordinary block, unlike a `model` block. To everyone it's half a block high and solid, whichever way its arms go. Its texture is used as it comes for the cube and all the arms, so a plain or lightly patterned one looks best.

### Ladders

```json
"rope_ladder": {"family": "ladder", "display": "Rope Ladder", "texture": "rope_ladder"}
```

It goes on the wall a player clicks, and goes if that wall does, and players climb it just as fast as vanilla's. Its `texture` is drawn flat against the wall, so see-through pixels show the wall behind, and it's what it looks like in an inventory too. For another shape, give it a model at `assets/models/<name>.json`, drawn against the south side, because that's the wall when it faces north, and it's turned for each other way it faces.

A player's game works out climbing for itself, from what it takes a block to be, so nothing but this family can be climbed: `minecraft:climbable` on any other block is refused. To their game it's a vine, so what they can aim at is a thin column in the middle of the block, not the whole of what's drawn. Each takes four of a small number of client block states, so there are only 10.

### More about a block

- **`"hardness": 0`** sets how long it takes to break, from 0, which is at once, to 5, which is an iron block. Leave it out for what its family says. Unlike a family, this can change later. The right tool is still what its family says.
- **`"drops": "nothing"`** means it never drops anything, not even with silk touch.
- **`"emissive": true`** draws a cube at full brightness even in the dark, so it seems to glow, without giving off any light. For light as well, use the `glow` or `glow_ore` family. Dark pixels stay dark, so paint it with that in mind.
- **`"from_module": true`** says a module hands this out, or places it. It then counts as something players can get, which no check can see for itself, so it's on you that the module really does.
- **`"light": 9`** gives off that much light, from 0 to 15, on any block, and a module can change it: `context.setLight(level, pos, 15)` or `machine.setLight(15)`. It stays with that block through a restart. A release changing this only reaches new ones, because it's part of what's in the world. The `glow` family starts at 12 and `glow_ore` at 4 if you leave it out, and everything else at 0.
- **`"unbreakable": true`** means nothing in the game can break or move it: no tool, explosion, piston, wither or dragon, like bedrock. Someone in creative mode still can, and so can a module. Players could never get rid of one, so it can't be crafted or placed by an item. Only a ruin or a module can put one in the world.
- **`"redstone": true`** lets it give a redstone signal, and **`"comparator": true`** lets a comparator read it. See "Redstone".

### Redstone

```java
context.bindBlock("beacon_post", new BlockBehavior() {
    @Override
    public int redstone(BlockState state, Level level, BlockPos pos, Direction side) {
        return side == Direction.EAST ? 15 : 0;
    }

    @Override
    public void neighborChanged(BlockState state, Level level, BlockPos pos, Block neighbor) {
        int power = level.getBestNeighborSignal(pos);
    }
});
```

`redstone` is what it gives out of each side, from 0 to 15, and needs `"redstone": true`. The game asks this often, so keep it quick and change nothing from it. Whenever the answer would change, call `context.redstoneChanged(level, pos)`, or nothing around it will ask again. `strongRedstone` is the same but reaches through the block it runs into, as a redstone torch does upwards. Most blocks don't need it.

`neighborChanged` is something next to it changing, which is when the power reaching it may have changed. `level.getBestNeighborSignal(pos)` is the strongest signal reaching it from any side, `level.hasNeighborSignal(pos)` is whether there's any, and `level.getSignal(pos.relative(side), side)` is what's coming from one side. A machine can use `machine.redstoneInput()` from its `tick` instead, and something that should react a little later can call `level.scheduleTick(pos, state.getBlock(), 4)` and do it in `scheduledTick`.

`comparator(state, level, pos)` is what a comparator reads, and needs `"comparator": true`. A machine with an inventory gives what a chest would if you leave it out.

### Placing and breaking

- `BlockBehavior.canPlace(context)` is asked just before a player places it, and saying no leaves it in their hand. `context` has the player, the item, and where, as `context.getClickedPos()`. `placed(state, level, pos, by, stack)` is it having just been placed.
- `BlockBehavior.canBreak(state, level, pos, player)` is asked when it would break, and saying no leaves it there. The cracks still spread while they dig, so for a block that should never give at all use `"unbreakable"`. Explosions, pistons and modules don't ask.
- `WorldEvents.canBreak(player, level, pos, state)` is the same for any block in the world, vanilla's too, and `WorldEvents.blockPlaced(player, level, pos, state, stack)` is any block a player places. Any module saying no is enough.

### Crops

## Names

Use `$block:name` and `$item:name` in recipes and models. For another feature's content, use `$item:other_feature/name`. Never write a slot ID yourself. `$biome:name` is a biome of this world's, and raw files have tokens of their own: see 'Raw files' in `docs/content-types.md`.

`display` is the only readable name players can see. Everything else in the pack and data pack is renamed to meaningless IDs automatically. Write it in English, and see "Text" for how it reaches players in other languages.

A released name can never be removed, because worlds may contain it. To retire something, keep it declared, mark it `"retired": true` and stop making it obtainable.

## Items and their stats

Items stack to 64 and do nothing by default. To make a tool, weapon or armor, set components on the recipe's result, for example `"components": {"minecraft:max_damage": 250, "minecraft:tool": {...}}`.

Anything with combat or tool numbers must say which tier it belongs to, with a `tier` on the item or block: `wood`, `stone`, `iron`, `diamond`, `netherite`, `beyond` or `mythic`. Numbers can also be declared in `stats`, as a statement of intent that gets the same check. Things with no such numbers need no tier.

```json
"items": {
  "ember_pick": {
    "display": "Ember Pickaxe", "texture": "ember_pick", "tier": "iron",
    "stats": {"durability": 250, "mining_speed": 6, "attack_damage": 4, "attack_speed": 1.2}
  },
  "ember_plate": {
    "display": "Ember Plate", "texture": "ember_plate", "tier": "iron",
    "stats": {"slot": "chest", "armor": 6, "durability": 240}
  }
}
```

`stats` can hold `durability`, `mining_speed`, `attack_damage`, `attack_speed`, `armor`, `armor_toughness`, `knockback_resistance`, `slot` (`head`, `chest`, `legs`, `feet` or `body`), and for blocks `hardness` and `blast_resistance`. `attack_damage` and `attack_speed` are the numbers a tooltip shows, so an iron sword is 6 and 1.6.

What a recipe's result really does is checked as well, so it has to agree with its item's tier. A result with a vanilla id has no item of yours to carry a tier, so put `tier` on the recipe instead.

Nothing may go over 110% of vanilla at its tier:

| Tier | Durability | Mining speed | Hardest hit | Damage per second | Armor by slot (head, chest, legs, feet, body) | Armor durability (chest) | Toughness |
|---|---|---|---|---|---|---|---|
| `wood` | 59 | 2 | 7 | 6.4 | 1, 3, 2, 1, 3 | 80 | 0 |
| `stone` | 131 | 4 | 9 | 8 | 2, 5, 4, 1, 4 | 240 | 0 |
| `iron` | 250 | 6 | 9 | 9.6 | 2, 6, 5, 2, 5 | 240 | 0 |
| `diamond` | 1561 | 8 | 9 | 11.2 | 3, 8, 6, 3, 11 | 528 | 2 |
| `netherite` | 2031 | 9 | 10 | 12.8 | 3, 8, 6, 3, 19 | 592 | 3 |

`beyond` is for late mid-game content, and allows 150% of netherite rather than 110%.

`mythic` is only for the endgame, and has no limits at all. The attributes and components refused below are allowed on it too, including enchantments, extra health and anything else that fits. It only ships from a node in the `end` stage, and has to take earlier materials to make. Let it be absurd.

Things to watch for:

- Damage per second is `attack_damage` times `attack_speed`. Vanilla's best is the sword, so an axe's hit needs an axe's slow swing. An item with no `attack_speed` swings at the base 4 a second, which is far over budget, so always set it.
- Attribute modifiers add to a base: `attack_damage` to 1 and `attack_speed` to 4. So an iron sword's are +5 and -2.4. Use `add_value`, and `mainhand` for weapon stats or an armor slot for armor stats, because anything else stacks with what a player already has.
- Raising any other attribute, such as `max_health` or `movement_speed`, is refused, because vanilla gear has no curve for it. Lowering one as a drawback is fine.
- `minecraft:unbreakable`, a `damage_per_block` of 0 and an `item_damage_per_attack` of 0 all count as infinite durability, which no tier allows.
- `minecraft:enchantments`, `stored_enchantments`, `death_protection`, `blocks_attacks`, `kinetic_weapon`, `piercing_weapon`, `attack_range`, `minimum_attack_charge`, `damage_type` and `glider` are refused on a recipe result. They add power with nothing to measure it against. Give the effect through a server module. An enchantment of your own can go on gear at a table or in loot: see 'Raw files' in `docs/content-types.md`.
- For worn armour with its own art rather than vanilla's, and for tools that can be enchanted, see 'Raw files' in `docs/content-types.md`.

## Recipes and discovery

Every recipe needs a `mode`:

- `open`: always craftable. For basics.
- `known`: must be learned first. Needs a `route` saying how, following `bible/discovery.md`.
- `guessable`: only for machine recipes with simple inputs and many possible combinations. Needs `"machine": true` and `feedback` describing how the machine reacts to a near miss, and a failed attempt should cost little.

Two checks look at all recipes in all features together:

- **Nothing from nothing.** No set of recipes may leave a player with more of something and less of nothing, for example an ingot that makes 9 nuggets when 8 nuggets make an ingot. This includes loops through vanilla's own storage recipes, like iron block to ingots. A loop that costs something else each time is a conversion and is allowed.
- **Everything can be had.** Every block and item needs a source: an ore or plant, a block or mob that drops it, a ruin's chest or walls, or a recipe whose inputs can all be had. Vanilla items and `#minecraft:` tags count as available. An ore with its own `drops` never reaches anyone's inventory, so it can't be a recipe input. An item with `places` is a source of the block it places. A server module handing something out doesn't count as a source unless the thing says `"from_module": true`, because no check can see that for itself.

## Ores

Each entry adds veins to the world, in chunks old and new. Its `id` must never be reused or changed, because chunks remember which ids they've already received. To change an ore's distribution later, add a new entry with a new id. `veinSize` can be at most 16, and can be a range, like `[4, 8]`, for veins of any size between those.

`"touchingAir": true` only forms it where it can be seen, on a cliff or a cave wall, so it can be spotted from the surface. That leaves out most of each vein, so it comes out much rarer than its yield says. It can't form in places players have been, because there veins stay hidden.

Ore only replaces natural blocks. In places players have been, veins are hidden fully inside rock, so nothing appears next to a base.

An ore's yield must suit the tier it feeds. Yield is `veinsPerChunk` times `veinSize`, or its average if it's a range, times the share of `minY` to `maxY` that's inside rock (Y -64 to 64), times the average of its drop `count`. All of a block's entries add up. If it drops several things, each is measured by itself.

| Tier | Vanilla ore | Yield per chunk | Allowed |
|---|---|---|---|
| `wood` | coal | 115 | 57 to 229 |
| `stone` | copper | 100 | 50 to 201 |
| `iron` | iron | 128 | 64 to 255 |
| `diamond` | diamond | 47 | 23 to 94 |
| `netherite` | ancient debris | 5 | 2.5 to 10 |
| `beyond` | none | 2.5 | 1.25 to 5 |
| `mythic` | none | 1.25 | 0.6 to 2.5 |

The tier it feeds is the highest of any `tier` on the ore entry, its block or what it drops, and the tier of anything those get crafted into. With no tier anywhere, it only has to stay under 255.

## Module code

Modules are checked in their compiled form. A module's jar may hold only its classes, `module.properties` with a single line `entry=<class>`, and the manifest Gradle adds. Art and data go in the feature's `assets`.

All of a module's classes must be in the package `gm.feature.<id>`, under the feature's own id. Module classes load through the game's own classes first, so a class with any other name might not be the one that runs.

These are refused on both sides: files, network, processes, reflection, class loading, threads, native code, `sun.*`, `jdk.*` and `Unsafe`, along with the libraries on the classpath that do those things for you, like `oshi`, Commons IO, `java.beans`, and Guava's `io` and `reflect`, and the packets that send a player's game to another address. `Class` only offers `getName`, `getSimpleName`, `getTypeName`, `isInstance`, `isAssignableFrom`, `cast`, `isEnum`, `isRecord`, `isArray` and `isInterface`. Lambdas, string concatenation, records and pattern switches all work, but nothing from `java.lang.invoke` may be called directly.

If a feature really needs something refused, say so in your report and quote the name from the failure message exactly. The owner can approve an exception for that one feature.

## Server modules

Java that runs on the server, swappable while the game runs. See `/reference/conduit-api/` for the interfaces.

```java
public final class EmberModule implements ServerModule {
    @Override
    public void enable(ServerModuleContext context) {
        context.bindBlock("ember_block", new BlockBehavior() {
            @Override
            public InteractionResult use(BlockState state, Level level, BlockPos pos, Player player, BlockHitResult hit) {
                player.sendSystemMessage(context.text("warm"));
                return InteractionResult.SUCCESS;
            }
        });
    }
}
```

Names passed to `bindBlock`, `bindItem` and `bindMachine` are the ones in `feature.json`. A machine keeps everything it remembers in `machine.data()`, because that survives the module being replaced. Keep tick work small: a machine runs 20 times a second, for every one placed.

What each behaviour can do is in `/reference/conduit-api/`, and all of it is optional except a machine's `tick`. A few that are easy to miss:

- `BlockBehavior.removed(state, level, pos)` runs when the block has left the world, however it went: broken, blown up, pushed by a piston, or replaced by a command or a module. Use it to take something off a list the moment it goes, instead of sweeping for it. It doesn't run for a chunk unloading, or for anything that happens while your module isn't loaded, so don't rely on it alone for what has to stay exactly right.
- `MachineBehavior.outputTaken(machine, slot, stack, player)` runs when a player takes something from an output slot, such as to give them experience the way a furnace does. A hopper emptying it doesn't count. `canTake(machine, slot, player)` can stop them, for a machine that's still busy.
- `MachineBehavior.removed(machine)` runs just before a machine goes, while `machine.data()` is still there, so it's where a machine drops what it holds. A command replacing it doesn't count, in the same way a chest's contents don't drop then.
- `MobBehavior.interact(mob, player, hand)` is a player using something on a mob. See "Mobs" in `docs/content-types.md`.
- `EffectBehavior` is what one of this feature's `"effects"` does. See "Status effects" in `docs/content-types.md`.
- `ItemBehavior.useOnEntity(stack, player, target, hand)` is this item used on a mob, if the mob itself had nothing to do with it. `ItemBehavior.mineBlock(stack, level, state, pos, miner)` is this item having just broken a block, which vanilla doesn't report for a player in creative mode.
- `ItemBehavior.finishUsing(stack, level, user)` is a timed use running its full length. See "What an item is" in `docs/content-types.md`.
- `mob.setTint(0xFF8800)` colours one mob's model, and `mob.makeBaby(600)` makes one half the size until it grows up that many seconds later, or for good with 0. Both last through a restart. A module can spawn one with `context.mob("name").create(...)` and call these on it as a `SlotMob`. A tint multiplies the model's colours, so paint a mob that's meant to be tinted in light greys.
- `context.shoot("name", player)` fires a projectile, and `context.bindProjectile`, `context.bindVehicle` and `context.bindProp` give yours behaviour. `context.placeVehicle`, `context.placeProp` and `context.beam` put things in the world. See "Projectiles", "Vehicles", "Props" and "Beams" in `docs/content-types.md`. Draw a shot with a projectile rather than a line of particles, because a projectile has a hitbox and damage the gates can check.
- `context.isNatural(level, pos)` says whether a block is as the world made it, which is how to leave anyone's building alone. Anything changed since doesn't count, whoever or whatever changed it, so grass spreading isn't natural either.
- `context.examine(player, state)` or `context.examine(player, entity)` examines something for a player, so a tool can teach what any feature teaches for looking closely at it.
- `context.showEffect(level, effect)` draws beams, surfaces, shaders or a ghost of a layout at a place in the world, and `context.shakeCamera(player, strength, seconds)` shakes a player's view, with no client module. See 'Drawing in the world' in `docs/content-types.md`.
- `context.sendClientValue(player, key, value)` tells this feature's client module on one player's computer how something is, which it hears with `context.onServerValue(key, listener)`. See "What a client module can know" in `docs/content-types.md`.

### Menus and books

A module can open a menu made of chest slots, or a book, and neither needs anything on a player's computer:

```java
context.openMenu(player, context.text("survey"), 3, new MenuBehavior() {
    @Override
    public void draw(MenuView menu) {
        menu.set(13, new ItemStack(Items.COMPASS));
    }

    @Override
    public void clicked(MenuView menu, int slot, boolean rightClick, boolean shift) {
        if (slot == 13) {
            menu.close();
        }
    }
});

context.openBook(player, context.textFor(player, "notes_title"), List.of(context.text("notes_first_page")));
```

A menu has from 1 to 6 rows of 9. Each slot is a button: what's in it is only a picture, which can't be taken, and `draw` runs again after every click. Give the items names with `DataComponents.CUSTOM_NAME` so they say what they do. A menu closes by itself if your module is unloaded, and `closed(menu)` tells you when it does for any reason. For several pages, call `openMenu` again with the next one.

A book page holds about 230 characters. It isn't a real item, so it can't be dropped or copied, and the player's hand doesn't change.

### Panels

A panel is a screen of its own, for a machine, an item, a mob or anything else a module decides: art you drew, item slots wherever you want them, bars, buttons, tabs, scrolling lists, a mob and somewhere to type. You describe it, a module runs it, and no code goes to anyone's computer.

```json
"panels": {
  "kiln": {
    "title": "Kiln",
    "width": 176,
    "height": 166,
    "background": "kiln_back",
    "inventory": {"x": 8, "y": 84},
    "widgets": [
      {"type": "slot", "x": 56, "y": 35, "slot": 0},
      {"type": "slot", "x": 116, "y": 35, "slot": 1},
      {"type": "bar", "id": "heat", "x": 80, "y": 36, "width": 24, "height": 16, "image": "flame", "text": "Heat"},
      {"type": "label", "id": "state", "x": 8, "y": 20, "text": "Cold"},
      {"type": "button", "id": "light", "x": 8, "y": 60, "width": 40, "height": 18, "text": "Light", "tooltip": "Burns one coal"}
    ]
  }
}
```

Everything is in pixels from the panel's top left corner, at most 320 by 230, which is what fits on a small screen. Images are `assets/panels/<name>.png` and are stretched to whatever they're drawn at. With no `background` it's drawn exactly like the game's own containers, with its slots drawn for you. `inventory` is where the player's own 36 slots go, 162 by 76, with the game's "Inventory" label 12 pixels above them, or `false` for none. Leave it out and they sit along the bottom. The game draws `title` for you at 8, 6, or at `title_x` and `title_y`, so don't paint it on or add a label for it, and leave room for "Inventory". With a `background`, your art has to show a frame for every slot, the player's too, or their items float on nothing. The instant check refuses art with none, and text that overlaps.

**It has to look like Minecraft.** Players should take it for one of the game's own screens, the way they do with most good mods. Buttons, tabs, list rows, bars and slots already look like the game's unless you say otherwise, so start from that and add to it rather than drawing a new look. If you draw a background, start from `panel_back(width, height, slots=[(56, 35)], inventory=(8, 84))` in assetkit's textures, which is the game's own panel with a frame for each slot and the player's inventory, and paint on that. Keep its light grey, its bevelled edge, its sunken frames and dark grey `#404040` text, and work in pixel art at the game's scale, so a 176 by 166 image for a 176 by 166 panel and never a scaled-down picture. Trims, icons, gauges and an accent colour from the world are all welcome, and so is more polish than vanilla has. Flat blocks of colour, gradients, smooth shapes and anything like a web page aren't.

| `type` | Needs | Can also have |
|---|---|---|
| `slot` | `x`, `y`, `slot`: which slot of the inventory it shows, from 0. `x` and `y` are where the 16 pixel item goes, so a frame in your art starts a pixel up and left of that | |
| `filter` | `id`, `x`, `y`, placed like a `slot` | `tooltip`, `enabled`, and `text`, for its name in a plain chest |
| `label` | `text` | `id`, to change it. `width`, to wrap it. `color` like `"#404040"`, `shadow` |
| `icon` | `icon`: an item, or `id` for a module to set one | `tooltip` |
| `image` | `width`, `height`, `image` | |
| `bar` | `id` or `value` from 0 to 1, `width`, `height`, and `image` or `color` to fill with | `direction`: `right`, `left`, `up` or `down`. `back_color`. `text`, for its name in a plain chest |
| `button` | `id`, `width`, `height` | `text`, `icon`, `tooltip`, `image`, `hover_image`, `disabled_image`, `enabled` |
| `tabs` | `id`, `tabs`: a list of `{"id": "offers", "text": "Offers"}`, where a tab can also have `"icon": "minecraft:emerald"`, and then it can leave out `text` | |
| `list` | `id`, `width`, `height` | `row_height`, 18 unless you say, and at least 22 for a second line. `max_rows`: the most it can ever have, 9 unless you say, up to 1000 |
| `mob` | `width`, `height`, `mob` | `portrait`, `size` |
| `text_field` | `id`, `width`, `height`, `max_length`, from 1 to 256 | `hint`, and `text`, for its name in a plain chest |

Any of them can have `page` with a tab's id, and then it only shows on that tab. Any with an `id` can have `"visible": false`, and then it isn't there until a module calls `setVisible`, like a warning, or a picture of something that hasn't happened yet. Only vanilla's mobs can be drawn moving, so `"mob": "minecraft:villager"` works by itself and one of this world's needs a `portrait`, an image of it. Render that from its model with assetkit.

A module opens it, and says what it does:

```java
context.openPanel(player, "kiln", machine, new PanelBehavior() {
    @Override
    public void tick(PanelView panel) {
        panel.setValue("heat", machine.data().getFloatOr("heat", 0));
        panel.setText("state", context.textFor(panel.player(), machine.data().getBooleanOr("lit", false) ? "burning" : "cold"));
    }

    @Override
    public void clicked(PanelView panel, String id, int row, boolean rightClick, boolean shift) {
        if (id.equals("light")) {
            machine.data().putBoolean("lit", true);
        }
    }
});
```

- `context.openPanel(player, "kiln", behavior)` is for anything, like an item's use. Its slots are an inventory of its own, and whatever's left in them goes back to the player when it closes.
- `context.openPanel(player, "kiln", container, behavior)` shows a real inventory, usually a machine's. It closes when that goes away.
- `context.openPanel(player, "talk", mob, behavior)` closes when the mob dies or they walk away.

`opened` sets what it starts with and `tick` keeps it current. Only what's really different gets sent, so setting everything every tick is fine. `clicked` hears buttons, tabs and rows, with the row's number for a list, `filtered` hears a filter slot being set, `typed` hears a text field, and `closed` hears it closing, whyever it closed. A module can use `setText`, `setValue`, `setEnabled`, `setVisible`, `setTooltip`, `setItem` for an icon, `setRows` for a list, `setFilter` and `filter`, `setTyped`, `setPage` and `close`, by the widget's `id`.

For someone to talk to or trade with, a `mob`, a `label` for what it says, and a `list` of what they can say or buy back with `PanelRow.of(context.textFor(panel.player(), "bread"), new ItemStack(Items.BREAD))` is all it takes. A row can be turned off with a reason: `new PanelRow(context.textFor(panel.player(), "sold_out"), icon, false, context.textFor(panel.player(), "come_back"))`. It can have a second line under its text with `.detail(text)`, in a list with a `row_height` of at least 22, and more pictures along its right with `.icons(new ItemStack(Items.EMERALD, 3), ...)`, like what something costs, each showing its count and its name when the mouse is over it. Up to 4 of those fit, and the text is cut short to leave room for them. A row's main icon shows its count too, so give it a stack of 1 unless the number means something.

A `filter` is a slot that only remembers an item, for "only take this" or "look for that". Clicking it with an item sets it to one of that item and they keep what they were holding, and clicking it with an empty hand clears it. `filtered(panel, id, stack)` hears that, with an empty stack for nothing, and `panel.filter(id)` says what it's set to. It's only a picture, so nothing can be lost in one, and it's yours to remember. Set it again in `opened`, because a panel forgets it when it closes.

Someone with no companion, or one too old for panels, gets the same panel as a plain chest, which does all the same things: slots are slots, and buttons, tabs, rows and filter slots are named items they can click. So nothing needs its own code, but keep it usable that way: a bar's value is only a number in an item's name there, and they can't type at all, so never make typing the only way. A row's second line and extra icons are written on its picture there. Every slot, filter, button, tab and row, and anything with an `id`, takes a place in that chest, which has 54.

A list with a `max_rows` over 45 can't have a place in that chest for every row, so it takes 11 of them: a page of 9 rows, and two for turning the page. With the companion it scrolls like any other. It can have up to 1000, but changing even one row sends them all again, so don't change a long list every tick. A panel with a filter slot, a tab with an icon or a list that long shows as the plain chest to a companion from before these, rather than being drawn wrongly.

The release gates open each new or changed panel on a real client and photograph it for the reviewer, before anything has driven it, so what a module sets in `opened` won't be in that picture.

### Text

Players read this world in the language their game is set to, English or German so far. Write everything in English, and it gets translated when the feature goes out. `display`, `tooltip`, knowledge, a panel's words and these `texts` all do that by themselves, and German names stay the same from then on, so what you write in English is what gets named. Don't write German anywhere yourself.

Text a module says goes in `texts`, by a name of your choosing:

```json
"texts": {
  "warm": "The block is warm.",
  "holds": "It holds %s of %s."
}
```

```java
player.sendSystemMessage(context.text("warm"));
player.sendSystemMessage(context.text("holds", stack.getCount(), stack.getHoverName()));
stack.set(DataComponents.CUSTOM_NAME, context.text("warm"));
```

- `context.text(name, values...)` is a message that each player's game shows in their own language, and it's what to use anywhere that takes a `Component`: chat, a menu's title, a book's pages, the name or lore on a stack. A value goes in where it says `%s`, and it can be a number, a string or another message, so give it `stack.getHoverName()` rather than its `getString()`, and each player sees that in their language too. If the values have to go in a different order in a sentence, `%1$s` and `%2$s` say which is which, and `%%` is a percent sign. Nothing else that looks like a place for a value works.
- `context.textFor(player, name, values...)` is the same as plain text in one player's language, for what only takes plain text: what a panel says, and a book's title.
- `"other_feature/name"` uses another feature's text.

A client module has `context.text(name, values...)` too, for what it draws.

`texts` go in the resource pack with everything else that gets translated, under names that give nothing away, so someone who unpacks it could read them, the same as a Codex page they haven't earned. Words that would really spoil something if read early can stay in the code, in English.

Text written straight into code, like `Component.literal("The block is warm.")`, stays English for everyone, and the instant check points it out. A number, a symbol or something a player typed is fine as it is. Tell a player about a thing by its message, not by reading its name into a sentence you've written, or the sentence comes out half in one language.

Words in another language can come out longer, so leave room on a label, and a button whose translation doesn't fit stays in English.

### Talking to other features

Modules can't share classes, but one can tell any others that care that something happened:

```java
CompoundTag message = new CompoundTag();
message.putInt("depth", pos.getY());
context.publish("sampled", message);

// In any other feature, or this one:
context.subscribe("core_drill/sampled", message -> { /* ... */ });
```

It goes to whoever is listening right then, and nobody listening is fine, so it's the way to let others react to your feature without your feature knowing about them. It's also the way to pass something on for another feature to record, as long as that one listens for it. Say what you publish in your feature's `summary`, so other builders can find it. A running module can't switch another off, or change what another does. For that, change the other feature itself: see 'Changing another feature' above.

### Things that happen in the world

Don't watch for these from a tick handler. Listen for them, and it takes no work at all until they happen:

```java
context.listen(new WorldEvents() {
    @Override
    public void blockBroken(ServerPlayer player, ServerLevel level, BlockPos pos, BlockState state, BlockEntity blockEntity) {
        if (state.is(context.block("rune_ore"))) { /* the exact depth it came from is pos.getY() */ }
    }
    @Override
    public void mobKilled(LivingEntity mob, DamageSource source) {
        if (mob.getType() == context.mob("rune_crab") && source.getEntity() instanceof ServerPlayer killer) { /* ... */ }
    }
    @Override
    public void itemEaten(ServerPlayer player, ItemStack stack) { /* ... */ }
    @Override
    public void playerJoined(ServerPlayer player) { /* ... */ }
    @Override
    public void knowledgeLearned(ServerPlayer player, String entry, String title) { /* ... */ }
    @Override
    public void blockExamined(ServerPlayer player, ServerLevel level, BlockPos pos, BlockState state) { /* ... */ }
    @Override
    public void mobExamined(ServerPlayer player, Entity mob) { /* ... */ }
    @Override
    public float damage(LivingEntity target, DamageSource source, float amount) { return amount; }
    @Override
    public boolean survives(LivingEntity target, DamageSource source, float amount) { return false; }
    @Override
    public double knockback(LivingEntity target, DamageSource source, double power) { return power; }
    @Override
    public void playerJumped(ServerPlayer player) { /* ... */ }
    @Override
    public void keyPressed(ServerPlayer player, PlayerKey key) { /* ... */ }
    @Override
    public void keyDoubleTapped(ServerPlayer player, PlayerKey key) { /* ... */ }
    @Override
    public void chunkLoaded(ServerLevel level, LevelChunk chunk, boolean isNew) { /* ... */ }
    @Override
    public void ruinPlaced(ServerLevel level, String ruin, BlockPos origin) { /* ... */ }
});
```

These fire for everything, vanilla's and every feature's, so check what it was first. `blockBroken` is only for what a player breaks, and the block is already gone, so `state` is what it was. `mobKilled` is anything living that dies, however it happened, including players, and `source.getEntity()` is who did it, if anyone. `itemEaten` is food and drink, including potions and milk, and `stack` is a copy of what they had just before. `playerJoined` doesn't include anyone already online when your module loads, so look through `context.server().getPlayerList().getPlayers()` in `enable` if that matters. `knowledgeLearned` is any feature's knowledge being learned for the first time, however it happened, with `entry` as its full name, `feature/name`, and `title` as what players read. Where a world shares what's learned, that's once for everyone, with whoever got there first. `blockExamined` and `mobExamined` are a player using something while crouching with an empty hand, whether or not there was anything to learn from it, and anything it taught has been learned by then. `mobExamined` is any entity, so check what it is. `ruinPlaced` is any feature's ruin having just been built, all of it, with `ruin` as its full name, `feature/name`, and `origin` as its corner, which is the moment to put a guardian in it or remember where it is. It's only heard while your module is loaded, and if a crash interrupts a big one, the rest of it gets built later and this isn't heard, so don't rely on it alone. `context.ruinsNear` can always say where they are.

`damage` is a player or a mob about to be hurt by that much, before armor or a shield, and what you return is how much it really is, so returning 0 means it doesn't land at all. Each module listening gets what the one before it said. `target.getHealth()` tells you if it might kill, though armor can still save them. `survives` is a hit that really is about to kill it, armor and all, and returning true means it lives, on half a heart unless you set its health to something else there. That goes ahead of a totem, so a totem isn't used up. `knockback` is how hard a hit pushes, which is 0.4 from most, and returning 0 means not at all. These all fire for everything, so check who it is first. Falling out of the world and `/kill` can't be changed, and a module hurting something from inside one of these doesn't ask again. Fair-play limits still apply: what a tier's gear can do is measured from the gear, so don't use this to make something stronger than its tier says.

`playerJumped` is a player's feet leaving the ground in a jump. `keyPressed`, `keyReleased` and `keyDoubleTapped` are keys a client tells the server about by itself, with nothing on anyone's computer: `FORWARD`, `BACK`, `LEFT`, `RIGHT`, `JUMP`, `SNEAK` and `SPRINT` from `PlayerKey`, whichever keys they've set for those. They're about the key, not what it did, so `JUMP` in the air is how a double jump starts. A double tap is two presses within 7 ticks, the same as the game wants for sprinting, and comes after the second `keyPressed`. A screen being open means nothing's pressed. Any other key needs a client module: see "Inventory screens and keys".

`chunkLoaded` is a chunk now loaded and in the world, with `isNew` for one that's just been generated, and `chunkUnloaded` is one about to go. These come hundreds of times a second while someone explores, so decide quickly and do any real work later.

A module that keeps throwing errors is switched off automatically.

Beyond the rules in Module code, a server module can use most of Minecraft, but of the module host only `gm.conduit.api`.

### Keeping things

A module can be replaced at any moment, and a release or a restart replaces it, so nothing in its fields lasts. What belongs to a block goes in `machine.data()`, and what belongs to a mob goes in its own data. For anything else, `context.state()` is this module's own saved data, which is all it takes:

```java
private CompoundTag state;

@Override
public void enable(ServerModuleContext context) {
    this.state = context.state();
}

private void award(ServerPlayer player) {
    this.state.putInt("awarded", this.state.getIntOr("awarded", 0) + 1);
}
```

Keep using the same tag rather than a copy, and change it whenever you like. It's saved with the world, still there when your module's replaced or the server restarts, and goes back with the world if that's rolled back. `disable()` is the last chance to write down what's in your fields, and it isn't called for a crash, so keep things in the tag as they change if they matter. Keep it small: it's all written at every save.

## Mixins

A mixin patches the game's own code on the server, which is how to change something no hook reaches. It's the last resort. It only takes effect at a restart, for everyone, and its code becomes part of the game's, so if it throws an exception the whole server goes down, where a module would just be switched off. Look for a hook first: world events, behaviours, and everything a server module can call. If you need one that doesn't exist, ask for it in `host_requests`.

Say why in `feature.json`, naming the hook you looked for:

```json
"mixins": {"why": "WorldEvents has nothing for a boat's movement, and ItemBehavior only hears about a boat being placed."}
```

Mixins go in `mixins/src/main/java/gm/feature/<id>/mixin/`, at most 4 for a feature and 12 features in a world. Nothing else goes in that package, and there are no resources, because what the game needs to know about them is written for you. Use the `java_api` tool with `private: true` to see a class's private members, and `code: "methodName"` for the bytecode an injection point has to match.

```java
package gm.feature.quick_boats.mixin;

@Mixin(AbstractBoat.class)
abstract class AbstractBoatMixin {
    // A boat with no one in it keeps going for longer. Vanilla slows one on water by this much each tick.
    @ModifyConstant(method = "floatBoat", constant = @Constant(floatValue = 0.9F))
    private float quick_boats$glide(float friction) {
        return QuickBoats.isQuick((AbstractBoat) (Object) this) ? 0.99F : friction;
    }
}
```

Put your own names on anything you add, as above with `quick_boats$`, because other mixins are patching the same classes. Each injection has to find what it's looking for, and if it doesn't, the release stops. The server makes every mixin apply as it starts, so a mistake shows up in testing rather than when someone first gets in a boat.

**Things a mixin can't do on a server.** A player's own game works out what they themselves do, so a mixin here doesn't change how a boat they're steering handles, how they walk or how they fly. Only what the server works out itself changes: an empty boat, a mob's boat, damage, drops, mobs, blocks, and anything else that gets decided on the server. Test what you actually change.

**Sharing with your server module.** A mixin can't see your module's classes, because modules come and go while the game runs. Classes in `gm.feature.<id>.shared`, in the same `mixins` folder, can be seen from both sides. That's where a mixin finds out what your module wants: the module can set a static field in `enable`, and it should clear that in `disable`. These classes live as long as the server does. A module can't have classes of its own in `mixin` or `shared`.

**What it can use.** The rules in Module code apply, along with these:
- The target must be in `net.minecraft`. These can't be patched, because they're what keeps the world and the release system safe: commands, the server's main class and console, crash reports, networking and login, the player and whitelist lists, chunks and how they're saved, anything in saved data's format, registries, and the classes that hold the game's blocks, items, mob types and block entity types. Nothing in `gm.conduit` or any other mod can be patched at all.
- Annotations: `@Mixin`, `@Shadow`, `@Unique`, `@Final`, `@Mutable`, `@Accessor`, `@Invoker`, `@Inject`, `@At`, `@Slice`, `@Desc`, `@Redirect`, `@ModifyArg`, `@ModifyArgs`, `@ModifyVariable`, `@ModifyConstant`, `@Constant`, `@Coerce`, and from MixinExtras `@ModifyExpressionValue`, `@ModifyReturnValue`, `@ModifyReceiver`, `@WrapOperation`, `@WrapMethod`, `@WrapWithCondition`, `@Local`, `@Share`, `@Expression` and `@Definition`.
- Refused: `@Overwrite`, which undoes other patches to that method, so use `@Inject` at `HEAD` with `cancellable = true` or `@WrapMethod` instead. Also `@Pseudo`, `@Group`, `@Debug`, `require = 0`, `constraints`, a mixin's `priority`, an injector's `order`, `locals` other than `CAPTURE_FAILHARD`, and `unsafe` on `@At`. `@At` only takes the game's own injection points, and its `target` is written out in full as `Lowner;name(arguments)result`. A selector can't be a pattern. Nothing in a mixin can target `<clinit>` or `createBlockStateDefinition`, or register anything: use slots.
- `@Redirect`, `@ModifyArg` and the like can't name anything in the Module code list as their target, like a call to `java.nio.file.Files`, and they can't go round a call to a chunk. Every `@At` that matches a call or a field has to say which one, owner included.
- Its code can use the game, `gm.conduit.api`, `java.lang`, `java.util`, `java.io`, `java.nio`, `java.math`, `java.time`, `java.text`, Fabric's API, Polymer, and these libraries: Guava's `collect` and `base`, Gson, fastutil, JOML, SLF4J, `com.mojang.serialization`, `com.mojang.math`, `com.mojang.datafixers.util`, and `io.netty.buffer`. It can't run commands, register anything, write straight to a chunk's sections, stop the server or touch crash reports. If it needs a block changed, use the level's own `setBlock`.
- A feature's folders hold only source and assets. There can't be a `build.gradle` or anything else that changes how it's built, and no links.

**When a mixin goes.** The world has to load without it, because it can go at any moment: by a rollback, by crashing, or by being removed. Testing tries exactly that, booting what the mixin's world saved on a server without it. So anything you add to what an entity or block saves has to be something a game without your mixin will just ignore, like an extra key, and it'll be lost if the mixin goes.

**When a mixin crashes.** If the server goes down and its crash report points to your mixin, that mixin is taken out of the live release, and the rest of your feature stays. The same mixin won't go out again until it's changed. Handle anything that could fail, and keep what it does small, because it may run far more often than a tick.

## Client modules

Java that runs on players' game clients: HUDs, maps and gauges, effects, drawing in the world, and helpers on inventory screens. See `/reference/companion-api/`. These run on friends' computers, so they may only use the companion API and approved Minecraft classes. No files, network, processes, reflection or class loading: the checks refuse those. Prefer doing things on the server. Use a client module only for what truly needs one. A server module can draw in the world itself, as 'Drawing in the world' in `docs/content-types.md` shows.

### Inventory screens and keys

A module can draw on an inventory screen and use the mouse and keys there, which is what inventory helpers need. Everything goes through `context`, so it all goes away by itself when the module unloads. This is holding shift and dragging across slots to move each one:

```java
public final class ShiftDrag implements ClientModule {
    private int lastSlot = -1;

    @Override
    public void enable(ModuleContext context) {
        context.onInventory(new InventoryHooks() {
            @Override
            public boolean mousePressed(InventoryView inventory, MouseInput mouse) {
                return moveWhatsUnder(inventory, mouse);
            }

            @Override
            public boolean mouseDragged(InventoryView inventory, MouseInput mouse) {
                return moveWhatsUnder(inventory, mouse);
            }

            @Override
            public boolean mouseReleased(InventoryView inventory, MouseInput mouse) {
                lastSlot = -1;
                return false;
            }
        });
    }

    private boolean moveWhatsUnder(InventoryView inventory, MouseInput mouse) {
        if (!mouse.shift() || mouse.button() != MouseInput.LEFT) {
            return false;
        }
        int slot = inventory.slotAt(mouse.x(), mouse.y());
        if (slot != lastSlot && !inventory.item(slot).isEmpty()) {
            inventory.quickMove(slot);
        }
        lastSlot = slot;
        return true;
    }
}
```

- `InventoryHooks` has `draw`, `mousePressed`, `mouseDragged`, `mouseReleased`, `mouseScrolled` and `keyPressed`. The mouse and key ones return true if they've dealt with it, so the game doesn't. If two modules want the same thing, the first to say it's dealt with it stops the other hearing of it.
- `InventoryView` is the inventory: `item(slot)`, `carried()`, `slotAt(x, y)`, `slotX(slot)`, `isOwn(slot)`, `hotbarIndex(slot)`, `accepts(slot, stack)`. Its actions are the ones a player could do by hand, and the server checks them the same way: `click`, `clickRight`, `quickMove`, `swapWithHotbar` and `gather`. It can't throw items out, and it can't reach anything else a player could do.
- `context.inventory()` gives a view at any time, for things that run from a tick: the open inventory screen's, or the player's own if no screen is open, so refilling the hotbar works while they play. It's null while any other screen is open.
- `context.key("open_map", KeyInput.of('M'))` is a key the player can change, in the game's controls menu like any other, under a heading of its own. Name it in `"keys": {"open_map": "Open Map"}` in `feature.json`, which is what the menu calls it, and use `onPressed(() -> ...)` and `isDown()` on what it gives you. Use this for anything a player presses in the world. The game still gets the key too, so pick one it isn't using, and remember friends have JourneyMap, which has J, B and N. If it clashes, the menu shows that in red and they can change it. What they choose is remembered.
- `context.onKeyPressed(key -> ...)` is any key going down in the world with no screen open, and `context.keyDown(key)` is whether one is held. These can't be changed in a menu, so they're for things like checking shift is down, not for a key of its own. Keys are numbered by where they are on the keyboard, so use `key.key() == KeyInput.of('R')` for a letter or a digit, and the constants in `KeyInput` for the rest.
- Actions are limited to 64 a tick between all modules, past which they return false, so a big job like sorting has to carry on from where it got to on the next tick. Keep that in the module's own fields, and get a fresh `context.inventory()` each time, because a view stops working once its screen closes.

Some limits exist to protect players, and no feature can get past them. Nothing typed into chat, a sign, a book, a text box or the server's password dialog ever reaches a module. Escape always closes the screen. The creative menu isn't hooked at all, because its slots work differently.

A stack from a view is only for looking at. A module can read `isEmpty`, `getCount`, `getMaxStackSize`, `isStackable`, `getHoverName`, `isDamageableItem`, `isDamaged`, `getDamageValue`, `getMaxDamage`, `ItemStack.isSameItem` and `ItemStack.isSameItemSameComponents`, and draw one with `graphics.item(stack, x, y)`. Items of ours look like a vanilla stand-in to a client, so tell them apart with `isSameItemSameComponents` or their name, not by what item they seem to be.

A player whose companion is older than these hooks gets told to update when they join, and modules that use them won't load for that player until they do.

Only what's listed here is allowed, so anything else is refused until the owner adds it:

- `gm.companion.api`, and Fabric's `HudElement`.
- From `java.lang`: `Object`, `String`, `StringBuilder`, `CharSequence`, `Comparable`, `Iterable`, `Runnable`, `Math`, `Number`, `Record`, `Enum`, the boxed types, and common exceptions.
- From `java.util`: the collections, `Collections`, `Arrays`, `Objects`, `Optional` and `Comparator`, and everything in `java.util.function`. Not streams.
- For drawing: `GuiGraphicsExtractor`, `Font` and `DeltaTracker`.
- `ItemStack`, but only what's listed above.
- For text: `Component`, `MutableComponent`, `FormattedText`, `FormattedCharSequence`, `Style`, `TextColor`, `ChatFormatting` and `Identifier`. Use `context.text` for words, so they come out in each player's language.
- For math: `Mth`, `ARGB`, `CommonColors`, `Vec2` and `Vec3`.
- `Minecraft`, but only `getInstance()`, `font`, `getFps()` and `getDeltaTracker()`.

Anything that can reach the player's session, such as `Minecraft.getUser()` or `com.mojang.authlib`, is refused, and so is LWJGL.

The companion also runs its own scan on every PC, which refuses a class if any constant in it contains certain text, including plain strings and your own method names. That means no strings containing paths like `sun/` or `java/net/`, and nothing named `lookup` or `forName`. The checks tell you if you hit this, and it's the one thing the owner can't approve here.

Each release signs its client modules, and players' companions refuse anything unsigned or older than a version they've run.

## Textures

Make textures with `assetkit`, which keeps them looking like they belong in Minecraft. See `assetkit/README.md`. Build colours from a small palette, keep contrast gentle, and avoid pure noise.
