"""Lets a builder run on a self-hosted model that speaks OpenAI's Responses API, as Codex uses, or Chat Completions.

Builders are Claude Code, with its tools, subagents and sandbox, and it only speaks Anthropic's Messages API. This
translates between them on this machine, so everything about a builder stays the same and only the model changes.

The model's key stays in this process. Claude Code only gets a throwaway password for this bridge, so nothing it runs
could find the real key, and whatever login it sends is never passed on.
"""
import asyncio
import contextlib
import hmac
import http.client
import json
import re
import secrets
import threading
import time
import urllib.error
import urllib.request
import uuid

import uvicorn
from starlette.applications import Starlette
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

RESPONSES = "responses"
CHAT = "chat"
NO_VISION = "[There was an image here, but this model can't see images.]"
READ_TIMEOUT_SECONDS = 600
CHARS_PER_TOKEN = 4
DOWN_SECONDS = 300  # How long after a failure everything waits before trying the model again.
ABOUT_THE_REQUEST = (400, 413, 422)  # The model's there, and it's only this one request that's wrong.


def _text_of(content):
    return content if isinstance(content, str) else "\n".join(block.get("text", "") for block in content if block.get("type") == "text")


def _data_url(block):
    source = block.get("source", {})
    return source.get("url") if source.get("type") == "url" else f"data:{source.get('media_type', 'image/png')};base64,{source.get('data', '')}"


def _split_tool_result(block, vision):
    """A tool's answer as text, and any images in it, which these APIs only take from the user."""
    content = block.get("content", "")
    if isinstance(content, str):
        return content, []
    parts, images = [], []
    for part in content:
        if part.get("type") == "text":
            parts.append(part.get("text", ""))
        elif part.get("type") == "image":
            if vision:
                images.append(part)
            else:
                parts.append(NO_VISION)
    return "\n".join(parts), images


def _tools(body):
    return [tool for tool in body.get("tools", []) if tool.get("input_schema") is not None]


def to_responses(body, model, vision):
    """Anthropic's request as a Responses API one. Answers come from a stateless server, so the whole history goes each time."""
    items = []
    for message in body.get("messages", []):
        content = message["content"]
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        if message["role"] == "assistant":
            for block in content:
                if block.get("type") == "text" and block.get("text"):
                    items.append({"role": "assistant", "content": [{"type": "output_text", "text": block["text"]}]})
                elif block.get("type") == "tool_use":
                    items.append({"type": "function_call", "call_id": block["id"], "name": block["name"], "arguments": json.dumps(block.get("input", {}))})
            continue
        parts = []
        for block in content:
            if block.get("type") == "tool_result":
                text, images = _split_tool_result(block, vision)
                items.append({"type": "function_call_output", "call_id": block["tool_use_id"], "output": text})
                parts.extend({"type": "input_image", "image_url": _data_url(image)} for image in images)
            elif block.get("type") == "text":
                parts.append({"type": "input_text", "text": block.get("text", "")})
            elif block.get("type") == "image":
                parts.append({"type": "input_image", "image_url": _data_url(block)} if vision else {"type": "input_text", "text": NO_VISION})
        if parts:
            items.append({"role": "user", "content": parts})
    request = {"model": model, "input": items, "stream": True, "store": False}
    if body.get("system"):
        request["instructions"] = _text_of(body["system"])
    if body.get("max_tokens"):
        request["max_output_tokens"] = body["max_tokens"]
    tools = _tools(body)
    if tools:
        request["tools"] = [{"type": "function", "name": tool["name"], "description": tool.get("description", ""), "parameters": tool["input_schema"]} for tool in tools]
        choice = body.get("tool_choice", {}).get("type")
        if choice == "any":
            request["tool_choice"] = "required"
        elif choice == "tool":
            request["tool_choice"] = {"type": "function", "name": body["tool_choice"]["name"]}
        elif choice == "none":
            request["tool_choice"] = "none"
    return request


