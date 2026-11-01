"""Every model call goes through here, so usage is always counted and limits are always respected."""
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
    "dm": {"model": "claude-haiku-5-5", "effort": "low"},
    "watcher": {"model": "claude-haiku-5-5", "effort": "low"},
    "director": {"model": "claude-opus-5-5", "effort": "medium"},
    "builder": {"model": "claude-opus-5-5", "effort": "medium"},
    "reviewer": {"model": "claude-opus-5-5", "effort": "medium"},
    "researcher": {"model": "claude-haiku-5-5", "effort": "low"},
    "director_quick": {"model": "claude-sonnet-5-5", "effort": "low"},
    "small_builder": {"model": "claude-sonnet-5-5", "effort": "medium"},
    "news": {"model": "claude-haiku-5-5", "effort": "low"},
    "teaser": {"model": "claude-haiku-5-5", "effort": "low"},
    "mind": {"model": "claude-haiku-5-5", "effort": "low"},
    "icon": {"model": "claude-opus-5-5", "effort": "medium"},
    "bug_investigator": {"model": "claude-opus-5-5", "effort": "medium"},
    "bug_fixer": {"model": "claude-opus-5-5", "effort": "medium"},
    "artist": {"model": "claude-opus-5-5", "effort": "low"},
    "modeller": {"model": "claude-opus-5-5", "effort": "medium"},
}
WORKER = {"model": "claude-opus-5-5", "effort": "low"}
MOVED = {}  # The roles the owner has moved off Claude, and the lane each now runs on.
SPEAKERS = ("interviewer", "triage", "dm", "watcher", "news", "teaser", "mind")  # Players are waiting on these, so Claude answers if the other model can't.


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


def moved(role):
    """The lane a role runs on if the owner has moved it. While that model's down, it runs on Claude."""
    lane = MOVED.get(role)
    return lane if lane and not lane.is_down() else None


async def ask(governor: Governor, role, prompt, *, lane=None, **options):
    """Runs one conversation turn for a role. By default it can use no tools at all, and it runs on Claude unless given a lane or moved."""
    lane = lane or moved(role)
    if lane is None or role not in SPEAKERS:
        return await _ask(governor, role, prompt, lane=lane, **options)
    try:
        result = await _ask(governor, role, prompt, lane=lane, **options)
        if not result.is_error and (result.structured is not None or not options.get("schema")):
            return result
        print(f"{role} got no answer from the other model: {result.stop_reason}", flush=True)
    except Exception as error:  # noqa: BLE001 - whatever went wrong there, Claude can still answer
        print(f"{role} got no answer from the other model: {type(error).__name__}", flush=True)
    return await _ask(governor, role, prompt, lane=None, **options)


async def _ask(governor, role, prompt, *, system=None, schema=None, resume=None, tools=None,
               allowed_tools=None, disallowed_tools=None, cwd=None, agents=None, max_turns=4, mcp_servers=None,
               permission_mode="dontAsk", budget=None, env=None, lane=None):
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
        # Budgets are the plan's. Claude Code prices another model as Claude with no cache, so one would stop it far too soon, and the turn limit still holds.
        max_budget_usd=None if lane and not lane.counted else budget,
        env={**(env or {}), **(lane.env if lane else {})},
        output_format={"type": "json_schema", "schema": schema} if schema else None,
    )
    started = time.monotonic()
    final = None
    async for message in query(prompt=prompt, options=options):
        if isinstance(message, RateLimitEvent) and lane is None:
            info = message.rate_limit_info
            governor.record_rate_limit(info.status, info.resets_at)
        elif isinstance(message, ResultMessage):
            final = message
    seconds = round(time.monotonic() - started, 1)
    if final is None:
        return Result("", None, "", 0.0, True, "no_result", seconds)
    # What Claude Code estimates for a model it doesn't know says nothing about the plan, which this doesn't touch.
    if lane is None or lane.counted:
        governor.record_usage(final.total_cost_usd)
    TIMELINE.parent.mkdir(parents=True, exist_ok=True)
    with TIMELINE.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"at": time.time(), "role": role, "seconds": seconds, "estimate": final.total_cost_usd,
                                 "error": final.is_error, "stop": final.stop_reason, **({"lane": lane.name} if lane else {})}) + "\n")
    return Result(final.result or "", final.structured_output, final.session_id, final.total_cost_usd or 0.0,
                  final.is_error, final.stop_reason or "", seconds)
