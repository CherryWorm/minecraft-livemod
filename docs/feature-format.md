# Feature bundle format

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
| `tinted_plant` | The same, tinted by biome |

Families are limited, and a name stays assigned to its slot forever, so don't create blocks casually. A block's family can never change once it's been released.

## Names

Use `$block:name` and `$item:name` in recipes and models. For another feature's content, use `$item:other_feature/name`. Never write a slot ID yourself.

`display` is the only readable name players can see. Everything else in the pack and data pack is renamed to meaningless IDs automatically.

A released name can never be removed, because worlds may contain it. To retire something, keep it declared and stop making it obtainable.

## Items and their stats

Items stack to 64 and do nothing by default. To make a tool, weapon or armor, set components on the recipe's result, for example `"components": {"minecraft:max_damage": 250, "minecraft:tool": {...}}`.

## Recipes and discovery

Every recipe needs a `mode`:

- `open`: always craftable. For basics.
- `known`: must be learned first. Needs a `route` saying how, following `bible/discovery.md`.
- `guessable`: only for machine recipes with simple inputs and many possible combinations. Needs `"machine": true` and `feedback` describing how the machine reacts to a near miss, and a failed attempt should cost little.

## Ores

Each entry adds veins to the world, in chunks old and new. Its `id` must never be reused or changed, because chunks remember which ids they've already received. To change an ore's distribution later, add a new entry with a new id. `veinSize` can be at most 16.

Ore only replaces natural blocks. In places players have been, veins are hidden fully inside rock, so nothing appears next to a base.

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

A module that keeps throwing errors is switched off automatically.

## Client modules

Java that runs on players' game clients: HUDs and effects. See `/reference/companion-api/`. These run on friends' computers, so they may only use the companion API and approved Minecraft classes. No files, network, processes, reflection or class loading: the checks refuse those. Prefer doing things on the server. Use a client module only for what truly needs one.

## Textures

Make textures with `assetkit`, which keeps them looking like they belong in Minecraft. See `assetkit/README.md`. Build colours from a small palette, keep contrast gentle, and avoid pure noise.
