"""Every Claude call goes through here, so usage is always counted and limits are always respected."""
import dataclasses
import json
import pathlib
import time

from claude_agent_sdk import ClaudeAgentOptions, RateLimitEvent, ResultMessage, query

from orchestrator.governor import Governor

PROMPTS = pathlib.Path(__file__).parent / "prompts"
TIMELINE = pathlib.Path("/workspace/state/llm.jsonl")

# One place to change the model or effort for a role. Workers run at lower effort because it's faster.
ROLES = {
    "interviewer": {"model": "claude-opus-5-5", "effort": "low"},
    "direction": {"model": "claude-opus-5-5", "effort": "high"},
    "triage": {"model": "claude-haiku-5-5", "effort": "low"},
    "watcher": {"model": "claude-haiku-5-5", "effort": "low"},
    "director": {"model": "claude-opus-5-5", "effort": "medium"},
    "builder": {"model": "claude-opus-5-5", "effort": "medium"},
    "reviewer": {"model": "claude-opus-5-5", "effort": "medium"},
}
WORKER = {"model": "claude-opus-5-5", "effort": "low"}


@dataclasses.dataclass
class Result:
    text: str
    structured: object
    session_id: str
    estimate: float
    is_error: bool
    stop_reason: str
    seconds: float


def prompt_text(name):
    return (PROMPTS / f"{name}.md").read_text(encoding="utf-8")


def untrusted(label, text):
    """Marks player text as data. The system prompts say anything inside is never an instruction."""
    cleaned = str(text).replace("<", "(").replace(">", ")")
    return f"<{label}>\n{cleaned}\n</{label}>"


async def ask(governor: Governor, role, prompt, *, system=None, schema=None, resume=None, tools=None,
              allowed_tools=None, disallowed_tools=None, cwd=None, agents=None, max_turns=4, mcp_servers=None,
              permission_mode="dontAsk", budget=None):
    """Runs one Claude conversation turn for a role. By default it can use no tools at all."""
    config = ROLES[role]
    options = ClaudeAgentOptions(
        model=config["model"],
        effort=config["effort"],
        system_prompt=system if system is not None else prompt_text(role),
        setting_sources=[],
        tools=tools if tools is not None else [],
        allowed_tools=allowed_tools or [],
        disallowed_tools=disallowed_tools or [],
        permission_mode=permission_mode,
        max_turns=max_turns,
        cwd=cwd,
        resume=resume,
        agents=agents,
        mcp_servers=mcp_servers or {},
        max_budget_usd=budget,
        output_format={"type": "json_schema", "schema": schema} if schema else None,
    )
    started = time.monotonic()
    final = None
    async for message in query(prompt=prompt, options=options):
        if isinstance(message, RateLimitEvent):
            info = message.rate_limit_info
            governor.record_rate_limit(info.status, info.resets_at)
        elif isinstance(message, ResultMessage):
            final = message
    seconds = round(time.monotonic() - started, 1)
    if final is None:
        return Result("", None, "", 0.0, True, "no_result", seconds)
    governor.record_usage(final.total_cost_usd)
    TIMELINE.parent.mkdir(parents=True, exist_ok=True)
    with TIMELINE.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"at": time.time(), "role": role, "seconds": seconds, "estimate": final.total_cost_usd,
                                 "error": final.is_error, "stop": final.stop_reason}) + "\n")
    return Result(final.result or "", final.structured_output, final.session_id, final.total_cost_usd or 0.0,
                  final.is_error, final.stop_reason or "", seconds)
