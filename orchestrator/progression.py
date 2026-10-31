"""A world's progression: a graph of what opens what, kept in bible/progression.json.

Each node is a step players can reach, and it lists the nodes that come before it. It's a graph rather than a line,
because a world with branches to choose between is more interesting. The agent writes it and the release gates hold
features to it. Plain standard library, because the agent's container and the broker on the host both use this.
"""
import json
import re

STAGES = ("early", "mid", "end")
NODE_ID = re.compile(r"[a-z][a-z0-9_]{1,40}")


def read(path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def save(path, progression):
    path.write_text(json.dumps(progression, indent=1) + "\n", encoding="utf-8")


def stage_of(progression, node):
    return progression["nodes"][node]["stage"]


def before(progression, node):
    """Every node that has to come before this one, however far back."""
    seen, waiting = set(), list(progression["nodes"].get(node, {}).get("requires", []))
    while waiting:
        current = waiting.pop()
        if current not in seen:
            seen.add(current)
            waiting += progression["nodes"].get(current, {}).get("requires", [])
    return seen


def _has_cycle(nodes):
    done, active = set(), set()

    def visit(node):
        if node in active:
            return True
        if node in done or node not in nodes:
            return False
        active.add(node)
        looped = any(visit(other) for other in nodes[node].get("requires", []))
        active.discard(node)
        done.add(node)
        return looped

    return any(visit(node) for node in nodes)


def problems(progression):
    """Returns everything wrong with a graph, so one try can fix it all."""
    nodes = progression.get("nodes") or {}
    found = []
    if not str(progression.get("goal", "")).strip():
        found.append("There's no goal: the endgame needs something for players to build towards.")
    for stage in STAGES:
        if not any(node.get("stage") == stage for node in nodes.values()):
            found.append(f"No node is in the {stage} stage. Every world needs all of {', '.join(STAGES)}.")
    for name, node in nodes.items():
        if not NODE_ID.fullmatch(name):
            found.append(f"Node {name!r} needs an id of lowercase letters, digits and underscores.")
        if node.get("stage") not in STAGES:
            found.append(f"Node {name} has stage {node.get('stage')!r}. Use one of {', '.join(STAGES)}.")
            continue
        for other in node.get("requires", []):
            if other not in nodes:
                found.append(f"Node {name} requires {other!r}, which doesn't exist.")
            elif STAGES.index(nodes[other].get("stage", "end")) > STAGES.index(node["stage"]):
                found.append(f"Node {name} is {node['stage']} but requires {other}, which is {nodes[other]['stage']}.")
    if found:
        return found
    if _has_cycle(nodes):
        return ["The graph has a loop, so some of it could never be reached."]
    for name, node in nodes.items():
        earlier = before(progression, name)
        stages = {nodes[other]["stage"] for other in earlier}
        # What a stage offers is only earned if the stage before it really stands in the way.
        if node["stage"] == "mid" and "early" not in stages:
            found.append(f"Node {name} is mid game but nothing from the early game comes before it.")
        if node["stage"] == "end" and "mid" not in stages:
            found.append(f"Node {name} is endgame but nothing from the mid game comes before it.")
        if node["stage"] != "early" and not str(node.get("opens_with", "")).strip():
            found.append(f"Node {name} doesn't say in opens_with which resource or knowledge opens it.")
    return found


def merge(progression, changes, reached_nodes):
    """Adds new nodes and reshapes ones nobody has reached. Returns the new graph and anything refused."""
    merged = json.loads(json.dumps(progression))
    refused = []
    for change in changes:
        name = change.get("id")
        if name in reached_nodes:
            refused.append(f"{name}: players have already reached it, so it stays as it is.")
            continue
        merged["nodes"][name] = {key: value for key, value in change.items() if key != "id"}
    found = problems(merged)
    return (progression, refused + found) if found else (merged, refused)


def from_direction(goal, nodes):
    return {"goal": goal, "nodes": {node["id"]: {key: value for key, value in node.items() if key != "id"} for node in nodes}}
