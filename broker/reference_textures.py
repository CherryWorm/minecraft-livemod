"""Copies a short list of vanilla textures out of the game's client jar, so the agent's art preview can show
its work beside vanilla's own. Standard library only: the game's files are only read, never run."""
import pathlib
import zipfile

BLOCKS = ("stone", "deepslate", "iron_ore", "diamond_ore", "coal_ore", "copper_ore", "iron_block", "copper_block",
          "gold_block", "oak_planks", "oak_log", "dirt", "grass_block_top", "sand", "gravel", "cobblestone", "glowstone",
          "furnace_front", "oak_leaves")
ITEMS = ("iron_ingot", "gold_ingot", "diamond", "raw_iron", "iron_pickaxe", "iron_sword", "iron_helmet", "apple", "bread",
         "stick")


def extract(jar, target):
    """Writes target/block/<name>.png and target/item/<name>.png, skipping files already there. Returns the paths under
    target that were copied, were already there, and that this jar doesn't have, since a later game version may move one.
    The preview says what it lacks and carries on, so a half-downloaded jar isn't worth stopping the caller for."""
    target = pathlib.Path(target)
    wanted = [f"block/{name}.png" for name in BLOCKS] + [f"item/{name}.png" for name in ITEMS]
    todo = [path for path in wanted if not (target / path).exists()]
    result = {"copied": [], "skipped": [path for path in wanted if path not in todo], "missing": []}
    if not todo:
        return result
    try:
        archive = zipfile.ZipFile(jar)
    except zipfile.BadZipFile:
        result["missing"] = todo
        return result
    with archive:
        present = set(archive.namelist())
        for path in todo:
            member = f"assets/minecraft/textures/{path}"
            if member not in present:
                result["missing"].append(path)
                continue
            destination = target / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            # Moved into place whole, so a crash can't leave half a file that every later run would skip.
            temporary = destination.with_suffix(".tmp")
            temporary.write_bytes(archive.read(member))
            temporary.replace(destination)
            result["copied"].append(path)
    return result
