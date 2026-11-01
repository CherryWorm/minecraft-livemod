"""Translating between Claude Code and a self-hosted model. A builder sees nothing different, so all of this has to be exact."""
import json
import unittest

from orchestrator import model_bridge as bridge

PNG = {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "AAAA"}}
BODY = {"model": "claude-opus-5-5", "max_tokens": 100, "system": [{"type": "text", "text": "Be good."}],
        "tools": [{"name": "Read", "description": "Reads", "input_schema": {"type": "object"}}, {"type": "web_search_20250305", "name": "web_search"}],
        "messages": [{"role": "user", "content": "Make a thing."},
                     {"role": "assistant", "content": [{"type": "thinking", "thinking": "hm", "signature": "x"}, {"type": "text", "text": "Reading."},
                                                       {"type": "tool_use", "id": "t1", "name": "Read", "input": {"path": "a"}}]},
                     {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": [{"type": "text", "text": "It says hi."}, PNG]},
                                                  {"type": "text", "text": "Go on.", "cache_control": {"type": "ephemeral"}}]}]}


def names(events):
    return [name for name, _ in events]


class ToResponses(unittest.TestCase):
    def setUp(self):
        self.request = bridge.to_responses(BODY, "local-model", vision=False)

    def test_the_basics(self):
        self.assertEqual(self.request["model"], "local-model")
        self.assertEqual(self.request["instructions"], "Be good.")
        self.assertEqual(self.request["max_output_tokens"], 100)
        self.assertTrue(self.request["stream"])
        self.assertFalse(self.request["store"])

    def test_only_tools_a_model_can_call_are_offered(self):
        self.assertEqual(self.request["tools"], [{"type": "function", "name": "Read", "description": "Reads", "parameters": {"type": "object"}}])

    def test_the_history_keeps_its_order(self):
        kinds = [item.get("type") or item["role"] for item in self.request["input"]]
        self.assertEqual(kinds, ["user", "assistant", "function_call", "function_call_output", "user"])

    def test_a_call_and_its_answer_stay_matched(self):
        call, answer = self.request["input"][2], self.request["input"][3]
        self.assertEqual(call["call_id"], answer["call_id"])
        self.assertEqual(json.loads(call["arguments"]), {"path": "a"})

    def test_a_model_that_cant_see_is_told_so(self):
        self.assertIn("can't see images", self.request["input"][3]["output"])
        self.assertNotIn("input_image", json.dumps(self.request))

    def test_a_model_that_can_see_gets_the_image_from_the_user(self):
        request = bridge.to_responses(BODY, "local-model", vision=True)
        self.assertEqual(request["input"][-1]["content"][0], {"type": "input_image", "image_url": "data:image/png;base64,AAAA"})

    def test_nothing_only_claude_understands_gets_through(self):
        text = json.dumps(self.request)
        for word in ("cache_control", "signature", "thinking", "web_search"):
            self.assertNotIn(word, text)

    def test_choosing_a_tool(self):
        self.assertEqual(bridge.to_responses({**BODY, "tool_choice": {"type": "any"}}, "m", False)["tool_choice"], "required")
        self.assertEqual(bridge.to_responses({**BODY, "tool_choice": {"type": "tool", "name": "Read"}}, "m", False)["tool_choice"], {"type": "function", "name": "Read"})


class ToChat(unittest.TestCase):
    def setUp(self):
        self.request = bridge.to_chat(BODY, "local-model", vision=False)

    def test_the_history_keeps_its_order(self):
        self.assertEqual([message["role"] for message in self.request["messages"]], ["system", "user", "assistant", "tool", "user"])

    def test_a_call_and_its_answer_stay_matched(self):
        assistant, tool = self.request["messages"][2], self.request["messages"][3]
        self.assertEqual(assistant["tool_calls"][0]["id"], tool["tool_call_id"])
        self.assertEqual(assistant["content"], "Reading.")

    def test_usage_is_asked_for(self):
        self.assertTrue(self.request["stream_options"]["include_usage"])


