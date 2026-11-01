#!/usr/bin/env python3
"""The world in a player's own language, on a real client: names, tooltips, the Codex, a panel and what modules say, in German, and all
of it unchanged in English, on one client changing language the way a player would. Then a client without Patchouli, which gets a written
book, and a plain chest in place of a panel. The translations are the fixture's, so no model's involved. Screenshots go in reports/language.
Start with a world from reset-dev-world.sh and a baseline, and reset it afterwards.

Usage: python3 -m broker.tests.language_test
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

from broker import deploy, runtime
from broker.tests.m8_test import Client, PLAYER, SPOT
from broker.tests.m14_test import report, results

SOURCE = runtime.BROKER / "testsrc-language"
FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "german"
SIZE = 16
SETTLE_SECONDS = 7
RAW_KEY = re.compile(r"(item|block|entity|text|tooltip|knowledge|conduit|companion)\.(gm\.|[a-z_]+)")
PROGRESSION = {"goal": "Something to test with", "nodes": {
    "e_first": {"stage": "early", "name": "First Step", "requires": []},
    "m_more": {"stage": "mid", "name": "Later On", "requires": ["e_first"], "opens_with": "Ember"},
    "x_last": {"stage": "end", "name": "The Very End", "requires": ["m_more"], "opens_with": "Glow"},
}}
PANEL = "german/ember_desk"


def build_source():
    runtime.sync_tree(runtime.REPO, SOURCE, ".env", "build/", ".gradle/", "run/")
    target = SOURCE / "mods" / "genesis" / "features" / "german"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(FIXTURE, target)
    (target / "de_de.json").unlink()
    textures = target / "assets" / "textures"
    textures.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (SIZE, SIZE), (0xCC, 0x55, 0x22, 255)).save(textures / "ember_token.png")
    Image.new("RGBA", (SIZE, SIZE), (0x88, 0x33, 0x22, 255)).save(textures / "ember_brick.png")
    bible = SOURCE / "bible"
    (bible / "lang").mkdir(parents=True, exist_ok=True)
    (bible / "progression.json").write_text(json.dumps(PROGRESSION), encoding="utf-8")
    shutil.copy(FIXTURE / "de_de.json", bible / "lang" / "de_de.json")


def release():
    result = subprocess.run(
        [sys.executable, "-m", "broker.promote", "--source", str(SOURCE), "--release-id", f"language-{int(time.time())}"],
        cwd=runtime.REPO, stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False, timeout=1800,
    )
    promoted = json.loads((runtime.BROKER / "last.json").read_text(encoding="utf-8"))
    print(json.dumps({key: promoted.get(key) for key in ("result", "gate", "tier", "stages")}), flush=True)
    if result.returncode != 0:
        print(promoted.get("reason"), result.stderr[-2000:], flush=True)
        sys.exit(1)


def slot(name, table="items"):
    ledger = json.loads((runtime.HISTORY / runtime.load_state()["current"] / "registry-ledger.json").read_text(encoding="utf-8"))
    return "gm:" + ledger[table][f"german/{name}"]["slot"]


def rcon(*command):
    return runtime.rcon("prod", *map(str, command), check=False)


def holding(item):
    rcon("clear", PLAYER)
    rcon("item", "replace", "entity", PLAYER, "hotbar.0", "with", item, 1)
    time.sleep(1)


def last(client, pattern):
    found = re.findall(pattern, client.text(), re.MULTILINE)
    return found[-1] if found else ""


def heard_since(client, start):
    return re.findall(r"\[M8\] chat: (.*)$", client.text()[start:], re.MULTILINE)


def said_by(client, item):
    """What using an item said in chat."""
    holding(slot(item))
    start = len(client.text())
    client.ask("use")
    time.sleep(1)
    return heard_since(client, start)


def held(client, item):
    holding(slot(item))
    client.ask("held")
    return last(client, r"\[M8\] holding (.*)$")


def set_language(client, code):
    client.ask(f"language {code}")
    time.sleep(2)
    client.ask("whatlanguage")
    return last(client, r"\[M8\] language (.*)$")


def learned(client, words):
    """Holding something is what teaches it, so it's been said by the time anything's looked at it."""
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        lines = [line for line in re.findall(r"\[M8\] chat: (.*)$", client.text(), re.MULTILINE) if words in line]
        if lines:
            return lines[-1]
        time.sleep(0.5)
    return ""


def release_notice(client):
    """What everyone's told just before a release, which comes from the broker rather than the game."""
    start = len(client.text())
    deploy.tell_players(deploy.RELOADING, "a test")
    time.sleep(2)
    return heard_since(client, start)


