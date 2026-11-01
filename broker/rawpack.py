"""The vanilla data pack and resource pack files a feature ships in its raw/ folder: what's allowed, what each one is called in a
release, and what needs a restart.

A builder writes raw/data/gm/enchantment/ember_edge.json. Players see gm:q3f1a..., because /enchant, /give and the pack would otherwise
tell them what's coming. Nothing here reads anything but paths, so the bundler and the checks can share it.
"""
import hashlib
import pathlib
import re

FOLDER = "raw"
NAMESPACE = "gm"
# What /reload reads again, read from RegistryDataLoader.RELOADABLE_REGISTRIES and MinecraftServer.reloadResources in the 26.3 jar, along with
# tags and functions. Everything else in a data pack is read once, when the server starts. Check these again when versions.env moves.
RELOADED = {"advancement", "recipe", "loot_table", "predicate", "item_modifier", "slot_source", "context_float_provider", "context_int_provider", "function", "tags"}
# Everything a feature can add to under its own names. Each of these is a registry the game loads by itself, so it takes no engine work.
RELOADED_RAW = {"advancement", "loot_table", "predicate", "item_modifier"}
STARTUP_RAW = {"enchantment", "jukebox_song", "painting_variant", "banner_pattern", "instrument", "decorated_pot_pattern", "damage_type",
               "cat_variant", "cat_sound_variant", "chicken_variant", "chicken_sound_variant", "cow_variant", "cow_sound_variant", "frog_variant",
               "pig_variant", "pig_sound_variant", "wolf_variant", "wolf_sound_variant"}
# Why the rest aren't there, for the ones builders are most likely to try.
REFUSED_DATA = {
    "worldgen": "Raw worldgen could place any ore in any amount, past every check on how rare things are. Use \"ores\", \"plants\", \"ruins\" and \"biomes\" in feature.json.",
    "recipe": "Recipes go in \"recipes\" in feature.json, where they're balanced and say how players find them.",
    "function": "A function can run any command at all, which gets around every balance check. Do it in a server module.",
    "dialog": "A dialog can send players to a web page or run commands as them. Use a panel.",
    "villager_trade": "A trade has nothing to measure it against yet, so it could hand out anything for anything. Ask in host_requests.",
    "trade_set": "A trade has nothing to measure it against yet, so it could hand out anything for anything. Ask in host_requests.",
    "dimension": "Dimensions aren't shipped as raw files. Ask in host_requests, or see docs/content-types.md if it covers them by now.",
    "trim_material": "A trim needs lists in the game's atlases that a raw file can't add to yet. Ask in host_requests.",
    "trim_pattern": "A trim needs lists in the game's atlases that a raw file can't add to yet. Ask in host_requests.",
}
# The kinds of thing that aren't files in a registry of their own, and the token each is written with.
TAG_TOKEN = "tag"
TEXTURE_TOKEN = "texture"
EQUIPMENT_TOKEN = "equipment"
NAME_TOKEN = "name"
BIOME_TOKEN = "biome"
# Where the things in raw/ take their pictures from. For a painting or a banner, the game works out the path from a bare id, and a mob variant says its whole path.
TEXTURE_FOLDERS = {"painting", "entity/banner", "entity/shield", "entity/decorated_pot", "entity/cat", "entity/chicken", "entity/cow", "entity/frog", "entity/pig", "entity/wolf"}
EQUIPMENT_TEXTURES = "entity/equipment"
ARMOUR_LAYERS = {"humanoid", "humanoid_leggings", "humanoid_baby", "wings", "wolf_body", "horse_body", "llama_body", "pig_saddle", "strider_saddle", "camel_saddle", "camel_husk_saddle",
                 "horse_saddle", "donkey_saddle", "mule_saddle", "skeleton_horse_saddle", "zombie_horse_saddle", "happy_ghast_body", "nautilus_body", "nautilus_saddle"}
RAW_NAME = re.compile(r"q[0-9a-f]{12}")
NAME_PART = "[a-z0-9_]+(?:/[a-z0-9_]+)?"


class Refused(Exception):
    """A raw file that can't ship, worded so the agent can fix it."""


def _leaf(registry):
    return registry.rsplit("/", 1)[-1]


TOKEN_FOLDERS = {_leaf(registry): registry for registry in RELOADED_RAW | STARTUP_RAW}
TOKEN = re.compile(rf"\$({'|'.join(sorted({*TOKEN_FOLDERS, TAG_TOKEN, TEXTURE_TOKEN, EQUIPMENT_TOKEN, NAME_TOKEN, BIOME_TOKEN}))}):({NAME_PART})")


