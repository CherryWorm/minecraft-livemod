"""A quick look at a feature's art beside vanilla's own, with no game running, so the builder can catch art that
looks wrong in about a second rather than after the gates and a review.

    from orchestrator import preview
    result = preview.render("mods/genesis/features/ember", "/tmp/ember.png", "/workspace/reference-textures")
    # read result["path"], and act on result["notes"]

`references` is what broker/reference_textures.py extracts: block/<name>.png and item/<name>.png.
This stands in for the client gate's scene, so it can't show lighting, block shapes or how a mob moves.
"""
import json
import pathlib
import re

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from assetkit import bbmodel, sheet

BLOCK = 48  # pixels per block: 3x, about the size a block looks from a few blocks away
SLOT = 54  # an inventory slot at GUI scale 3, with its 48 pixel item
WIDTH = 1240  # images much past 1500 pixels get shrunk before the builder sees them, which blurs what it's judging
MARGIN, GAP = 16, sheet.GAP
DIM, MARK, SKY = (160, 160, 168), (255, 225, 60), (120, 167, 255)
MOB_BACKDROP = (84, 96, 110)
SLOT_FILL, SLOT_DARK, SLOT_LIGHT, PANEL = (139, 139, 139), (55, 55, 55), (255, 255, 255), (198, 198, 198)
NAME_FONT, SMALL_FONT = ImageFont.load_default(14), ImageFont.load_default(12)

# Vanilla's grass and leaf textures are grey, and the game multiplies them by the biome's colour. These are plains,
# read from colormap/grass.png and foliage.png in the 26.3 client jar.
GRASS_TINT, FOLIAGE_TINT = (145, 189, 89), (119, 171, 47)
VANILLA_TINTS = {"block/grass_block_top": GRASS_TINT, "block/oak_leaves": FOLIAGE_TINT}
PLANT_FAMILIES = ("plant", "glow_plant", "tinted_plant")

# What each family sits among in its wall, and the vanilla blocks beside it. None means open sky, for see-through leaves.
CONTEXT = {
    "stone": ("stone", ("cobblestone", "deepslate")),
    "ore": ("stone", ("iron_ore", "copper_ore", "diamond_ore", "coal_ore")),
    "deep_ore": ("deepslate", ()),  # vanilla's deepslate ores aren't in the references, and stone ones would mislead here
    "metal": ("stone", ("iron_block", "copper_block", "gold_block")),
    "wood": ("stone", ("oak_planks", "oak_log")),
    "soil": ("stone", ("dirt", "gravel", "sand")),
    "glow": ("stone", ("glowstone",)),
    "machine": ("stone", ("furnace_front", "iron_block")),
    "cutout": (None, ("oak_leaves", "oak_log")),
}
BESIDE_SPOTS = ((1, 1), (3, 1), (0, 2), (4, 2))  # reading order, around the new block's L shape
NEW_SPOTS = ((2, 1), (2, 2), (3, 2))
NEW_OUTLINE = ((2, 1), (3, 1), (3, 2), (4, 2), (4, 3), (2, 3), (2, 1))
PLANT_OUTLINE = ((1, 1), (4, 1), (4, 2), (1, 2), (1, 1))
FLAT_STAND_INS = {"stone": (126, 126, 126), "deepslate": (80, 80, 83), "grass_block_top": (83, 109, 51)}  # their averages

# The first group sharing a word with an item's name decides what it's shown beside. Whole words, so "capstone" isn't a "cap".
FOOD_PEERS, ARMOR_PEERS = ("apple", "bread"), ("iron_helmet",)
TOOL_PEERS, OTHER_PEERS = ("iron_pickaxe",), ("iron_ingot", "diamond")
ITEM_KINDS = (
    ({"pick", "pickaxe", "axe", "hatchet", "shovel", "spade", "hoe", "hammer", "mattock"}, TOOL_PEERS),
    ({"sword", "blade", "dagger", "knife", "sabre", "saber", "spear", "mace", "scythe"}, ("iron_sword",)),
    ({"helmet", "helm", "hood", "chestplate", "cuirass", "leggings", "greaves", "boots", "armor", "armour"}, ARMOR_PEERS),
    ({"ingot", "bar", "nugget", "alloy"}, ("iron_ingot", "gold_ingot")),
    ({"raw", "chunk", "lump"}, ("raw_iron",)),
    ({"gem", "gemstone", "crystal", "shard", "jewel", "pearl", "ruby", "sapphire"}, ("diamond",)),
    ({"rod", "stick", "staff", "wand", "twig"}, ("stick",)),
    ({"apple", "berry", "berries", "bread", "loaf", "fruit", "meat", "stew", "soup", "cookie", "pie", "cake"}, FOOD_PEERS),
)

