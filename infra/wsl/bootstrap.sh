#!/bin/bash
# Prepares a fresh Ubuntu 24.04 host for the Living Mod stack.
# Runs on the dedicated WSL distro during development and on the rented server later.
# Usage (as root): bootstrap.sh [--wsl]
set -euo pipefail

SERVICE_USER=livingmod
ROOT_DIR=/srv/livingmod

apt-get update -qq
apt-get install -y -qq ca-certificates curl gnupg git jq python3 rsync zstd

if ! command -v docker >/dev/null; then
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  . /etc/os-release
  cat >/etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: ${UBUNTU_CODENAME:-$VERSION_CODENAME}
Components: stable
Signed-By: /etc/apt/keyrings/docker.asc
EOF
  apt-get update -qq
  apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin
fi

if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  useradd --create-home --shell /bin/bash "$SERVICE_USER"
fi
usermod -aG docker "$SERVICE_USER"

install -d -o "$SERVICE_USER" -g "$SERVICE_USER" "$ROOT_DIR" "$ROOT_DIR/repo" "$ROOT_DIR/runtime"

if [[ "${1:-}" == "--wsl" ]]; then
  # No Windows drives and no launching Windows programs, so nothing in this distro
  # can reach the Windows side. Windows can still reach in through wsl.exe and localhost.
  cat >/etc/wsl.conf <<EOF
[boot]
systemd=true

[user]
default=$SERVICE_USER

[interop]
enabled=false
appendWindowsPath=false

[automount]
enabled=false
mountFsTab=false
EOF
fi

systemctl enable docker >/dev/null 2>&1 || true
echo "bootstrap complete"
