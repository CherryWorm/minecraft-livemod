#!/bin/bash
# Run from Git Bash on Windows. Stops the stack cleanly so the world saves, then lets WSL sleep.
set -euo pipefail
export MSYS_NO_PATHCONV=1

wsl.exe -d livingmod -- /srv/livingmod/repo/scripts/stack.sh stop
powershell.exe -NoProfile -Command '
  Get-CimInstance Win32_Process -Filter "Name=''wsl.exe''" |
    Where-Object { $_.CommandLine -match "livingmod.*sleep infinity" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId }
'
