#!/usr/bin/env python3
"""Asks a Minecraft server for its status, as a game client's server list does.

Usage: ping.py [host] [port]. Exits non-zero if nothing answers.
"""
import json
import socket
import struct
import sys


def varint(value):
    out = b""
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out += bytes([byte | 0x80])
        else:
            return out + bytes([byte])


def read_varint(sock):
    value = shift = 0
    while True:
        raw = sock.recv(1)
        if not raw:
            raise ConnectionError("connection closed")
        value |= (raw[0] & 0x7F) << shift
        if not raw[0] & 0x80:
            return value
        shift += 7


def packet(payload):
    return varint(len(payload)) + payload


def main():
    host = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 25565
    with socket.create_connection((host, port), timeout=10) as sock:
        name = host.encode()
        handshake = varint(0) + varint(0xFFFFFFF) + varint(len(name)) + name + struct.pack(">H", port) + varint(1)
        sock.sendall(packet(handshake) + packet(varint(0)))
        read_varint(sock)
        read_varint(sock)
        remaining = read_varint(sock)
        data = b""
        while len(data) < remaining:
            chunk = sock.recv(remaining - len(data))
            if not chunk:
                raise ConnectionError("connection closed")
            data += chunk
    status = json.loads(data)
    print(json.dumps({key: status.get(key) for key in ("version", "players", "description")}, indent=2))


if __name__ == "__main__":
    main()
