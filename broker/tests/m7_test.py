#!/usr/bin/env python3
"""The M7 exit test: on a real client, a signed HUD module appears with no restart, and these are all refused:
a jar with no signature, a validly signed jar using file APIs, and an older signed version replayed. Then the
player's own off-switch removes the module.

Usage: python3 -m broker.tests.m7_test
"""
import base64
import pathlib
import re
import shutil
import struct
import subprocess
import sys
import time
import zipfile

from broker import runtime, sign

CONTAINER = "livingmod-m7-client"
MODULES = runtime.RUNTIME / "prod" / "modules"
SAMPLE_LIBS = runtime.REPO / "mods" / "sample-module" / "build" / "libs"
FAILED = re.compile(r"BUILD FAILED|Game crashed|\.java:\d+: error:")


def report(name, passed, detail=""):
    print(f"{'PASS' if passed else 'FAIL'}  {name}  {detail}", flush=True)
    return passed


def class_using_files():
    """A minimal class whose constant pool names java/io/File, which is all the check needs to see."""
    names = [b"gm/sample/Bad", b"java/lang/Object", b"java/io/File"]
    pool = bytearray()
    for name in names:
        pool += b"\x01" + struct.pack(">H", len(name)) + name
    pool += b"\x07" + struct.pack(">H", 1) + b"\x07" + struct.pack(">H", 2) + b"\x07" + struct.pack(">H", 3)
    count = len(names) + 3 + 1
    return (b"\xca\xfe\xba\xbe" + struct.pack(">HHH", 0, 69, count) + bytes(pool)
            + struct.pack(">HHHHHHH", 0x21, 4, 5, 0, 0, 0, 0))


def prepare():
    """Returns the sample jar, plus a copy of it with a file-using class added."""
    jar = next(path for path in SAMPLE_LIBS.glob("sample-module-*.jar") if not path.name.endswith("-sources.jar"))
    MODULES.mkdir(parents=True, exist_ok=True)
    for name in ("m7_unsigned", "m7_forbidden", "m7_older", "m7_good"):
        for leftover in MODULES.glob(f"{name}.*"):
            leftover.unlink()
    shutil.copy(jar, MODULES / "m7_unsigned.jar")

    forbidden = MODULES / "m7_forbidden.jar"
    shutil.copy(jar, forbidden)
    with zipfile.ZipFile(forbidden, "a") as archive:
        archive.writestr("gm/sample/Bad.class", class_using_files())
    # A real signature and its real generation, so the only thing wrong with this jar is what's in it.
    signed = sign.sign_module(forbidden, "m7_forbidden")
    (MODULES / "m7_forbidden.sig").write_text(signed["signature"], encoding="ascii")
    forbidden.with_name("m7_forbidden.jar.sig").unlink()

    # Two signatures of the same module, so the older one can be replayed after the newer has run.
    good = MODULES / "m7_good.jar"
    shutil.copy(jar, good)
    older = sign.sign_module(good, "m7_good")
    newer = sign.sign_module(good, "m7_good")
    good.with_name("m7_good.jar.sig").unlink()
    (MODULES / "m7_good.sig").write_text(newer["signature"], encoding="ascii")
    shutil.copy(good, MODULES / "m7_older.jar")
    (MODULES / "m7_older.sig").write_text(older["signature"], encoding="ascii")
    return signed["generation"], older["generation"], newer["generation"]


def wait_log(log, process, pattern, seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        text = log.read_text(encoding="utf-8", errors="replace")
        found = re.search(pattern, text, re.MULTILINE)
        if found:
            return found
        if FAILED.search(text) or process.poll() is not None:
            raise RuntimeError(f"The client stopped waiting for {pattern}:\n{text[-1500:]}")
        time.sleep(0.25)
    raise TimeoutError(f"Timed out waiting for {pattern}:\n{log.read_text(encoding='utf-8', errors='replace')[-800:]}")


def main():
    with sign._locked():
        sign._load_key()
    forbidden, older, newer = prepare()
    public = sign.public_key_text()
    base64.b64decode(public, validate=True)

    runtime.REPORTS.mkdir(parents=True, exist_ok=True)
    log = runtime.REPORTS / "m7-client.log"
    # Generations are remembered per client, so a run after this one needs a clean slate to prove the same things.
    shutil.rmtree(runtime.REPO / "mods" / "companion" / "build" / "run" / "clientGameTest" / "config" / "companion", ignore_errors=True)
    subprocess.run(["docker", "rm", "-f", CONTAINER], capture_output=True, check=False)
    with log.open("w", encoding="utf-8") as stream:
        process = subprocess.Popen(
            ["./scripts/stack.sh", "--profile", "tools", "run", "--rm", "-T", "--name", CONTAINER, "testclient",
             "./gradlew", "--no-daemon", "--console=plain", ":companion:runClientGameTest"],
            cwd=runtime.REPO, stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT,
            env={**__import__("os").environ, "CLIENT_TEST": "safety", "TEST_SERVER": "localhost:25565", "COMPANION_TEST_KEY": public},
        )
    results = []
    try:
        wait_log(log, process, r"\[M7\] joined", 420)
        time.sleep(5)
        runtime.rcon("prod", "conduit", "module", "push", "m7_unsigned", "m7_unsigned", "1")
        found = wait_log(log, process, r"\[M7\] refused unsigned refused=(\d+) active=(\w+)", 60)
        results.append(report("a jar with no signature is refused", found.group(2) == "false", found.group(0)))

        runtime.rcon("prod", "conduit", "module", "push", "m7_forbidden", "m7_forbidden", str(forbidden))
        found = wait_log(log, process, r"\[M7\] refused forbidden refused=(\d+) active=(\w+)", 60)
        results.append(report("a signed jar that uses file APIs is refused", found.group(2) == "false", found.group(0)))
        text = log.read_text(encoding="utf-8", errors="replace")
        results.append(report("it says why", "it refers to java/io/File" in text))

        runtime.rcon("prod", "conduit", "module", "push", "m7_good", "m7_good", str(newer))
        wait_log(log, process, r"\[M7\] signed module active", 60)
        results.append(report("a signed module appears with no restart", True, f"generation {newer}"))

        runtime.rcon("prod", "conduit", "module", "push", "m7_older", "m7_good", str(older))
        found = wait_log(log, process, r"\[M7\] refused older refused=(\d+)", 60)
        results.append(report("an older signed version can't be replayed", True, found.group(0)))

        found = wait_log(log, process, r"\[M7\] after turning off active=(\w+)", 60)
        results.append(report("the player's off-switch removes it", found.group(1) == "false", found.group(0)))
        wait_log(log, process, r"\[M7\] finished", 60)
        process.wait(timeout=90)
    finally:
        if process.poll() is None:
            subprocess.run(["docker", "rm", "-f", CONTAINER], capture_output=True, check=False)
            process.wait(timeout=30)
    shots = pathlib.Path(runtime.REPO / "mods" / "companion" / "build" / "run" / "clientGameTest" / "screenshots")
    out = runtime.REPORTS / "m7"
    out.mkdir(parents=True, exist_ok=True)
    for path in shots.glob("*m7_*.png"):
        shutil.copy(path, out)
    print("screenshots:", sorted(path.name for path in out.glob("*.png")), flush=True)
    failed = [result for result in results if not result]
    print(f"{len(results) - len(failed)} of {len(results)} checks passed", flush=True)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
