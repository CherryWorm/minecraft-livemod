# Where the agent runs. It starts as root only long enough to read its secrets, then drops to an
# unprivileged user who can't read those files. There is no Docker socket in here.
FROM python:3.13-slim

ARG CLAUDE_AGENT_SDK_VERSION

# CLAUDE_CODE_SUBPROCESS_ENV_SCRUB runs Bash in a sandbox built on bubblewrap and socat. Without them
# Claude Code refuses to start or to run commands, which is the safe way to fail. Git and rsync are for
# the agent's own repository, and ffmpeg lets assetkit encode sounds.
RUN apt-get update -qq \
 && apt-get install -y -qq --no-install-recommends bubblewrap socat git rsync ffmpeg \
 && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir "claude-agent-sdk==${CLAUDE_AGENT_SDK_VERSION}" pillow==11.3.0 numpy==2.3.3

# Uid 1000 owns the secrets on the host. The agent shares its group, so it can use the workspace with
# the broker, but it isn't the owner of anything else.
RUN groupadd --gid 1000 livingmod \
 && useradd --uid 1001 --gid 1000 --create-home --home-dir /home/agent agent

COPY entrypoint.sh /usr/local/bin/agent-entrypoint.sh
RUN chmod 755 /usr/local/bin/agent-entrypoint.sh

WORKDIR /home/agent
ENTRYPOINT ["/usr/local/bin/agent-entrypoint.sh"]
