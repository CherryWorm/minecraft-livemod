#!/usr/bin/env python3
"""Runs on the host and answers the agent's requests. The agent has no Docker access, so this is the only
way anything it writes reaches a server, and every request goes through the same gates.

The agent's repository only supplies features and design documents. Everything else, including the code
that polices it, comes from this trusted checkout, so the agent can't change the rules it's checked by.

Usage: python3 -m broker.daemon
"""
import json
import shutil
import subprocess
import sys
import time

from broker import runtime

WORKSPACE = runtime.RUNTIME / "agent-workspace"
REQUESTS = WORKSPACE / "requests"
RESPONSES = WORKSPACE / "responses"
AGENT_REPO = WORKSPACE / "repo"
ASSEMBLED = runtime.BROKER / "assembled"
REPORTS_FOR_AGENT = WORKSPACE / "reports"
CACHE_JAR = "/cache/gradle/caches/fabric-loom/26.3/minecraft-client.jar"


def assemble(commit):
    """Trusted code plus the agent's features and documents, as they were at one commit."""
    runtime.sync_tree(runtime.REPO, ASSEMBLED, ".env", "build/", ".gradle/", "run/", "runtime/")
    features = ASSEMBLED / "mods" / "genesis" / "features"
    if features.exists():
        shutil.rmtree(features)
    features.mkdir(parents=True)
    archive = subprocess.run(
        ["git", "-c", "safe.directory=*", "-C", str(AGENT_REPO), "archive", commit, "mods/genesis/features", "bible"],
        capture_output=True, check=False,
    )
    if archive.returncode != 0:
        # An early commit may have no features yet, which git archive reports as an error for that path.
        archive = subprocess.run(["git", "-c", "safe.directory=*", "-C", str(AGENT_REPO), "archive", commit],
                                 capture_output=True, check=True)
    subprocess.run(["tar", "-x", "-C", str(ASSEMBLED), "mods/genesis/features", "bible"], input=archive.stdout, check=False)
    return ASSEMBLED


def promote(commit, release_id, *flags):
    source = assemble(commit)
    subprocess.run(
        [sys.executable, "-m", "broker.promote", "--source", str(source), "--release-id", release_id, *flags],
        cwd=runtime.REPO, stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False, timeout=1200,
    )
    report = json.loads((runtime.BROKER / "last.json").read_text(encoding="utf-8"))
    # Screenshots go where the agent can read them.
    copied = []
    for path in report.get("screenshots", []):
        target = REPORTS_FOR_AGENT / release_id
        target.mkdir(parents=True, exist_ok=True)
        shutil.copy(path, target)
        copied.append(f"/workspace/reports/{release_id}/{path.rsplit('/', 1)[-1]}")
    report["screenshots"] = copied
    return report


def javap(class_name):
    if not all(part.replace("$", "").isidentifier() for part in class_name.split(".")):
        return {"reason": "That isn't a class name."}
    result = runtime.run(
        ["./scripts/stack.sh", "run", "--rm", "-T", "builder", "bash", "-c",
         f"CP=$(find /cache/gradle/caches/modules-2/files-2.1/net.fabricmc.fabric-api -name '*.jar' | tr '\\n' ':'); "
         f"javap -public -cp \"{CACHE_JAR}:$CP\" '{class_name}'"],
        check=False, timeout=60,
    )
    lines = [line for line in result.stdout.splitlines() if "Container " not in line]
    return {"output": "\n".join(lines)[:12000]}


def handle(request):
    kind = request["kind"]
    if runtime.AGENT_DISABLED.exists() and kind != "javap":
        return {"result": "blocked", "gate": "control", "reason": "The kill switch is on."}
    release_id = request.get("release_id", f"check-{request['id']}")
    if kind == "check":
        return promote(request["commit"], release_id, "--check-only")
    if kind == "gates":
        return promote(request["commit"], release_id, "--no-deploy")
    if kind == "release":
        return promote(request["commit"], release_id)
    if kind == "javap":
        return javap(request["class_name"])
    return {"result": "blocked", "gate": "broker", "reason": f"Unknown request {kind}"}


def main():
    for folder in (REQUESTS, RESPONSES, REPORTS_FOR_AGENT):
        folder.mkdir(parents=True, exist_ok=True)
    print("broker waiting for requests", flush=True)
    while True:
        # One at a time, oldest first: there's one shadow server, and releases must not overlap.
        pending = sorted(REQUESTS.glob("*.json"), key=lambda path: path.stat().st_mtime)
        if not pending:
            time.sleep(0.5)
            continue
        path = pending[0]
        request = json.loads(path.read_text(encoding="utf-8"))
        started = time.monotonic()
        try:
            answer = handle(request)
        except Exception as error:  # noqa: BLE001 - the agent should hear about any failure, not hang
            answer = {"result": "blocked", "gate": "broker", "reason": f"{type(error).__name__}: {error}"}
        print(f"{request['kind']} {request['id']}: {answer.get('result', 'answered')} "
              f"in {time.monotonic() - started:.1f}s", flush=True)
        temporary = RESPONSES / f".{request['id']}.tmp"
        temporary.write_text(json.dumps(answer), encoding="utf-8")
        temporary.rename(RESPONSES / f"{request['id']}.json")
        path.unlink()


if __name__ == "__main__":
    main()
