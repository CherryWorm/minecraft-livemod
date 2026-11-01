# Feature bundle format

Knowledge, machine recipes, mobs, plants, ruins, biomes and sounds are in `docs/content-types.md`.

Each feature is one folder, `mods/genesis/features/<id>/`, where `<id>` is lowercase letters, digits and underscores.

```
<id>/
  feature.json
  assets/
    textures/<name>.png        16x16 unless you have reason otherwise
    textures/<name>.png.mcmeta only for animation
    models/<block_name>.json   optional custom block model
    lang.json                  optional extra translated text
  server/                      optional Java module, on the server
    src/main/java/...
    src/main/resources/module.properties   contains entry=<class>
  client/                      optional Java module, on players' clients
    src/main/java/...
    src/main/resources/module.properties
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

Families are limited, and a name stays assigned to its slot forever, so don't create blocks casually. A block's family can never change once it's been released.

A cube block can have different textures on its faces. `side` covers any side you don't name, and a face with nothing named uses `texture`. A block always faces the same way once placed, so `front` is always north, and it can't turn to face the player.

```json
"press": {"family": "machine", "display": "Press", "texture": "press_side",
          "faces": {"front": "press_front", "side": "press_side", "top": "press_top", "bottom": "press_top"}}
```

A `model` block is any shape you can model, with moving parts, for machines that should look like machines. It works like a `machine` block for modules and saving data, and its hitbox is always one full block, though the model can reach beyond that. Its `texture` is what it looks like in an inventory. Make the model the way you'd make a mob's, as described in `assetkit/README.md`, with its feet on the block's floor at Y 0 and its centre over X 0, Z 0.

```json
"great_press": {"family": "model", "display": "Great Press", "texture": "great_press_icon", "model": "great_press", "tool": "pickaxe"}
```

An animation called `idle` plays by itself. Start and stop others from a module with `machine.play("stamp")` and `machine.stop("stamp")`. Every moving part is an entity for players' computers to draw, so this suits things that matter. Use a cube for anything players will place by the hundred.

## Names

Use `$block:name` and `$item:name` in recipes and models. For another feature's content, use `$item:other_feature/name`. Never write a slot ID yourself.

`display` is the only readable name players can see. Everything else in the pack and data pack is renamed to meaningless IDs automatically.

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
- `minecraft:enchantments`, `stored_enchantments`, `death_protection`, `blocks_attacks`, `kinetic_weapon`, `piercing_weapon`, `attack_range`, `minimum_attack_charge`, `damage_type` and `glider` are refused on a recipe result. They add power with nothing to measure it against. Give the effect through a server module.

## Recipes and discovery

Every recipe needs a `mode`:

- `open`: always craftable. For basics.
- `known`: must be learned first. Needs a `route` saying how, following `bible/discovery.md`.
- `guessable`: only for machine recipes with simple inputs and many possible combinations. Needs `"machine": true` and `feedback` describing how the machine reacts to a near miss, and a failed attempt should cost little.

Two checks look at all recipes in all features together:

- **Nothing from nothing.** No set of recipes may leave a player with more of something and less of nothing, for example an ingot that makes 9 nuggets when 8 nuggets make an ingot. This includes loops through vanilla's own storage recipes, like iron block to ingots. A loop that costs something else each time is a conversion and is allowed.
- **Everything can be had.** Every block and item needs a source: an ore or plant, a block or mob that drops it, a ruin's chest or walls, or a recipe whose inputs can all be had. Vanilla items and `#minecraft:` tags count as available. An ore with its own `drops` never reaches anyone's inventory, so it can't be a recipe input. A server module handing something out doesn't count as a source, because no check can see that, so give it a recipe as well or mark it `retired` if nothing should make it.

## Ores

Each entry adds veins to the world, in chunks old and new. Its `id` must never be reused or changed, because chunks remember which ids they've already received. To change an ore's distribution later, add a new entry with a new id. `veinSize` can be at most 16.

Ore only replaces natural blocks. In places players have been, veins are hidden fully inside rock, so nothing appears next to a base.

An ore's yield must suit the tier it feeds. Yield is `veinsPerChunk` times `veinSize`, times the share of `minY` to `maxY` that's inside rock (Y -64 to 64), times the average of its drop `count`. All of a block's entries add up.

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

