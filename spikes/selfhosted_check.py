#!/usr/bin/env python3
"""Whether the model you've set up can really do the job: it has to answer, call a tool, act on what the tool says, and answer
in the form it's given, which is how chat is read. Costs nothing from your plan. Run inside the agent's container, by the agent's entrypoint:

  ./scripts/stack.sh --profile agent run --rm -T --no-deps agent python3 /spikes/selfhosted_check.py
"""
import asyncio
import pathlib
import sys
import tempfile

from orchestrator import lanes, llm


class Meter:
    def record_usage(self, estimate):
        pass

    def record_rate_limit(self, status, resets_at):
        pass


async def run():
    self_hosted = lanes.SelfHosted()
    if self_hosted.lane is None:
        sys.exit("No self-hosted model is set up. Run scripts/set-selfhosted-model.sh first.")
    server = asyncio.create_task(self_hosted.serve())
    await asyncio.sleep(1)
    with tempfile.TemporaryDirectory() as folder:
        secret_word = "periwinkle"
        (pathlib.Path(folder) / "note.txt").write_text(f"The word is {secret_word}.\n", encoding="utf-8")
        result = await llm.ask(Meter(), "builder", "Read note.txt with the Read tool, then write that word on its own to word.txt with the Write tool. Then say done.",
                               system="You follow instructions exactly, using your tools.", tools=["Read", "Write"], allowed_tools=["Read", "Write"],
                               cwd=folder, max_turns=8, budget=5.0, lane=self_hosted.lane)
        written = pathlib.Path(folder) / "word.txt"
        worked = written.exists() and secret_word in written.read_text(encoding="utf-8")
    form = {"type": "object", "properties": {"reply": {"type": "string"}}, "required": ["reply"]}
    chat = await llm.ask(Meter(), "builder", "Say hello to Sam.", system="You're a friendly character.", schema=form, max_turns=3, budget=5.0, lane=self_hosted.lane)
    spoke = isinstance(chat.structured, dict) and bool(chat.structured.get("reply"))
    server.cancel()
    print(f"answered: {not result.is_error} ({result.stop_reason}), in {result.seconds}s")
    print(f"used its tools properly: {worked}")
    print(f"answered in the form it was given: {spoke}, in {chat.seconds}s")
    for answer in (result, chat):
        if answer.is_error:
            print(answer.text[:800])
    sys.exit(0 if worked and spoke else 1)


asyncio.run(run())
