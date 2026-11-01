"""Signs updates to what's on friends' PCs. The updater (updater/Updater.java) installs anything this signs, with no limits on what it
can do, so unlike the key in broker/sign.py this one must never go near the server. It lives on the owner's PC, and a companion only
gets signed from what's already on the public main branch. If the key is lost, everyone downloads the pack once more with a new one.

Usage: python3 -m broker.client_release key                         Creates the key if it's missing, and prints the public half to pin.
       python3 -m broker.client_release sign <staging> <out> <generation>
"""
import base64
import hashlib
import os
import pathlib
import re
import shutil
import sys

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from broker import runtime

KEY_FILE = "client_release.pem"
FOLDERS = ("mods", "config", "resourcepacks")
NAME = re.compile(r"[A-Za-z0-9+_-][A-Za-z0-9+._-]*")
HEADER = "livingmod-update 1"


class ReleaseError(Exception):
    pass


def key_path():
    return runtime.RUNTIME / "secrets" / KEY_FILE


def load_key(path=None, create=False):
    path = path or key_path()
    if not path.exists():
        if not create:
            raise ReleaseError(f"There's no signing key at {path}. This has to run on the owner's PC.")
        path.parent.mkdir(parents=True, exist_ok=True)
        key = Ed25519PrivateKey.generate()
        # Mode set at creation, so it's never readable by anyone else, and it's never replaced, because the updaters pin the public half.
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        return key
    return serialization.load_pem_private_key(path.read_bytes(), password=None)


def public_text(key):
    raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode("ascii")


def release(staging, out, generation, key):
    """Everything under staging's folders goes out under its hash, with a signed list of what goes where."""
    (out / "files").mkdir(parents=True, exist_ok=True)
    lines = [HEADER, f"generation {generation}"]
    for folder in FOLDERS:
        if not (staging / folder).is_dir():
            continue
        for path in sorted((staging / folder).iterdir()):
            if not path.is_file() or not NAME.fullmatch(path.name):
                raise ReleaseError(f"The updater wouldn't accept {folder}/{path.name}.")
            data = path.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            shutil.copyfile(path, out / "files" / digest)
            lines.append(f"file {folder}/{path.name} {digest} {len(data)}")
    body = ("\n".join(lines) + "\n").encode("utf-8")
    (out / "manifest").write_bytes(body)
    (out / "manifest.sig").write_text(base64.b64encode(key.sign(body)).decode("ascii") + "\n", encoding="ascii")


def main():
    if sys.argv[1:2] == ["key"]:
        print(public_text(load_key(create=True)))
    elif sys.argv[1:2] == ["sign"] and len(sys.argv) == 5:
        release(pathlib.Path(sys.argv[2]), pathlib.Path(sys.argv[3]), int(sys.argv[4]), load_key())
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
