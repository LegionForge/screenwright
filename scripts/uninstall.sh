#!/usr/bin/env bash
# Remove Screenwright. Does not remove the Playwright Chromium browser cache
# or ffmpeg, since those may be shared with other tools on this machine.
set -euo pipefail

info() { printf '\033[1;34m==>\033[0m %s\n' "$1"; }
warn() { printf '\033[1;33mwarning:\033[0m %s\n' "$1" >&2; }

if command -v pipx >/dev/null 2>&1 && pipx list --short 2>/dev/null | grep -q '^screenwright '; then
  info "Uninstalling screenwright (pipx)..."
  pipx uninstall screenwright
elif python3 -m pip show screenwright >/dev/null 2>&1; then
  info "Uninstalling screenwright (pip)..."
  python3 -m pip uninstall -y screenwright
else
  warn "screenwright doesn't appear to be installed via pipx or pip — nothing to do."
  exit 0
fi

info "Done. Playwright's browser cache (under \$HOME/Library/Caches/ms-playwright on" \
     "macOS, or \$HOME/.cache/ms-playwright on Linux) was left in place in case other" \
     "tools use it — remove it manually if you no longer need it."
