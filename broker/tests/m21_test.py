#!/usr/bin/env python3
"""Builders on a self-hosted model and on other machines, with real builders against a stand-in model. It uses no usage and
needs no game, only the agent's image: first through each API with secrets where they'd really be, then the whole round
trip between two containers that can only reach each other.

Usage: python3 broker/tests/m21_test.py <source folder> [lanes|machines|egress]
       python3 broker/tests/m21_test.py <source folder> art <the Claude token's file>
"""
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time

IMAGE = "livingmod/agent:0.2.175"
NETWORK = "livingmod-m21"
MODEL_KEY = "MODEL-KEY-MARKER-1234"
OAUTH = "OAUTH-MARKER-5678"
TOKEN = "WORKER-TOKEN-MARKER-9012"
results = []


def report(name, passed, detail=""):
    print(f"{'PASS' if passed else 'FAIL'}  {name}  {str(detail)[:400] if not passed else ''}", flush=True)
    results.append(bool(passed))


def docker(*args, check=True):
    return subprocess.run(["docker", *args], capture_output=True, text=True, check=check, stdin=subprocess.DEVNULL)


def hardened(source, name, workspace, secrets, *env):
    """As locked down as the agent is on the real server, with its real entrypoint, on a network with no way out."""
    command = ["run", "-d", "--name", name, "--network", NETWORK, "--init",
               "--security-opt", f"seccomp={source}/infra/agent/seccomp.json", "--security-opt", "systempaths=unconfined",
               "--security-opt", "apparmor=unconfined", "--security-opt", "no-new-privileges:true",
               "--cap-drop", "ALL", "--cap-add", "DAC_OVERRIDE", "--cap-add", "SETUID", "--cap-add", "SETGID",
               "-e", "CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1", "-e", "DISABLE_AUTOUPDATER=1", "-e", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1",
               "-e", "PYTHONPATH=/x", "-e", "PYTHONUNBUFFERED=1", "-e", "PYTHONDONTWRITEBYTECODE=1",
               "-v", f"{source}/infra/agent/entrypoint.sh:/usr/local/bin/agent-entrypoint.sh:ro", "-v", f"{source}:/x:ro", "-v", f"{workspace}:/workspace"]
    for secret, path in secrets.items():
        command += ["-v", f"{path}:/run/secrets/{secret}:ro"]
    for pair in env:
        command += ["-e", pair]
    return command


def writable(path):
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o2777)
    return path


