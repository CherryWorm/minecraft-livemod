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

A recipe can make several things, with `"outputs": [{"item": "$item:silver_nugget", "count": 1}, {"item": "$item:lead_ingot", "count": 2}]` in place of `output`. `attempt.outputs()` is everything it makes, and `attempt.output()` is the first. `attempt.recipe()` says which recipe it was, and `attempt.consume(inputs)` takes what it uses from those stacks, in the amounts it says, so a machine doesn't need its own table. To use another feature's recipes, name its machine as `"alloy_kiln/alloy_kiln"`.

### A machine's inventory

```json
"kiln": {"family": "machine", "display": "Kiln", "texture": "kiln", "inventory": {"inputs": 2, "fuel": 1, "outputs": 1}}
```

This gives a `machine` or `model` block real slots, up to 27 in all, numbered inputs first, then fuel, then outputs. It works like a furnace for everything else in the game: hoppers fill its inputs from above and its fuel from the sides, and take its outputs from below, and what's in it drops when it's broken. Without any fuel slots, the sides fill its inputs too. From a module:

```java
public void tick(SlotBlockEntity machine) {
    List<ItemStack> inputs = List.of(machine.getItem(0), machine.getItem(1));
    MachineAttempt attempt = context.attemptRecipe(null, "kiln", inputs);
    if (attempt.succeeded() && machine.getItem(3).isEmpty()) {
        attempt.consume(inputs);
        machine.setItem(3, attempt.output().copy());
    }
}

public boolean accepts(SlotBlockEntity machine, int slot, ItemStack stack) {
    return slot != 2 || stack.is(Items.COAL);
}
```

Pass `null` for the player when nobody's there, as with a machine a hopper keeps fed. A recipe that has to be learned then only works if this world shares what's learned and someone knows it. `accepts` says what can go in each input and fuel slot, and nothing can go in an output. `machine.openMenu(player, title)` shows the inventory on a chest's screen, with inputs and fuel on the left and outputs on the right, usually from a `BlockBehavior.use`.

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

- `category` is `monster` or `creature`, and can't change after release. There are 240 of the first and 480 of the second.
- `model` is `assets/models/<model>.bbmodel`. Model each creature for itself with `assetkit/sculpt.py`, so it looks like nothing else in the world. See `assetkit/README.md`. It needs animations named `idle` and `walk`, and `attack` if it fights, and should have `hurt` and `death`. The game plays all of these by itself, and a mob stays until its `death` finishes, up to 5 seconds. Set `width` and `height` from what `sculpt.stats` says.
- `behaviour` is `hostile`, `neutral` (fights back), `passive` or `skittish` (avoids players).
- `spawn` is optional. Leave it out for something only a module summons. `light` is `dark`, `bright` or `any`. `cap` limits how many gather near one player. Biomes can be ids or `#tags`.
- `sounds` is optional, and the game plays these by itself: `"sounds": {"idle": "$sound:crab_click", "hurt": "$sound:crab_yelp", "death": "minecraft:entity.fox.death"}`. Each is one of this world's from `"sounds"` below, or vanilla's by its name. `idle` plays every so often. With none of its own it's quiet when idle, and gets the game's plain hurt and death sounds.

For anything more, bind code to it: `context.bindMob("rune_crab", new MobBehavior() { ... })`, with `tick(mob)`, `hurt(mob, source)` and `interact(mob, player, hand)`. A model's animations are played with `mob.animator().playAnimation("name")`.

To give a mob from another feature a new look, its own model replaces the old one for every one of them, including those already out there: `"reskins": {"fraying_tears/frayling": "frayling_v2"}`, with `assets/models/frayling_v2.bbmodel` in your feature. Its size stays what the mob's definition says, so keep the same shape, and the same animation names, or it will stand still.

`interact` is how a mob gets fed, tamed or sheared by using something on it. It runs ahead of its mind, so anything but `PASS` is the end of it, and `PASS` carries on to its mind if it has one. It runs once for each hand, and using up the item is up to you:

```java
context.bindMob("rune_crab", new MobBehavior() {
    @Override
    public InteractionResult interact(SlotMob mob, Player player, InteractionHand hand) {
        if (hand != InteractionHand.MAIN_HAND || !player.getMainHandItem().is(context.item("rune_berry"))) {
            return InteractionResult.PASS;
        }
        player.getMainHandItem().shrink(1);
        context.playSound("crab_munch", mob.level(), mob.blockPosition(), 1.0F, 1.0F);
        return InteractionResult.SUCCESS;
    }
});
```

## Minds

A mob can have a mind: at the moments that matter, a very fast and cheap model decides what it does, as itself. Most mobs shouldn't have one. Give it to the ones players will want to talk to, make friends with or get to know: a hermit, a shopkeeper, a beloved companion, a village elder, a boss that reads the fight. Everything else about a mob stays plain code, and if the day's share of usage runs out, it just carries on without words.

