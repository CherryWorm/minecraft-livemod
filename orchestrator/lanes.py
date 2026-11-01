"""Which model a builder runs on. Everything else that thinks stays on Claude: directing, reviewing, chat and minds.

Claude is the plan's limited allowance. A self-hosted model has no such limit, so it takes work on top of what Claude's
builders can do. A reviewer on Claude still has to pass everything it makes, so it can't lower what reaches players.
"""
import dataclasses
import os

from orchestrator import model_bridge

SELF_HOSTED = "self_hosted"
REMOTE = "remote"
MACHINE_GONE = ("no_worker", "worker_silent")  # An attempt that never really happened.
MODEL_KEY_FD = 5
# Keeps a builder's history within what the model can hold, because Claude Code assumes Claude's otherwise.
COMPACT_ENV = "CLAUDE_CODE_AUTO_COMPACT_WINDOW"
NO_IMAGES_NOTE = ("This model can't see images, so you can't look at art yourself. Follow assetkit's rules closely, use its palettes rather than "
                  "inventing colours, and don't ask helpers to judge how something looks. A reviewer checks the art on a real game client.\n\n")


@dataclasses.dataclass
class Lane:
    name: str
    env: dict
    counted: bool = False  # Whether it uses up the plan's allowance.
    note: str = ""


def _read_key():
    """Handed over as an open file, so the key is never in an environment that anything else could inherit or read."""
    try:
        with os.fdopen(MODEL_KEY_FD) as stream:
            return stream.read().strip()
    except OSError:
        return ""


class SelfHosted:
    """Set up from the environment, and only there at all if the owner has turned it on."""

    def __init__(self):
        self.url = os.environ.get("AGENT_SELFHOSTED_URL", "")
        self.slots = int(os.environ.get("AGENT_SELFHOSTED_BUILDERS", "0"))
        self.bridge = None
        self.lane = None
        if self.url and self.slots > 0:
            vision = os.environ.get("AGENT_SELFHOSTED_VISION", "") == "1"
            self.bridge = model_bridge.ModelBridge(self.url, _read_key(), os.environ.get("AGENT_SELFHOSTED_MODEL", ""),
                                                   os.environ.get("AGENT_SELFHOSTED_API", model_bridge.RESPONSES), vision)
            env = {**self.bridge.client_env(), COMPACT_ENV: os.environ.get("AGENT_SELFHOSTED_CONTEXT", "128000")}
            self.lane = Lane(SELF_HOSTED, env, note="" if vision else NO_IMAGES_NOTE)

    async def serve(self):
        if self.bridge:
            await model_bridge.serve(self.bridge.app(), "127.0.0.1", self.bridge.port, "the model bridge")