# RGB distance between average colours. Vanilla's distinct blocks are 11 or more apart. The pairs under this, like stone,
# cobblestone and gravel at 3 to 6, are told apart by pattern alone, so a new block this close has nothing but pattern either.
SAME_COLOUR = 8
# An ore is mostly rock, so its average sits near plain rock whatever its flecks are: vanilla copper_ore is 6 from stone.
# So ores only answer to other ores, and everything else only to things that aren't ores.
ORE_FAMILIES = ("ore", "deep_ore")
# Median HSV saturation above the surrounding vanilla rock (0 for stone and deepslate). Rock this far above it is as vivid
# as vanilla's dirt or planks (0.52). The median ignores an ore's flecks, which are meant to be colourful.
ROCK_SATURATION = 0.5
ROCK_FAMILIES = ("stone",) + ORE_FAMILIES  # vanilla's wood, soil and metal are rightly far more colourful than stone
# Luminance spread against vanilla stone's (10.8). Four times that is well past cobblestone and coal ore, vanilla's roughest
# ordinary surfaces at 30, and past assetkit's cobble, gravel and planks in all but their lightest colours. Metal, machine
# and glow blocks show a frame or a light on purpose, as furnace_front (53) and glowstone (62) do, so this skips them.
CONTRAST_TIMES = 4
CONTRAST_FAMILIES = ROCK_FAMILIES + ("wood", "soil")


def _text(draw, xy, text, fill, font):
    draw.text(xy, text, fill=fill, font=font)


def _fit(text, font, width):
    """Cuts text to a pixel width, so a long name can't run into its neighbour."""
    if font.getlength(text) <= width:
        return text
    while text and font.getlength(text + "...") > width:
        text = text[:-1]
    return text + "..."


def _big(img, size):
    return img.resize((size, size), Image.NEAREST)


def _tint(img, colour):
    a = np.asarray(img).copy()
    a[..., :3] = (a[..., :3].astype(float) * np.array(colour) / 255).astype(np.uint8)
    return Image.fromarray(a)


def _flat(colour):
    return Image.new("RGBA", (BLOCK, BLOCK), colour + (255,))