def book(client):
    client.ask("guide")
    return json.loads(last(client, r"\[M8\] guide: (.*)$"))


def keep_screenshots(shots, out):
    """A client starting again clears the folder, so what each one took has to be copied out before the next."""
    out.mkdir(parents=True, exist_ok=True)
    for path in shots.glob("*.png"):
        shutil.copy(path, out)


def check_english(client):
    # What the last run left it set to is still in its options.
    report("the client starts in English", set_language(client, "en_us") == "en_us")
    tooltip = held(client, "ember_token")
    report("English: an item keeps its name", "Ember Token" in tooltip, tooltip)
    report("English: and its tooltip", "Warm to the touch" in tooltip and "Burns 50% hotter" in tooltip, tooltip)
    tooltip = held(client, "plain_thing")
    report("English: nothing shows a raw key", not RAW_KEY.search(tooltip), tooltip)
    said = said_by(client, "ember_reader")
    report("English: a module says what was written", any("The token is warm in your hand." in line for line in said), said)
    report("English: with values filled in", any("You hold 3 of Ember Token." in line for line in said), said)
    line = learned(client, "On Embers")
    report("English: learning something says so", "You've learned" in line and "[Read it]" in line, line)
    notice = release_notice(client)
    report("English: so does a release", any("Reloading the world for a moment. What's changing: a test." in said for said in notice), notice)
    time.sleep(SETTLE_SECONDS)
    found = book(client)
    report("English: the book's page has its name", "On Embers" in found["entries"], found)
    report("English: and its categories", any("First Steps" in name for name in found["categories"]), found)
    client.ask("guideopen")
    client.ask("guideshow 0 On Embers")
    rcon("conduit", "panel", PLAYER, PANEL)
    time.sleep(1)
    client.ask("title")
    report("English: a panel keeps its title", "Ember Desk" in last(client, r"\[M8\] title (.*)$"), last(client, r"\[M8\] title (.*)$"))
    client.ask("shot english_panel")
    client.ask("closemenu")
    holding(slot("ember_token"))
    client.ask("inventory")
    client.ask("hoverhotbar 0")
    client.ask("shot english_tooltip")
    client.ask("close")
    client.ask("shot english_hud")


def check_german(client):
    # With nothing new learned, so this can only be down to the language changing.
    time.sleep(2)
    found = book(client)
    report("German: the book changes language with the game", "Von der Glut" in found["entries"] and "On Embers" not in found["entries"], found)
    tooltip = held(client, "ember_token")
    report("German: an item has its German name", "Glutmarke" in tooltip and "Ember Token" not in tooltip, tooltip)
    report("German: and its tooltip", "hlt sich warm an" in tooltip and "Brennt 50%" in tooltip, tooltip)
    report("German: a line nobody translated falls back to English", "Nobody has translated this line" in tooltip, tooltip)
    tooltip = held(client, "plain_thing")
    report("German: so does a name nobody translated, and never a raw key", "Plain Thing" in tooltip and not RAW_KEY.search(tooltip), tooltip)
    tooltip = held(client, "glow_stone")
    report("German: a name can have an umlaut in it", re.search(r"Gl.+hstein", tooltip) is not None, tooltip)
    said = said_by(client, "ember_reader")
    report("German: a module's text is in German", any("Die Marke liegt warm in der Hand." in line for line in said), said)
    report("German: with values filled in, in German too", any(re.search(r"Du h.+ltst 3 von Glutmarke\.", line) for line in said), said)
    report("German: text nobody translated stays in English", any("Nobody has translated this sentence." in line for line in said), said)
    report("German: a translation that lost a code isn't used", any("This one lost 3 in translation." in line for line in said), said)
    line = learned(client, "Vom Leuchten")
    report("German: learning something says so in German", "gelernt" in line and "[Lesen]" in line, line)
    notice = release_notice(client)
    report("German: so does a release", any("Die Welt" in said and "a test" in said for said in notice), notice)
    time.sleep(SETTLE_SECONDS)
    found = book(client)
    report("German: the book's pages have German names", {"Von der Glut", "Vom Leuchten"} <= set(found["entries"]), found)
    report("German: and its categories", any("Erste Schritte" in name for name in found["categories"]) and any("Erster Abschnitt" in name for name in found["categories"]), found)
    client.ask("guideopen")
    client.ask("guidecategory Erste Schritte")
    client.ask("guideshow 0 Von der Glut")
    client.ask("guideindex")
    rcon("conduit", "panel", PLAYER, PANEL)
    time.sleep(1)
    client.ask("title")
    report("German: a panel has a German title", "Glutpult" in last(client, r"\[M8\] title (.*)$"), last(client, r"\[M8\] title (.*)$"))
    client.ask("shot german_panel")
    client.ask("closemenu")
    holding(slot("ember_opener"))
    client.ask("use")
    time.sleep(1)
    client.ask("title")
    client.ask("shot german_panel_driven")
    client.ask("closemenu")
    holding(slot("ember_token"))
    client.ask("inventory")
    client.ask("hoverhotbar 0")
    client.ask("shot german_tooltip")
    client.ask("close")
    client.ask("shot german_hud")