def _registry(parts):
    """Which registry a path in a data pack belongs to, from the folders under its namespace."""
    if not parts:
        return ""
    if parts[0] == "tags":
        return "/".join(parts[:3 if parts[1:2] == ("worldgen",) else 2])
    return "/".join(parts[:2]) if parts[0] == "worldgen" else parts[0]


def needs_restart(relative):
    """Whether changing this file in a data pack only takes effect when the server starts. Unknown means yes, because
    a reload that quietly changes nothing is worse than a restart. Tags reload, except worldgen's, because chunks being generated read those."""
    parts = pathlib.PurePosixPath(relative).parts
    if len(parts) < 3 or parts[0] != "data":
        return False
    registry = _registry(parts[2:-1])
    if registry.startswith("tags/worldgen"):
        return True
    return registry.split("/")[0] not in RELOADED


def startup_files(datapack):
    """A hash of what in a data pack can only be read when the server starts, to tell whether a release changes any."""
    digest = hashlib.sha256()
    if datapack.exists():
        for path in sorted(file for file in datapack.rglob("*") if file.is_file()):
            relative = path.relative_to(datapack).as_posix()
            if needs_restart(relative):
                digest.update(relative.encode())
                digest.update(path.read_bytes())
    return digest.hexdigest()


def raw_id(feature_id, name):
    """What a raw file is called in the release. It's the same whichever folder it's in, because the game looks up
    an armour's art from its name, and it never changes, because worlds and items hold on to it."""
    return "q" + hashlib.sha256(f"{feature_id}/{name}".encode()).hexdigest()[:12]


def biome_id(feature_id, name):
    """What a biome declared in feature.json is called in the release."""
    return "b" + hashlib.sha256(f"{feature_id}/{name}".encode()).hexdigest()[:10]


def resolve(match, feature_id):
    """Turns a token into the id the game will see."""
    kind, name = match.group(1), match.group(2)
    owner, _, own_name = name.rpartition("/")
    hashed = (biome_id if kind == BIOME_TOKEN else raw_id)(owner or feature_id, own_name)
    return hashed if kind == NAME_TOKEN else f"{NAMESPACE}:{hashed}"


class RawFile:
    """One file in a feature's raw/ folder, with what it's called there and in the release.

    kind is "data" or "assets". registry is the folder it belongs to. token is what refers to it, or None if nothing can.
    """

    def __init__(self, path, relative, kind, namespace, registry, name, suffix, token):
        self.path, self.relative, self.kind, self.namespace = path, relative, kind, namespace
        self.registry, self.name, self.suffix, self.token = registry, name, suffix, token

    @property
    def is_json(self):
        return self.suffix == ".json"

    @property
    def is_vanilla_tag(self):
        return self.namespace == "minecraft"

    def target(self, feature_id):
        """Where it goes in the release, as a path under the pack or data pack."""
        if self.is_vanilla_tag:
            return f"data/minecraft/{self.registry}/{self.name}.json"
        return f"{self.kind}/{NAMESPACE}/{self.registry}/{raw_id(feature_id, self.name)}{self.suffix}"


def _split(path):
    """Splits a file name from everything after its first dot, because a picture's animation is name.png.mcmeta."""
    name, dot, suffix = path.partition(".")
    return name, f"{dot}{suffix}"


