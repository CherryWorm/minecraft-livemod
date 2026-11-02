#!/usr/bin/env python3
"""Checks what's really on the website's /world pages against what must never be there, on the machine that has both. Nothing it looks for is ever printed,
only how many pages turned up and where, so that it can be run by anyone: what players said in private, who they are, the machine's secrets, and in the
spoiler-free pages, the names of features. It changes nothing.

Usage: PYTHONPATH=. python3 scripts/check-world-pages.py [runtime folder]
"""
import html
import json
import os
import pathlib
import re
import sys

from orchestrator import scrub

STYLE = re.compile(r"<style>.*?</style>|<link rel=\"icon\"[^>]*>", re.S)


def words_in(value):
    return [word.lower() for word in scrub._WORD.findall(value)]


def private_sources(state):
    names = set(state.get("briefs", {})) | set(state.get("interviews", {})) | set(state.get("private_chats", {})) | set(state.get("languages", {})) | set(state.get("notices", {}))
    names |= {entry.get("player") for entry in state.get("bugs", {}).values() if entry.get("player")}
    said = [json.dumps(brief, ensure_ascii=False) for brief in state.get("briefs", {}).values()]
    said += [entry.get("text", "") for chat in state.get("private_chats", {}).values() for entry in chat]
    said += [entry.get("text", "") for interview in state.get("interviews", {}).values() for entry in interview.get("transcript", [])]
    said += [entry.get("text", "") for entry in state.get("bugs", {}).values()]
    return {name for name in names if name and len(name) > 2 and name != "the server"}, scrub._phrases(said)


def main():
    runtime = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else os.environ.get("RUNTIME_DIR", "runtime"))
    pages = runtime / "world-pages"
    workspace = runtime / "agent-workspace"
    state = json.loads((workspace / "state/opening.json").read_text(encoding="utf-8"))
    names, phrases = private_sources(state)
    secrets, unread = [], 0
    for path in (runtime / "secrets").glob("*.secret"):
        try:
            secrets.append(path.read_text(encoding="utf-8", errors="replace").strip())
        except OSError:
            unread += 1  # Only root can read some of these. Run it as root to check them too.
    secrets = [secret for secret in secrets if len(secret) >= scrub.SHORTEST_SECRET]
    features = {path.parent.name for path in (workspace / "repo/mods/genesis/features").glob("*/feature.json")} | {feature["id"] for feature in [*state.get("queue", []), *state.get("in_flight", {}).values()] if feature.get("id")}
    features = {feature for feature in features if len(feature) > 3}
    named = re.compile(r"(?<![\w-])(?:" + "|".join(re.escape(name) for name in sorted(names, key=len, reverse=True)) + r")(?![\w-])", re.IGNORECASE) if names else None
    found = {"a player's name": [], "something said in private": [], "a secret": [], "a secret's shape": [], "a feature's name, on a spoiler-free page": []}
    checked = 0
    for path in pages.rglob("*.html"):
        relative = path.relative_to(pages).as_posix()
        text = html.unescape(STYLE.sub("", path.read_text(encoding="utf-8", errors="replace")))
        checked += 1
        words = words_in(text)
        if named and named.search(text):
            found["a player's name"].append(relative)
        if any(tuple(words[start:start + scrub.PHRASE_WORDS]) in phrases for start in range(len(words) - scrub.PHRASE_WORDS + 1)):
            found["something said in private"].append(relative)
        if any(secret in text for secret in secrets):
            found["a secret"].append(relative)
        if scrub._KEY_SHAPES.search(text):
            found["a secret's shape"].append(relative)
        if not relative.startswith("spoilers/"):
            lowered = (relative + " " + text).lower()
            if any(feature in lowered or feature.replace("_", " ") in lowered for feature in features):
                found["a feature's name, on a spoiler-free page"].append(relative)
    print(f"{checked} pages checked, against {len(names)} players, {len(phrases)} runs of private words, {len(secrets)} secrets ({unread} more can't be read from here) and {len(features)} features")
    for what, where in found.items():
        print(f"{len(where)} with {what}" + (": " + ", ".join(where[:5]) if where else ""))
    return 1 if any(found.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
