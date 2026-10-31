#!/bin/bash
# Reads the secrets as root, then runs the command as the unprivileged agent user. The files can't be
# opened by that user, so nothing the agent runs can read them.
set -euo pipefail

token=""
if [[ -s /run/secrets/claude_token ]]; then
  token=$(tr -d '[:space:]' </run/secrets/claude_token)
fi

# The game connection's secret is handed over as an open file, so it never appears in an environment
# that a child process could inherit or read through /proc.
if [[ -s /run/secrets/bridge ]]; then
  exec 3</run/secrets/bridge
fi

# Group-writable, so the broker can read and clean up what the agent leaves in the shared workspace.
umask 002

exec setpriv --reuid=1001 --regid=1000 --clear-groups \
  env HOME=/home/agent \
  ${token:+CLAUDE_CODE_OAUTH_TOKEN="$token"} \
  "$@"
