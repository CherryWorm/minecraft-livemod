#!/usr/bin/env python3
"""Runs one server command over RCON and prints the reply. Usage: rcon.py <command...>"""
import pathlib
import socket
import struct
import sys

AUTH = 3
COMMAND = 2


def send(sock, request_id, kind, body):
    payload = struct.pack("<ii", request_id, kind) + body.encode("utf-8") + b"\x00\x00"
    sock.sendall(struct.pack("<i", len(payload)) + payload)


def read_exact(sock, count):
    data = b""
    while len(data) < count:
        chunk = sock.recv(count - len(data))
        if not chunk:
            raise ConnectionError("server closed the connection")
        data += chunk
    return data


def receive(sock):
    length = struct.unpack("<i", read_exact(sock, 4))[0]
    packet = read_exact(sock, length)
    request_id, _ = struct.unpack("<ii", packet[:8])
    return request_id, packet[8:-2].decode("utf-8", "replace")


def main():
    password = pathlib.Path("/run/secrets/rcon").read_text().strip()
    with socket.create_connection(("127.0.0.1", 25575), timeout=30) as sock:
        send(sock, 1, AUTH, password)
        if receive(sock)[0] == -1:
            sys.exit("rcon authentication failed")
        send(sock, 2, COMMAND, " ".join(sys.argv[1:]))
        print(receive(sock)[1])


if __name__ == "__main__":
    main()
