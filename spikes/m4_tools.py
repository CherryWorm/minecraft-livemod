#!/usr/bin/env python3
"""Part of M4, for what chatting with test players doesn't reach: the tuner acting on feedback through the agent's own
path, a real builder making a mid-game machine, and another modelling a creature from nothing.

Run inside the agent's container, after M4 has shipped something: python3 /spikes/m4_tools.py
"""
import asyncio
import json
import pathlib
import sys

from orchestrator import llm, main, progression, research, workshop

SPEC = ("A machine from this world's mid game that does some simple automated work for players. They load materials into it by using "
        "them on it, and it slowly makes something out of them that's useful in this world. Use the theme for what it is and how it "
        "reacts. Its recipe needs a material from the step right before this node, which world_index will show you. Declare what it "
        "automates. Keep it to one machine and what it makes.")


CREATURE_SPEC = ("One creature from this world's early game, harmless and easy to come across, that's unmistakably its own thing and "
                 "suits the theme. Give it a model made for it and a material players get from it. Keep this feature to the creature and what it drops.")


def released():
    for path in sorted(main.FEATURES.glob("*/feature.json")):
        yield path.parent.name, json.loads(path.read_text(encoding="utf-8"))


def something_to_tune():
    """Something players could plausibly call too rare, so there's a number for the tuner to change."""
    for _, manifest in released():
        for block, definition in manifest.get("blocks", {}).items():
            if definition.get("drops") and any(ore.get("block") == block for ore in manifest.get("ores", [])):
                return definition["display"]
    return None


def mid_game_node():
    """A mid-game step with something already built right before it, so a builder has something to make it from. Early in a
    world there may not be one yet, so this grows the graph the way the director would."""
    graph = progression.read(main.PROGRESSION)
    built = {manifest.get("node") for _, manifest in released()}
    for name, node in graph["nodes"].items():
        if node["stage"] == "mid" and set(node.get("requires", [])) & built:
            return name
    early = next((name for name in built if name in graph["nodes"]), None)
    if early is None:
        return None
    merged, refused = progression.merge(graph, [{"id": "test_workshop", "stage": "mid", "name": "A first workshop", "requires": [early],
                                                 "opens_with": "what the step before it makes", "holds": "A first machine"}], set())
    if refused:
        print(f"couldn't grow the graph: {refused}")
        return None
    progression.save(main.PROGRESSION, merged)
    workshop.commit_all("A mid-game step to test with")
    return "test_workshop"


async def on_released(feature_id, tree):
    print(f"released {feature_id}", flush=True)


async def check():
    failures = []
    governor = main.Governor()
    web = research.Research(governor)
    shop = workshop.Workshop(governor, on_released, web)

    target = something_to_tune()
    if target is None:
        print("nothing with an ore has shipped, so the tuner has nothing to work on")
    else:
        intent = llm.untrusted("intent", json.dumps({"number": 1, "wants": f"Everyone's saying {target} is way too rare. We've found hardly any of it."}))
        result = await llm.ask(governor, "director_quick", intent, schema=main.SORTER_SCHEMA, allowed_tools=main.SORTER_TOOLS,
                               mcp_servers={"world": shop.world_server(can_tune=True)}, max_turns=10)
        log = pathlib.Path("/workspace/state/tunes.jsonl")
        tunes = log.read_text(encoding="utf-8").strip().splitlines() if log.exists() else []
        print(f"tuner: handled={result.structured} seconds={result.seconds} estimate={result.estimate:.4f}\n  tunes: {tunes}")
        if not tunes:
            failures.append(f"the tuner should have made {target} more common, but it said: {result.text[:300]}")

    node = mid_game_node()
    early = next((name for name, entry in progression.read(main.PROGRESSION)["nodes"].items() if entry["stage"] == "early"), None)
    if node is None or early is None:
        failures.append("there's nowhere in the graph to try these features")
    else:
        # Side by side, like real features, so that they have to take turns releasing.
        print(f"building a mid-game machine in {node} and a creature in {early}", flush=True)
        machine, creature = await asyncio.gather(shop.build("mid_machine_check", SPEC, node, "mid"), shop.build("creature_check", CREATURE_SPEC, early, "early"))
        if not machine:
            failures.append("a builder should have been able to ship a mid-game machine")
        if not creature:
            failures.append("a builder should have been able to ship a creature modelled for itself")

    for failure in failures:
        print("FAIL:", failure)
    print("PASS" if not failures else "FAILED")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(check()))
