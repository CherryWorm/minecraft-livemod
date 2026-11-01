#!/usr/bin/env python3
"""The Codex in Patchouli, on a real client with the mods a friend has: empty until a player knows something, filed by the
progression, opened by command, by key and at one entry, with recipes in it, and new pages arriving without a restart. Then
a client without Patchouli, which still has to get a book. Start with a world from reset-dev-world.sh and a baseline.

Usage: python3 -m broker.tests.m22_test
"""
import json
import os
import re
import shutil
import sys
import time

from broker import guide, promote, runtime
from broker.tests.m8_test import Client, PLAYER, SOURCE, SPOT, build_source, generate_land, release, slot
from broker.tests.m14_test import report, results

# What a player knows is sent at most this long after it changes.
SETTLE_SECONDS = 7
# Long enough for a client to download a new pack and reload.
RELOAD_SECONDS = 20
GEMS, SAYING, NEW_PAGE = "On Cutting Gems", "The Broken Saying", "On Bright Dust"
LONG_TEXT = ("Two measures of dust, pressed together, will make a gem if you know how to ask them. " * 4
             + "\nThe press does not care who works it. It cares about patience, and about clean hands. " * 5
             + "\nNo gem has ever been hurried. Some have been ruined by trying. " * 4).strip()
PROGRESSION = {
    "goal": "Something to test with",
    "nodes": {
        "e_lore": {"stage": "early", "name": "Rune Work", "requires": []},
        "m_more": {"stage": "mid", "name": "Deeper Runes", "requires": ["e_lore"], "opens_with": "Rune dust"},
        "x_last": {"stage": "end", "name": "The Last Rune", "requires": ["m_more"], "opens_with": "Rune gems"},
    },
}


def manifest_path():
    return SOURCE / "mods" / "genesis" / "features" / "lore" / "feature.json"


def edit_feature(change):
    manifest = json.loads(manifest_path().read_text(encoding="utf-8"))
    change(manifest)
    manifest_path().write_text(json.dumps(manifest, indent=1), encoding="utf-8")


def place_in_progression():
    (SOURCE / "bible").mkdir(exist_ok=True)
    (SOURCE / "bible" / "progression.json").write_text(json.dumps(PROGRESSION), encoding="utf-8")

    def change(manifest):
        manifest["node"] = "e_lore"
        manifest["knowledge"]["gem_cutting"]["text"] = LONG_TEXT
    edit_feature(change)


def push_content():
    """What a release does to a running server, without the build and gates before it, because Gradle's cache lock can't be shared with the client it's running."""
    content = runtime.BROKER / "testsrc-m22-content"
    promote.compile_content(SOURCE, SOURCE / "mods", content)
    shutil.copytree(runtime.HISTORY / runtime.load_state()["current"] / "content" / "modules", content / "modules")
    runtime.apply_content("prod", content)
    runtime.reload_content("prod")


def in_book(client):
    client.ask("guide")
    return json.loads(re.findall(r"\[M8\] guide: (.*)$", client.text(), re.MULTILINE)[-1])


