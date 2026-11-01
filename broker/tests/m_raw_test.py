#!/usr/bin/env python3
"""The vanilla files a feature ships in raw/, through real releases and on a real client: an advancement earned in play, an enchantment
offered at a real table that really hits harder, loot added to a vanilla table, tags, a real climb up a ladder, armour with its own look,
a music disc in a jukebox, a painting, and a biome by its token. Bad files are refused in seconds, and the tier each change needs is checked by
really releasing it. Start with a world from reset-dev-world.sh and a baseline, and reset it afterwards.

Usage: python3 -m broker.tests.m_raw_test
"""
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time

from PIL import Image

from broker import bundles, rawpack, runtime
from broker.tests.m8_test import Client, PLAYER, SPOT
from broker.tests.m14_test import report, results
from broker.tests.m16_test import make_sound

SOURCE = runtime.BROKER / "testsrc-mraw"
FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "rawkit"
FEATURE = "rawkit"
RED = (0xEE, 0x33, 0x22)
GREEN = (0x22, 0xEE, 0x44)
BLUE = (0x22, 0x44, 0xEE)
SLOT_SIZE = 16
# Long enough to get to the wall and well up it, and not to the top. What it's held to is what vanilla's ladder does in the same time.
CLIMB_TICKS = 50
CLIMB_MATCHES_WITHIN = 0.6
SAME_PLACE = 0.2
LADDER_HEIGHT = 12
INSTANT_SECONDS = 30
LOOT_ROLLS = 30
# In the enchanting table's menu: the item, the lapis, 27 of inventory, then the hotbar.
TABLE_HOTBAR = 29


def feature_folder():
    return SOURCE / "mods" / "genesis" / "features" / FEATURE


def manifest_path():
    return feature_folder() / "feature.json"


def raw_path(relative):
    return feature_folder() / "raw" / relative


def build_source():
    runtime.sync_tree(runtime.REPO, SOURCE, ".env", "build/", ".gradle/", "run/")
    target = feature_folder()
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(FIXTURE, target)
    textures = target / "assets" / "textures"
    textures.mkdir(parents=True, exist_ok=True)
    for name, colour in (("kit_token", (0x77, 0x55, 0x33, 255)), ("kit_stone", (0x66, 0x66, 0x70, 255)), ("kit_vine", (0x33, 0x88, 0x33, 255))):
        Image.new("RGBA", (SLOT_SIZE, SLOT_SIZE), colour).save(textures / f"{name}.png")
    # Rungs with gaps between, because a ladder you can see through is what shows it's drawn as a ladder.
    rung = Image.new("RGBA", (SLOT_SIZE, SLOT_SIZE), (0, 0, 0, 0))
    rung.paste((0x99, 0x66, 0x22, 255), (2, 0, 4, SLOT_SIZE))
    rung.paste((0x99, 0x66, 0x22, 255), (12, 0, 14, SLOT_SIZE))
    for y in (2, 7, 12):
        rung.paste((0x99, 0x66, 0x22, 255), (2, y, 14, y + 2))
    rung.save(textures / "kit_rung.png")
    make_sound(target / "assets" / "sounds" / "kit_song.ogg")
    for layer in ("humanoid", "humanoid_leggings"):
        path = raw_path(f"assets/gm/textures/entity/equipment/{layer}/kit_plate.png")
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGBA", (64, 32), (*GREEN, 255)).save(path)
    painting = raw_path("assets/gm/textures/painting/kit_view.png")
    painting.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (32, 32), (*RED, 255)).save(painting)
    cow = raw_path("assets/gm/textures/entity/cow/kit_cow.png")
    cow.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (64, 64), (*BLUE, 255)).save(cow)
    for folder in ("banner", "shield"):
        mark = raw_path(f"assets/gm/textures/entity/{folder}/kit_mark.png")
        mark.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGBA", (64, 64), (0, 0, 0, 0)).save(mark)


