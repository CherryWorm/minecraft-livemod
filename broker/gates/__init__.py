"""Release gates, in the order they run. Each raises GateFailed with a message the agent can act on."""


class GateFailed(Exception):
    def __init__(self, gate, message):
        super().__init__(f"{gate}: {message}")
        self.gate = gate
        self.message = message
