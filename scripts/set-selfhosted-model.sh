#!/bin/bash
# Sets up another model for builders, bug fixes and chat, with its key stored so that only root can read it. Claude Opus still
# directs, reviews and makes the art. It's only turned on once a test shows the model can do the job.
# Run this yourself, as root: the key is your credential and never needs to pass through anyone else.
# Usage: sudo ./scripts/set-selfhosted-model.sh [the model's URL]
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a

if [[ $EUID -ne 0 ]]; then
  echo "Run this as root."
  exit 1
fi

MOVED_ROLES=builder,small_builder,bug_investigator,bug_fixer,interviewer,triage,dm,watcher,news,teaser,mind

url=${1:-}
if [[ -z "$url" ]]; then
  read -r -p "The model's URL (like https://gpu.example.com/v1): " url
fi
url=${url%/}
api=""
case "$url" in
  */chat/completions) url=${url%/chat/completions}; api=chat ;;
  */responses) url=${url%/responses}; api=responses ;;
esac
if [[ -z "$api" ]]; then
  read -r -p "Which API it speaks, responses (as Codex uses) or chat [responses]: " api
  api=${api:-responses}
fi
read -r -s -p "Its API key, or nothing if it has none (not shown): " key
echo

echo "What it offers:"
# Given on standard input, because anything on a command line can be seen by everything else on this machine.
printf 'header = "Authorization: Bearer %s"\n' "$key" | curl -sS --max-time 20 --config - "$url/models" | python3 -c '
import json, sys
answer = json.load(sys.stdin)
print(answer.get("error") or "\n".join("  " + str(model.get("id")) for model in answer.get("data", [])))
' || echo "  (it wouldn't say)"
read -r -p "The model's name, as its server knows it: " model
read -r -p "Run builders, bug fixes and chat only on it, rather than Claude? y or n [y]: " moved
read -r -p "How many big builders it can run at once [8]: " builders
builders=${builders:-8}
read -r -p "Can it see images? y or n [n]: " vision
read -r -p "How many tokens it can hold in one conversation [128000]: " context
context=${context:-128000}

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
set_value AGENT_SELFHOSTED_ROLES "$([[ "$moved" == n* ]] && echo || echo "$MOVED_ROLES")"
set_value AGENT_SELFHOSTED_VISION "$([[ "$vision" == y* ]] && echo 1 || echo)"
set_value AGENT_SELFHOSTED_CONTEXT "$context"
set_value EGRESS_EXTRA_HOSTS "$host"
set_value EGRESS_EXTRA_PORTS "$port"

as_owner() {
  su - "$(stat -c %U .env)" -c "cd '$PWD' && $1"
}
echo "Testing it, which takes a minute or so. Everything keeps running as it was until this passes."
as_owner "./scripts/stack.sh --profile agent up -d --no-deps --force-recreate egress </dev/null"
if as_owner "./scripts/stack.sh --profile agent run --rm -T --no-deps agent python3 /spikes/selfhosted_check.py </dev/null"; then
  as_owner "./scripts/agent-up.sh --no-build"
  echo "It's on."
else
  set_value AGENT_SELFHOSTED_BUILDERS 0
  set_value AGENT_SELFHOSTED_ROLES ""
  echo "It couldn't do the job, so it stays off and everything's still on Claude. What it said is above."
  exit 1
fi