def promote(*flags, release=None):
    started = time.monotonic()
    result = subprocess.run(
        [sys.executable, "-m", "broker.promote", "--source", str(SOURCE), "--release-id", release or f"mraw-{int(time.time())}", *flags],
        cwd=runtime.REPO, stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False, timeout=1800,
    )
    promoted = json.loads((runtime.BROKER / "last.json").read_text(encoding="utf-8"))
    print(json.dumps({key: promoted.get(key) for key in ("result", "gate", "tier", "stages")}), flush=True)
    return result.returncode, promoted, time.monotonic() - started


def check_refused_at_once():
    """Each of these would otherwise take a boot to find out about, or stop one altogether, or get past the balance rules."""
    def with_file(relative, contents):
        path = raw_path(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(contents) if not isinstance(contents, str) else contents, encoding="utf-8")
        return path

    enchantment = json.loads(raw_path("data/gm/enchantment/kit_edge.json").read_text(encoding="utf-8"))
    original = json.dumps(enchantment)
    bad = [
        ("an enchantment with a field missing", lambda: with_file("data/gm/enchantment/kit_edge.json", {key: value for key, value in enchantment.items() if key != "max_cost"}), "missing max_cost",
         lambda: with_file("data/gm/enchantment/kit_edge.json", original)),
        ("an enchantment that runs a command", lambda: with_file("data/gm/enchantment/kit_edge.json", {**enchantment, "effects": {"minecraft:post_attack": [{"enchanted": "attacker", "affected": "attacker", "effect": {"type": "minecraft:run_command", "command": "op Player0"}}]}}), "run_command",
         lambda: with_file("data/gm/enchantment/kit_edge.json", original)),
        ("an enchantment far stronger than vanilla's", lambda: with_file("data/gm/enchantment/kit_edge.json", {**enchantment, "effects": {"minecraft:damage": [{"effect": {"type": "minecraft:add", "value": 1000}}]}}), "over vanilla's best",
         lambda: with_file("data/gm/enchantment/kit_edge.json", original)),
        ("a function", lambda: with_file("data/gm/function/give_all.mcfunction", "give @a diamond 64"), "any command", lambda: raw_path("data/gm/function/give_all.mcfunction").unlink()),
        ("a recipe that isn't in feature.json", lambda: with_file("data/gm/recipe/free.json", {"type": "minecraft:crafting_shapeless"}), "feature.json", lambda: raw_path("data/gm/recipe/free.json").unlink()),
        ("climbing on a block that can't", lambda: with_file("data/minecraft/tags/block/climbable.json", {"values": ["$block:kit_stone"]}), "ladder family", lambda: raw_path("data/minecraft/tags/block/climbable.json").unlink()),
        ("a tag making something into a diamond", lambda: with_file("data/minecraft/tags/item/diamond_tool_materials.json", {"values": ["$item:kit_token"]}), "vanilla costs", lambda: raw_path("data/minecraft/tags/item/diamond_tool_materials.json").unlink()),
    ]
    for name, spoil, mention, restore in bad:
        spoil()
        code, promoted, seconds = promote("--lint-only")
        restore()
        report(f"{name} is refused at the instant check", code == 2 and promoted.get("gate") == "static" and mention in str(promoted.get("reason")), f"{seconds:.0f}s {str(promoted.get('reason'))[:200]}")
        report("and in seconds", seconds < INSTANT_SECONDS, f"{seconds:.0f}s")
    manifest = manifest_path().read_text(encoding="utf-8")
    manifest_path().write_text(manifest.replace('"$biome:kit_meadow", "minecraft:plains"', '"$biome:kit_meadow", "minecraft:not_a_biome"'), encoding="utf-8")
    code, promoted, seconds = promote("--lint-only")
    manifest_path().write_text(manifest, encoding="utf-8")
    report("a plant in a biome that doesn't exist is refused at the instant check", code == 2 and "isn't a biome" in str(promoted.get("reason")), f"{seconds:.0f}s {str(promoted.get('reason'))[:200]}")
    code, promoted, seconds = promote("--lint-only")
    report("and with all that put back, it passes", code == 0 and promoted.get("result") == "passed_lint", f"{seconds:.0f}s {str(promoted.get('reason'))[:400]}")


def slot(name, table="items"):
    ledger = json.loads((runtime.HISTORY / runtime.load_state()["current"] / "registry-ledger.json").read_text(encoding="utf-8"))
    return "gm:" + ledger[table][f"{FEATURE}/{name}"]["slot"]


