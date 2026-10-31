#!/bin/bash
# Reads the login token as root, then runs the command as the unprivileged agent user. The token file
# is root-only, so nothing the agent runs can open it.
set -euo pipefail

token=""
if [[ -s /run/secrets/claude_token ]]; then
  token=$(tr -d '[:space:]' </run/secrets/claude_token)
fi

exec setpriv --reuid=1000 --regid=1000 --clear-groups \
  env HOME=/home/agent \
  ${token:+CLAUDE_CODE_OAUTH_TOKEN="$token"} \
  "$@"