def _missing_texture():
    """The game's purple and black checks, so a missing texture looks here the way it would there."""
    ys, xs = np.mgrid[0:16, 0:16]
    purple = ((xs // 8) + (ys // 8)) % 2 == 0
    return Image.fromarray(np.where(purple[..., None], (248, 0, 248, 255), (0, 0, 0, 255)).astype(np.uint8))


def _surface(img):
    """Average colour, saturation and contrast of the pixels that aren't see-through."""
    a = np.asarray(img, dtype=float)
    rgb = a[a[..., 3] > 0][:, :3]
    if not len(rgb):
        return None
    top = rgb.max(axis=1)
    saturation = (top - rgb.min(axis=1)) / np.maximum(top, 1)
    return {"mean": rgb.mean(axis=0), "saturation": float(np.median(saturation)),
            "contrast": float((rgb @ np.array((0.3, 0.59, 0.11))).std())}


def _rgb(mean):
    return "(" + ",".join(str(int(round(v))) for v in mean) + ")"


def _distance(a, b):
    return float(np.linalg.norm(a["mean"] - b["mean"]))


class _Vanilla:
    """The references folder, remembering what was asked for and wasn't there."""

    def __init__(self, folder):
        self.textures, self.absent = {}, set()
        root = pathlib.Path(folder) if folder else None
        for path in sorted(root.glob("*/*.png")) if root and root.is_dir() else ():
            key = f"{path.parent.name}/{path.stem}"
            try:
                img = sheet._frames(Image.open(path).convert("RGBA"))[0]
            except Exception:  # noqa: BLE001 - Pillow raises many types for a broken file
                continue
            self.textures[key] = _tint(img, VANILLA_TINTS[key]) if key in VANILLA_TINTS else img

    def get(self, key):
        found = self.textures.get(key)
        if found is None:
            self.absent.add(key)
        return found

    def block(self, name):
        found = self.get(f"block/{name}")
        return _big(found, BLOCK) if found else None

    def block_surfaces(self):
        surfaces = {key[len("block/"):]: _surface(img) for key, img in self.textures.items() if key.startswith("block/")}
        return {name: surface for name, surface in surfaces.items() if surface}


def _manifest(folder, notes):
    try:
        manifest = json.loads((folder / "feature.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        notes.append(f"feature.json can't be read: {error}")
        return {}
    if not isinstance(manifest, dict):
        notes.append("feature.json isn't a JSON object.")
        return {}
    return manifest


def _entries(manifest, key):
    """Only well-formed entries, since this runs on half-written features too."""
    found = manifest.get(key)
    return {name: entry for name, entry in found.items() if isinstance(entry, dict)} if isinstance(found, dict) else {}


def _field(entry, key, default):
    return str(entry.get(key) or default)


def _texture(folder, name, label, notes):
    """Returns the first frame and a line describing the file, or None and a note if the file can't be used."""
    path = folder / "assets" / "textures" / f"{name}.png"
    if not path.exists():
        notes.append(f"{label}: texture {name}.png is missing.")
        return None, "texture missing"
    try:
        img = Image.open(path).convert("RGBA")
    except Exception as error:  # noqa: BLE001 - Pillow raises many types for a broken file
        notes.append(f"{label}: {name}.png can't be read: {error}")
        return None, "unreadable"
    frames = sheet._frames(img)
    first = frames[0]
    colours = len(sheet._colours(first))
    if colours > sheet.MAX_COLOURS:
        notes.append(f"{label}: {colours} colours, over the limit of {sheet.MAX_COLOURS}. Use a smaller palette.")
    if len(frames) > 1 and not path.with_suffix(".png.mcmeta").exists():
        notes.append(f"{label}: {name}.png is a {img.width}x{img.height} strip with no .mcmeta, so it can't animate.")
    info = f"{first.width}x{first.height}, {colours} colours"
    return first, info + (f", {len(frames)} frames, first shown" if len(frames) > 1 else "")


# ---------------------------------------------------------------- blocks

def _surroundings(vanilla, name):
    """A vanilla block and what to call it, or its average colour if it's not in the references."""
    found = vanilla.block(name)
    return (found, name) if found else (_flat(FLAT_STAND_INS[name]), f"flat colour standing in for {name}")


def _wall(tile, family, vanilla):
    """A small wall of vanilla with the new block outlined in it. Returns the image and a caption naming the vanilla."""
    wall = Image.new("RGBA", (BLOCK * 5, BLOCK * 3), SKY + (255,))
    if family in PLANT_FAMILIES:
        ground, called = _surroundings(vanilla, "grass_block_top")
        for x in range(5):
            wall.alpha_composite(ground, (x * BLOCK, 2 * BLOCK))
            if 1 <= x <= 3:
                wall.alpha_composite(tile, (x * BLOCK, BLOCK))
        outline, caption = PLANT_OUTLINE, f"on {called}, under open sky"
    else:
        surround, wanted = CONTEXT.get(family, CONTEXT["stone"])
        called = "open sky"
        if surround:
            base, called = _surroundings(vanilla, surround)
            for y in range(3):
                for x in range(5):
                    wall.alpha_composite(base, (x * BLOCK, y * BLOCK))
        beside = []
        for name, (x, y) in zip(wanted, BESIDE_SPOTS):
            peer = vanilla.block(name)
            if peer:
                wall.alpha_composite(peer, (x * BLOCK, y * BLOCK))
                beside.append(name)
        for x, y in NEW_SPOTS:
            wall.alpha_composite(tile, (x * BLOCK, y * BLOCK))
        outline = NEW_OUTLINE
        caption = f"in {called}" + (f", beside {', '.join(beside)}" if beside else "")
    ImageDraw.Draw(wall).line([(x * BLOCK, min(y * BLOCK, wall.height - 1)) for x, y in outline], fill=MARK, width=1)
    return wall, caption


def _block_cell(block, vanilla):
    tile = _big(block["shown"], BLOCK)
    wall, caption = _wall(tile, block["family"], vanilla)
    tiled = sheet._tiled(tile, 1)
    cell = Image.new("RGBA", (wall.width + GAP + tiled.width, 36 + wall.height + 18), sheet.BG + (255,))
    draw = ImageDraw.Draw(cell)
    _text(draw, (0, 0), _fit(block["label"], NAME_FONT, cell.width), sheet.INK, NAME_FONT)
    tinted = ", tinted as in plains" if block["family"] == "tinted_plant" else ""
    _text(draw, (0, 18), _fit(f"{block['family']}, {block['info']}{tinted}", SMALL_FONT, cell.width), DIM, SMALL_FONT)
    cell.paste(wall, (0, 36))
    cell.paste(tiled, (wall.width + GAP, 36))
    _text(draw, (0, 36 + wall.height + 2), _fit(caption, SMALL_FONT, cell.width), DIM, SMALL_FONT)
    return cell


def _check_blocks(blocks, vanilla, notes):
    """The facts about each block that come from plain measurement. Plants aren't surfaces, so these don't apply to them."""
    reference = vanilla.block_surfaces()
    vanilla_ores = CONTEXT["ore"][1]
    solid = [block for block in blocks if block["surface"] and block["family"] not in PLANT_FAMILIES]
    for index, block in enumerate(solid):
        label, surface, family = block["label"], block["surface"], block["family"]
        is_ore = family in ORE_FAMILIES
        lookalikes = [name for name in reference if (name in vanilla_ores) == is_ore]
        closest = min(lookalikes, key=lambda name: _distance(surface, reference[name]), default=None)
        if closest and _distance(surface, reference[closest]) < SAME_COLOUR:
            notes.append(f"{label}: average colour {_rgb(surface['mean'])} is nearly the same as vanilla {closest} "
                         f"{_rgb(reference[closest]['mean'])}. Players could mistake one for the other.")
        for other in solid[index + 1:]:
            if (other["family"] in ORE_FAMILIES) == is_ore and _distance(surface, other["surface"]) < SAME_COLOUR:
                notes.append(f"{label} and {other['label']} have nearly the same average colour, "
                             f"{_rgb(surface['mean'])} and {_rgb(other['surface']['mean'])}. Players could mistake one for the other.")
        rock = CONTEXT.get(family, CONTEXT["stone"])[0]
        if family in ROCK_FAMILIES and rock in reference and surface["saturation"] > reference[rock]["saturation"] + ROCK_SATURATION:
            notes.append(f"{label}: surface saturation {surface['saturation']:.2f}, against {reference[rock]['saturation']:.2f} "
                         f"for vanilla {rock}. Rock should stay close to grey, with any colour in flecks.")
        if family in CONTRAST_FAMILIES and "stone" in reference and surface["contrast"] > reference["stone"]["contrast"] * CONTRAST_TIMES:
            notes.append(f"{label}: surface contrast {surface['contrast']:.0f}, against {reference['stone']['contrast']:.0f} "
                         "for vanilla stone. High contrast reads as noise from a distance.")


# ---------------------------------------------------------------- items

def _item_peers(name, item):
    components = item.get("components") if isinstance(item.get("components"), dict) else {}
    stats = item.get("stats") if isinstance(item.get("stats"), dict) else {}
    if "minecraft:food" in components:
        return FOOD_PEERS
    if stats.get("slot"):
        return ARMOR_PEERS
    words = set(re.findall(r"[a-z]+", f"{name} {item.get('display', '')}".lower()))
    for kind, peers in ITEM_KINDS:
        if words & kind:
            return peers
    if stats or item.get("handheld") or "minecraft:tool" in components:
        return TOOL_PEERS
    return OTHER_PEERS


def _slot(img, x, y, canvas):
    """A vanilla inventory slot, since that's the background players judge an item against."""
    draw = ImageDraw.Draw(canvas)
    right, bottom = x + SLOT - 1, y + SLOT - 1
    draw.rectangle((x, y, right, bottom), fill=SLOT_FILL)
    draw.rectangle((x, y, right - 3, y + 2), fill=SLOT_DARK)
    draw.rectangle((x, y, x + 2, bottom - 3), fill=SLOT_DARK)
    draw.rectangle((x + 3, bottom - 2, right, bottom), fill=SLOT_LIGHT)
    draw.rectangle((right - 2, y + 3, right, bottom), fill=SLOT_LIGHT)
    canvas.alpha_composite(_big(img, SLOT - 6), (x + 3, y + 3))


def _item_cell(item, vanilla):
    peers = [(name, vanilla.get(f"item/{name}")) for name in item["peers"]]
    peers = [(name, img) for name, img in peers if img]
    panel = (1 + len(peers)) * SLOT + 16
    caption = "beside " + ", ".join(name for name, _ in peers) if peers else "no vanilla to compare"
    width = max(panel, min(220, int(max(NAME_FONT.getlength(item["label"]), SMALL_FONT.getlength(caption))) + 4))
    cell = Image.new("RGBA", (width, 18 + SLOT + 8 + 18), sheet.BG + (255,))
    draw = ImageDraw.Draw(cell)
    _text(draw, (0, 0), _fit(item["label"], NAME_FONT, width), sheet.INK, NAME_FONT)
    draw.rectangle((0, 18, panel - 1, 18 + SLOT + 7), fill=PANEL)
    _slot(item["shown"], 4, 22, cell)
    draw.rectangle((3, 21, 4 + SLOT, 22 + SLOT), outline=MARK)
    for index, (_, img) in enumerate(peers):
        _slot(img, 12 + (index + 1) * SLOT, 22, cell)
    _text(draw, (0, 18 + SLOT + 10), _fit(caption, SMALL_FONT, width), DIM, SMALL_FONT)
    return cell


# ---------------------------------------------------------------- mobs

def _mob_cell(label, model):
    views = (("front", 0), ("3/4", -35), ("side", -90), ("back", 180))  # bbmodel.preview's angles, without its animation poses
    side = 56 * 4
    cell = Image.new("RGBA", (side * len(views), 20 + side + 18), sheet.BG + (255,))
    draw = ImageDraw.Draw(cell)
    _text(draw, (0, 0), _fit(label, NAME_FONT, cell.width), sheet.INK, NAME_FONT)
    for index, (view, yaw) in enumerate(views):
        backdrop = Image.new("RGBA", (side, side), MOB_BACKDROP + (255,))
        backdrop.alpha_composite(bbmodel.render(model, yaw=yaw, scale=4))
        cell.paste(backdrop, (index * side, 20))
        _text(draw, (index * side + 4, 20 + side + 2), view, DIM, SMALL_FONT)
    return cell


def _mob_cells(mobs, folder, notes):
    cells = []
    for name, mob in mobs.items():
        label, model = _field(mob, "display", name), _field(mob, "model", name)
        path = folder / "assets" / "models" / f"{model}.bbmodel"
        if not path.exists():
            notes.append(f"{label}: model {model}.bbmodel is missing.")
            continue
        try:
            cells.append(_mob_cell(label, bbmodel.load(path)))
        except Exception as error:  # noqa: BLE001 - a half-written model can fail in many ways, and the rest should still show
            notes.append(f"{label}: {model}.bbmodel can't be drawn: {type(error).__name__}: {error}")
    return cells


# ---------------------------------------------------------------- the whole image

def _flow(cells):
    """Lays cells out in rows no wider than WIDTH."""
    rows, row, used = [], [], 0
    for cell in cells:
        if row and used + cell.width > WIDTH:
            rows.append(row)
            row, used = [], 0
        row.append(cell)
        used += cell.width + GAP * 2
    rows.append(row)
    width = max(sum(cell.width + GAP * 2 for cell in row) - GAP * 2 for row in rows)
    height = sum(max(cell.height for cell in row) + GAP * 2 for row in rows) - GAP * 2
    image = Image.new("RGBA", (width, height), sheet.BG + (255,))
    y = 0
    for row in rows:
        x = 0
        for cell in row:
            image.paste(cell, (x, y))
            x += cell.width + GAP * 2
        y += max(cell.height for cell in row) + GAP * 2
    return image


def _line(text, font, fill):
    image = Image.new("RGBA", (WIDTH, int(font.size * 1.4)), sheet.BG + (255,))
    _text(ImageDraw.Draw(image), (0, 0), _fit(text, font, WIDTH), fill, font)
    return image


def _unused_files(folder, blocks, items, mobs):
    """Only what feature.json names reaches the game, so art that nothing names is work nobody will see."""
    textures = {_field(entry, "texture", name) for name, entry in {**blocks, **items}.items()}
    for block in blocks.values():
        textures.update((block.get("faces") or {}).values())
    models = {_field(mob, "model", name) for name, mob in mobs.items()}
    models.update(block["model"] for block in blocks.values() if block.get("model"))
    unused = [path.name for path in sorted((folder / "assets" / "textures").glob("*.png")) if path.stem not in textures]
    return unused + [path.name for path in sorted((folder / "assets" / "models").glob("*.bbmodel")) if path.stem not in models]


def render(feature_folder, out, references=None):
    """Draws a feature's blocks, items, mobs and other models beside vanilla's art to `out`. Returns {"path": str, "notes": [str]}. It
    always writes an image, so a caller can read it without first checking there was anything to draw."""
    folder = pathlib.Path(feature_folder)
    notes = []
    manifest = _manifest(folder, notes)
    vanilla = _Vanilla(references)
    if not vanilla.textures:
        notes.append(f"No vanilla textures at {references}, so nothing here is compared with vanilla: walls show flat "
                     "colour and items stand alone.")

    declared_blocks, declared_items, mobs = (_entries(manifest, key) for key in ("blocks", "items", "mobs"))
    # Whatever else is alive has a model in just the same way, so it gets drawn and counted as used in the same way.
    mobs = {**mobs, **{name: entry for table in ("projectiles", "vehicles", "props") for name, entry in _entries(manifest, table).items()}}
    blocks = []
    for name, block in declared_blocks.items():
        label, family = _field(block, "display", name), _field(block, "family", "stone")
        first, info = _texture(folder, _field(block, "texture", name), label, notes)
        if (folder / "assets" / "models" / f"{name}.json").exists():
            notes.append(f"{label}: has a custom model, but this shows its texture on a flat face, not its real shape.")
        # The biome colour goes over a tinted plant in the game, which is the only way to see if it turns muddy.
        shown = _tint(first, GRASS_TINT) if first and family == "tinted_plant" else first
        blocks.append({"label": label, "family": family, "shown": shown or _missing_texture(), "info": info,
                       "surface": _surface(first) if first else None})
    _check_blocks(blocks, vanilla, notes)

    items = []
    for name, item in declared_items.items():
        label = _field(item, "display", name)
        first, _ = _texture(folder, _field(item, "texture", name), label, notes)
        items.append({"label": label, "shown": first or _missing_texture(), "peers": _item_peers(name, item)})

    unused = _unused_files(folder, declared_blocks, declared_items, mobs)
    if unused:
        notes.append("Nothing in feature.json uses these, so they never reach the game: " + ", ".join(unused))

    panels = []
    if blocks:
        panels += [_line("Blocks", NAME_FONT, sheet.INK), _flow([_block_cell(block, vanilla) for block in blocks])]
    if items:
        panels += [_line("Items at inventory scale", NAME_FONT, sheet.INK), _flow([_item_cell(item, vanilla) for item in items])]
    modelled = {name: block for name, block in declared_blocks.items() if block.get("model")}
    mob_cells = _mob_cells({**mobs, **modelled}, folder, notes)
    if mob_cells:
        panels += [_line("Mobs, model blocks and other models", NAME_FONT, sheet.INK), _flow(mob_cells)]
    title = _field(manifest, "id", folder.name)
    if panels:
        legend = (f"{title}: new art is outlined in yellow. Everything else in a wall or row of slots is vanilla, named under it "
                  "in reading order. Right of each wall, the new block tiled 3x3.")
    else:
        legend = f"{title}: nothing visual to preview."
        notes.append("Nothing visual to preview: feature.json declares no blocks, items or mobs with art.")
    panels.insert(0, _line(legend, SMALL_FONT, DIM))

    if vanilla.absent and vanilla.textures:
        notes.append("Not in the references folder, so left out: " + ", ".join(sorted(vanilla.absent)))

    image = Image.new("RGBA", (max(panel.width for panel in panels) + MARGIN * 2,
                               sum(panel.height + GAP for panel in panels) + MARGIN * 2 - GAP), sheet.BG + (255,))
    y = MARGIN
    for panel in panels:
        image.paste(panel, (MARGIN, y))
        y += panel.height + GAP
    out = pathlib.Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(out, "PNG")
    return {"path": str(out), "notes": notes}