def own(name):
    return f"gm:{rawpack.raw_id(FEATURE, name)}"


def rcon(*command):
    return runtime.rcon("prod", *map(str, command), check=False)


def holding(*items):
    rcon("clear", PLAYER)
    for place, (item, count) in enumerate(items):
        rcon("item", "replace", "entity", PLAYER, f"hotbar.{place}", "with", item, count)
    time.sleep(1)


def last(client, pattern):
    found = re.findall(pattern, client.text(), re.MULTILINE)
    return found[-1] if found else None


def platform(x, y, z, wall=False):
    for command in (("fill", x - 5, y - 1, z - 5, x + 5, y + 14, z + 8, "minecraft:air"),
                    ("fill", x - 5, y - 1, z - 5, x + 5, y - 1, z + 8, "minecraft:smooth_stone")):
        rcon(*command)
    if wall:
        rcon("fill", x - 5, y, z + 2, x + 5, y + 14, z + 2, "minecraft:stone")


def climb_from(client, x, y, z, ticks=CLIMB_TICKS):
    rcon("tp", PLAYER, x + 0.5, y, z + 0.5, 0, 0)
    time.sleep(1.5)
    client.ask(f"climb {ticks}")
    found = last(client, r"\[M8\] climbed from (\S+) (\S+) (\S+) climbing (\w+) .* to (\S+) (\S+) (\S+) climbing (\w+) ")
    return float(found[5]) - float(found[1]), found[7]


