#!/usr/bin/env python3
"""This world's recipes in JEI, on a real client: nothing until a player knows it, each custom item told apart from the
stand-in it shares with the others, and machine recipes too. Start with a world from reset-dev-world.sh and a baseline.

Usage: python3 -m broker.tests.m19_test
"""
import json
import os
import re
import shutil
import sys
import time

from broker import runtime
from broker.tests.m8_test import Client, PLAYER, SPOT, build_source, generate_land, release, slot
from broker.tests.m14_test import report, results

# The real recipe list is sent at most this long after anything changes.
SETTLE_SECONDS = 7
GEM, TABLET, SHARD, SALT, CRUCIBLE = "Rune Gem", "Rune Tablet", "Rune Shard", "Rune Salt", "Rune Crucible"


def in_jei(client, request="jei"):
    client.ask(request)
    return json.loads(re.findall(r"\[M8\] jei: (.*)$", client.text(), re.MULTILINE)[-1])


def main():
    generate_land()
    build_source()
    print("releasing the test feature", flush=True)
    release()
    os.environ["CLIENT_TEST_JEI"] = "1"
    runtime.REPORTS.mkdir(parents=True, exist_ok=True)
    mods = runtime.WORK / "mods"
    client = Client(mods, runtime.REPORTS / "m19-client.log")
    try:
        client.wait(r"\[M8\] joined as [A-Za-z0-9_]+$", 420)
        time.sleep(15)
        x, y, z = SPOT
        for command in (("gamemode", "survival", PLAYER), ("difficulty", "peaceful"), ("time", "set", "noon"), ("forceload", "add", str(x - 16), str(z - 16), str(x + 16), str(z + 16)),
                        ("fill", str(x - 6), str(y - 1), str(z - 6), str(x + 6), str(y - 1), str(z + 6), "minecraft:smooth_stone"),
                        ("fill", str(x - 6), str(y), str(z - 6), str(x + 6), str(y + 6), str(z + 6), "minecraft:air"),
                        ("tp", PLAYER, str(x), str(y), str(z), "0", "20"), ("clear", PLAYER)):
            runtime.rcon("prod", *command, check=False)

        shown = in_jei(client)
        report("JEI is running and shows nothing the player doesn't know", not any(name in str(shown) for name in (GEM, TABLET, SHARD, SALT, CRUCIBLE)) and "isn't running" not in str(shown), shown)

        # An open recipe arrives once they've held something it uses, and a gated one doesn't.
        dust, tablet, gem = slot("rune_dust"), slot("rune_tablet"), slot("rune_gem")
        runtime.rcon("prod", "give", PLAYER, dust, "8")
        runtime.rcon("prod", "give", PLAYER, "minecraft:amethyst_shard", "1")
        time.sleep(SETTLE_SECONDS)
        shown = in_jei(client)
        report("an open recipe shows up once they've held what it uses", all(name in str(shown) for name in (TABLET, SHARD, CRUCIBLE)), shown)
        report("a recipe they haven't learned still doesn't", GEM not in str(shown), shown)
        report("nor a machine recipe they haven't worked out", SALT not in str(shown), shown)

        # Reading the tablet teaches it.
        runtime.rcon("prod", "clear", PLAYER)
        runtime.rcon("prod", "give", PLAYER, tablet, "1")
        time.sleep(1)
        client.ask("use")
        client.wait(r"\[M8\] chat: .*You've learned .*On Cutting Gems", 30)
        time.sleep(SETTLE_SECONDS)
        shown = in_jei(client)
        report("learning a recipe puts it in JEI, without a restart", GEM in str(shown), shown)

        # A machine recipe shows up once it's been made.
        crucible = slot("rune_crucible", "blocks")
        runtime.rcon("prod", "setblock", str(x), str(y), str(z + 3), crucible)
        runtime.rcon("prod", "clear", PLAYER)
        runtime.rcon("prod", "give", PLAYER, dust, "1")
        runtime.rcon("prod", "item", "replace", "entity", PLAYER, "weapon.offhand", "with", gem, "1")
        time.sleep(1)
        client.ask(f"useblock {x} {y} {z + 3}")
        client.wait(r"\[M8\] chat: The crucible made something", 20)
        time.sleep(SETTLE_SECONDS)
        shown = in_jei(client)
        report("a machine recipe shows once it's been made, and where", any(SALT in line and "Crucible" in line for line in shown), shown)

        # Asking about one item has to answer for that item, not for everything sharing its stand-in. Only proves
        # anything with several recipes known, which there are by now, and a block's item may have a different stand-in.
        for thing, name in ((gem, GEM), (crucible, CRUCIBLE)):
            runtime.rcon("prod", "clear", PLAYER)
            runtime.rcon("prod", "give", PLAYER, thing, "1")
            time.sleep(1)
            about = in_jei(client, "jeimakes")
            report(f"asking about {name} shows only what makes it", len(about) == 1 and name in about[0], about)
            client.ask("standin")

        client.ask("jeipage")
    finally:
        client.stop()

    shots = mods / "companion" / "build" / "run" / "clientGameTest" / "screenshots"
    out = runtime.REPORTS / "m19"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    for path in shots.glob("*m8_jei*.png"):
        shutil.copy(path, out)
    print("screenshots:", sorted(path.name for path in out.glob("*.png")), flush=True)
    failed = results.count(False)
    print(f"{len(results) - failed} of {len(results)} checks passed", flush=True)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