def to_chat(body, model, vision):
    """Anthropic's request as a Chat Completions one."""
    messages = []
    if body.get("system"):
        messages.append({"role": "system", "content": _text_of(body["system"])})
    for message in body.get("messages", []):
        content = message["content"]
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        if message["role"] == "assistant":
            text = "".join(block.get("text", "") for block in content if block.get("type") == "text")
            calls = [{"id": block["id"], "type": "function", "function": {"name": block["name"], "arguments": json.dumps(block.get("input", {}))}}
                     for block in content if block.get("type") == "tool_use"]
            messages.append({"role": "assistant", "content": text or None, **({"tool_calls": calls} if calls else {})})
            continue
        parts = []
        for block in content:
            if block.get("type") == "tool_result":
                text, images = _split_tool_result(block, vision)
                messages.append({"role": "tool", "tool_call_id": block["tool_use_id"], "content": text})
                parts.extend({"type": "image_url", "image_url": {"url": _data_url(image)}} for image in images)
            elif block.get("type") == "text":
                parts.append({"type": "text", "text": block.get("text", "")})
            elif block.get("type") == "image":
                parts.append({"type": "image_url", "image_url": {"url": _data_url(block)}} if vision else {"type": "text", "text": NO_VISION})
        if parts:
            messages.append({"role": "user", "content": parts})
    # No limit on length and no asking for usage. Servers disagree on how to ask, and may refuse what they don't know. What
    # Claude Code asks for is Claude's limit anyway, which can be more than another model allows.
    request = {"model": model, "messages": messages, "stream": True}
    tools = _tools(body)
    if tools:
        request["tools"] = [{"type": "function", "function": {"name": tool["name"], "description": tool.get("description", ""), "parameters": tool["input_schema"]}} for tool in tools]
        choice = body.get("tool_choice", {}).get("type")
        if choice == "any":
            request["tool_choice"] = "required"
        elif choice == "tool":
            request["tool_choice"] = {"type": "function", "function": {"name": body["tool_choice"]["name"]}}
        elif choice == "none":
            request["tool_choice"] = "none"
    return request