def _classify_data(path, relative, parts):
    namespace, rest = parts[1], parts[2:]
    registry = _registry(rest[:-1])
    top = registry.split("/")[0]
    if namespace == NAMESPACE and registry not in RELOADED_RAW | STARTUP_RAW and not registry.startswith("tags/"):
        if top in REFUSED_DATA:
            raise Refused(f"raw/{relative}: {REFUSED_DATA[top]}")
        raise Refused(f"raw/{relative}: a feature can't add to {registry or 'that folder'} yet, so nothing would make sense of this. "
                      f"It can add to {', '.join(sorted(RELOADED_RAW | STARTUP_RAW))} and tags. Say what you wanted in host_requests.")
    if namespace == "minecraft" and not registry.startswith("tags/"):
        if top == "loot_table":
            raise Refused(f"raw/{relative} would replace vanilla's whole table. Use \"loot_additions\" in feature.json, which adds to it.")
        if top in REFUSED_DATA:
            raise Refused(f"raw/{relative}: {REFUSED_DATA[top]}")
        raise Refused(f"raw/{relative} would replace part of vanilla, and vanilla stays vanilla. Put your own under data/gm/, or add to one of vanilla's tags under data/minecraft/tags/.")
    if namespace not in (NAMESPACE, "minecraft"):
        raise Refused(f"raw/{relative} uses the namespace {namespace}. Use gm for this world's own, or minecraft for adding to vanilla's tags.")
    name, suffix = _split(parts[-1])
    if suffix != ".json":
        raise Refused(f"raw/{relative}: only .json files can go in a data pack here.")
    if namespace == "minecraft":
        depth = 2 + registry.count("/")
        return RawFile(path, relative, "data", namespace, registry, "/".join([*parts[depth + 1:-1], name]), suffix, None)
    if len(rest) - 1 != registry.count("/") + 1:
        raise Refused(f"raw/{relative} is in a folder of its own, which would show in what players see. Put it straight in data/gm/{registry}/.")
    return RawFile(path, relative, "data", namespace, registry, name, suffix, TAG_TOKEN if registry.startswith("tags/") else _leaf(registry))


def _classify_assets(path, relative, parts):
    namespace, rest = parts[1], parts[2:-1]
    if namespace != NAMESPACE:
        raise Refused(f"raw/{relative} would change vanilla's own look or sound for everyone. Put your own under assets/gm/.")
    folder = "/".join(rest)
    name, suffix = _split(parts[-1])
    if rest[:1] == ("equipment",) and len(rest) == 1 and suffix == ".json":
        return RawFile(path, relative, "assets", namespace, folder, name, suffix, EQUIPMENT_TOKEN)
    if rest[:1] == ("textures",) and suffix in (".png", ".png.mcmeta"):
        inner = "/".join(rest[1:])
        worn = inner.startswith(f"{EQUIPMENT_TEXTURES}/") and inner.split("/")[-1] in ARMOUR_LAYERS and len(rest) == 4
        if inner in TEXTURE_FOLDERS or worn:
            return RawFile(path, relative, "assets", namespace, folder, name, suffix, TEXTURE_TOKEN)
    raise Refused(f"raw/{relative}: a feature's raw art can be equipment/<name>.json, and textures in entity/equipment/<layer>, {', '.join(sorted(TEXTURE_FOLDERS))}. "
                  "Shaders, fonts and language files aren't taken: shaders have to go through \"screen_effects\", and text through \"texts\" in feature.json. "
                  "A block or item's own art goes in assets/textures/, and a block's own model in assets/models/.")


def classify(path, relative):
    """Says what a raw file is, or refuses it with the reason."""
    parts = pathlib.PurePosixPath(relative).parts
    if path.is_symlink():
        raise Refused(f"raw/{relative} is a link. What it points at would be copied into the release, so it has to be a real file.")
    if len(parts) < 3 or parts[0] not in ("data", "assets"):
        raise Refused(f"raw/{relative}: everything in raw/ goes under data/<namespace>/ or assets/<namespace>/.")
    return _classify_data(path, relative, parts) if parts[0] == "data" else _classify_assets(path, relative, parts)


def files(feature_dir):
    """Every raw file a feature has, sorted so that a release comes out the same each time."""
    root = feature_dir / FOLDER
    if not root.is_dir():
        return []
    return [classify(path, path.relative_to(root).as_posix()) for path in sorted(root.rglob("*")) if path.is_file() or path.is_symlink()]


def safe_path(relative):
    """Whether a path in the pack is a raw file, renamed to something that gives nothing away."""
    parts = pathlib.PurePosixPath(relative).parts
    if len(parts) < 4 or parts[:2] != ("assets", NAMESPACE):
        return False
    name, suffix = _split(parts[-1])
    if not RAW_NAME.fullmatch(name):
        return False
    try:
        _classify_assets(pathlib.Path(relative), relative, parts)
    except Refused:
        return False
    return suffix in (".json", ".png", ".png.mcmeta")


def texture_shape(folder):
    """What a picture's width and height must be, as a check and how to say so, or None for no rule beyond being a picture. Worn
    armour is the one that goes wrong quietly, because the game stretches anything over its model."""
    if folder.split("/")[-1] in ("humanoid", "humanoid_leggings", "humanoid_baby"):
        return lambda width, height: width >= 64 and width % 64 == 0 and height * 2 == width, "64 by 32, or a multiple of that"
    return None
