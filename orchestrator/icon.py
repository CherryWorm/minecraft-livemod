"""Draws the server icon once a world has a theme. It's a nice touch rather than a need, so a failure only gets logged."""
import pathlib
import shutil

from orchestrator import llm, workshop

FOLDER = pathlib.Path("/workspace/icon")
TOOLS = ["Read", "Write", "Edit", "Glob", "Bash"]


async def make(governor):
    FOLDER.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(workshop.REPO / "bible" / "theme.md", FOLDER / "theme.md")
    for attempt in range(2):
        result = await llm.ask(governor, "icon", "Make the icon.", tools=TOOLS, allowed_tools=TOOLS, disallowed_tools=workshop.BUILDER_DENIED,
                               cwd=str(FOLDER), max_turns=30, budget=3.0)
        answer = await workshop.request("server_icon")
        if answer.get("result") == "installed":
            print(f"server icon installed: {result.text[:200]}", flush=True)
            return True
        print(f"the server icon wasn't accepted: {answer.get('reason')}", flush=True)
    return False
