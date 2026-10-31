#!/bin/bash
# Run from Git Bash on Windows. Development only: the rented server doesn't need this.
# WSL stops a distro when no wsl.exe session is attached, even with Docker running, which would
# kill the server without saving. This holds one hidden session open, then starts the stack.
set -euo pipefail
export MSYS_NO_PATHCONV=1

powershell.exe -NoProfile -Command '
  $held = Get-CimInstance Win32_Process |
    Where-Object { $_.Name -eq "wsl.exe" -and $_.CommandLine -match "livingmod.*sleep infinity" }
  if (-not $held) {
    Start-Process wsl.exe -ArgumentList "-d","livingmod","--","sleep","infinity" -WindowStyle Hidden
  }
'
wsl.exe -d livingmod -- /srv/livingmod/repo/scripts/stack.sh up -d "$@"
