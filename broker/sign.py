"""Signs client modules, so the companion can refuse anything the broker didn't release, even if the server
relaying it is compromised. No container mounts this folder, so the agent, the build and the game servers
can't reach the key.

The companion checks the result in ModuleVerifier: Ed25519 over the module's id, its generation and the jar's
SHA-256 hex digest, one per line. It refuses any generation older than one it has already run, so replaying an
old module does nothing.

Usage: python3 -m broker.sign   Creates the keypair if it's missing, and prints the public key to pin.
"""
import base64
import contextlib
import fcntl
import hashlib
import json
import os
import pathlib
import re
import stat

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from broker import runtime

SIGNING = runtime.BROKER / "signing"
PRIVATE_KEY = "module_key.pem"
# Named after the resource the companion reads, so this file can be copied in as it is.
PUBLIC_KEY = "module_key.pub"
GENERATIONS = "generations.json"
MODULE_ID = re.compile(r"[a-z0-9_]+")


class SigningError(Exception):
    """Something's wrong with the signing folder. Worded for the owner, because the agent can't fix it."""


@contextlib.contextmanager
def _locked():
    """Holds the folder for one bump of a generation, so overlapping runs can't hand out the same number twice."""
    SIGNING.mkdir(parents=True, exist_ok=True)
    SIGNING.chmod(0o700)
    with open(SIGNING / ".lock", "w", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def _write_atomically(path, data, mode):
    """Either the whole file lands or none of it. os.open sets the mode at creation, so there's never a moment
    when a private key is readable by anyone else."""
    temporary = path.with_name(path.name + ".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(descriptor, "wb") as stream:
        os.fchmod(stream.fileno(), mode)
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _public_text(key):
    raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode("ascii")


def _load_key():
    """Returns the private key, making the pair the first time. Called with the folder locked.

    It never replaces a key, because companions have the public half pinned and would refuse everything after.
    """
    private, public, generations = SIGNING / PRIVATE_KEY, SIGNING / PUBLIC_KEY, SIGNING / GENERATIONS
    if private.exists():
        if stat.S_IMODE(private.stat().st_mode) & 0o077:
            raise SigningError(f"{private} can be read by other users. Treat it as compromised: "
                               "make a new key, pin it in the companion, and only then release again.")
        try:
            key = serialization.load_pem_private_key(private.read_bytes(), password=None)
        except ValueError as error:
            raise SigningError(f"{private} isn't a readable key: {error}") from error
        if not isinstance(key, Ed25519PrivateKey):
            raise SigningError(f"{private} isn't an Ed25519 key.")
        # Starting again from 1 would go unnoticed here, and every companion would then refuse the modules.
        if not generations.exists():
            raise SigningError(f"{generations} is missing while the key exists, so generations would restart and "
                               "companions would refuse them. Restore it from a backup.")
    elif public.exists():
        raise SigningError(f"{private} is missing but {public} is there. Companions have that key pinned, so a new one "
                           "would make them refuse everything. Restore it, or delete both and pin the new key.")
    else:
        if not generations.exists():
            _write_atomically(generations, b"{}\n", 0o600)
        key = Ed25519PrivateKey.generate()
        _write_atomically(private, key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                     serialization.NoEncryption()), 0o600)
        print(f"New module signing key. Pin this in the companion: {_public_text(key)}", flush=True)
    if not public.exists():
        _write_atomically(public, (_public_text(key) + "\n").encode("ascii"), 0o644)
    return key


def _next_generation(module_id):
    """Saved before anything is signed, so a crash can waste a number but never use one twice."""
    path = SIGNING / GENERATIONS
    try:
        generations = json.loads(path.read_text(encoding="utf-8"))
        last = generations.get(module_id, 0)
    except (OSError, ValueError, AttributeError) as error:
        raise SigningError(f"{path} can't be read: {error}. Restore it from a backup, because guessing "
                           "could reuse a generation.") from error
    if not isinstance(last, int) or isinstance(last, bool) or last < 0:
        raise SigningError(f"{path} has {last!r} for {module_id}, which isn't a generation. Restore it from a backup.")
    generations[module_id] = last + 1
    _write_atomically(path, (json.dumps(generations, indent=1, sort_keys=True) + "\n").encode("utf-8"), 0o600)
    return last + 1


def signed_message(module_id, generation, digest):
    """The bytes both sides sign and verify. ModuleVerifier.signatureValid must build exactly this."""
    return f"{module_id}\n{generation}\n{digest}".encode("utf-8")


def _digest(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def sign_module(path, module_id):
    """Signs a jar under a new generation, and writes the signature next to it as <jar>.sig.

    Returns {"generation": int, "signature": base64 text}.
    """
    # An id holding a newline could make two different modules sign the same bytes.
    if not isinstance(module_id, str) or not MODULE_ID.fullmatch(module_id):
        raise SigningError(f"{module_id!r} isn't a valid module id. Ids are lowercase letters, digits and underscores.")
    digest = _digest(path)
    with _locked():
        key = _load_key()
        generation = _next_generation(module_id)
    signature = base64.b64encode(key.sign(signed_message(module_id, generation, digest))).decode("ascii")
    # The same text the server sends. Base64 with no newline, because that's what Java's decoder expects.
    pathlib.Path(f"{path}.sig").write_text(signature, encoding="ascii")
    return {"generation": generation, "signature": signature}


def sign_release(content, previous=None):
    """Signs every client module in a release's content, and writes the <feature>.json that travels with it.
    ModulePush reads that file, and won't send a jar without one.

    A jar that's the same as in the previous release keeps its record, so nobody's game reloads a module for no
    reason. A rollback passes no previous release, because old code has to go out under a new generation."""
    for jar in sorted((content / "modules" / "client").glob("*.jar")):
        record_path = jar.with_suffix(".json")
        if previous is not None:
            old_jar = previous / "modules" / "client" / jar.name
            old_record = old_jar.with_suffix(".json")
            if old_jar.exists() and old_record.exists() and old_jar.read_bytes() == jar.read_bytes():
                record_path.write_bytes(old_record.read_bytes())
                continue
        record_path.write_text(json.dumps(sign_module(jar, jar.stem), indent=1) + "\n", encoding="utf-8")


def mark_for_testing(content):
    """Lets the shadow server send a release's client modules before they're signed, because signing is only for
    what really goes out. A real companion refuses these. Only the gate's test client takes them, and it still runs
    the code check."""
    for jar in sorted((content / "modules" / "client").glob("*.jar")):
        jar.with_suffix(".json").write_text(json.dumps({"generation": 1, "signature": ""}) + "\n", encoding="utf-8")


def public_key_text():
    """The public key as base64 of its raw 32 bytes, one of the two forms ModuleVerifier accepts."""
    return (SIGNING / PUBLIC_KEY).read_text(encoding="ascii").strip()


def verify_signature(path, module_id, generation, signature, public_key=None):
    """Checks a signature the way the companion does, for tests and spot checks. Returns True or False."""
    try:
        key = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key or public_key_text(), validate=True))
        key.verify(base64.b64decode(signature, validate=True), signed_message(module_id, generation, _digest(path)))
    except (InvalidSignature, ValueError):
        return False
    return True


if __name__ == "__main__":
    with _locked():
        _load_key()
    print(public_key_text())