def main():
    generate_land()
    build_source()
    place_in_progression()
    print("releasing the test feature", flush=True)
    release()
    os.environ["CLIENT_TEST_JEI"] = "1"
    os.environ["CLIENT_TEST_PATCHOULI"] = "1"
    runtime.REPORTS.mkdir(parents=True, exist_ok=True)
    # A release builds in the folder a client would otherwise run from, and Gradle only lets one of them in at a time.
    mods = runtime.BROKER / "testsrc-m22-client"
    runtime.sync_tree(runtime.WORK / "mods", mods, ".gradle/")
    client = Client(mods, runtime.REPORTS / "m22-client.log")
    try:
        client.wait(r"\[M8\] joined as [A-Za-z0-9_]+$", 420)
        report("a client with Patchouli joins a server without it", True)
        time.sleep(15)
        x, y, z = SPOT
        for command in (("gamemode", "survival", PLAYER), ("difficulty", "peaceful"), ("time", "set", "noon"), ("forceload", "add", str(x - 16), str(z - 16), str(x + 16), str(z + 16)),
                        ("fill", str(x - 6), str(y - 1), str(z - 6), str(x + 6), str(y - 1), str(z + 6), "minecraft:smooth_stone"),
                        ("fill", str(x - 6), str(y), str(z - 6), str(x + 6), str(y + 6), str(z + 6), "minecraft:air"),
                        ("tp", PLAYER, str(x), str(y), str(z), "0", "20"), ("clear", PLAYER)):
            runtime.rcon("prod", *command, check=False)

        time.sleep(SETTLE_SECONDS)
        book = in_book(client)
        report("a player who knows nothing has nothing in their book", not book["entries"] and not book["categories"], book)
        client.ask("command codex")
        client.wait(r"\[M8\] chat: .*Nothing is written here yet", 20)
        report("and the command says so", True)

        runtime.rcon("prod", "give", PLAYER, slot("rune_tablet"), "1")
        time.sleep(1)
        client.ask("use")
        client.wait(rf"\[M8\] chat: .*You've learned .*{GEMS}.*Read it", 30)
        time.sleep(SETTLE_SECONDS)
        book = in_book(client)
        report("what they've learned is in the book, without a restart", GEMS in book["entries"], book)
        report("and nothing they haven't", SAYING not in book["entries"] and len(book["entries"]) == 1, book)
        report("filed under its stage and node", "First Steps" in book["categories"] and "First Steps / Rune Work" in book["categories"], book)
        report("with no sign of stages they haven't reached", len(book["categories"]) == 2, book)

        client.ask("guideopen")
        report("the command opens it", True)
        client.ask("guidekey")
        report("so does its key", True)
        client.ask(f"guideat {guide.flag('lore/gem_cutting')}")
        screen = re.findall(r"\[M8\] screen: (\S+)", client.text())[-1]
        report("the link in chat opens it at that entry", screen == "GuiBookEntry", screen)
        pages = guide.text_pages(LONG_TEXT)
        report("long text takes several pages", len(pages) > 2, len(pages))
        for page in (0, 2, len(pages)):
            client.ask(f"guideshow {page} {GEMS}")
        report("every page of the entry can be shown, including its recipe", True)
        client.ask("guidecategory First Steps")
        client.ask("guidecategory Rune Work")
        client.ask("guideindex")
        report("so can its categories and the index", True)

        print("sending a new entry to a connected client", flush=True)
        edit_feature(lambda manifest: manifest["knowledge"].update(
            {"bright_dust": {"title": NEW_PAGE, "text": "It gets everywhere.", "routes": [{"type": "obtain", "id": "$item:rune_dust"}]}}))
        push_content()
        time.sleep(RELOAD_SECONDS)
        runtime.rcon("prod", "give", PLAYER, slot("rune_dust"), "1")
        client.wait(rf"\[M8\] chat: .*You've learned .*{NEW_PAGE}", 60)
        time.sleep(SETTLE_SECONDS)
        book = in_book(client)
        report("a page from a new release reaches a running game", NEW_PAGE in book["entries"] and GEMS in book["entries"], book)
    finally:
        client.stop()

    text = client.text()
    problems = re.findall(r".*(?:Patchouli|patchouli).*(?:ERROR|Error|Exception|Failed).*", text)
    report("Patchouli had nothing to complain about", not problems, problems[:5])
    report("every flag it was asked about had an answer", "Queried for unknown config flag: k" not in text)

    shots = mods / "companion" / "build" / "run" / "clientGameTest" / "screenshots"
    out = runtime.REPORTS / "m22"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    for path in shots.glob("*m22_*.png"):
        shutil.copy(path, out)

    print("now a client without Patchouli", flush=True)
    del os.environ["CLIENT_TEST_PATCHOULI"]
    client = Client(mods, runtime.REPORTS / "m22-plain-client.log")
    try:
        client.wait(r"\[M8\] joined as [A-Za-z0-9_]+$", 420)
        time.sleep(15)
        client.ask("codex")
        report("without Patchouli, /codex still opens a written book", "[M8] the codex opened" in client.text())
    finally:
        client.stop()

    print("screenshots:", sorted(path.name for path in out.glob("*.png")), flush=True)
    failed = results.count(False)
    print(f"{len(results) - failed} of {len(results)} checks passed", flush=True)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
