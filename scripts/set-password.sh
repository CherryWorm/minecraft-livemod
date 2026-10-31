#!/bin/bash
# Sets the one password for the website and the game. It makes up a good one unless you pass --ask to type your own.
# Nothing needs restarting. Everyone is asked again the next time they join, and nobody already playing is thrown out.
# Read the current one with: cat "$RUNTIME_DIR/secrets/password.secret"
# Usage: set-password.sh [--ask]
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . ./versions.env; . ./.env; set +a

if [[ "${1:-}" == "--ask" ]]; then
  read -rs -p "New password: " password
  echo
  [[ -n "$password" ]] || { echo "That's empty, so nothing changed."; exit 1; }
else
  # About 79 bits, in a shape that survives being read out and typed into a game.
  password=$(python3 -c 'import secrets; letters = "abcdefghjkmnpqrstuvwxyz23456789"; print("-".join("".join(secrets.choice(letters) for _ in range(4)) for _ in range(4)))')
fi

umask 077
mkdir -p "$RUNTIME_DIR/secrets" "$RUNTIME_DIR/site-auth"
hash=$(printf '%s\n' "$password" | docker run --rm -i "caddy:$CADDY_VERSION" caddy hash-password --bcrypt-cost 10)
# The site's container reads this as a different user.
umask 022
cat >"$RUNTIME_DIR/site-auth/auth.caddy" <<EOF
basic_auth bcrypt "Living Mod" {
	player $hash
}
EOF
umask 077
# Written in place, because the game's container has this exact file mounted.
printf '%s' "$password" | python3 scripts/password_hash.py >"$RUNTIME_DIR/secrets/game_password.secret"
printf '%s\n' "$password" >"$RUNTIME_DIR/secrets/password.secret"
unset password hash

if [[ -n "$(./scripts/stack.sh ps -q --status running site 2>/dev/null </dev/null)" ]]; then
  ./scripts/stack.sh exec -T site caddy reload --config /etc/caddy/Caddyfile </dev/null >/dev/null 2>&1
fi
echo "Password set. It's in $RUNTIME_DIR/secrets/password.secret, and the website's user name is: player"
