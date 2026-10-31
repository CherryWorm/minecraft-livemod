# Content beyond blocks and items

More things `feature.json` can declare. `docs/feature-format.md` covers the basics. All of these ship with no restart unless it says otherwise.

## Knowledge: how recipes are learned

A knowledge entry is something a player can come to know. It shows up in their codex (`/codex`) with your text, and unlocks recipes.

```json
"knowledge": {
  "gem_cutting": {
    "title": "On Cutting Gems",
    "text": "Written the way the world would say it. Hints, not instructions.",
    "routes": [
      {"type": "obtain", "id": "$item:rune_dust"},
      {"type": "examine", "id": "$block:rune_ore"},
      {"type": "examine", "id": "minecraft:drowned"},
      {"type": "kill", "id": "$mob:rune_crab"},
      {"type": "read", "id": "$item:rune_tablet"},
      {"type": "fragments", "id": "$item:rune_shard", "needed": 3}
    ]
  }
}
```

An entry can have one route or several, and any one of them teaches it.

| Route | How a player triggers it |
|---|---|
| `obtain` | Having the item in their inventory |
| `examine` | Sneaking and using an empty hand on that block or mob |
| `kill` | Killing that mob |
| `read` | Using the item, which uses it up. Good for tablets and blueprints found in loot |
| `fragments` | Using the item, which uses it up and counts one piece. Learned at `needed` pieces |

A recipe that names an entry in `route` can't be crafted until it's learned:

```json
"rune_gem": {"mode": "known", "route": "gem_cutting", "json": {"type": "minecraft:crafting_shapeless", "...": "..."}}
```

`route` can name another feature's entry as `other_feature/name`. `known` works for crafting recipes and machine recipes only. For smelting, stonecutting and so on use `open`. An `open` recipe appears in a player's recipe book once they hold something it uses.

Whether learning is shared by everyone or per player is set for the whole world in `bible/discovery.json`.

A module can teach something itself with `context.teach(player, "name")`, for a discovery only code can detect, and ask `context.knows(player, "name")`.

## Machine recipes

Declared in `recipes`, with `machine` naming the machine rather than using `json`:

```json
"rune_salt": {
  "mode": "guessable",
  "machine": "crucible",
  "feedback": "The crucible hums louder the closer you are.",
  "inputs": [{"item": "$item:rune_dust", "count": 1}, {"item": "$item:rune_gem", "count": 1}],
  "output": {"item": "$item:rune_salt", "count": 1}
}
```

Your module asks whether what a player offered matches. Order doesn't matter.

```java
MachineAttempt attempt = context.attemptRecipe(player, "crucible", List.of(left, right));
if (attempt.succeeded()) { /* consume the inputs and give attempt.output() */ }
else if (attempt.nearMiss()) { /* attempt.closest() of attempt.needed() matched, so react */ }
else if (attempt.locked()) { /* it's right, but they haven't learned it yet */ }
```

Use `known` with a `route` for recipes learned elsewhere, `open` for ones that are always available, and `guessable` for ones meant to be found by experimenting. A failed attempt should cost little, and the machine should react in a way players can see or hear.

## Mobs

```json
"mobs": {
  "rune_crab": {
    "category": "creature",
    "display": "Rune Crab",
    "model": "rune_crab",
    "behaviour": "skittish",
    "health": 8, "damage": 0, "speed": 0.25, "width": 0.8, "height": 0.6,
    "followRange": 24, "armor": 0,
    "drops": {"item": "rune_dust", "count": [1, 2]},
    "spawn": {"weight": 10, "light": "dark", "minY": 40, "maxY": 200, "cap": 3, "underground": false, "biomes": ["#minecraft:is_beach"]}
  }
}
```

- `category` is `monster` or `creature`, and can't change after release. There are 24 of the first and 16 of the second, so don't spend them casually.
- `model` is `assets/models/<model>.bbmodel`, made with `assetkit/bbmodel.py`. It needs animations named `idle` and `walk`, and `attack` if it fights.
- `behaviour` is `hostile`, `neutral` (fights back), `passive` or `skittish` (avoids players).
- `spawn` is optional. Leave it out for something only a module summons. `light` is `dark`, `bright` or `any`. `cap` limits how many gather near one player. Biomes can be ids or `#tags`.