def check_climbing(client, x, y, z):
    rung, vine = slot("kit_rung", "blocks"), slot("kit_vine", "blocks")
    platform(x, y, z, wall=True)
    rcon("gamemode", "survival", PLAYER)
    rcon("effect", "give", PLAYER, "minecraft:resistance", 600, 5, "true")
    for height in range(0, LADDER_HEIGHT):
        rcon("setblock", x, y + height, z + 1, f"{rung}[facing=north]")
        rcon("setblock", x - 3, y + height, z + 1, "minecraft:ladder[facing=north]")
    time.sleep(1)
    client.ask(f"blockat {x} {y} {z + 1}")
    seen = last(client, r"\[M8\] the client sees (.*)$")
    report("a ladder block is vines to a client, which is what makes it climb", "vines" in str(seen), seen)
    vanilla, _ = climb_from(client, x - 3, y, z)
    time.sleep(3)
    gained, climbing = climb_from(client, x, y, z)
    report("a player really climbs it, as fast as vanilla's", vanilla > 1 and abs(gained - vanilla) < CLIMB_MATCHES_WITHIN, f"{gained:.2f} blocks up in {CLIMB_TICKS} ticks, and {vanilla:.2f} on vanilla's")
    report("and it still counts as climbing partway up", climbing == "true", climbing)
    # Holding sneak stops someone sliding back down a ladder, which gives both sides time to say where they are.
    client.ask("sneak")
    climb_from(client, x, y, z)
    time.sleep(1)
    client.ask("position")
    where = last(client, r"\[M8\] position (\S+) (\S+) (\S+) climbing")
    answer = rcon("data", "get", "entity", PLAYER, "Pos")
    server_y = float(re.findall(r"(-?\d+\.\d+)d", answer)[1])
    report("holding sneak keeps them there, as on vanilla's", float(where[1]) > y + 1, where[1])
    report("and the server agrees where they are, so it won't throw them off", abs(server_y - float(where[1])) < SAME_PLACE, f"client {where[1]} server {server_y}")
    client.ask("unsneak")
    time.sleep(1)
    client.ask("position")
    falling = last(client, r"\[M8\] position (\S+) (\S+) (\S+) climbing")
    report("letting go slides them down instead of dropping them", float(falling[1]) < float(where[1]), f"{where[1]} to {falling[1]}")
    rcon("tp", PLAYER, x + 0.5, y, z - 2.5, 0, -10)
    client.ask("shot ladder")

    # Polymer takes vines' states for this family, and the real plant has to go on looking like itself.
    rcon("setblock", x + 2, y, z + 1, "minecraft:twisting_vines[age=7]")
    time.sleep(1)
    client.ask(f"blockat {x + 2} {y} {z + 1}")
    real = last(client, r"\[M8\] the client sees (.*)$")
    report("real vines aren't taken for one", real == "Block{minecraft:twisting_vines}[age=0]", real)
    rcon("setblock", x + 2, y, z + 1, "minecraft:air")

    # Is it the block's family that does it? The same tag on anything else, slipped in behind the checks, because they'd refuse it.
    pack = runtime.RUNTIME / "prod" / "world" / "datapacks" / "mraw_control" / "data" / "minecraft" / "tags" / "block"
    pack.mkdir(parents=True, exist_ok=True)
    (pack / "climbable.json").write_text(json.dumps({"values": [vine]}), encoding="utf-8")
    (pack.parents[3] / "pack.mcmeta").write_text(json.dumps({"pack": {"description": "test", "min_format": runtime.data_format(), "max_format": runtime.data_format()}}), encoding="utf-8")
    rcon("reload")
    time.sleep(2)
    rcon("datapack", "enable", '"file/mraw_control"')
    time.sleep(2)
    for height in range(0, LADDER_HEIGHT):
        rcon("setblock", x + 3, y + height, z + 1, vine)
    time.sleep(1)
    tagged = rcon("execute", "if", "block", x + 3, y, z + 1, "#minecraft:climbable")
    report("a plant block really is tagged climbable on the server", "passed" in tagged, tagged)
    client.ask(f"blockat {x + 3} {y} {z + 1}")
    gained, climbing = climb_from(client, x + 3, y, z)
    report("and to a client it's no such thing, so a tag alone can't do it", gained < 0.5 and climbing == "false", f"{gained:.2f} blocks up, climbing {climbing}")
    rcon("datapack", "disable", '"file/mraw_control"')
    shutil.rmtree(pack.parents[3])
    rcon("reload")
    time.sleep(2)

    # Placed the way a player places one: clicking the side of a wall.
    rcon("fill", x - 1, y, z + 1, x - 1, y + 3, z + 1, "minecraft:air")
    rcon("tp", PLAYER, x - 0.5, y, z - 0.5, 0, 20)
    holding((rung, 4))
    client.ask(f"useon {x - 1} {y + 1} {z + 2} north")
    time.sleep(1)
    placed = rcon("execute", "if", "block", x - 1, y + 1, z + 1, f"{rung}[facing=north]")
    report("clicking a wall with one puts it on that wall", "passed" in placed, placed)
    rcon("setblock", x - 1, y + 1, z + 2, "minecraft:air")
    time.sleep(1)
    gone = rcon("execute", "if", "block", x - 1, y + 1, z + 1, "minecraft:air")
    report("and with the wall gone, it goes", "passed" in gone, gone)
    rcon("effect", "clear", PLAYER)


def check_armour(client, x, y, z, shots):
    plate = slot("kit_plate")
    platform(x, y, z)
    rcon("gamemode", "survival", PLAYER)
    holding((plate, 1))
    client.ask("worn")
    worn = last(client, r"\[M8\] worn as (.*)$")
    report("a client is told what an item is worn as", worn == f"chest {own('kit_plate')}", worn)
    client.ask("use")
    time.sleep(1)
    answer = rcon("data", "get", "entity", PLAYER, "equipment.chest")
    report("using it puts it on, as with vanilla's", plate in answer, answer)
    # From in front, on something that can't move: the way any other player would see someone wearing it.
    rcon("tp", PLAYER, x + 0.5, y, z + 0.5, 0, 10)
    rcon("kill", "@e[type=armor_stand]")
    rcon("summon", "minecraft:armor_stand", x + 0.5, y, z + 3.5, '{NoGravity:1b,Rotation:[180f,0f],equipment:{chest:{id:"%s",count:1}}}' % plate)
    client.ask("shot armour")
    rcon("kill", "@e[type=armor_stand]")
    picture = sorted(shots.glob("*m8_armour.png"))
    green = 0
    if picture:
        with Image.open(picture[-1]) as image:
            green = sum(1 for r, g, b in image.convert("RGB").getdata() if g > 120 and g > r * 2 and g > b * 2)
    report("and it's drawn in its own art, not vanilla's", green > 500, f"{green} pixels of the armour's green")


