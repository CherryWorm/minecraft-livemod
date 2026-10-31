"""Protects the owner's plan limits and the kill switch. Plain code, so nothing in chat can argue with it.

Rate limit events say allowed, warning or rejected, but rarely how much is left, so pacing comes from a
running estimate kept here. The estimate is in dollars only because that's what the SDK reports. On a
plan it's a measure of usage, not a bill.
"""
import json
import os
import pathlib
import time

STATE_ROOT = pathlib.Path(os.environ.get("WORKSPACE", "/workspace")) / "state"
CONTROL = pathlib.Path(os.environ.get("CONTROL_DIR", "/control"))

DAILY_USAGE_LIMIT = float(os.environ.get("AGENT_DAILY_USAGE_LIMIT", "25"))
MAX_BUILDERS = int(os.environ.get("AGENT_MAX_BUILDERS", "2"))
FAILURE_LIMIT = 5
FAILURE_PAUSE_SECONDS = 30 * 60
IDLE_AFTER_SECONDS = 2 * 24 * 60 * 60


class Governor:
    def __init__(self):
        self.path = STATE_ROOT / "governor.json"
        self.state = {"day": "", "usage": 0.0, "paused_until": 0, "last_warning": 0, "failures": 0, "last_player_seen": 0}
        self.owner_stopped = False  # Set from the game, which is what actually enforces it.
        if self.path.exists():
            self.state.update(json.loads(self.path.read_text(encoding="utf-8")))

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.state, indent=1), encoding="utf-8")

    def _roll_day(self):
        today = time.strftime("%Y-%m-%d", time.gmtime())
        if self.state["day"] != today:
            self.state["day"] = today
            self.state["usage"] = 0.0

    def record_usage(self, estimate):
        self._roll_day()
        self.state["usage"] += float(estimate or 0)
        self._save()

    def record_rate_limit(self, status, resets_at):
        """rejected means stop until the reset. A warning means slow down well before reaching it."""
        if status == "rejected":
            self.state["paused_until"] = int(resets_at or (time.time() + 1800))
        elif status == "allowed_warning":
            self.state["last_warning"] = int(time.time())
        self._save()

    def record_gate_result(self, passed):
        self.state["failures"] = 0 if passed else self.state["failures"] + 1
        if self.state["failures"] >= FAILURE_LIMIT:
            self.state["building_paused_until"] = int(time.time()) + FAILURE_PAUSE_SECONDS
            self.state["failures"] = 0
        self._save()

    def player_seen(self):
        self.state["last_player_seen"] = int(time.time())
        self._save()

    def killed(self):
        return self.owner_stopped or (CONTROL / "agent_disabled").exists()

    def why_not_speak(self):
        """Talking is cheap, so it only stops for the kill switch or a hard limit."""
        if self.killed():
            return "kill switch"
        if time.time() < self.state["paused_until"]:
            return "paused until limits reset"
        return None

    def why_not_build(self):
        """Returns the reason building should wait, or None if it can go ahead."""
        self._roll_day()
        reason = self.why_not_speak()
        if reason:
            return reason
        # A run of failed builds shouldn't silence the character, so this only stops building.
        if time.time() < self.state.get("building_paused_until", 0):
            return "too many failed attempts in a row"
        if self.state["usage"] >= DAILY_USAGE_LIMIT:
            return f"daily usage estimate reached ({self.state['usage']:.2f})"
        seen = self.state["last_player_seen"]
        if seen and time.time() - seen > IDLE_AFTER_SECONDS:
            return "nobody has played for two days"
        return None

    def builders_allowed(self):
        """Parallel work uses limits faster, so a recent warning drops it to one builder at a time."""
        recently_warned = time.time() - self.state["last_warning"] < 3600
        return 1 if recently_warned else MAX_BUILDERS
