"""How one feature changes another. A mod is one codebase, so a builder can reach into another feature's folder, as long as it says
which ones and why, or it can add to another feature's data from its own folder, which can't collide with anything.
"""
import json
import re

FEATURE_ID = r"[a-z][a-z0-9_]{1,40}"
OWN_NAME = re.compile(r"\$(block|item|mob|sound):([a-z0-9_]+)(?![a-z0-9_/])")
CONFLICT_HUNK = re.compile(r"^<<<<<<< .*?\n(.*?)^=======\n.*?^>>>>>>> .*?\n", re.MULTILINE | re.DOTALL)
# The kinds of thing another feature can be added to. The rest of a manifest, like its node, is its own business.
ADDABLE = ("knowledge", "blocks", "items", "mobs", "ruins", "recipes", "changes_reached")
WHY = "why"
# Text that can grow a paragraph. Anything else that's text is a name, and adding to a name would only make it wrong.
GROWING_TEXT = ("text", "character")


def read_manifest(text):
    """What a feature.json says, or None if there's no telling. One waiting on a merge still says what its builder meant, in the half that's theirs."""
    for version in (text, CONFLICT_HUNK.sub(r"\1", text)):
        try:
            manifest = json.loads(version)
        except ValueError:
            continue
        return manifest if isinstance(manifest, dict) else None
    return None


def declared(text):
    """The other features a feature.json says it changes, or None if it can't be read. They come from a model and become paths, so only real names count."""
    manifest = read_manifest(text)
    if manifest is None:
        return None
    named = manifest.get("changes_features")
    return {name for name in named if re.fullmatch(FEATURE_ID, name)} if isinstance(named, dict) else set()


def _as_written_by(value, feature_id):
    """$item:name in what's added means the adder's own, wherever it ends up."""
    if isinstance(value, str):
        return OWN_NAME.sub(lambda found: f"${found.group(1)}:{feature_id}/{found.group(2)}", value)
    if isinstance(value, list):
        return [_as_written_by(item, feature_id) for item in value]
    if isinstance(value, dict):
        return {key: _as_written_by(item, feature_id) for key, item in value.items()}
    return value


def _add(manifest, path, added):
    """Adds to one place in a manifest, and only ever adds. Returns what's wrong, if anything."""
    parts = path.split(".")
    if parts[0] not in ADDABLE or (len(parts) < 3 and parts[0] != "changes_reached"):
        return f"can only add to something inside {', '.join(ADDABLE)}, like knowledge.gem_cutting.routes, so not {path}"
    place = manifest
    for part in parts[:-1]:
        if isinstance(place, list) and part.isdigit() and int(part) < len(place):
            place = place[int(part)]
        elif isinstance(place, dict) and part in place:
            place = place[part]
        else:
            return f"adds to {path}, and there's no {part} there"
    leaf = parts[-1]
    if not isinstance(place, dict):
        return f"adds to {path}, which isn't a named place"
    current = place.get(leaf)
    if current is None:
        place[leaf] = added
    elif isinstance(current, list) and isinstance(added, list):
        current.extend(added)
    elif isinstance(current, dict) and isinstance(added, dict):
        clash = sorted(set(current) & set(added))
        if clash:
            return f"adds {clash[0]} to {path}, which already has one, and adding can't replace anything"
        current.update(added)
    elif isinstance(current, str) and isinstance(added, str) and leaf in GROWING_TEXT:
        place[leaf] = f"{current}\n{added}"
    else:
        return f"adds to {path}, but only a list, an object or a page's text can be added to, and what's added has to be the same kind of thing"
    return None


def apply_additions(manifests):
    """Puts each feature's adds_to where it's going, so everything that reads a manifest afterwards sees the whole of it, the gates included.
    Returns what couldn't be added, and everything else still happens."""
    problems = []
    for feature_id in sorted(manifests):
        additions = manifests[feature_id].get("adds_to") or {}
        if not isinstance(additions, dict):
            problems.append(f"{feature_id}: adds_to has to be an object of features, like {{\"other_feature\": {{\"why\": \"...\", \"knowledge.name.routes\": [...]}}}}.")
            continue
        for target, places in additions.items():
            if target == feature_id or target not in manifests:
                problems.append(f"{feature_id}: adds to {target!r}, " + ("which is itself, so just change it." if target == feature_id else "which isn't a feature that's out."))
            elif not isinstance(places, dict):
                problems.append(f"{feature_id}: what it adds to {target} has to be an object of places, like {{\"why\": \"...\", \"knowledge.name.routes\": [...]}}.")
            else:
                for path, added in places.items():
                    problem = None if path == WHY else _add(manifests[target], path, _as_written_by(added, feature_id))
                    if problem:
                        problems.append(f"{feature_id}: {problem}, in {target}.")
    return problems
