#!/bin/sh
# Starts the proxy, adding a self-hosted model's address or the main server's to what it allows, if there is one.
set -eu

filter=/etc/tinyproxy/allowed-hosts
config=/etc/tinyproxy/tinyproxy.conf
if [ -n "${EGRESS_EXTRA_HOSTS:-}${EGRESS_EXTRA_PORTS:-}" ]; then
  # The image's files are read-only, so these go where the proxy can write.
  cp "$filter" /run/tinyproxy/allowed-hosts
  sed "s|^Filter .*|Filter \"/run/tinyproxy/allowed-hosts\"|" "$config" >/run/tinyproxy/tinyproxy.conf
  config=/run/tinyproxy/tinyproxy.conf
  for host in ${EGRESS_EXTRA_HOSTS:-}; do
    printf '^%s$\n' "$(printf '%s' "$host" | sed 's/\./\\./g')" >>/run/tinyproxy/allowed-hosts
  done
  for port in ${EGRESS_EXTRA_PORTS:-}; do
    echo "ConnectPort $port" >>"$config"
  done
fi
exec tinyproxy -d -c "$config"