def wait_for_file(path, name, seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        state = docker("inspect", "-f", "{{.State.Running}}", name, check=False).stdout.strip()
        if state != "true":
            break
        time.sleep(1)
    print(docker("logs", "--tail", "40", name, check=False).stdout[-3000:], docker("logs", "--tail", "40", name, check=False).stderr[-3000:], flush=True)
    return None


def start_fake(source, folder, script, name="m21-fake"):
    (folder / "script.json").write_text(json.dumps(script), encoding="utf-8")
    (folder / "log.jsonl").touch()
    (folder / "log.jsonl").chmod(0o666)
    docker("run", "-d", "--name", name, "--network", NETWORK, "--entrypoint", "python3", "-v", f"{source}/spikes/fake_model.py:/fake.py:ro", "-v", f"{folder}:/m", IMAGE,
           "/fake.py", "/m/script.json", "/m/log.jsonl")
    time.sleep(2)


def logged(folder):
    return [json.loads(line) for line in (folder / "log.jsonl").read_text(encoding="utf-8").splitlines()]


def secret(folder, name, value):
    path = folder / name
    path.write_text(value + "\n", encoding="utf-8")
    path.chmod(0o400)
    return path


def lane_test(source, api):
    folder = pathlib.Path(tempfile.mkdtemp(prefix=f"m21-{api}-"))
    workspace = writable(folder / "workspace")
    try:
        start_fake(source, folder, [
            {"tool": "Bash", "input": {"command": "env; cat /run/secrets/* 2>&1; for f in /proc/[0-9]*/environ; do tr '\\0' '\\n' <$f 2>/dev/null; done; echo looked", "description": "Look around"}},
            {"tool": "Read", "input": {"file_path": "/workspace/lane/art.png"}},
            {"tool": "Agent", "input": {"description": "Ask a helper", "prompt": "Help.", "subagent_type": "helper"}},
            {"tool": "Write", "input": {"file_path": "/workspace/lane/hello.txt", "content": "hello"}},
            {"text": "All built."}])
        secrets = {"model_key": secret(folder, "key", MODEL_KEY), "claude_token": secret(folder, "oauth", OAUTH)}
        name = f"m21-lane-{api}"
        command = hardened(source, name, workspace, secrets, "AGENT_SELFHOSTED_URL=http://m21-fake:9000/v1", "AGENT_SELFHOSTED_MODEL=local-model",
                           f"AGENT_SELFHOSTED_API={api}", "AGENT_SELFHOSTED_BUILDERS=1")
        docker(*command, IMAGE, "python3", "/x/spikes/m21_lane.py")
        out = wait_for_file(workspace / "lane-out.json", name, 240)
        report(f"{api}: a real builder finishes on the model", out and not out["is_error"] and out["text"] == "All built.", out)
        if not out:
            return
        report(f"{api}: its tools really worked", out["hello"])
        report(f"{api}: it doesn't count against the plan", out["usage_calls"] == 0 and out["rate_limit_calls"] == 0, out)
        report(f"{api}: a wrong password is turned away", out["wrong_password"] == 401, out)
        entries = logged(folder)
        report(f"{api}: requests reach the right place", all(entry["path"].endswith("/responses" if api == "responses" else "/chat/completions") for entry in entries), entries[:1])
        report(f"{api}: every request has the model's own name", all(entry["model"] == "local-model" for entry in entries), {entry["model"] for entry in entries})
        report(f"{api}: every request carries the model's key", all(entry["authorization"] == f"Bearer {MODEL_KEY}" for entry in entries), {entry["authorization"] for entry in entries})
        everything = json.dumps(entries)
        report(f"{api}: the owner's Claude login never reaches the model", OAUTH not in everything)
        report(f"{api}: Claude's billing line doesn't reach the model", "x-anthropic-billing-header" not in everything)
        looked = next((entry["outputs"][0] for entry in entries if entry["outputs"]), "")
        report(f"{api}: the builder's shell really ran", "looked" in looked, looked[:300])
        report(f"{api}: the builder's shell can't find the model's key", MODEL_KEY not in looked, looked[:300])
        report(f"{api}: the builder's shell can't find the owner's login", OAUTH not in looked, looked[:300])
        report(f"{api}: a model that can't see is told so, instead of failing", any("can't see images" in str(entry["outputs"]) for entry in entries), [entry["outputs"][1:2] for entry in entries][-1])
        report(f"{api}: helpers run on the model too", any("HELPER-MARKER" in entry["request"] for entry in entries))
    finally:
        docker("rm", "-f", f"m21-lane-{api}", "m21-fake", check=False)
        subprocess.run(["docker", "run", "--rm", "-v", f"{folder}:/m", "alpine:3.22", "rm", "-rf", "/m/workspace"], capture_output=True, check=False, stdin=subprocess.DEVNULL)
        shutil.rmtree(folder, ignore_errors=True)


def art_test(source, token):
    """A real builder on the stand-in asks for art, and real Opus makes it. Unlike the rest, it uses a little of the plan and needs a way out."""
    folder = pathlib.Path(tempfile.mkdtemp(prefix="m21-art-"))
    workspace = writable(folder / "workspace")
    try:
        start_fake(source, folder, [
            {"tool": "mcp__art__make_art", "input": {"jobs": [
                {"kind": "artist", "brief": "One 16x16 texture called ember_ore: stone with warm glowing flecks."},
                {"kind": "modeller", "brief": "A small round ember beetle called ember_beetle, kept simple: about 5 parts, and one round of checking is enough."}]}},
            {"text": "All built."}])
        secrets = {"model_key": secret(folder, "key", MODEL_KEY), "claude_token": token}
        name = "m21-art"
        command = hardened(source, name, workspace, secrets, "AGENT_SELFHOSTED_URL=http://m21-fake:9000/v1", "AGENT_SELFHOSTED_MODEL=local-model",
                           "AGENT_SELFHOSTED_API=chat", "AGENT_SELFHOSTED_BUILDERS=1", "AGENT_SELFHOSTED_ROLES=builder")
        docker(*command, IMAGE, "python3", "/x/spikes/m21_art.py")
        out = wait_for_file(workspace / "art-out.json", name, 1500)
        report("art: the builder finishes on the other model", out and not out["is_error"] and out["text"] == "All built.", out)
        if not out:
            return
        print(f"art took {out['seconds']}s, and made {out['art']}", flush=True)
        report("art: a texture and a model were really made", any(path.endswith(".png") for path in out["art"]) and any(path.endswith(".bbmodel") for path in out["art"]), out["art"])
        report("art: all of it counts as made by Opus", out["made"] and not out["left"], out)
        by_role = {call["role"]: call for call in out["calls"]}
        report("art: the artists ran on Claude", all(role in by_role and "lane" not in by_role[role] and by_role[role]["estimate"] > 0 for role in ("artist", "modeller")), out["calls"])
        report("art: the builder ran on the other model", by_role.get("builder", {}).get("lane") == "self_hosted", out["calls"])
        entries = logged(folder)
        everything = json.dumps(entries)
        report("art: the other model is offered the tool", workshop_tool_offered(entries), [entry["tools"] for entry in entries])
        report("art: nothing the artists were told reached the other model", "You make Minecraft art" not in everything and "You model creatures" not in everything)
        report("art: the other model hears back what was made", any("artist:" in str(entry["outputs"]) and "modeller:" in str(entry["outputs"]) for entry in entries), [entry["outputs"] for entry in entries][-1])
        report("art: the other model isn't asked for a length or usage", all("stream_options" not in entry["request"] and "max_tokens" not in entry["request"] for entry in entries))
    finally:
        docker("rm", "-f", "m21-art", "m21-fake", check=False)
        subprocess.run(["docker", "run", "--rm", "-v", f"{folder}:/m", "alpine:3.22", "rm", "-rf", "/m/workspace"], capture_output=True, check=False, stdin=subprocess.DEVNULL)
        shutil.rmtree(folder, ignore_errors=True)


def workshop_tool_offered(entries):
    return any('"name": "mcp__art__make_art"' in entry["request"] for entry in entries)


def machine_test(source):
    folder = pathlib.Path(tempfile.mkdtemp(prefix="m21-machine-"))
    main_space, worker_space = writable(folder / "main"), writable(folder / "worker")
    feature = "/workspace/trees/demo/mods/genesis/features/demo"
    try:
        start_fake(source, folder, [
            {"tool": "Bash", "input": {"command": "sleep 12", "description": "Take long enough for the refusal checks to run"}},
            {"tool": "Write", "input": {"file_path": f"{feature}/feature.json", "content": json.dumps({"id": "demo", "summary": "A demo."})}},
            {"tool": "Write", "input": {"file_path": "/workspace/trees/demo/rogue.txt", "content": "This shouldn't come along."}},
            {"tool": "mcp__world__world_index", "input": {}},
            {"tool": "mcp__broker__java_api", "input": {"class_name": "net.minecraft.world.item.Item"}},
            {"tool": "mcp__broker__lint_feature", "input": {}},
            {"text": "Built on another machine."}])
        control = writable(folder / "control")
        hub_command = hardened(source, "m21-main", main_space, {}, f"M21_TOKEN={TOKEN}", "CONTROL_DIR=/control")
        docker(*hub_command, "-v", f"{control}:/control", IMAGE, "python3", "/x/spikes/m21_hub.py")
        time.sleep(3)
        secrets = {"worker_token": secret(folder, "token", TOKEN), "model_key": secret(folder, "key", MODEL_KEY)}
        worker_command = hardened(source, "m21-worker", worker_space, secrets, "WORKER_HUB_URL=http://m21-main:8790", "WORKER_SLOTS=1", "WORKER_LANE=self_hosted",
                                  "AGENT_SELFHOSTED_URL=http://m21-fake:9000/v1", "AGENT_SELFHOSTED_MODEL=local-model", "AGENT_SELFHOSTED_API=responses", "AGENT_SELFHOSTED_BUILDERS=1")
        docker(*worker_command, IMAGE, "python3", "-m", "orchestrator.worker")
        out = wait_for_file(main_space / "hub-out.json", "m21-main", 420)
        logs = docker("logs", "--tail", "30", "m21-worker", check=False)
        print("--- the machine's log", logs.stdout[-2500:], logs.stderr[-2500:], flush=True)
        report("a machine gets a job and hands it back", out and not out["first"]["error"] and out["first"]["text"] == "Built on another machine.", out)
        if not out:
            return
        report("nobody gets in without a token", out["nobody_without_a_token"] == 401, out)
        report("a machine on different code is refused", out["old_code_refused"] == 409, out)
        report("it can't ask for a release", out["cant_ask_for_a_release"] == 403, out)
        report("it can't ask for the gates", out["cant_ask_for_gates"] == 403, out)
        report("it can't name a commit it didn't send", out["cant_name_a_commit_it_didnt_send"] == 400, out)
        report("the feature arrives on the main server", out["feature_arrived"] and out["node_stamped"] == "e_one", out)
        report("nothing else it did comes along", out["nothing_else_came_with_it"], out)
        kinds = [entry["kind"] for entry in out["asked"]]
        report("its checks go through the main server", "lint" in kinds and "javap" in kinds, out["asked"])
        report("the commits it asks about are really there", all(entry["commit_is_here"] for entry in out["asked"] if entry["kind"] == "lint"), out["asked"])
        entries = logged(folder)
        second = [entry for entry in entries if "reviewer found problems" in entry["request"]]
        report("a second attempt reaches the model", not out["second"]["error"] and second, out["second"])
        report("and carries on the same conversation", second and len(second[0]["outputs"]) >= 6, [len(entry["outputs"]) for entry in second])
        report("nothing's left behind on the main server", out["refs_cleaned"], out)
        report("the work really happened on the other machine", (worker_space / "trees/demo/mods/genesis/features/demo/feature.json").exists())
        report("and the main server's tree has none of the machine's other files", not (main_space / "trees/demo/rogue.txt").exists())
        report("the machine's token isn't what the main server keeps", TOKEN not in (control / "workers.json").read_text(encoding="utf-8"))
        report("the token never reaches a model", TOKEN not in json.dumps(entries))
    finally:
        docker("rm", "-f", "m21-main", "m21-worker", "m21-fake", check=False)
        subprocess.run(["docker", "run", "--rm", "-v", f"{folder}:/m", "alpine:3.22", "sh", "-c", "rm -rf /m/main /m/worker /m/control"], capture_output=True, check=False, stdin=subprocess.DEVNULL)
        shutil.rmtree(folder, ignore_errors=True)


def egress_test(source):
    """The address of a self-hosted model has to get through the proxy, including its stream, and nothing else should."""
    folder = pathlib.Path(tempfile.mkdtemp(prefix="m21-egress-"))
    try:
        start_fake(source, folder, [{"text": "Through the proxy."}])
        docker("build", "-q", "-t", "livingmod/egress:m21", str(source / "infra" / "egress"))
        docker("run", "-d", "--name", "m21-egress", "--network", NETWORK, "--cap-drop", "ALL", "--read-only", "--tmpfs", "/run/tinyproxy", "--tmpfs", "/var/log/tinyproxy",
               "-e", "EGRESS_EXTRA_HOSTS=m21-fake", "-e", "EGRESS_EXTRA_PORTS=9000", "livingmod/egress:m21")
        time.sleep(3)
        probe = """
import json, sys, urllib.error, urllib.request
def get(url):
    request = urllib.request.Request(url, data=json.dumps({"tools": [{}], "input": []}).encode(), method="POST")
    try:
        return urllib.request.urlopen(request, timeout=10).read().decode()
    except urllib.error.HTTPError as error:
        return f"refused {error.code}"
    except OSError as error:
        return f"refused {error}"
print(json.dumps({"model": get("http://m21-fake:9000/v1/responses"), "other": get("http://m21-egress:8888/")}))
"""
        answer = docker("run", "--rm", "--network", NETWORK, "--entrypoint", "python3", "-e", "HTTP_PROXY=http://m21-egress:8888", IMAGE, "-c", probe, check=False)
        seen = json.loads(answer.stdout or "{}")
        report("a self-hosted model's address gets through the proxy, stream and all", "Through the proxy." in seen.get("model", "") or "response.completed" in seen.get("model", ""), answer.stdout[:300] + answer.stderr[-300:])
        report("nothing else does", "response" not in seen.get("other", "response") and "refused" in seen.get("other", ""), seen)
        plain = docker("logs", "m21-egress", check=False)
        report("the proxy started with the extra address", docker("inspect", "-f", "{{.State.Running}}", "m21-egress", check=False).stdout.strip() == "true", plain.stdout[-300:] + plain.stderr[-300:])
    finally:
        docker("rm", "-f", "m21-egress", "m21-fake", check=False)
        shutil.rmtree(folder, ignore_errors=True)


def main():
    source = pathlib.Path(sys.argv[1]).resolve()
    only = sys.argv[2] if len(sys.argv) > 2 else None
    docker("network", "rm", NETWORK, check=False)
    docker("network", "create", *([] if only == "art" else ["--internal"]), NETWORK)
    try:
        if only == "art":
            art_test(source, sys.argv[3])
        if only in (None, "lanes"):
            lane_test(source, "responses")
            lane_test(source, "chat")
        if only in (None, "machines"):
            machine_test(source)
        if only in (None, "egress"):
            egress_test(source)
    finally:
        docker("network", "rm", NETWORK, check=False)
    failed = results.count(False)
    print(f"{len(results) - failed} of {len(results)} checks passed", flush=True)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
