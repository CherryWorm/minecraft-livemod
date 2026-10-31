"""The connection to the game: events come in, and typed operations go out."""
import asyncio
import json
import os


class Bridge:
    def __init__(self, host=None, port=25580):
        self.host = host or os.environ.get("BRIDGE_HOST", "prod")
        self.port = port
        self.secret = os.environ["BRIDGE_SECRET"].strip()
        self.reader = None
        self.writer = None
        self.next_id = 1
        self.pending = {}
        self.events = asyncio.Queue()

    async def connect(self, retry_seconds=2):
        """Keeps trying, because the server may be restarting. That's normal, not a failure."""
        while True:
            try:
                self.reader, self.writer = await asyncio.open_connection(self.host, self.port)
                self.writer.write((json.dumps({"auth": self.secret}) + "\n").encode())
                await self.writer.drain()
                return
            except OSError:
                await asyncio.sleep(retry_seconds)

    async def run(self):
        """Reads messages forever, reconnecting whenever the server goes away."""
        while True:
            try:
                line = await self.reader.readline()
            except OSError:
                line = b""
            if not line:
                for future in self.pending.values():
                    if not future.done():
                        future.set_exception(ConnectionError("game connection lost"))
                self.pending.clear()
                await self.connect()
                continue
            message = json.loads(line)
            if "reply" in message:
                future = self.pending.pop(message["reply"], None)
                if future and not future.done():
                    future.set_result(message)
            elif "event" in message:
                await self.events.put(message)

    async def call(self, op, **arguments):
        request_id = self.next_id
        self.next_id += 1
        future = asyncio.get_running_loop().create_future()
        self.pending[request_id] = future
        self.writer.write((json.dumps({"id": request_id, "op": op, **arguments}) + "\n").encode())
        await self.writer.drain()
        reply = await asyncio.wait_for(future, timeout=15)
        if not reply.get("ok"):
            raise RuntimeError(reply.get("error", "operation failed"))
        return reply.get("result")

    async def whisper(self, player, text):
        return await self.call("whisper", player=player, text=text)

    async def broadcast(self, text):
        return await self.call("broadcast", text=text)

    async def capture(self, player, on):
        return await self.call("capture", player=player, on=on)

    async def players(self):
        return await self.call("players")

    async def border(self, size):
        return await self.call("border", size=size)
