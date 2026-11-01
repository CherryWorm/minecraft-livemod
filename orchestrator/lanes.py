"""Which model a job runs on. Directing, reviewing and art always stay on Claude, and so does research, which needs Claude's web tools.

Claude is the plan's limited allowance, and another model doesn't have to be. Left as it comes, that model takes work on top of
what Claude's builders can do. The owner can also move roles onto it completely, so that those don't use the plan at all. A
reviewer on Claude still has to pass everything it makes, so it can't lower what reaches players.
"""
import dataclasses
import os

from orchestrator import model_bridge

SELF_HOSTED = "self_hosted"
REMOTE = "remote"
MACHINE_GONE = ("no_worker", "worker_silent")  # An attempt that never really happened.
MOVABLE = ("builder", "small_builder", "bug_investigator", "bug_fixer", "interviewer", "triage", "dm", "watcher", "news", "teaser", "mind")
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
    is_down: object = lambda: False


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
        self.roles = set(os.environ.get("AGENT_SELFHOSTED_ROLES", "").split(",")) & set(MOVABLE)
        self.bridge = None
        self.lane = None
        if self.url and self.slots > 0:
            vision = os.environ.get("AGENT_SELFHOSTED_VISION", "") == "1"
            self.bridge = model_bridge.ModelBridge(self.url, _read_key(), os.environ.get("AGENT_SELFHOSTED_MODEL", ""),
                                                   os.environ.get("AGENT_SELFHOSTED_API", model_bridge.RESPONSES), vision)
            # Claude Code can hide tools until they're asked for, in a way only Claude's service understands. It also starts every
            # request with a line for Claude's billing that changes each time, which stops another model's cache from working.
            env = {**self.bridge.client_env(), COMPACT_ENV: os.environ.get("AGENT_SELFHOSTED_CONTEXT", "128000"), "ENABLE_TOOL_SEARCH": "false", "CLAUDE_CODE_ATTRIBUTION_HEADER": "0"}
            self.lane = Lane(SELF_HOSTED, env, note="" if vision else NO_IMAGES_NOTE, is_down=self.bridge.is_down)

    def is_up(self):
        return self.lane is not None and not self.lane.is_down()

    def takes(self, role):
        """Whether a role runs here rather than on Claude. It goes back while the model's down, so the world keeps growing."""
        return self.is_up() and role in self.roles

    async def serve(self):
        if self.bridge:
            await model_bridge.serve(self.bridge.app(), "127.0.0.1", self.bridge.port, "the model bridge")
