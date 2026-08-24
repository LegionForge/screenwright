#!/usr/bin/env bash
# Install Screenwright as an isolated CLI tool (pipx) plus its Chromium
# browser. Falls back to `pip install --user` if pipx isn't available.
set -euo pipefail

PACKAGE="${SCREENWRIGHT_PACKAGE:-screenwright}"

info() { printf '\033[1;34m==>\033[0m %s\n' "$1"; }
warn() { printf '\033[1;33mwarning:\033[0m %s\n' "$1" >&2; }
die()  { printf '\033[1;31merror:\033[0m %s\n' "$1" >&2; exit 1; }

command -v python3 >/dev/null 2>&1 || die "python3 is required but not found on PATH."

if command -v pipx >/dev/null 2>&1; then
  info "Installing $PACKAGE with pipx..."
  pipx install "$PACKAGE"
  BIN="screenwright"
else
  warn "pipx not found — falling back to 'pip install --user'. Installing pipx" \
       "instead is recommended (https://pipx.pypa.io) so Screenwright's" \
       "dependencies stay isolated from your other Python environments."
  python3 -m pip install --user "$PACKAGE"
  BIN="screenwright"
fi

if command -v "$BIN" >/dev/null 2>&1; then
  info "Installing the Playwright Chromium browser..."
  python3 -m playwright install chromium
else
  warn "'$BIN' not found on PATH yet — you may need to open a new shell, or" \
       "add pipx's/pip's user bin directory to PATH, then run:" \
       "'python3 -m playwright install chromium' yourself."
fi

command -v ffmpeg >/dev/null 2>&1 \
  || warn "ffmpeg not found — optional; only needed if you set record_mp4 = true" \
          "on a flow. Install via your OS package manager (e.g. 'brew install ffmpeg')."

info "Done. Try: screenwright flows examples/basic.toml"