```json
"mobs": {
  "hermit_crab": {
    "category": "creature", "display": "Old Pinch", "model": "hermit_crab", "behaviour": "neutral", "health": 20, "damage": 2, "speed": 0.15, "width": 1, "height": 1,
    "mind": {
      "character": "A grumpy old crab who has lived under the pier longer than anyone remembers. Vain about his shell. Knows where the tin is, and how to cut gems, but tells nobody who hasn't brought him something shiny.",
      "voice": "words",
      "actions": ["follow", "flee", "stay", "wander", "lead", "give", "teach"],
      "animations": ["wave", "sulk"],
      "sounds": ["$sound:crab_click"],
      "loves": ["minecraft:emerald"],
      "stash": [{"item": "$item:rune_dust", "count": 3, "trust": 2}],
      "teaches": {"gem_cutting": 4},
      "leads_to": ["$block:tin_ore"],
      "greets": true
    }
  }
}
```

- **`character`** is all it knows about anything, up to 800 characters, and it's read at every decision. Write who it is, what it wants and what it knows, in a way that gives it a reason to be interesting. Never put anything in it that's coming later.
- **`voice`** is `words`, `cries` for something that only makes noises like "Pika!", or `silent` for something that only moves. A creature that can't talk but clearly understands is often better than one that can.
- **`actions`** is what it can choose from: `follow`, `flee`, `stay`, `wander`, `lead` (to the nearest block in `leads_to`, within 24 blocks), `give`, `teach` and `attack` (neutral or hostile only, and a neutral one only against someone it distrusts).
- **`animations`** and **`sounds`** are how it expresses itself, so give it a few that suit it. They have to exist in its model. Moving is how a creature talks.
- **`stash`** is what it can hand over. It's per player and per kind of mob, so killing one doesn't refill it, and it needs that much **trust** first. Up to 8 things in all, from this feature's step in the progression or earlier.
- **`teaches`** gives the trust needed for knowledge it can pass on. The entry still needs its own routes, because nobody should depend on a model to progress.
- **`greets`** makes it react the first time each player comes near.

Players talk to it by facing it up close and typing in chat, or by using its name from further away. Using an empty hand on it says hello, and using an item offers it. Trust runs from -10 to 10: gifts raise it, and hitting one lowers it with that whole kind. It remembers per player. What's said to one creature can spread as rumour to others, changing as it goes.

For a boss, list `"moves": ["slam", "charge"]` and optionally `"fight_seconds": 10`. Every so often during a fight its mind picks the next move from what's happening, or plain code picks one if it can't. Moves play the animation of the same name, and do what your module says:

```java
context.bindMob("colossus", new MobBehavior() {
    @Override
    public void move(SlotMob mob, String name, LivingEntity target) {
        if (name.equals("slam")) { /* ... */ }
    }
});
```

## Plants

A `plant` or `tinted_plant` block placed in the world, old and new, but not in a chunk where someone has built.

```json
"plants": [
  {"id": "moss_cap_v1", "block": "moss_cap", "on": ["minecraft:grass_block"], "perChunk": 1.5,
   "minY": 40, "maxY": 200, "underground": false, "biomes": ["minecraft:plains"]}
]
```

`underground` true means cave floors rather than the open surface. An `id` is permanent, like an ore's: chunks remember which ids they've had.

A `glow_plant` block is a plant that gives light at level 10. There are only 2, so spend them on something that matters.

## What an item is

An item can say what it is, so every stack of it has these from the start, including ones from drops and loot:

```json
"items": {
  "tide_berry": {
    "display": "Tide Berry",
    "components": {
      "minecraft:food": {"nutrition": 4, "saturation": 2.4},
      "minecraft:consumable": {"consume_seconds": 1.6}
    }
  },
  "brine_seed": {
    "display": "Brine Seed",
    "places": {"block": "$block:brinewort", "on": ["minecraft:sand", "minecraft:gravel"]}
  },
  "tin_pick": {
    "display": "Tin Pickaxe",
    "handheld": true,
    "tier": "stone",
    "components": {"minecraft:max_damage": 180, "minecraft:max_stack_size": 1}
  }
}
```

- `components` are the game's own item components, and a tool or weapon's numbers here answer to the same tier curve as anywhere else. Prefer this to setting them on a recipe's result, which only covers what's crafted.
- `places` makes it a seed, or anything like one: using it on the top of a block puts that block above and uses one up. Leave out `on` to allow anything solid.
- `handheld` holds it the way vanilla holds a tool.
- `"tooltip": ["Always points north"]` adds fixed lines to its tooltip.
- `"use": {"seconds": 1, "animation": "brush"}` makes using it take that long, showing that animation, and then `ItemBehavior.finishUsing` runs. It isn't used up unless your module does that. The animations are `none`, `eat`, `drink`, `block`, `bow`, `trident`, `crossbow`, `spyglass`, `toot_horn`, `brush`, `bundle` and `spear`.
- `"variants": {"gilded": "ledger_gilded"}` gives it other pictures. A stack shows one when it has `"minecraft:custom_model_data": {"strings": ["gilded"]}`, from a recipe's result or a module, and its usual `texture` otherwise.
- `"compass": ["needle_0", "needle_1", "needle_2", "needle_3"]` makes it turn like a compass, with as many frames as you like up to 64, the first pointing straight ahead and the rest going round clockwise. It points where a stack's `minecraft:lodestone_tracker` says, which a module sets, and spins if there's nothing there or it's in another dimension.