def check_enchantment(client, x, y, z):
    blade, edge = slot("kit_blade"), own("kit_edge")
    client.ask("registry minecraft:enchantment")
    known = last(client, r"\[M8\] registry minecraft:enchantment has (.*)$")
    report("a client knows the enchantment, by a name that gives nothing away", edge in str(known), known)
    platform(x, y, z)
    table = (x + 2, y, z)
    rcon("setblock", *table, "minecraft:enchanting_table")
    rcon("tp", PLAYER, x + 0.5, y, z + 0.5, 90, 20)
    rcon("experience", "add", PLAYER, 30, "levels")
    holding((blade, 1), ("minecraft:lapis_lazuli", 8))
    client.ask(f"useblock {table[0]} {table[1]} {table[2]}")
    time.sleep(1)
    client.ask(f"click {TABLE_HOTBAR} shift")
    client.ask(f"click {TABLE_HOTBAR + 1} shift")
    time.sleep(1)
    client.ask("enchantoffer")
    offer = last(client, r"\[M8\] the table offers (.*)$")
    report("a real table offers it for an item of this world", edge in str(offer), offer)
    client.ask("menubutton 0")
    time.sleep(1)
    client.ask("click 0 shift")
    client.ask("closemenu")
    time.sleep(1)
    answer = rcon("data", "get", "entity", PLAYER, "Inventory")
    report("choosing it enchants the item", edge in answer, answer)
    # A shift-click out of the menu fills the hotbar from its far end.
    rcon("item", "replace", "entity", PLAYER, "hotbar.0", "from", "entity", PLAYER, "hotbar.8")
    time.sleep(1)
    client.ask("held")
    held = last(client, r"\[M8\] holding (.*)$")
    report("and the tooltip says so, in the words from the file", "Kit Edge" in str(held), held)

    # Whether it does what it says: the same hit with and without it.
    def hit(enchanted):
        rcon("kill", "@e[type=pig]")
        rcon("tp", PLAYER, x + 0.5, y, z + 0.5, 0, 40)
        holding((blade, 1))
        if enchanted:
            rcon("enchant", PLAYER, edge, 3)
        rcon("summon", "minecraft:pig", x + 0.5, y, z + 2.0, "{NoAI:1b,Health:10f}")
        time.sleep(2)
        client.ask("mine 2")
        time.sleep(1)
        answer = rcon("data", "get", "entity", "@e[type=pig,limit=1,sort=nearest]", "Health")
        found = re.search(r"(-?\d+(?:\.\d+)?)f", answer)
        return 10 - float(found.group(1)) if found else None

    plain, sharp = hit(False), hit(True)
    rcon("kill", "@e[type=pig]")
    report("a hit with it really does more, by what the file says", plain is not None and sharp is not None and abs(sharp - plain - 2.0) < 0.01, f"{plain} without, {sharp} at level 3")

    # And from loot, on a book.
    rcon("clear", PLAYER)
    answer = rcon("loot", "give", PLAYER, "loot", own("kit_book"))
    time.sleep(1)
    client.ask("held")
    held = last(client, r"\[M8\] holding (.*)$")
    report("a loot table can hand it out", "Kit Edge" in str(held), f"{answer} {held}")


def check_loot(client):
    token = slot("kit_token")
    rcon("clear", PLAYER)
    for _ in range(LOOT_ROLLS):
        rcon("loot", "give", PLAYER, "loot", "minecraft:chests/simple_dungeon")
    found = rcon("clear", PLAYER, token, 0)
    report("a vanilla loot table now gives what was added to it", re.search(r"Found ([1-9]\d*)", found), found)
    everything = rcon("data", "get", "entity", PLAYER, "Inventory")
    vanilla = set(re.findall(r'minecraft:[a-z_]+', everything))
    report("and everything it gave before", len(vanilla) >= 3, sorted(vanilla)[:8])
    rcon("clear", PLAYER)


