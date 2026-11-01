#!/usr/bin/env python3
"""Joins the server the way a game client does, with no game involved.

Logs in through the proxy, accepts and downloads the resource pack, checks its SHA-1, and enters the
world. Needs a proxy with online-mode off, so it only ever runs against local or test stacks.

Usage: smoketest_join.py [--host H] [--port P] [--name NAME] [--stay SECONDS] [--watch-for TEXT]
Exits 0 only if the player reached the world and stayed connected.
"""
import argparse
import hashlib
import socket
import struct
import sys
import time
import urllib.request
import uuid
import zlib

from ping import varint

PROTOCOL = 777  # Minecraft 26.3

# From the server's own --reports packets.json. A new Minecraft version needs these regenerated.
LOGIN_DISCONNECT, LOGIN_HELLO, LOGIN_FINISHED, LOGIN_COMPRESSION, LOGIN_QUERY, LOGIN_COOKIE = 0, 1, 2, 3, 4, 5
TO_LOGIN_HELLO, TO_LOGIN_QUERY_ANSWER, TO_LOGIN_ACK, TO_LOGIN_COOKIE = 0, 2, 3, 4

CONFIG_COOKIE, CONFIG_DISCONNECT, CONFIG_FINISH, CONFIG_KEEP_ALIVE, CONFIG_PING = 0, 2, 3, 4, 5
CONFIG_PACK_PUSH, CONFIG_KNOWN_PACKS = 9, 15
TO_CONFIG_COOKIE, TO_CONFIG_FINISH, TO_CONFIG_KEEP_ALIVE, TO_CONFIG_PONG = 1, 3, 4, 5
TO_CONFIG_PACK_STATUS, TO_CONFIG_KNOWN_PACKS = 6, 7

PLAY_DISCONNECT, PLAY_KEEP_ALIVE, PLAY_LOGIN, PLAY_PING, PLAY_PACK_PUSH, PLAY_START_CONFIG = 32, 45, 50, 62, 82, 120
TO_PLAY_KEEP_ALIVE, TO_PLAY_CONFIG_ACK, TO_PLAY_LOADED, TO_PLAY_PONG, TO_PLAY_PACK_STATUS = 28, 16, 44, 45, 50

PACK_LOADED, PACK_ACCEPTED, PACK_DOWNLOADED = 0, 3, 4


class Failed(Exception):
    pass


class Reader:
    def __init__(self, data):
        self.data = data
        self.at = 0

    def take(self, count):
        out = self.data[self.at:self.at + count]
        self.at += count
        return out

    def varint(self):
        value = shift = 0
        while True:
            byte = self.take(1)[0]
            value |= (byte & 0x7F) << shift
            if not byte & 0x80:
                return value
            shift += 7

    def string(self):
        return self.take(self.varint()).decode("utf-8", "replace")

    def rest(self):
        return self.data[self.at:]


def string(value):
    encoded = value.encode("utf-8")
    return varint(len(encoded)) + encoded


def readable(raw):
    """Pulls the readable text out of a disconnect reason, which may be JSON or NBT."""
    return "".join(chr(b) if 32 <= b < 127 else " " for b in raw).strip()


class Connection:
    def __init__(self, host, port):
        self.sock = socket.create_connection((host, port), timeout=20)
        self.threshold = None
        # Bytes are kept here until a whole frame arrives, so a read timeout can't lose our place.
        self.buffer = bytearray()

    def _next_frame(self):
        value = shift = 0
        for at, byte in enumerate(self.buffer):
            value |= (byte & 0x7F) << shift
            if not byte & 0x80:
                start = at + 1
                if len(self.buffer) < start + value:
                    return None
                frame = bytes(self.buffer[start:start + value])
                del self.buffer[:start + value]
                return frame
            shift += 7
        return None

    def send(self, packet_id, payload=b""):
        data = varint(packet_id) + payload
        if self.threshold is not None:
            data = varint(0) + data
        self.sock.sendall(varint(len(data)) + data)

    def receive(self):
        while (raw := self._next_frame()) is None:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise Failed("server closed the connection")
            self.buffer += chunk
        frame = Reader(raw)
        if self.threshold is not None:
            size = frame.varint()
            body = zlib.decompress(frame.rest()) if size else frame.rest()
            frame = Reader(body)
        return frame.varint(), frame