These are refused on both sides: files, network, processes, reflection, class loading, threads, native code, `sun.*`, `jdk.*` and `Unsafe`. `Class` only offers `getName`, `getSimpleName`, `getTypeName`, `isInstance`, `isAssignableFrom`, `cast`, `isEnum`, `isRecord`, `isArray` and `isInterface`. Lambdas, string concatenation, records and pattern switches all work, but nothing from `java.lang.invoke` may be called directly.

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
                player.sendSystemMessage(Component.literal("The block is warm."));
                return InteractionResult.SUCCESS;
            }
        });
    }
}
```

Names passed to `bindBlock`, `bindItem` and `bindMachine` are the ones in `feature.json`. A machine keeps everything it remembers in `machine.data()`, because that survives the module being replaced. Keep tick work small: a machine runs 20 times a second, for every one placed.

What each behaviour can do is in `/reference/conduit-api/`, and all of it is optional except a machine's `tick`. A few that are easy to miss:

- `BlockBehavior.removed(state, level, pos)` runs when the block has left the world, however it went: broken, blown up, pushed by a piston, or replaced by a command or a module. Use it to take something off a list the moment it goes, instead of sweeping for it. It doesn't run for a chunk unloading, or for anything that happens while your module isn't loaded, so don't rely on it alone for what has to stay exactly right.
- `MachineBehavior.removed(machine)` runs just before a machine goes, while `machine.data()` is still there, so it's where a machine drops what it holds. A command replacing it doesn't count, in the same way a chest's contents don't drop then.
- `MobBehavior.interact(mob, player, hand)` is a player using something on a mob. See "Mobs" in `docs/content-types.md`.
- `ItemBehavior.useOnEntity(stack, player, target, hand)` is this item used on a mob, if the mob itself had nothing to do with it. `ItemBehavior.mineBlock(stack, level, state, pos, miner)` is this item having just broken a block, which vanilla doesn't report for a player in creative mode.

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
});
```

These fire for everything, vanilla's and every feature's, so check what it was first. `blockBroken` is only for what a player breaks, and the block is already gone, so `state` is what it was. `mobKilled` is anything living that dies, however it happened, including players, and `source.getEntity()` is who did it, if anyone. `itemEaten` is food and drink, including potions and milk, and `stack` is a copy of what they had just before. `playerJoined` doesn't include anyone already online when your module loads, so look through `context.server().getPlayerList().getPlayers()` in `enable` if that matters.

A module that keeps throwing errors is switched off automatically.

Beyond the rules in Module code, a server module can use most of Minecraft, but of the module host only `gm.conduit.api`. Keep state in the game's own storage.

## Client modules

Java that runs on players' game clients: HUDs and effects. See `/reference/companion-api/`. These run on friends' computers, so they may only use the companion API and approved Minecraft classes. No files, network, processes, reflection or class loading: the checks refuse those. Prefer doing things on the server. Use a client module only for what truly needs one.

Only what's listed here is allowed, so anything else is refused until the owner adds it:

- `gm.companion.api`, and Fabric's `HudElement`.
- From `java.lang`: `Object`, `String`, `StringBuilder`, `CharSequence`, `Comparable`, `Iterable`, `Runnable`, `Math`, `Number`, `Record`, `Enum`, the boxed types, and common exceptions.
- From `java.util`: the collections, `Collections`, `Arrays`, `Objects`, `Optional` and `Comparator`, and everything in `java.util.function`. Not streams.
- For drawing: `GuiGraphicsExtractor`, `Font` and `DeltaTracker`.
- For text: `Component`, `MutableComponent`, `FormattedText`, `FormattedCharSequence`, `Style`, `TextColor`, `ChatFormatting` and `Identifier`.
- For math: `Mth`, `ARGB`, `CommonColors`, `Vec2` and `Vec3`.
- `Minecraft`, but only `getInstance()`, `font`, `getFps()` and `getDeltaTracker()`.

Anything that can reach the player's session, such as `Minecraft.getUser()` or `com.mojang.authlib`, is refused, and so is LWJGL.

The companion also runs its own scan on every PC, which refuses a class if any constant in it contains certain text, including plain strings and your own method names. That means no strings containing paths like `sun/` or `java/net/`, and nothing named `lookup` or `forName`. The checks tell you if you hit this, and it's the one thing the owner can't approve here.

Each release signs its client modules, and players' companions refuse anything unsigned or older than a version they've run.

## Textures

Make textures with `assetkit`, which keeps them looking like they belong in Minecraft. See `assetkit/README.md`. Build colours from a small palette, keep contrast gentle, and avoid pure noise.
