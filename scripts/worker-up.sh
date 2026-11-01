#!/bin/bash
# Runs builders on this machine for the main server. Needs Docker and a checkout at the same commit as the server.
# Your token and any model key are asked for once, stored where only root can read them, and never shown.
# Usage: ./scripts/worker-up.sh <https://server> <slots> <self_hosted|claude>
set -euo pipefail
cd "$(dirname "$0")/.."

hub=${1:?Give the main server\'s address, like https://203.0.113.5}
slots=${2:-2}
lane=${3:-self_hosted}
dir=${WORKER_DIR:-$PWD/runtime-worker}
mkdir -p "$dir/secrets" "$dir/workspace"
chmod 700 "$dir/secrets"
env_file="$dir/worker.env"
hub_host=$(python3 -c 'import sys, urllib.parse; print(urllib.parse.urlsplit(sys.argv[1]).hostname)' "$hub")
hub_port=$(python3 -c 'import sys, urllib.parse; print(urllib.parse.urlsplit(sys.argv[1]).port or "")' "$hub")

ask_secret() {
  local file=$1 prompt=$2 value
  if [[ ! -s "$file" ]]; then
    read -r -s -p "$prompt (not shown): " value
    echo
    (umask 077 && printf '%s\n' "$value" >"$file")
  fi
}
ask_secret "$dir/secrets/worker_token.secret" "This machine's token, from add-worker.sh"
touch "$dir/secrets/model_key.secret" "$dir/secrets/claude_token.secret"

model_host="" model_port=""
{
  echo "WORKER_DIR=$dir"
  echo "WORKER_HUB_URL=$hub"
  echo "WORKER_SLOTS=$slots"
  echo "WORKER_LANE=$lane"
  if [[ "$lane" == "self_hosted" ]]; then
    read -r -p "The model's base URL, up to and including /v1: " url
    read -r -p "The model's name, as its server knows it: " model
    read -r -p "Which API it speaks, responses or chat [responses]: " api
    read -r -p "Can it see images? y or n [n]: " vision
    read -r -p "How many tokens it can hold in one conversation [128000]: " context
    ask_secret "$dir/secrets/model_key.secret" "Its API key, or nothing if it has none"
    model_host=$(python3 -c 'import sys, urllib.parse; print(urllib.parse.urlsplit(sys.argv[1]).hostname)' "$url")
    model_port=$(python3 -c 'import sys, urllib.parse; print(urllib.parse.urlsplit(sys.argv[1]).port or "")' "$url")
    echo "AGENT_SELFHOSTED_URL=$url"
    echo "AGENT_SELFHOSTED_MODEL=$model"
    echo "AGENT_SELFHOSTED_API=${api:-responses}"
    echo "AGENT_SELFHOSTED_BUILDERS=$slots"
    echo "AGENT_SELFHOSTED_VISION=$([[ "$vision" == y* ]] && echo 1 || echo)"
    echo "AGENT_SELFHOSTED_CONTEXT=${context:-128000}"
  else
    ask_secret "$dir/secrets/claude_token.secret" "A Claude login token from claude setup-token"
  fi
  echo "EGRESS_EXTRA_HOSTS=\"$hub_host $model_host\""
  echo "EGRESS_EXTRA_PORTS=\"$hub_port $model_port\""
} >"$env_file"
# The agent's user has to be able to write here. Docker can do this whatever user runs this script.
docker run --rm -v "$dir/workspace:/w" alpine:3.22 sh -c 'chown 1000:1000 /w && chmod 2775 /w' </dev/null

docker compose --project-directory infra --env-file versions.env --env-file "$env_file" -f infra/worker.yaml up -d --build
echo "Started. See how it's doing with: docker logs -f livingmod-worker-worker-1"
