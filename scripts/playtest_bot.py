#!/usr/bin/env python3
"""A scripted player that can hold a conversation, for testing the agent with nobody online.

Answers each private message from the agent with the next line of its script, says its public lines once
the character has spoken, and writes everything it hears to a log the end-to-end test reads. It also
watches every packet for words it must never receive, which is how the test proves one player's private
answers don't reach another.

Needs a proxy with online-mode off, so it only ever runs against local or test stacks.

Usage: playtest_bot.py --name NAME --script FILE --log FILE [--never-see WORD,WORD] [--seconds N]
"""
import argparse
import json
import pathlib
import random
import socket
import struct
import sys
import time
import zlib

import smoketest_join as client
from ping import varint

# From the server's own --reports packets.json. A new Minecraft version needs these regenerated.
PLAY_SYSTEM_CHAT, PLAY_PLAYER_CHAT, PLAY_COMBAT_KILL = 124, 66, 69
TO_PLAY_CHAT, TO_PLAY_COMMAND, TO_PLAY_CLIENT_COMMAND = 9, 7, 12
RESPAWN = 0
CHARACTER_MARK = "§d"
PRIVATE_MARK = "[Agent]"
ANSWER_DELAY_SECONDS = 3


def read_nbt(data, tag=None):
    """Network NBT has no root name. Only what chat components use needs to be right here."""
    if tag is None:
        tag = data.take(1)[0]
    if tag == 8:
        return data.take(struct.unpack(">H", data.take(2))[0]).decode("utf-8", "replace")
    if tag == 10:
        result = {}
        while (inner := data.take(1)[0]) != 0:
            name = data.take(struct.unpack(">H", data.take(2))[0]).decode("utf-8", "replace")
            result[name] = read_nbt(data, inner)
        return result
    if tag == 9:
        inner = data.take(1)[0]
        return [read_nbt(data, inner) for _ in range(struct.unpack(">i", data.take(4))[0])]
    if tag in (1, 2, 3, 4, 5, 6):
        data.take({1: 1, 2: 2, 3: 4, 4: 8, 5: 4, 6: 8}[tag])
        return None
    if tag in (7, 11, 12):
        data.take(struct.unpack(">i", data.take(4))[0] * {7: 1, 11: 4, 12: 8}[tag])
        return None
    raise ValueError(f"unknown NBT tag {tag}")


def flatten(component):
    if isinstance(component, str):
        return component
    if isinstance(component, list):
        return "".join(flatten(part) for part in component)
    if isinstance(component, dict):
        text = component.get("text", "") or component.get("", "")
        if "translate" in component:
            # What a client with no language file for it shows, which is what the tests go by.
            text = str(component.get("fallback", component["translate"]))
            for value in component.get("with", []):
                text = text.replace("%s", flatten(value) if isinstance(value, (dict, list, str)) else str(value), 1)
        return flatten(text) + "".join(flatten(part) for part in component.get("extra", []))
    return ""


class Bot:
    def __init__(self, args):
        self.name = args.name
        script = json.loads(pathlib.Path(args.script).read_text(encoding="utf-8"))
        self.answers = list(script.get("answers", []))
        self.public = list(script.get("public", []))
        self.never_see = [word.encode() for word in (args.never_see or "").split(",") if word]
        self.log_path = pathlib.Path(args.log)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.character_spoke = False
        self.due = []
        self.conn = None

    def log(self, kind, **fields):
        with self.log_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"at": time.time(), "kind": kind, "player": self.name, **fields}, ensure_ascii=False) + "\n")

    def say(self, text):
        payload = (client.string(text) + struct.pack(">qq", int(time.time() * 1000), random.getrandbits(63))
                   + b"\x00" + varint(0) + bytes(3) + b"\x00")
        self.conn.send(TO_PLAY_CHAT, payload)
        self.log("said", text=text)

    def dm(self, text):
        self.conn.send(TO_PLAY_COMMAND, client.string(f"dm {text}"))
        self.log("said", text=text)

    def on_system_chat(self, data):
        text = flatten(read_nbt(data))
        self.log("heard", text=text)
        if CHARACTER_MARK in text:
            if not self.character_spoke:
                self.character_spoke = True
                now = time.monotonic()
                for index, line in enumerate(self.public):
                    self.due.append((now + 30 * (index + 1), line, self.say))
        elif PRIVATE_MARK in text and self.answers:
            self.due.append((time.monotonic() + ANSWER_DELAY_SECONDS, self.answers.pop(0), self.dm))

    def play(self, until):
        conn = self.conn
        while time.monotonic() < until:
            for entry in [entry for entry in self.due if entry[0] <= time.monotonic()]:
                self.due.remove(entry)
                entry[2](entry[1])
            conn.sock.settimeout(1)
            try:
                packet_id, data = conn.receive()
            except TimeoutError:
                continue
            for word in self.never_see:
                if word in data.data:
                    self.log("leak", word=word.decode())
            if packet_id == client.PLAY_LOGIN:
                self.log("joined")
                conn.send(client.TO_PLAY_LOADED)
            elif packet_id == PLAY_SYSTEM_CHAT:
                self.on_system_chat(data)
            elif packet_id == PLAY_PLAYER_CHAT:
                self.log("player_chat", bytes=len(data.data))
            elif packet_id == PLAY_COMBAT_KILL:
                self.log("died")
                conn.send(TO_PLAY_CLIENT_COMMAND, varint(RESPAWN))
            elif packet_id == client.PLAY_PACK_PUSH:
                client.accept_pack(conn, data, client.TO_PLAY_PACK_STATUS)
                self.log("pack")
            elif packet_id == client.PLAY_DISCONNECT:
                raise client.Failed(f"kicked: {client.readable(data.rest())}")
            elif packet_id == client.PLAY_KEEP_ALIVE:
                conn.send(client.TO_PLAY_KEEP_ALIVE, data.rest())
            elif packet_id == client.PLAY_PING:
                conn.send(client.TO_PLAY_PONG, data.rest())
            elif packet_id == client.PLAY_START_CONFIG:
                self.log("held_or_moved")
                conn.send(client.TO_PLAY_CONFIG_ACK)
                client.configure(conn, require_pack=False)

    def run(self, host, port, seconds):
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            try:
                self.conn = client.Connection(host, port)
                client.login(self.conn, host, port, self.name)
                client.configure(self.conn)
                self.play(until)
            except (client.Failed, OSError, zlib.error, socket.timeout) as error:
                self.log("disconnected", reason=str(error))
                time.sleep(5)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=25565)
    parser.add_argument("--name", required=True)
    parser.add_argument("--script", required=True)
    parser.add_argument("--log", required=True)
    parser.add_argument("--never-see", default="")
    parser.add_argument("--seconds", type=int, default=3600)
    args = parser.parse_args()
    Bot(args).run(args.host, args.port, args.seconds)
    sys.exit(0)


if __name__ == "__main__":
    main()