class FromResponses(unittest.TestCase):
    def setUp(self):
        self.reply = bridge.Reply("claude-opus-5-5")
        self.reader = bridge.ResponsesReader(self.reply)

    def test_text_comes_as_it_arrives(self):
        self.reader.feed({"type": "response.output_text.delta", "delta": "Hel"})
        self.reader.feed({"type": "response.output_text.delta", "delta": "lo"})
        self.reader.feed({"type": "response.completed", "response": {"usage": {"input_tokens": 3, "output_tokens": 2}}})
        events = self.reply.take()
        self.assertEqual(names(events), ["message_start", "content_block_start", "content_block_delta", "content_block_delta", "content_block_stop", "message_delta", "message_stop"])
        self.assertEqual(events[-2][1]["delta"]["stop_reason"], "end_turn")
        self.assertEqual(events[-2][1]["usage"], {"input_tokens": 3, "output_tokens": 2})

    def test_a_tool_call_ends_the_turn_as_one(self):
        self.reader.feed({"type": "response.output_text.delta", "delta": "Let me look."})
        self.reader.feed({"type": "response.output_item.done", "item": {"type": "function_call", "call_id": "c1", "name": "Read", "arguments": "{\"path\":\"a\"}"}})
        self.reader.feed({"type": "response.completed", "response": {}})
        message = bridge.collected(self.reply.take())
        self.assertEqual(message["stop_reason"], "tool_use")
        self.assertEqual([block["type"] for block in message["content"]], ["text", "tool_use"])
        self.assertEqual(message["content"][1]["input"], {"path": "a"})
        self.assertEqual(message["content"][1]["id"], "c1")

    def test_blocks_are_numbered_in_order_and_closed(self):
        self.reader.feed({"type": "response.output_text.delta", "delta": "a"})
        self.reader.feed({"type": "response.output_item.done", "item": {"type": "function_call", "call_id": "c1", "name": "Read", "arguments": "{}"}})
        self.reader.feed({"type": "response.output_item.done", "item": {"type": "function_call", "call_id": "c2", "name": "Read", "arguments": "{}"}})
        self.reader.done()
        events = self.reply.take()
        self.assertEqual([data["index"] for name, data in events if name == "content_block_start"], [0, 1, 2])
        self.assertEqual([data["index"] for name, data in events if name == "content_block_stop"], [0, 1, 2])

    def test_running_out_of_room_says_so(self):
        self.reader.feed({"type": "response.incomplete", "response": {"incomplete_details": {"reason": "max_output_tokens"}}})
        self.assertEqual(self.reply.take()[-2][1]["delta"]["stop_reason"], "max_tokens")

    def test_a_failure_says_what_went_wrong(self):
        self.reader.feed({"type": "response.failed", "response": {"error": {"message": "Out of memory"}}})
        name, data = self.reply.take()[-1]
        self.assertEqual(name, "error")
        self.assertEqual(data["error"]["message"], "Out of memory")

    def test_it_only_finishes_once(self):
        self.reader.feed({"type": "response.completed", "response": {}})
        self.reader.done()
        self.assertEqual(names(self.reply.take()).count("message_stop"), 1)


class FromChat(unittest.TestCase):
    def setUp(self):
        self.reply = bridge.Reply("claude-opus-5-5")
        self.reader = bridge.ChatReader(self.reply)

    def test_a_tool_call_in_pieces_arrives_whole(self):
        self.reader.feed({"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c1", "function": {"name": "Read", "arguments": "{\"pa"}}]}}]})
        self.reader.feed({"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": "th\":\"a\"}"}}]}, "finish_reason": "tool_calls"}]})
        self.reader.feed({"choices": [], "usage": {"prompt_tokens": 7, "completion_tokens": 9}})
        self.reader.done()
        message = bridge.collected(self.reply.take())
        self.assertEqual(message["content"][0]["input"], {"path": "a"})
        self.assertEqual(message["stop_reason"], "tool_use")
        self.assertEqual(message["usage"], {"input_tokens": 7, "output_tokens": 9})

    def test_two_calls_at_once_dont_get_tangled(self):
        self.reader.feed({"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "a", "function": {"name": "Read", "arguments": "{\"n\":"}},
                                                                {"index": 1, "id": "b", "function": {"name": "Glob", "arguments": "{\"n\":"}}]}}]})
        self.reader.feed({"choices": [{"delta": {"tool_calls": [{"index": 1, "function": {"arguments": "2}"}}, {"index": 0, "function": {"arguments": "1}"}}]}}]})
        self.reader.done()
        content = bridge.collected(self.reply.take())["content"]
        self.assertEqual([(block["id"], block["input"]["n"]) for block in content], [("a", 1), ("b", 2)])

    def test_what_a_model_thinks_isnt_shown(self):
        self.reader.feed({"choices": [{"delta": {"reasoning_content": "secret plan"}}]})
        self.reader.feed({"choices": [{"delta": {"content": "Done."}, "finish_reason": "stop"}]})
        self.reader.done()
        message = bridge.collected(self.reply.take())
        self.assertEqual(message["content"], [{"type": "text", "text": "Done."}])
        self.assertEqual(message["stop_reason"], "end_turn")


class TheKey(unittest.TestCase):
    def setUp(self):
        self.bridge = bridge.ModelBridge("https://gpu.example/v1/", "real-key", "local-model")

    def test_a_builder_never_gets_the_real_key(self):
        self.assertNotIn("real-key", json.dumps(self.bridge.client_env()))

    def test_the_owners_login_is_cleared(self):
        self.assertEqual(self.bridge.client_env()["CLAUDE_CODE_OAUTH_TOKEN"], "")

    def test_the_real_key_goes_to_the_model(self):
        upstream = self.bridge._upstream({"model": "m"})
        self.assertEqual(upstream.full_url, "https://gpu.example/v1/responses")
        self.assertEqual(upstream.get_header("Authorization"), "Bearer real-key")

    def test_a_model_with_no_key_gets_no_header(self):
        self.assertIsNone(bridge.ModelBridge("http://gpu/v1", "", "m")._upstream({}).get_header("Authorization"))

    def test_chat_goes_to_its_own_path(self):
        self.assertEqual(bridge.ModelBridge("http://gpu/v1", "", "m", api=bridge.CHAT)._upstream({}).full_url, "http://gpu/v1/chat/completions")


if __name__ == "__main__":
    unittest.main()
