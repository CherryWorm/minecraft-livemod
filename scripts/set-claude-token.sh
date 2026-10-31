#!/bin/bash
# Creates the agent's Claude login token, stores it so only root can read it, and tests it.
# Run this yourself, as root: the token is your credential and never needs to pass through anyone else.
# From Windows: wsl -d livingmod -u root /srv/livingmod/repo/scripts/set-claude-token.sh
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . ./.env; . ./versions.env; set +a

if [[ $EUID -ne 0 ]]; then
  echo "Run this as root: wsl -d livingmod -u root $0"
  exit 1
fi

secret="$RUNTIME_DIR/secrets/claude_token.secret"
minimum_length=100
claude='"$(python3 -c "import claude_agent_sdk, pathlib; print(pathlib.Path(claude_agent_sdk.__file__).parent / \"_bundled\" / \"claude\")")"'

./scripts/stack.sh --profile agent build agent >/dev/null

read -r -p "Is your token still on screen from an earlier run? Type y to skip signing in, or press Enter: " skip
if [[ "$skip" != "y" ]]; then
  cat <<'EOF'

Step 1 of 2: sign in.
A link will appear below. WSL can't open your browser from here, so copy it into your browser, approve
access, then paste the code back here if asked. Your token is then printed in this window.

EOF
  ./scripts/stack.sh --profile agent run --rm --no-deps --entrypoint bash agent -c \
    "exec setpriv --reuid=1000 --regid=1000 --clear-groups env HOME=/tmp $claude setup-token"
fi

cat <<'EOF'

Step 2 of 2: store it.
Copy the WHOLE token. A long token can wrap onto several lines, so make sure you have all of them.
Paste it here, then press Enter on an empty line. Nothing will show as you paste.
EOF

token=""
while IFS= read -rs line; do
  [[ -z "$line" ]] && break
  token+="$line"
done
# Removes the line breaks and spaces a wrapped paste brings along.
token=$(printf '%s' "$token" | tr -d '[:space:]')

if [[ ! "$token" =~ ^sk-ant-oat[0-9]+-[A-Za-z0-9_-]+$ ]]; then
  echo "That doesn't look like a token, so nothing changed. It should start with sk-ant-oat."
  exit 1
fi
if [[ ${#token} -lt $minimum_length ]]; then
  echo "That's only ${#token} characters, so part of it is probably missing. Nothing changed."
  exit 1
fi

(umask 077 && printf '%s\n' "$token" >"$secret")
chown root:root "$secret"
chmod 400 "$secret"
stored_length=${#token}
unset token
echo "Stored ${stored_length} characters, readable by root only."

echo "Testing it..."
if ./scripts/stack.sh --profile agent run --rm --no-deps -T agent bash -c \
  "$claude -p 'Reply with exactly the word: working' --model claude-haiku-5-5 --max-turns 1" </dev/null; then
  echo "The token works. You can close this window, and clear the scrollback if you like."
else
  echo "Claude rejected the token. Run this again and choose to sign in, which issues a new one."
  exit 1
fi
