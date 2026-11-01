"""Translating between Claude Code and a self-hosted model. A builder sees nothing different, so all of this has to be exact."""
import contextlib
import io
import json
import unittest
import urllib.error
import urllib.request
from unittest import mock

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

    def test_it_doesnt_ask_for_a_stream_because_some_servers_lose_tool_calls_in_them(self):
        self.assertIs(self.request["stream"], False)

    def test_it_only_sends_what_every_server_takes(self):
        self.assertEqual(set(self.request) - {"tools"}, {"model", "messages", "stream"})


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

    def test_a_server_that_doesnt_report_usage_gets_a_rough_figure(self):
        reader = bridge.ChatReader(self.reply, sent=400)
        reader.feed({"choices": [{"delta": {"content": "12345678"}}]})
        reader.done()
        self.assertEqual(self.reply.take()[-2][1]["usage"], {"input_tokens": 100, "output_tokens": 2})

    def test_a_whole_answer_with_a_call_and_real_usage(self):
        self.reader.whole({"choices": [{"message": {"content": "", "reasoning_content": None, "tool_calls": [{"id": "c1", "index": 0, "type": "function", "function": {"name": "Read", "arguments": "{\"path\":\"a\"}"}}]},
                                        "finish_reason": "tool_calls"}], "usage": {"prompt_tokens": 7, "completion_tokens": 9}})
        self.reader.done()
        message = bridge.collected(self.reply.take())
        self.assertEqual([block["type"] for block in message["content"]], ["tool_use"])
        self.assertEqual(message["content"][0]["input"], {"path": "a"})
        self.assertEqual(message["stop_reason"], "tool_use")
        self.assertEqual(message["usage"], {"input_tokens": 7, "output_tokens": 9})

    def test_whole_answers_with_unnumbered_calls_dont_get_them_mixed_up(self):
        calls = [{"id": name, "type": "function", "function": {"name": "Read", "arguments": "{}"}} for name in ("a", "b")]
        self.reader.whole({"choices": [{"message": {"content": "Both.", "tool_calls": calls}, "finish_reason": "tool_calls"}]})
        self.reader.done()
        self.assertEqual([block.get("id") for block in bridge.collected(self.reply.take())["content"]], [None, "a", "b"])

    def test_a_whole_answer_cut_short_says_so(self):
        self.reader.whole({"choices": [{"message": {"content": "Hel"}, "finish_reason": "length"}]})
        self.reader.done()
        self.assertEqual(self.reply.take()[-2][1]["delta"]["stop_reason"], "max_tokens")

    def test_a_refusal_in_a_successful_reply_is_a_failure(self):
        with self.assertRaisesRegex(ValueError, "Out of credit"):
            self.reader.whole({"error": {"message": "Out of credit"}})


class WhenItFails(unittest.TestCase):
    def setUp(self):
        self.bridge = bridge.ModelBridge("https://gpu.example/v1", "real-key", "m")
        self.reply = bridge.Reply("claude-opus-5-5")

    def fail(self, code, times=bridge.FAILURES_TO_BE_DOWN):
        for _ in range(times):
            self.bridge._failed(self.reply, "no", code)

    def test_it_starts_out_up(self):
        self.assertFalse(self.bridge.is_down())

    def test_claude_code_tries_again_after_what_might_pass(self):
        for code in (429, 500, 503):
            self.bridge._failed(self.reply, "no", code)
            self.assertEqual(self.reply.status, code)

    def test_claude_code_gives_up_on_what_wont(self):
        self.bridge._failed(self.reply, "no", 401)
        self.assertEqual(self.reply.status, 400)

    def test_a_wrong_key_or_an_outage_means_its_down(self):
        for code in (401, 403, 404, 502):
            self.bridge.failures = 0
            self.fail(code)
            self.assertTrue(self.bridge.is_down(), code)

    def test_one_failure_doesnt_move_everything_to_claude(self):
        self.fail(502, bridge.FAILURES_TO_BE_DOWN - 1)
        self.assertFalse(self.bridge.is_down())

    def test_being_busy_isnt_being_down(self):
        self.fail(429, 20)
        self.assertFalse(self.bridge.is_down())

    def test_bad_requests_arent_either(self):
        self.fail(400, 20)
        self.assertFalse(self.bridge.is_down())

    def test_it_tries_again_after_a_while(self):
        self.fail(502)
        self.bridge.failed_at -= bridge.DOWN_SECONDS + 1
        self.assertFalse(self.bridge.is_down())

    def test_a_server_repeating_the_key_doesnt_get_it_into_the_logs(self):
        with contextlib.redirect_stdout(io.StringIO()) as printed:
            self.bridge._failed(self.reply, "Bad key: real-key", 401)
        self.assertNotIn("real-key", printed.getvalue() + json.dumps(self.reply.take()))


class Answering(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.bridge = bridge.ModelBridge("https://gpu.example/v1", "real-key", "m", api=bridge.CHAT)

    def request(self):
        body = {"model": "claude-opus-5-5", "stream": True, "messages": [{"role": "user", "content": "Hi."}]}
        return mock.Mock(headers={"x-api-key": self.bridge.password}, json=mock.AsyncMock(return_value=body))

    async def refused_with(self, code):
        error = urllib.error.HTTPError("https://gpu.example", code, "no", {}, io.BytesIO(b"no"))
        with mock.patch.object(urllib.request, "urlopen", side_effect=error), contextlib.redirect_stdout(io.StringIO()):
            return await self.bridge.messages(self.request())

    async def test_a_limit_reaches_claude_code_as_a_limit_so_it_waits(self):
        self.assertEqual((await self.refused_with(429)).status_code, 429)

    async def test_an_outage_reaches_it_as_an_outage_so_it_tries_again(self):
        self.assertEqual((await self.refused_with(503)).status_code, 503)

    async def test_a_wrong_key_makes_it_give_up_rather_than_try_all_over_again(self):
        self.assertEqual((await self.refused_with(401)).status_code, 400)

    async def test_a_reply_that_isnt_an_answer_is_a_failure_and_not_silence(self):
        stream = mock.MagicMock()
        stream.__enter__.return_value.read.return_value = b'{"error": {"message": "Out of credit"}}'
        with mock.patch.object(urllib.request, "urlopen", return_value=stream), contextlib.redirect_stdout(io.StringIO()):
            answer = await self.bridge.messages(self.request())
        self.assertEqual(answer.status_code, 502)
        self.assertIn(b"Out of credit", answer.body)

    async def test_claude_code_still_gets_a_stream_and_working_again_clears_failures(self):
        self.bridge.failures = 99
        stream = mock.MagicMock()
        stream.__enter__.return_value.read.return_value = json.dumps({"choices": [{"message": {"content": "Hello there", "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "Read", "arguments": "{}"}}]}, "finish_reason": "tool_calls"}]}).encode()
        with mock.patch.object(urllib.request, "urlopen", return_value=stream):
            answer = await self.bridge.messages(self.request())
            sent = "".join([chunk async for chunk in answer.body_iterator])
        self.assertEqual(answer.status_code, 200)
        for piece in ("event: message_start", "Hello there", '"name": "Read"', '"stop_reason": "tool_use"', "event: message_stop"):
            self.assertIn(piece, sent)
        self.assertEqual(self.bridge.failures, 0)


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