def check_advancements(client):
    token, gift = slot("kit_token"), slot("kit_gift")
    client.ask("advancements")
    found = last(client, r"\[M8\] advancements: (.*)$")
    report("a client is told about the advancements", own("kit_root") in str(found) and "Kit Beginnings" in str(found), found)
    report("what's one step on shows, under a name that gives nothing away", own("kit_got_token") in str(found) and "kit_got" not in str(found), found)
    report("its icon is this world's item, not the stand-in", token.split(":")[1] in str(found), found)
    rcon("clear", PLAYER)
    rcon("experience", "set", PLAYER, 0, "points")
    rcon("give", PLAYER, token)
    announced = client.wait(r"\[M8\] chat: .*Kit Collector", 30)
    report("holding the item earns it, and it's announced in the words from the file", bool(announced), announced.group(0) if announced else "")
    client.ask("advancements")
    found = last(client, r"\[M8\] advancements: (.*)$")
    report("the client knows it's done", f"{own('kit_got_token')}=Kit Collector" in str(found) and "|true" in str(found), found)
    answer = rcon("clear", PLAYER, gift, 0)
    report("and its reward was handed out, from a loot table of its own", re.search(r"Found 1", answer), answer)
    client.ask("advancementscreen advancements")


def check_tags():
    token, stone = slot("kit_token"), slot("kit_stone", "blocks")
    x, y, z = SPOT
    holding((token, 1))
    answer = rcon("execute", "if", "items", "entity", PLAYER, "weapon.mainhand", "#minecraft:piglin_loved")
    report("an item is in a vanilla tag", "passed" in answer, answer)
    holding(("minecraft:stick", 1))
    answer = rcon("execute", "if", "items", "entity", PLAYER, "weapon.mainhand", "#minecraft:piglin_loved")
    report("and nothing else was added", "failed" in answer, answer)
    holding(("minecraft:gold_ingot", 1))
    answer = rcon("execute", "if", "items", "entity", PLAYER, "weapon.mainhand", "#minecraft:piglin_loved")
    report("and what was there still is", "passed" in answer, answer)
    rcon("setblock", x, y + 5, z, stone)
    answer = rcon("execute", "if", "block", x, y + 5, z, "#minecraft:dampens_vibrations")
    report("a block is in a vanilla tag", "passed" in answer, answer)
    rcon("setblock", x, y + 5, z, "minecraft:air")


def check_disc(client, x, y, z):
    disc = slot("kit_disc")
    sound = f"gm:{bundles._sound_id(FEATURE, 'kit_song')}"
    platform(x, y, z)
    client.ask("registry minecraft:jukebox_song")
    known = last(client, r"\[M8\] registry minecraft:jukebox_song has (.*)$")
    report("a client knows the song", own("kit_song") in str(known), known)
    client.ask(f"soundknown {sound}")
    report("and the pack has its sound", last(client, rf"\[M8\] the pack (.*) {re.escape(sound)}$") == "has", last(client, rf"\[M8\] the pack (.*) {re.escape(sound)}$"))
    rcon("setblock", x + 2, y, z, "minecraft:jukebox")
    rcon("tp", PLAYER, x + 0.5, y, z + 0.5, 90, 20)
    holding((disc, 1))
    client.ask("held")
    held = last(client, r"\[M8\] holding (.*)$")
    report("a disc's tooltip names its song", "Kit Song, by nobody" in str(held), held)
    client.ask(f"useblock {x + 2} {y} {z}")
    time.sleep(1)
    answer = rcon("execute", "if", "block", x + 2, y, z, "minecraft:jukebox[has_record=true]")
    report("a jukebox takes it", "passed" in answer, answer)
    played = client.wait(rf"\[M8\] sound: {re.escape(sound)}", 15)
    report("and the player's game starts playing it", bool(played), played.group(0) if played else "")
    rcon("setblock", x + 2, y, z, "minecraft:air")


