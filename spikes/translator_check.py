#!/usr/bin/env python3
"""Asks the real translator model about a small feature, and prints what it wrote and what it cost, for a person to read.
Needs the agent's container and costs a little usage. Nothing it writes goes anywhere but a temporary folder.

Usage: ./scripts/stack.sh --profile agent run --rm -T --no-deps agent python3 /spikes/translator_check.py
"""
import asyncio
import json
import pathlib
import tempfile

from orchestrator import translation, wording
from orchestrator.governor import Governor

MANIFEST = {
    "id": "ember",
    "blocks": {"ember_ore": {"display": "Ember Ore"}, "ember_block": {"display": "Block of Ember"}},
    "items": {"ember": {"display": "Raw Ember"}, "ember_pick": {"display": "Ember Pickaxe", "tooltip": ["Mines 20% faster in the dark", "Stays warm"]}, "iron_rod": {"display": "Iron Rod"}},
    "knowledge": {"on_ember": {
        "title": "On Cutting Ember",
        "text": "Three $item:ember in a crafting table make $block:ember_block.\nIt's found below Y 16 in stone, and it's easier to see at night, when $block:ember_ore gives off a faint light. "
                "Whoever first dug it up didn't live to write this down, so go carefully.",
    }},
    "texts": {
        "warm": "The block is warm.",
        "holds": "It holds %s of %s, and it could hold %s more.",
        "reorder": "%1$s was made from %2$s.",
        "coloured": "§7The kiln is §cburning§7 and it's §f%s§7 full.",
    },
    "panels": {"kiln": {"title": "Ember Kiln", "widgets": [
        {"type": "button", "id": "go", "width": 40, "text": "Light", "tooltip": "Burns one piece of coal"},
        {"type": "label", "id": "state", "text": "Cold"},
        {"type": "tabs", "id": "pages", "tabs": [{"id": "work", "text": "Work"}, {"id": "offers", "text": "Offers"}]},
    ]}},
}


async def main():
    with tempfile.TemporaryDirectory() as temporary:
        root = pathlib.Path(temporary)
        folder = root / "features" / "ember"
        folder.mkdir(parents=True)
        (folder / "feature.json").write_text(json.dumps(MANIFEST), encoding="utf-8")
        governor = Governor()
        before = governor.state.get("usage", 0)
        translator = translation.Translator(governor, root, lambda message: print(f"would commit: {message}", flush=True))
        await translator.feature(folder)
        store = wording.read_store(root, "de_de")
        print(json.dumps(store, indent=1, ensure_ascii=False), flush=True)
        wanted = {english for _, english, _, _ in wording.wanted_in(folder)}
        got = set(store[wording.NAMES]) | set(store[wording.TEXTS])
        print("not translated:", sorted(wanted - got), flush=True)
        print("usage:", round(governor.state.get("usage", 0) - before, 4), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