def login(conn, host, port, name):
    conn.send(0, varint(PROTOCOL) + string(host) + struct.pack(">H", port) + varint(2))
    conn.send(TO_LOGIN_HELLO, string(name) + uuid.uuid4().bytes)
    while True:
        packet_id, data = conn.receive()
        if packet_id == LOGIN_COMPRESSION:
            conn.threshold = data.varint()
        elif packet_id == LOGIN_FINISHED:
            player_id = uuid.UUID(bytes=data.take(16))
            print(f"logged in through the proxy as {data.string()} ({player_id})")
            conn.send(TO_LOGIN_ACK)
            return
        elif packet_id == LOGIN_HELLO:
            raise Failed("the proxy requires a real Minecraft login (online-mode is on)")
        elif packet_id == LOGIN_DISCONNECT:
            raise Failed(f"refused at login: {readable(data.rest())}")
        elif packet_id == LOGIN_QUERY:
            conn.send(TO_LOGIN_QUERY_ANSWER, varint(data.varint()) + b"\x00")
        elif packet_id == LOGIN_COOKIE:
            conn.send(TO_LOGIN_COOKIE, string(data.string()) + b"\x00")


def accept_pack(conn, data, status_packet):
    pack_id = data.take(16)
    url = data.string()
    expected = data.string()
    forced = data.take(1) == b"\x01"
    print(f"offered resource pack (required={forced}): {url}", flush=True)
    conn.send(status_packet, pack_id + varint(PACK_ACCEPTED))
    with urllib.request.urlopen(url, timeout=20) as response:
        body = response.read()
    actual = hashlib.sha1(body).hexdigest()
    if actual != expected:
        raise Failed(f"pack checksum mismatch: offered {expected}, downloaded {actual}")
    print(f"PACK_OK {actual} ({len(body)} bytes, checksum matches)", flush=True)
    conn.send(status_packet, pack_id + varint(PACK_DOWNLOADED))
    conn.send(status_packet, pack_id + varint(PACK_LOADED))


def configure(conn, require_pack=True):
    got_pack = False
    while True:
        packet_id, data = conn.receive()
        if packet_id == CONFIG_FINISH:
            if require_pack and not got_pack:
                raise Failed("configuration finished without offering a resource pack")
            conn.send(TO_CONFIG_FINISH)
            print("configuration finished")
            return
        if packet_id == CONFIG_DISCONNECT:
            raise Failed(f"kicked during configuration: {readable(data.rest())}")
        if packet_id == CONFIG_KEEP_ALIVE:
            conn.send(TO_CONFIG_KEEP_ALIVE, data.rest())
        elif packet_id == CONFIG_PING:
            conn.send(TO_CONFIG_PONG, data.rest())
        elif packet_id == CONFIG_KNOWN_PACKS:
            conn.send(TO_CONFIG_KNOWN_PACKS, varint(0))
        elif packet_id == CONFIG_COOKIE:
            conn.send(TO_CONFIG_COOKIE, string(data.string()) + b"\x00")
        elif packet_id == CONFIG_PACK_PUSH:
            accept_pack(conn, data, TO_CONFIG_PACK_STATUS)
            got_pack = True


def play(conn, stay, watch_for=None):
    joined_at = None
    while joined_at is None or time.monotonic() - joined_at < stay:
        conn.sock.settimeout(1 if joined_at else 20)
        try:
            packet_id, data = conn.receive()
        except TimeoutError:
            if joined_at:
                continue
            raise Failed("timed out waiting to enter the world")
        if watch_for and watch_for.encode("utf-8") in data.rest():
            print(f"SAW {watch_for}", flush=True)
        if packet_id == PLAY_LOGIN:
            joined_at = joined_at or time.monotonic()
            print("JOINED the world", flush=True)
            conn.send(TO_PLAY_LOADED)
        elif packet_id == PLAY_PACK_PUSH:
            accept_pack(conn, data, TO_PLAY_PACK_STATUS)
        elif packet_id == PLAY_DISCONNECT:
            raise Failed(f"kicked: {readable(data.rest())}")
        elif packet_id == PLAY_KEEP_ALIVE:
            conn.send(TO_PLAY_KEEP_ALIVE, data.rest())
        elif packet_id == PLAY_PING:
            conn.send(TO_PLAY_PONG, data.rest())
        elif packet_id == PLAY_START_CONFIG:
            print("reconfiguring, the proxy is moving us to a backend", flush=True)
            conn.send(TO_PLAY_CONFIG_ACK)
            configure(conn, require_pack=False)
    print(f"stayed connected for {stay}s")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=25565)
    parser.add_argument("--name", default="smoketest")
    parser.add_argument("--stay", type=int, default=8)
    parser.add_argument("--watch-for", help="prints SAW and this text if it turns up in anything the server sends")
    args = parser.parse_args()
    try:
        conn = Connection(args.host, args.port)
        login(conn, args.host, args.port, args.name)
        configure(conn)
        play(conn, args.stay, args.watch_for)
    except (Failed, OSError, zlib.error) as error:
        print(f"FAILED: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
