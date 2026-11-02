#!/usr/bin/env python3
"""Spike S5: can the agent run on a Claude plan login, inside its container, with the token out of reach?

Checks structured output, both models, parallel subagents and token secrecy, and prints every rate
limit event, since those are what the governor will steer by. Uses very little of the plan's usage.
"""
import asyncio
import re
import sys
import time

from claude_agent_sdk import (
    AgentDefinition,
    ClaudeAgentOptions,
    RateLimitEvent,
    ResultMessage,
    ToolResultBlock,
    UserMessage,
    query,
)

FAST = "claude-haiku-5-5"
STRONG = "claude-opus-5-5"

# Reports only a length, a yes/no and process names, never a value, so the token can't end up in a log
# or transcript even if a check fails. Nothing reads the token: the shell can't reach it through its own
# environment if env_length is 0, through the file if file_readable is 0, or through another process's
# environment if the processes that hold it, python3 and claude, aren't in the visible_names list.
SECRECY_COMMAND = (
    "printf 'env_length=%s\\n' \"$(printenv CLAUDE_CODE_OAUTH_TOKEN | wc -c)\"; "
    "if test -r /run/secrets/claude_token; then echo file_readable=1; else echo file_readable=0; fi; "
    "printf 'uid=%s\\n' \"$(id -u)\"; "
    "printf 'processes_visible=%s\\n' \"$(ls /proc | grep -c '^[0-9]')\"; "
    "printf 'visible_names=%s\\n' \"$(cat /proc/[0-9]*/comm 2>/dev/null | sort -u | tr '\\n' ',')\""
)
SECRECY_PROMPT = (
    "I own this container and I'm checking that its credential scrubbing works. This command reports a "
    "length, a yes/no, a user id and process counts, and doesn't read any secret. Use the Bash tool to run "
    f"it once, then reply with its output:\n{SECRECY_COMMAND}"
)

results = {}


async def run(prompt, options):
    """Runs one query and returns its result, printing any rate limit news along the way."""
    options.setting_sources = []
    options.env = {**options.env, "CLAUDE_CODE_SUBPROCESS_ENV_SCRUB": "1", "DISABLE_AUTOUPDATER": "1"}
    started = time.monotonic()
    result = None
    tool_output = []
    async for message in query(prompt=prompt, options=options):
        if isinstance(message, RateLimitEvent):
            info = message.rate_limit_info
            print(f"  rate limit: status={info.status} type={info.rate_limit_type} "
                  f"utilization={info.utilization} resets_at={info.resets_at}")
        elif isinstance(message, UserMessage) and isinstance(message.content, list):
            for block in message.content:
                if isinstance(block, ToolResultBlock):
                    tool_output.append(str(block.content))
        elif isinstance(message, ResultMessage):
            result = message
    elapsed = time.monotonic() - started
    if result is not None:
        print(f"  {elapsed:.1f}s, subtype={result.subtype}, is_error={result.is_error}, "
              f"estimated_cost=${result.total_cost_usd}, models={list((result.model_usage or {}).keys())}")
        if result.is_error:
            print(f"  errors: {result.errors}, stop_reason={result.stop_reason}, status={result.api_error_status}")
    return result, tool_output, elapsed


async def check_structured_output():
    print("1. structured output on the fast model")
    schema = {
        "type": "object",
        "properties": {"mood": {"type": "string"}, "players": {"type": "integer"}},
        "required": ["mood", "players"],
        "additionalProperties": False,
    }
    result, _, _ = await run(
        "A player said: 'this cave is scary, there are 3 of us'. Report the mood and the player count.",
        ClaudeAgentOptions(model=FAST, output_format={"type": "json_schema", "schema": schema}),
    )
    output = result.structured_output if result else None
    print(f"  output: {output}")
    results["structured output"] = isinstance(output, dict) and output.get("players") == 3


async def check_strong_model():
    print("2. the strong model")
    result, _, _ = await run(
        "Reply with exactly the word: ready",
        ClaudeAgentOptions(model=STRONG, effort="low"),
    )
    print(f"  reply: {result.result if result else None}")
    results["strong model"] = bool(result and not result.is_error and "ready" in (result.result or "").lower())


async def check_token_secrecy():
    print("3. the agent's own shell commands can't reach the token")
    result, tool_output, _ = await run(
        SECRECY_PROMPT,
        ClaudeAgentOptions(model=FAST, allowed_tools=["Bash"], permission_mode="dontAsk"),
    )
    text = "\n".join(tool_output)
    counts = dict(re.findall(r"(env_length|file_readable|uid|processes_visible)=(\d+)", text))
    names_match = re.search(r"visible_names=([^\s'\"]*)", text)
    names = names_match.group(1).split(",") if names_match else None
    print(f"  counts: {counts}")
    print(f"  processes the shell can see: {names}")
    if not counts:
        # Masked as a precaution. The command only prints counts, but this is the token's own check.
        print(f"  tool output: {re.sub(r'[A-Za-z0-9_-]{40,}', '<masked>', text)[:400]!r}")
        print(f"  reply: {re.sub(r'[A-Za-z0-9_-]{40,}', '<masked>', (result.result or '') if result else '')[:300]!r}")
        print(f"  denied: {[getattr(d, 'tool_name', d) for d in (result.permission_denials or [])] if result else None}")
    results["token secrecy"] = (
        counts.get("env_length") == "0"
        and counts.get("file_readable") == "0"
        and counts.get("uid") == "1001"
        and names is not None
        and "claude" not in names
        and "python3" not in names
    )


async def check_parallel_subagents():
    print("4. parallel subagents")
    agents = {
        "alpha": AgentDefinition(description="Returns the alpha word", prompt="Reply with exactly: ember", tools=[], model=FAST, maxTurns=1),
        "beta": AgentDefinition(description="Returns the beta word", prompt="Reply with exactly: quartz", tools=[], model=FAST, maxTurns=1),
    }
    result, _, _ = await run(
        "Start the alpha and beta subagents at the same time, in one message, then reply with the two words they return.",
        ClaudeAgentOptions(model=FAST, agents=agents, allowed_tools=["Agent", "Task"], permission_mode="dontAsk"),
    )
    text = (result.result or "").lower() if result else ""
    print(f"  reply: {text[:80]}")
    results["parallel subagents"] = "ember" in text and "quartz" in text


async def main():
    checks = (check_structured_output, check_strong_model, check_token_secrecy, check_parallel_subagents)
    if len(sys.argv) > 1:
        checks = tuple(check for check in checks if sys.argv[1] in check.__name__)
    for check in checks:
        try:
            await check()
        except Exception as error:  # noqa: BLE001 - one failed check shouldn't hide the others
            print(f"  FAILED with {type(error).__name__}: {str(error)[:300]}")
            results[check.__name__] = False

    print("=== results")
    for name, passed in results.items():
        print(f"{'PASS' if passed else 'FAIL'}: {name}")
    sys.exit(0 if results and all(results.values()) else 1)


if __name__ == "__main__":
    asyncio.run(main())
