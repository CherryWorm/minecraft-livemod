# Where the agent runs. It starts as root only long enough to read its login token, then drops to an
# unprivileged user who can't read the token file. There is no Docker socket in here.
FROM python:3.13-slim

ARG CLAUDE_AGENT_SDK_VERSION

# CLAUDE_CODE_SUBPROCESS_ENV_SCRUB runs Bash in a sandbox built on these two. Without them Claude Code
# refuses to start or to run commands, which is the safe way to fail.
RUN apt-get update -qq \
 && apt-get install -y -qq --no-install-recommends bubblewrap socat \
 && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir "claude-agent-sdk==${CLAUDE_AGENT_SDK_VERSION}"

RUN useradd --uid 1000 --create-home --home-dir /home/agent agent

COPY entrypoint.sh /usr/local/bin/agent-entrypoint.sh
RUN chmod 755 /usr/local/bin/agent-entrypoint.sh

WORKDIR /home/agent
ENTRYPOINT ["/usr/local/bin/agent-entrypoint.sh"]
