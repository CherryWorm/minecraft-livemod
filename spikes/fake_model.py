#!/usr/bin/env python3
"""A stand-in for a self-hosted model, for broker/tests/m21_test.py. It speaks the Responses API and Chat Completions, does
what its script says, and writes down everything it's sent, so the test can see exactly what reaches a model's server.

Usage: python3 fake_model.py <script.json> <log.jsonl>
"""
import http.server
import json
import socketserver
import sys
import threading

SCRIPT = json.load(open(sys.argv[1], encoding="utf-8"))
LOG = sys.argv[2]
LOCK = threading.Lock()


def tool_outputs(body):
    """The answers it's been given so far, whichever API it's being spoken to in."""
    if "input" in body:
        return [item["output"] for item in body["input"] if item.get("type") == "function_call_output"]
    return [message["content"] for message in body.get("messages", []) if message.get("role") == "tool"]


def step_for(body):
    text = json.dumps(body.get("instructions", "")) + json.dumps(body.get("messages", [{}])[0])
    # Requests with no tools are Claude Code's own small errands, and a helper's job is done as soon as it's asked.
    if not body.get("tools") or "HELPER-MARKER" in text:
        return {"text": "ok"}
    done = len(tool_outputs(body))
    return SCRIPT[done] if done < len(SCRIPT) else {"text": "done"}


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        with LOCK, open(LOG, "a", encoding="utf-8") as stream:
            stream.write(json.dumps({"path": self.path, "authorization": self.headers.get("Authorization"), "api_key": self.headers.get("x-api-key"), "model": body.get("model"),
                                     "tools": len(body.get("tools") or []), "outputs": tool_outputs(body), "request": json.dumps(body)[:200000]}) + "\n")
        step = step_for(body)
        self.send_response(200)
        if not self.path.endswith("/responses"):
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(chat_answer(step)).encode())
            return
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for event in responses_events(step):
            self.wfile.write(f"data: {json.dumps(event)}\n\n".encode())
            self.wfile.flush()


def responses_events(step):
    yield {"type": "response.created", "response": {"id": "r1"}}
    if "tool" in step:
        call = {"type": "function_call", "id": "fc1", "call_id": f"call_{abs(hash(json.dumps(step))) % 10**8}", "name": step["tool"], "arguments": json.dumps(step["input"])}
        yield {"type": "response.output_item.added", "item": {**call, "arguments": ""}}
        yield {"type": "response.function_call_arguments.delta", "delta": call["arguments"]}
        yield {"type": "response.output_item.done", "item": call}
    else:
        yield {"type": "response.output_text.delta", "delta": step["text"][:1]}
        yield {"type": "response.output_text.delta", "delta": step["text"][1:]}
    yield {"type": "response.completed", "response": {"usage": {"input_tokens": 10, "output_tokens": 5}}}


def chat_answer(step):
    message = {"role": "assistant", "content": step.get("text", ""), "reasoning_content": "thinking"}
    if "tool" in step:
        arguments = json.dumps(step["input"])
        message["tool_calls"] = [{"id": f"call_{abs(hash(arguments)) % 10**8}", "type": "function", "function": {"name": step["tool"], "arguments": arguments}}]
    return {"choices": [{"index": 0, "message": message, "finish_reason": "tool_calls" if "tool" in step else "stop"}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}}


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


Server(("0.0.0.0", 9000), Handler).serve_forever()
