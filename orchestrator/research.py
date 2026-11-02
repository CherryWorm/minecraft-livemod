"""Looks things up on the web for the roles that plan and build.

Pages can say anything, so they're only ever read by a role with web tools and nothing else: no shell, no files and
nothing private in its prompt. It's the only process given the web proxy's password. Everyone else asks it a question
and gets text back, and their own network stays limited to Anthropic.
"""
import asyncio
import hashlib
import os
import pathlib
import re

from claude_agent_sdk import create_sdk_mcp_server, tool

from orchestrator import llm, scrub, voice
from orchestrator.governor import CONTROL

SECRET_FD = 4  # Opened for us by the container's entrypoint, like the game connection's secret.
PROXY = "web:3128"
NOTES = pathlib.Path("/workspace/research")
WEB_TOOLS = ["WebSearch", "WebFetch"]
TOOL_NAME = "mcp__web__research"
SECONDS_LIMIT = 240
USAGE_LIMIT = 1.0
DESCRIPTION = ("Looks something up on the public web and returns a short answer with its sources. Takes up to a minute. Use it when "
               "the answer would change what you make: how something real works, how other mods or games handled an idea, facts "
               "a theme draws on. Finished answers are kept, so look through /workspace/research first. Questions leave this "
               "server, so never put a player's name or anything a player said in one.")


def too_private(question, names, briefs):
    """Questions go out to search engines and websites, so nothing that points back at a player may be in one."""
    lowered = question.lower()
    if any(re.search(rf"\b{re.escape(name.lower())}\b", lowered) for name in names):
        return True
    return voice.guard(question, briefs) is None


def note_path(question):
    """Named after the question, so that a builder can spot one that's already been answered."""
    normal = " ".join(question.lower().split())
    slug = re.sub(r"[^a-z0-9]+", "-", normal).strip("-")[:70]
    return NOTES / f"{slug}-{hashlib.sha256(normal.encode()).hexdigest()[:8]}.md"


class Research:
    def __init__(self, governor, private_words=lambda: (set(), [])):
        self.governor = governor
        self.private_words = private_words  # Returns the players' names and their briefs.
        try:
            with os.fdopen(SECRET_FD) as stream:
                self.secret = stream.read().strip()
                scrub.keep_out(self.secret)
        except OSError:
            self.secret = None

    def why_not(self):
        if self.secret is None:
            return "the web isn't set up here"
        if (CONTROL / "no_research").exists():
            return "the owner has turned research off"
        return self.governor.why_not_build()

    async def answer(self, question):
        """Returns the text to hand back, and whether getting it took a new search."""
        names, briefs = self.private_words()
        if too_private(question, names, briefs):
            return "That question has a player's name or private words in it. Ask without them.", False
        note = note_path(question)
        if note.exists():
            return note.read_text(encoding="utf-8"), False
        reason = self.why_not()
        if reason:
            return f"Research isn't available right now: {reason}. Go with what you know.", False

        url = f"http://research:{self.secret}@{PROXY}"
        try:
            result = await asyncio.wait_for(
                llm.ask(self.governor, "researcher", llm.untrusted("question", question), tools=WEB_TOOLS, allowed_tools=WEB_TOOLS,
                        budget=USAGE_LIMIT, env={"HTTPS_PROXY": url, "HTTP_PROXY": url}),
                SECONDS_LIMIT)
        except TimeoutError:
            return "That search took too long, so it was stopped. Go with what you know.", False
        if result.is_error or not result.text:
            print(f"research failed: {result.stop_reason} {result.text[:200]}", flush=True)
            return "That search didn't work. Go with what you know.", False
        NOTES.mkdir(parents=True, exist_ok=True)
        note.write_text(f"Question: {question}\n\n{result.text}\n", encoding="utf-8")
        return result.text, True

    def server(self, limit):
        """A tool for one job, which can only spend so long looking things up before it has to get on with the work."""
        used = 0

        @tool("research", DESCRIPTION, {"question": str})
        async def research(args):
            nonlocal used
            print("research: used research", flush=True)
            if used >= limit:
                return {"content": [{"type": "text", "text": "That's all the research this job gets. Go with what you know."}]}
            text, new = await self.answer(args["question"])
            used += 1 if new else 0
            return {"content": [{"type": "text", "text": llm.untrusted("research", text)}]}

        return create_sdk_mcp_server("web", tools=[research])