def check_no_companion_features(client):
    """A client without Patchouli gets a written book, and one without panels a plain chest."""
    client.ask("language de_de")
    time.sleep(2)
    holding(slot("ember_token"))
    client.ask("command codex")
    time.sleep(2)
    client.ask("bookpage")
    page = last(client, r"\[M8\] book page (.*)$")
    report("written book: it's in German", "Von der Glut" in page and "Glutmarke" in page, page)
    client.ask("shot german_written_book")
    client.ask("close")
    holding(slot("ember_book"))
    client.ask("use")
    time.sleep(1)
    client.ask("bookpage")
    page = last(client, r"\[M8\] book page (.*)$")
    report("a module's book is in German", "Die erste Seite der Notizen." in page, page)
    client.ask("close")
    client.ask("nopanels")
    time.sleep(3)
    rcon("conduit", "panel", PLAYER, PANEL)
    time.sleep(1)
    client.ask("menunames")
    names = last(client, r"\[M8\] menu names (.*)$")
    report("a plain chest says the same in German", "Anz" in names and "Arbeit" in names and "Angebote" in names, names)
    client.ask("shot german_plain_chest")
    client.ask("closemenu")


def main():
    build_source()
    print("releasing the test feature", flush=True)
    release()
    runtime.REPORTS.mkdir(parents=True, exist_ok=True)
    mods = runtime.WORK / "mods"
    shots = mods / "companion" / "build" / "run" / "clientGameTest" / "screenshots"
    if shots.exists():
        shutil.rmtree(shots)
    os.environ["CLIENT_TEST_PATCHOULI"] = "1"
    os.environ["COMPANION_ALLOW_UNSIGNED"] = "true"
    client = Client(mods, runtime.REPORTS / "language-client.log")
    try:
        client.wait(r"\[M8\] joined as [A-Za-z0-9_]+$", 420)
        time.sleep(15)
        x, y, z = SPOT
        rcon("gamemode", "creative", PLAYER)
        rcon("tp", PLAYER, x, y + 5, z, 0, 0)
        time.sleep(3)
        for command in (("difficulty", "peaceful"), ("time", "set", "noon"), ("fill", x - 4, y - 1, z - 4, x + 4, y + 3, z + 4, "minecraft:air"),
                        ("fill", x - 4, y - 1, z - 4, x + 4, y - 1, z + 4, "minecraft:smooth_stone")):
            rcon(*command)
        rcon("tp", PLAYER, x, y, z, 0, 0)
        time.sleep(1)
        check_english(client)
        report("the client changes language", set_language(client, "de_de") == "de_de")
        check_german(client)
        report("and back again", set_language(client, "en_us") == "en_us")
        tooltip = held(client, "ember_token")
        report("English again: nothing stuck", "Ember Token" in tooltip and "Warm to the touch" in tooltip, tooltip)
    finally:
        client.stop()
    out = runtime.REPORTS / "language"
    if out.exists():
        shutil.rmtree(out)
    keep_screenshots(shots, out)

    del os.environ["CLIENT_TEST_PATCHOULI"]
    time.sleep(10)
    client = Client(mods, runtime.REPORTS / "language-client-plain.log")
    try:
        client.wait(r"\[M8\] joined as [A-Za-z0-9_]+$", 420)
        time.sleep(10)
        check_no_companion_features(client)
    finally:
        client.stop()

    keep_screenshots(shots, out)
    print(f"screenshots in {out}", flush=True)
    failed = results.count(False)
    print(f"{len(results) - failed} of {len(results)} checks passed", flush=True)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
