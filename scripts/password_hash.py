#!/usr/bin/env python3
"""Turns the password on stdin into the salted hash the game checks it against (see gm.conduit.PasswordGate).

The hash is all the game's process ever gets, because code the agent wrote runs in there too.
"""
import base64
import hashlib
import os
import sys

ROUNDS = 200_000


def hash_password(password):
    salt = os.urandom(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ROUNDS)
    return f"pbkdf2_sha256${ROUNDS}${base64.b64encode(salt).decode()}${base64.b64encode(derived).decode()}"


if __name__ == "__main__":
    print(hash_password(sys.stdin.read().strip()))