For anything more, bind code to it: `context.bindMob("rune_crab", new MobBehavior() { ... })`, with `tick(mob)` and `hurt(mob, source)`. A model's animations are played with `mob.animator().playAnimation("name")`.

## Plants

A `plant` or `tinted_plant` block placed in the world, old and new, but not in a chunk where someone has built.

```json
"plants": [
  {"id": "moss_cap_v1", "block": "moss_cap", "on": ["minecraft:grass_block"], "perChunk": 1.5,
   "minY": 40, "maxY": 200, "underground": false, "biomes": ["minecraft:plains"]}
]
```

`underground` true means cave floors rather than the open surface. An `id` is permanent, like an ore's: chunks remember which ids they've had.

## Ruins

A small built thing that turns up in land nobody has been to yet. It has to fit in one chunk.

```json
"ruins": {
  "shrine": {
    "id": "shrine_v1",
    "parts": [
      {"x": 0, "y": 0, "z": 0, "block": "$block:rune_stone"},
      {"x": 1, "y": 0, "z": 0, "block": "minecraft:chest"}
    ],
    "on": ["minecraft:sand", "minecraft:gravel"],
    "replaces": ["minecraft:air", "minecraft:water", "minecraft:seagrass"],
    "chance": 0.02,
    "minY": 30, "maxY": 80,
    "underground": false,
    "biomes": ["minecraft:beach"],
    "loot": {"type": "minecraft:chest", "pools": [{"rolls": 2, "entries": [{"type": "minecraft:item", "name": "$item:rune_tablet"}]}]}
  }
}
```

`x` and `z` run from 0 to 15, and `y` from the ground up. A ruin is placed whole or not at all. `chance` is per chunk: 0.02 is about one in fifty. On the surface it sits on the sea floor if there's water. Underground it's placed at a random height, which is only right for something meant to be found while digging.

## Loot tables

Minecraft 26 changed this format, and the game ignores fields it doesn't know without saying so. Use `modifier`, not `functions`, and `condition`, not `conditions`:

```json
{"type": "minecraft:chest", "pools": [{"rolls": 3, "entries": [
  {"type": "minecraft:item", "name": "$item:rune_shard", "weight": 3,
   "modifier": [{"type": "minecraft:set_count", "count": {"type": "minecraft:uniform", "min": 1, "max": 2}}]},
  {"type": "minecraft:item", "name": "minecraft:iron_nugget", "weight": 8}
]}]}
```

A block's `drops` handles the rest for you: silk touch gives the block itself, and fortune works on `ore` and `deep_ore`. A mob's `drops` respect looting.

## Ores by biome

Add `"biomes": ["minecraft:beach", "minecraft:ocean"]` to an ore to limit where it forms.

## Biomes

Needs a restart, which players are held through, so these go out in batches.

```json
"biomes": {
  "rune_meadow": {
    "base": "minecraft:plains",
    "effects": {"grass_color": "#2e8b57", "foliage_color": "#2e8b57", "water_color": "#2e8b8b"},
    "attributes": {"minecraft:visual/sky_color": "#78a7ff"},
    "proportion": 0.25
  }
}
```

It starts as an exact copy of `base`, and replaces `proportion` of it. If you change only `effects` and the `minecraft:visual/` or `minecraft:audio/` attributes, it's a sibling and spreads into land that already exists, because it's safe there. If you change `temperature`, `downfall`, `has_precipitation`, `features`, `carvers` or any other attribute, such as `minecraft:gameplay/natural_mob_spawns`, it only appears in land generated from then on, because changing those in existing land could freeze water or break a mob farm.

## Sounds

List names in `"sounds": ["chime"]`, with `assets/sounds/chime.ogg` from `assetkit/sounds.py`. Refer to one as `$sound:chime` in data, or look it up in a module.

## Using your content from a module

`context.block("name")`, `context.item("name")` and `context.mob("name")` give you the real objects for names in `feature.json`, or `"other_feature/name"` for another feature's.

## What the engine doesn't do yet

Structures larger than a chunk, new dimensions and client rendering beyond the HUD. Build the closest thing that works, and say what you wanted in `host_requests`.
