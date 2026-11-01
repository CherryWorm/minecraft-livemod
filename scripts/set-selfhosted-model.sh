#!/bin/bash
# Sets up builders on a self-hosted model, with its key stored so that only root can read it.
# Run this yourself, as root: the key is your credential and never needs to pass through anyone else.
# Usage: sudo ./scripts/set-selfhosted-model.sh
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a

if [[ $EUID -ne 0 ]]; then
  echo "Run this as root."
  exit 1
fi

read -r -p "The model's base URL, up to and including /v1 (like https://gpu.example.com/v1): " url
read -r -p "The model's name, as its server knows it: " model
read -r -p "Which API it speaks, responses (as Codex uses) or chat [responses]: " api
api=${api:-responses}
read -r -p "How many builders it can serve at once [2]: " builders
builders=${builders:-2}
read -r -p "Can it see images? y or n [n]: " vision
read -r -p "How many tokens it can hold in one conversation [128000]: " context
context=${context:-128000}
read -r -s -p "Its API key, or nothing if it has none (not shown): " key
echo

secret="$RUNTIME_DIR/secrets/model_key.secret"
(umask 077 && printf '%s\n' "$key" >"$secret")
chown root:root "$secret"
chmod 400 "$secret"

host=$(python3 -c 'import sys, urllib.parse; print(urllib.parse.urlsplit(sys.argv[1]).hostname)' "$url")
port=$(python3 -c 'import sys, urllib.parse; print(urllib.parse.urlsplit(sys.argv[1]).port or "")' "$url")
set_value() {
  if grep -q "^$1=" .env; then
    sed -i "s|^$1=.*|$1=$2|" .env
  else
    echo "$1=$2" >>.env
  fi
}
set_value AGENT_SELFHOSTED_URL "$url"
set_value AGENT_SELFHOSTED_MODEL "$model"
set_value AGENT_SELFHOSTED_API "$api"
set_value AGENT_SELFHOSTED_BUILDERS "$builders"
set_value AGENT_SELFHOSTED_VISION "$([[ "$vision" == y* ]] && echo 1 || echo)"
set_value AGENT_SELFHOSTED_CONTEXT "$context"
set_value EGRESS_EXTRA_HOSTS "$host"
set_value EGRESS_EXTRA_PORTS "$port"

echo "Saved. Start it with ./scripts/agent-up.sh as the user who runs the agent."