def check_painting(client, x, y, z, shots):
    client.ask("registry minecraft:painting_variant")
    known = last(client, r"\[M8\] registry minecraft:painting_variant has (.*)$")
    report("a client knows the painting", own("kit_view") in str(known), known)
    platform(x, y, z)
    rcon("fill", x - 3, y, z + 4, x + 3, y + 5, z + 4, "minecraft:stone")
    rcon("kill", "@e[type=painting]")
    answer = rcon("summon", "minecraft:painting", x, y + 1, z + 3, '{variant:"%s",facing:2b}' % own("kit_view"))
    rcon("tp", PLAYER, x + 0.5, y, z - 1.5, 0, -5)
    client.ask("shot painting")
    picture = sorted(shots.glob("*m8_painting.png"))
    red = 0
    if picture:
        with Image.open(picture[-1]) as image:
            red = sum(1 for r, g, b in image.convert("RGB").getdata() if r > 120 and r > g * 2 and r > b * 2)
    report("it's drawn on the wall in its own art", red > 500, f"{red} red pixels, {answer}")
    rcon("kill", "@e[type=painting]")
    rcon("summon", "minecraft:cow", x + 0.5, y, z + 1.5, '{NoAI:1b,variant:"%s"}' % own("kit_cow"))
    client.ask("shot cow")
    rcon("kill", "@e[type=cow]")
    picture = sorted(shots.glob("*m8_cow.png"))
    blue = 0
    if picture:
        with Image.open(picture[-1]) as image:
            blue = sum(1 for r, g, b in image.convert("RGB").getdata() if b > 120 and b > r * 2 and b > g * 1.5)
    report("a mob variant is drawn in its own art", blue > 500, f"{blue} blue pixels")
    for registry, name in (("minecraft:damage_type", "kit_scald"), ("minecraft:banner_pattern", "kit_mark"), ("minecraft:cow_variant", "kit_cow")):
        client.ask(f"registry {registry}")
        known = last(client, rf"\[M8\] registry {registry} has (.*)$")
        report(f"a client knows {registry}", own(name) in str(known), known)
    rcon("kill", "@e[type=painting]")


def check_biome_token():
    ledger_patch = json.loads((runtime.RUNTIME / "prod" / "config" / "conduit" / "surface_patches.json").read_text(encoding="utf-8"))
    biome_patch = json.loads((runtime.RUNTIME / "prod" / "config" / "conduit" / "biome_patches.json").read_text(encoding="utf-8"))
    ours = biome_patch[0]["to"]
    report("a plant's $biome: token comes out as the biome's real name", any(ours in plant.get("biomes", []) for plant in ledger_patch), ours)
    x, y, z = SPOT
    # Wide enough, because the game blurs the edges of biomes when it's asked what biome a spot is in.
    filled = rcon("fillbiome", x - 8, y - 8, z - 8, x + 8, y + 8, z + 8, ours)
    answer = rcon("execute", "if", "biome", x, y, z, ours)
    report("and that biome exists in the game", "passed" in answer, f"{filled} {answer}")


def check_tiers():
    """What each kind of change really needs, by releasing it. A restart shows as the server's start time changing. The test client has gone by now,
    because a release builds with Gradle and the two would fight over its files, so something that can't leave holds the item for the tag to look at."""
    def started():
        return runtime.inspect_state("prod")["StartedAt"]

    x, y, z = SPOT
    rcon("summon", "minecraft:armor_stand", x, y + 2, z, '{NoGravity:1b,Tags:["mraw"],equipment:{mainhand:{id:"minecraft:stick",count:1}}}')
    in_tag = ("execute", "if", "items", "entity", "@e[tag=mraw,limit=1]", "weapon.mainhand", "#minecraft:piglin_loved")
    answer = rcon(*in_tag)
    report("before a release, it isn't in the tag", "failed" in answer, answer)
    before = started()
    tag = raw_path("data/minecraft/tags/item/piglin_loved.json")
    tag.write_text(json.dumps({"values": ["$item:kit_token", "minecraft:stick"]}), encoding="utf-8")
    manifest = json.loads(manifest_path().read_text(encoding="utf-8"))
    manifest["loot_additions"][0]["pools"][0]["rolls"] = 2
    manifest_path().write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    code, promoted, _ = promote()
    report("a change to a tag and to added loot only needs a reload", code == 0 and promoted.get("tier") == "T1", f"{promoted.get('tier')} {str(promoted.get('reason'))[:300]}")
    report("and the server didn't restart", started() == before, started())
    time.sleep(5)
    answer = rcon(*in_tag)
    report("and it took effect", "passed" in answer, answer)

    advancement = raw_path("data/gm/advancement/kit_got_token.json")
    data = json.loads(advancement.read_text(encoding="utf-8"))
    data["rewards"]["experience"] = 9
    advancement.write_text(json.dumps(data), encoding="utf-8")
    code, promoted, _ = promote()
    report("nor does a change to an advancement", code == 0 and promoted.get("tier") == "T1", f"{promoted.get('tier')} {str(promoted.get('reason'))[:300]}")
    report("and the server didn't restart", started() == before, started())

    # This one stops short of going out, because the test server is enough to see what it needs.
    enchantment = raw_path("data/gm/enchantment/kit_edge.json")
    data = json.loads(enchantment.read_text(encoding="utf-8"))
    data["weight"] = 9
    enchantment.write_text(json.dumps(data), encoding="utf-8")
    code, promoted, _ = promote("--no-deploy")
    report("a change to an enchantment needs a restart", promoted.get("tier") == "T3", f"{promoted.get('tier')} {promoted.get('result')} {str(promoted.get('reason'))[:300]}")
    data["weight"] = 10
    enchantment.write_text(json.dumps(data), encoding="utf-8")


