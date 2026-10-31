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
# Mob minds get their own small share of the day, so chatting to creatures can't use up what building needs.
MIND_DAILY_USAGE = float(os.environ.get("AGENT_MIND_USAGE_LIMIT", str(DAILY_USAGE_LIMIT / 10)))
MINDS_PER_MINUTE = 30
FAILURE_LIMIT = 5
FAILURE_PAUSE_SECONDS = 30 * 60
IDLE_AFTER_SECONDS = 2 * 24 * 60 * 60


class Governor:
    def __init__(self):
        self.path = STATE_ROOT / "governor.json"
        self.state = {"day": "", "usage": 0.0, "paused_until": 0, "last_warning": 0, "failures": 0, "last_player_seen": 0}
        self.owner_stopped = False  # Set from the game, which is what actually enforces it.
        self.mind_calls = []
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
            self.state["mind_usage"] = 0.0

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

    def record_mind(self, estimate):
        self._roll_day()
        self.state["mind_usage"] = self.state.get("mind_usage", 0.0) + float(estimate or 0)
        self._save()

    def why_no_mind(self):
        """Returns the reason mobs should run on plain code for now, or None. It takes a call from the budget if not."""
        self._roll_day()
        reason = self.why_not_speak()
        if reason:
            return reason
        if (CONTROL / "no_minds").exists():
            return "the owner has turned minds off"
        if self.state.get("mind_usage", 0.0) >= MIND_DAILY_USAGE:
            return "the day's share for minds is used up"
        now = time.time()
        self.mind_calls = [stamp for stamp in self.mind_calls if now - stamp < 60]
        if len(self.mind_calls) >= MINDS_PER_MINUTE:
            return "too many in the last minute"
        self.mind_calls.append(now)
        return None

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
