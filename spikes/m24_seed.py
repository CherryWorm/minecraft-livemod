#!/usr/bin/env python3
"""Sets up a world whose direction is already chosen, without spending anything on choosing one, with one feature in it that has a
real bug, for m24_test. Runs in the agent's container."""
import json
import pathlib
import shutil

from orchestrator import main, progression, workshop

INCOMING = pathlib.Path("/workspace/incoming_feature")


def node(name, stage, requires):
    return {"id": name, "stage": stage, "name": name.replace("_", " ").title(), "requires": requires, "opens_with": "what comes before it", "holds": "things for this stage"}


workshop.setup_repo()
main.BIBLE.mkdir(parents=True, exist_ok=True)
(main.BIBLE / "theme.md").write_text("A quiet world of old stone and small comforts, in muted greys and warm browns.", encoding="utf-8")
(main.BIBLE / "persona.md").write_text("Warden, the patient caretaker of this world, who speaks in short, friendly sentences.", encoding="utf-8")
(main.BIBLE / "persona_name.txt").write_text("Warden", encoding="utf-8")
(main.BIBLE / "discovery.md").write_text("Most recipes are open, and appear in the recipe book when you hold what they use.", encoding="utf-8")
(main.BIBLE / "discovery.json").write_text(json.dumps({"scope": "shared"}), encoding="utf-8")
(main.BIBLE / "stages.yaml").write_text(main.STAGES_TEMPLATE, encoding="utf-8")
graph = progression.from_direction("Build the Great Hearth.", [node("first_comforts", "early", []), node("workshop", "mid", ["first_comforts"]), node("great_hearth", "end", ["workshop"])])
assert not progression.problems(graph), progression.problems(graph)
progression.save(main.PROGRESSION, graph)
target = main.FEATURES / "tonic"
if target.exists():
    shutil.rmtree(target)
shutil.copytree(INCOMING, target)
workshop.commit_all("The direction for this world, and something in it")

main.STATE.mkdir(parents=True, exist_ok=True)
main.OPENING.write_text(json.dumps({
    "direction_chosen": True, "border_open": True, "release_count": 1, "intent_count": 0,
    "briefs": {"Dana": {"wants": "cosy building", "theme_ideas": "", "mods_enjoyed": [], "dislikes": "", "notes": ""}}}), encoding="utf-8")
print("seeded", flush=True)