A release that changes these reaches stacks in inventories the next time that player joins.

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

Without any of what follows, the ground under its corner at `x` 0, `z` 0 is what counts, and all of it is built level from there, so it can float or bury itself on a slope.

- **`"followTerrain": true`** counts each part's `y` from the ground under that part, so it sits flush on a slope. A part at `y` -1 goes into the ground and one at `y` 1 stands above it, wherever the ground is. Every column it uses has to have its ground in `on`, so a wide ruin needs a wide `on`, and a ruin under trees sits on the forest floor. `"maxSlope": 8` is how far the ground may rise and fall under it before it won't go there, which is 8 if you leave it out. It's only for the surface.
- **`"layouts": [[...], [...]]`** replaces `parts` with several shapes, and each one placed picks one of them.
- **`"chance": 0.5` on a part** means it's only there half the time, so counts can vary without a layout for each.
- **`"spacing": 40`** keeps any two of this ruin at least that many chunks apart. It also makes them rare: that spacing gives one possible spot in every 60 by 60 chunks, which is one and a half times as wide. `chance` is then how likely each spot is to get one, and you can leave it out for all of them. Some spots won't suit it and stay empty, so allow for fewer than that.
- **`"highGround": 3`** only places it where the ground in the middle of its chunk is at least that many blocks above the average of the middles of the four chunks around it, so it sits on a rise, and not just on a slope. It's only for the surface, and it can't move a ruin to the top of a hill, only leave out the chunks that aren't one. In the worlds it's been tried on, 3 leaves between one chunk in ten and one in four, depending how hilly the land is, on top of what `chance` or `spacing` leave, so allow for that.
- **A block state** goes after a part's block, written the way commands write it: `"minecraft:ladder[facing=north]"`, or `"minecraft:lantern[hanging=true]"`. Nothing else is checked when it's placed, so one that needs something to hold on to will stay there until something next to it changes, and then fall off if there's nothing there. With `followTerrain`, the columns next to it may not be at the height you drew.
- **`"loot": {...}` on a part** gives that one container its own loot table. The ruin's own `loot` is for any container that hasn't got one. Only vanilla's chests, barrels, shulker boxes, dispensers, droppers, hoppers and crafters can hold loot.

```json
"crater": {
  "id": "crater_v1",
  "layouts": [
    [{"x": 6, "y": -1, "z": 6, "block": "$block:scorched"}, {"x": 7, "y": 0, "z": 6, "block": "$block:aerolite", "chance": 0.5}],
    [{"x": 9, "y": -1, "z": 9, "block": "$block:scorched"}, {"x": 9, "y": 1, "z": 9, "block": "$block:aerolite"}]
  ],
  "on": ["minecraft:grass_block", "minecraft:dirt", "minecraft:stone"],
  "replaces": ["minecraft:air", "minecraft:short_grass", "minecraft:grass_block", "minecraft:dirt", "minecraft:stone"],
  "followTerrain": true,
  "spacing": 30,
  "minY": 50, "maxY": 200
}
```

A ruin's `id` is permanent, like an ore's. Chunks remember which ids they've had, so to change a ruin that's out, give the new version a new `id`. That's a new ruin in land nobody's been to, and the old ones stay where they are.

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

A block's `drops` can also name vanilla's items, and can be a list, all of which come together:

```json
"drops": [{"item": "minecraft:copper_ingot"}, {"item": "minecraft:glass_pane", "count": [0, 2]}, {"item": "brass_scrap"}]
```

Diamonds, emeralds, netherite and vanilla's other rarest things can't come from a block this way, because what the world keeps placing soon makes them common. Put those in a ruin's loot instead, as a rare find. And something crafted can't break into more of vanilla's materials than it took, on average, or it would make them from nothing. A mob's `drops` is still one thing, and from this world.

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

List names in `"sounds": ["chime"]`, with `assets/sounds/chime.ogg` from `assetkit/sounds.py`. Refer to one as `$sound:chime` in data.

A module plays one by name, for everyone close enough to hear it. It can be `"other_feature/name"` for another feature's. A volume above 1 carries further, and pitch runs from 0.5 to 2:

```java
context.playSound("chime", level, pos, 1.0F, 1.0F);
```

For anything more, `context.sound("chime")` gives the game's own `SoundEvent`, so `level.playSound(null, pos, context.sound("chime"), SoundSource.BLOCKS, 1.0F, 1.0F)` chooses its volume slider.

## Using your content from a module

`context.block("name")`, `context.item("name")`, `context.mob("name")` and `context.sound("name")` give you the real objects for names in `feature.json`, or `"other_feature/name"` for another feature's.

## What the engine doesn't do yet

Structures larger than a chunk, new dimensions, screens beyond chest-style menus and books, and client rendering beyond the HUD. Armor can only look like vanilla's when worn, and custom tools can't take enchantments at an enchanting table. Build the closest thing that works, and say what you wanted in `host_requests`.