def check_bad_file_stops_at_the_test_server():
    """Something the instant checks can't see, because only the game's own parser knows: it has to stop on the test server, and never reach the live one."""
    before = runtime.inspect_state("prod")["StartedAt"]
    current = runtime.load_state()["current"]
    enchantment = raw_path("data/gm/enchantment/kit_edge.json")
    data = json.loads(enchantment.read_text(encoding="utf-8"))
    original = json.dumps(data)
    data["slots"] = ["elbow"]
    enchantment.write_text(json.dumps(data), encoding="utf-8")
    code, promoted, _ = promote()
    enchantment.write_text(original, encoding="utf-8")
    report("what only the game can tell is wrong stops at the test server", code == 2 and promoted.get("gate") in ("shadow", "static"), f"{promoted.get('gate')} {str(promoted.get('reason'))[:400]}")
    report("and the live server never saw it", runtime.inspect_state("prod")["StartedAt"] == before and runtime.load_state()["current"] == current, runtime.load_state()["current"])


def main():
    build_source()
    check_refused_at_once()
    print("releasing the test feature", flush=True)
    code, promoted, _ = promote()
    if code != 0:
        print(promoted.get("reason"), flush=True)
        sys.exit(1)

    runtime.REPORTS.mkdir(parents=True, exist_ok=True)
    mods = runtime.WORK / "mods"
    shots = mods / "companion" / "build" / "run" / "clientGameTest" / "screenshots"
    if shots.exists():
        shutil.rmtree(shots)
    client = Client(mods, runtime.REPORTS / "mraw-client.log")
    try:
        client.wait(r"\[M8\] joined as [A-Za-z0-9_]+$", 420)
        time.sleep(15)
        x, y, z = SPOT
        # Creative until there's a floor, because the fall from up here can kill a player waiting for the chunks to load.
        rcon("gamemode", "creative", PLAYER)
        rcon("tp", PLAYER, x, y + 5, z, 0, 0)
        time.sleep(3)
        for command in (("difficulty", "peaceful"), ("time", "set", "noon"), ("gamerule", "doDaylightCycle", "false"), ("forceload", "add", x - 40, z - 40, x + 80, z + 40)):
            rcon(*command)
        platform(x, y, z)
        rcon("tp", PLAYER, x, y, z, 0, 0)
        time.sleep(1)
        check_biome_token()
        check_advancements(client)
        check_tags()
        check_loot(client)
        check_climbing(client, x + 20, y, z)
        check_armour(client, x + 40, y, z, shots)
        check_enchantment(client, x + 60, y, z)
        check_disc(client, x, y, z + 20)
        check_painting(client, x + 20, y, z + 20, shots)
    finally:
        client.stop()

    out = runtime.REPORTS / "mraw"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    for path in shots.glob("*m8_*.png"):
        shutil.copy(path, out)
    check_tiers()
    if os.environ.get("MRAW_BAD_FILE", "1") == "1":
        check_bad_file_stops_at_the_test_server()
    failed = results.count(False)
    print(f"{len(results) - failed} of {len(results)} checks passed", flush=True)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
