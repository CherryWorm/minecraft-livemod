#!/usr/bin/env python3
"""Writes seccomp.json: Docker's default rules plus only what bubblewrap needs to make namespaces.

The agent container needs bubblewrap so that credential scrubbing works, and Docker's defaults block it.
Turning seccomp off would drop the whole layer, so this keeps every other restriction.
"""
import json
import pathlib
import urllib.request

SOURCE = "https://raw.githubusercontent.com/moby/profiles/main/seccomp/default.json"
ALLOWED = ["clone", "mount", "pivot_root", "setns", "umount2", "unshare"]


def main():
    with urllib.request.urlopen(SOURCE, timeout=30) as response:
        profile = json.load(response)
    profile["syscalls"].append({"names": ALLOWED, "action": "SCMP_ACT_ALLOW"})
    path = pathlib.Path(__file__).with_name("seccomp.json")
    path.write_text(json.dumps(profile, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {path}: {len(profile['syscalls'])} rules, default action {profile['defaultAction']}")


if __name__ == "__main__":
    main()