class Reply:
    """Builds Anthropic's stream of events. Only one block can be open at a time, and a tool call goes out whole, so
    several calls arriving at once can't get tangled. Text goes out as it comes."""

    def __init__(self, model):
        self.model = model
        self.index = -1
        self.text_open = False
        self.used_tool = False
        self.finished = False
        self.status = 502
        self.events = [("message_start", {"type": "message_start", "message": {
            "id": f"msg_{uuid.uuid4().hex}", "type": "message", "role": "assistant", "model": model, "content": [],
            "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": 0, "output_tokens": 0}}})]

    def take(self):
        events, self.events = self.events, []
        return events

    def text(self, delta):
        if not delta:
            return
        if not self.text_open:
            self.index += 1
            self.text_open = True
            self.events.append(("content_block_start", {"type": "content_block_start", "index": self.index, "content_block": {"type": "text", "text": ""}}))
        self.events.append(("content_block_delta", {"type": "content_block_delta", "index": self.index, "delta": {"type": "text_delta", "text": delta}}))

    def close_text(self):
        if self.text_open:
            self.events.append(("content_block_stop", {"type": "content_block_stop", "index": self.index}))
            self.text_open = False

    def tool(self, call_id, name, arguments):
        self.close_text()
        self.index += 1
        self.used_tool = True
        self.events.append(("content_block_start", {"type": "content_block_start", "index": self.index,
                                                    "content_block": {"type": "tool_use", "id": call_id or f"toolu_{uuid.uuid4().hex}", "name": name, "input": {}}}))
        self.events.append(("content_block_delta", {"type": "content_block_delta", "index": self.index, "delta": {"type": "input_json_delta", "partial_json": arguments or "{}"}}))
        self.events.append(("content_block_stop", {"type": "content_block_stop", "index": self.index}))

    def finish(self, input_tokens=0, output_tokens=0, too_long=False):
        if self.finished:
            return
        self.finished = True
        self.close_text()
        reason = "max_tokens" if too_long else "tool_use" if self.used_tool else "end_turn"
        self.events.append(("message_delta", {"type": "message_delta", "delta": {"stop_reason": reason, "stop_sequence": None},
                                              "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens}}))
        self.events.append(("message_stop", {"type": "message_stop"}))

    def error(self, message, status=502):
        self.finished = True
        self.status = status
        self.events.append(("error", {"type": "error", "error": {"type": "api_error", "message": str(message)[:500]}}))


class ResponsesReader:
    def __init__(self, reply):
        self.reply = reply

    def feed(self, event):
        kind = event.get("type", "")
        if kind == "response.output_text.delta":
            self.reply.text(event.get("delta", ""))
        elif kind == "response.output_item.done":
            item = event.get("item", {})
            if item.get("type") == "function_call":
                self.reply.tool(item.get("call_id") or item.get("id"), item.get("name"), item.get("arguments"))
        elif kind in ("response.completed", "response.incomplete"):
            response = event.get("response", {})
            usage = response.get("usage") or {}
            too_long = (response.get("incomplete_details") or {}).get("reason") == "max_output_tokens"
            self.reply.finish(usage.get("input_tokens", 0), usage.get("output_tokens", 0), too_long)
        elif kind in ("response.failed", "error"):
            failure = event.get("response", {}).get("error") or event.get("error") or event
            self.reply.error(failure.get("message", failure) if isinstance(failure, dict) else failure)

    def done(self):
        self.reply.finish()


class ChatReader:
    """Claude Code goes by usage to know when to compact a builder's history, so a server that doesn't report it gets a rough figure."""

    def __init__(self, reply, sent=0):
        self.reply = reply
        self.calls = {}
        self.too_long = False
        self.usage = {}
        self.sent = sent
        self.written = 0

    def feed(self, event):
        self.usage = event.get("usage") or self.usage
        for choice in event.get("choices") or []:
            delta = choice.get("delta") or {}
            self.reply.text(delta.get("content"))
            self.written += len(delta.get("content") or "")
            for call in delta.get("tool_calls") or []:
                held = self.calls.setdefault(call.get("index", 0), {"id": None, "name": None, "arguments": ""})
                held["id"] = call.get("id") or held["id"]
                function = call.get("function") or {}
                held["name"] = function.get("name") or held["name"]
                held["arguments"] += function.get("arguments") or ""
                self.written += len(function.get("arguments") or "")
            if choice.get("finish_reason") == "length":
                self.too_long = True

    def done(self):
        for _, call in sorted(self.calls.items()):
            self.reply.tool(call["id"], call["name"], call["arguments"])
        self.calls = {}
        self.reply.finish(self.usage.get("prompt_tokens") or self.sent // CHARS_PER_TOKEN, self.usage.get("completion_tokens") or self.written // CHARS_PER_TOKEN, self.too_long)


def collected(events):
    """The same answer as one message, for a caller that didn't ask for a stream."""
    blocks = {}
    message = {}
    for name, data in events:
        if name == "message_start":
            message = data["message"]
        elif name == "content_block_start":
            blocks[data["index"]] = dict(data["content_block"])
        elif name == "content_block_delta":
            delta = data["delta"]
            block = blocks[data["index"]]
            if delta["type"] == "text_delta":
                block["text"] += delta["text"]
            else:
                block["_json"] = block.get("_json", "") + delta["partial_json"]
        elif name == "message_delta":
            message.update(data["delta"])
            message["usage"] = data["usage"]
    content = []
    for _, block in sorted(blocks.items()):
        if "_json" in block:
            block["input"] = json.loads(block.pop("_json") or "{}")
        content.append(block)
    message["content"] = content
    return message


class ModelBridge:
    def __init__(self, url, key, model, api=RESPONSES, vision=False, port=8791):
        self.url = url.rstrip("/")
        self.key = key
        self.model = model
        self.api = api
        self.vision = vision
        self.port = port
        self.password = secrets.token_urlsafe(32)
        self.failed_at = 0
        self.worked_at = 0

    def is_down(self):
        return self.failed_at > self.worked_at and time.monotonic() - self.failed_at < DOWN_SECONDS

    def client_env(self):
        """What a builder's Claude Code needs to use this. The empty one stops it sending the owner's login here."""
        return {"ANTHROPIC_BASE_URL": f"http://127.0.0.1:{self.port}", "ANTHROPIC_AUTH_TOKEN": self.password,
                "ANTHROPIC_API_KEY": "", "CLAUDE_CODE_OAUTH_TOKEN": ""}

    def _allowed(self, request):
        offered = request.headers.get("x-api-key") or request.headers.get("authorization", "").removeprefix("Bearer ")
        return hmac.compare_digest(offered, self.password)

    def _upstream(self, translated):
        path = "/responses" if self.api == RESPONSES else "/chat/completions"
        return urllib.request.Request(self.url + path, data=json.dumps(translated).encode(), method="POST", headers={
            "Content-Type": "application/json", "Accept": "text/event-stream", **({"Authorization": f"Bearer {self.key}"} if self.key else {})})

    def _failed(self, reply, message, code):
        """Claude Code waits and tries again after a 429 or a 5xx, and gives up straight away on anything else, like a wrong key."""
        if code not in ABOUT_THE_REQUEST:
            self.failed_at = time.monotonic()
        if self.key:
            message = message.replace(self.key, "[the key]")
        print(message[:500], flush=True)
        reply.error(message, code if code == 429 or code >= 500 else 400)

    def _pump(self, upstream, reader, reply, queue, loop):
        """Reads the model's stream on a thread, because the standard library's client blocks."""
        def send(events):
            asyncio.run_coroutine_threadsafe(queue.put(events), loop).result()
        try:
            with urllib.request.urlopen(upstream, timeout=READ_TIMEOUT_SECONDS) as stream:
                self.worked_at = time.monotonic()
                for line in stream:
                    if not line.startswith(b"data:"):
                        continue
                    data = line[5:].strip()
                    if data == b"[DONE]":
                        break
                    reader.feed(json.loads(data))
                    if reply.events:
                        send(reply.take())
            reader.done()
        except urllib.error.HTTPError as error:
            self._failed(reply, f"The model's server said {error.code}: {error.read()[:300].decode('utf-8', 'replace')}", error.code)
        except (OSError, ValueError, http.client.HTTPException) as error:
            self._failed(reply, f"Couldn't reach the model's server: {error}", 502)
        send(reply.take())
        send(None)

    async def messages(self, request):
        if not self._allowed(request):
            return JSONResponse({"type": "error", "error": {"type": "authentication_error", "message": "Not for you."}}, status_code=401)
        body = await request.json()
        translated = (to_responses if self.api == RESPONSES else to_chat)(body, self.model, self.vision)
        reply = Reply(body.get("model", self.model))
        # Pictures say next to nothing about how many tokens they take.
        reader = ResponsesReader(reply) if self.api == RESPONSES else ChatReader(reply, len(re.sub(r'data:[^"]*', "", json.dumps(translated))))
        queue = asyncio.Queue()
        threading.Thread(target=self._pump, args=(self._upstream(translated), reader, reply, queue, asyncio.get_running_loop()), daemon=True).start()
        first = await queue.get()
        failure = next((data for name, data in first if name == "error"), None)
        if failure:
            # Nothing's been sent yet, so Claude Code can be given a real status and know whether to try again.
            return JSONResponse(failure, status_code=reply.status)

        async def events():
            batch = first
            while batch is not None:
                for event in batch:
                    yield event
                batch = await queue.get()

        if body.get("stream"):
            async def stream():
                async for name, data in events():
                    yield f"event: {name}\ndata: {json.dumps(data)}\n\n"
            return StreamingResponse(stream(), media_type="text/event-stream")
        everything = [event async for event in events()]
        failure = next((data for name, data in everything if name == "error"), None)
        return JSONResponse(failure, status_code=reply.status) if failure else JSONResponse(collected(everything))

    async def count_tokens(self, request):
        if not self._allowed(request):
            return JSONResponse({}, status_code=401)
        # Only used to judge when to compact, so a rough figure will do.
        return JSONResponse({"input_tokens": len(await request.body()) // 4})

    def app(self):
        return Starlette(routes=[Route("/v1/messages", self.messages, methods=["POST"]),
                                 Route("/v1/messages/count_tokens", self.count_tokens, methods=["POST"])])


class _Quiet(uvicorn.Server):
    """The agent has its own way of being stopped, so a web server mustn't take over its signals."""

    @contextlib.contextmanager
    def capture_signals(self):
        yield


async def serve(app, host, port, name):
    """Runs alongside everything else. Not being able to listen mustn't take the rest of the agent down with it."""
    try:
        await _Quiet(uvicorn.Config(app, host=host, port=port, lifespan="off", log_level="warning", access_log=False)).serve()
    except (SystemExit, OSError) as error:
        print(f"{name} couldn't start listening on port {port}: {error}", flush=True)

