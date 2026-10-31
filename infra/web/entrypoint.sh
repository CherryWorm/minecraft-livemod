#!/bin/sh
# Squid wants a hash rather than the password itself, so this makes one on a disk that goes away with the container.
set -eu
printf 'research:%s\n' "$(openssl passwd -apr1 -stdin </run/secrets/web_proxy)" >/run/squid/password
exec squid -N -f /etc/squid/squid.conf
