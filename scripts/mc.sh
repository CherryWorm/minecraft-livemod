#!/bin/bash
# Runs one server command and prints the reply. Usage: mc.sh [--server prod|shadow] <command...>
# stdin is closed on purpose: docker exec would otherwise swallow the rest of any calling script.
set -euo pipefail
server=prod
if [[ "${1:-}" == "--server" ]]; then
  server=$2
  shift 2
fi
exec "$(dirname "$0")/stack.sh" exec -T "$server" python3 /opt/mc/rcon.py "$@" </dev/null
