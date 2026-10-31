#!/bin/bash
# docker compose with the project's pinned versions and host settings. Usage: stack.sh <compose args>
set -euo pipefail
cd "$(dirname "$0")/.."
exec docker compose --project-directory infra --env-file versions.env --env-file .env -f infra/compose.yaml "$@"
