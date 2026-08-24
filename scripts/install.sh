#!/usr/bin/env bash
# Install Screenwright as an isolated CLI tool (pipx) plus its Chromium
# browser. Falls back to `pip install --user` if pipx isn't available.
set -euo pipefail

PACKAGE="${SCREENWRIGHT_PACKAGE:-screenwright}"

info() { printf '\033[1;34m==>\033[0m %s\n' "$1"; }
warn() { printf '\033[1;33mwarning:\033[0m %s\n' "$1" >&2; }
die()  { printf '\033[1;31merror:\033[0m %s\n' "$1" >&2; exit 1; }

command -v python3 >/dev/null 2>&1 || die "python3 is required but not found on PATH."

PLAYWRIGHT_PYTHON="python3"

if command -v pipx >/dev/null 2>&1; then
  info "Installing $PACKAGE with pipx..."
  pipx install "$PACKAGE"
  BIN="screenwright"
  # pipx installs into an isolated venv the system python3 can't see, so
  # plain `python3 -m playwright install chromium` would fail with
  # "No module named 'playwright'" even though the install just succeeded —
  # the interpreter that actually has playwright as a dependency is the
  # one inside that venv, not whatever `python3` resolves to on PATH.
  PIPX_VENVS="$(pipx environment --value PIPX_LOCAL_VENVS 2>/dev/null || true)"
  if [ -n "$PIPX_VENVS" ] && [ -x "$PIPX_VENVS/$PACKAGE/bin/python3" ]; then
    PLAYWRIGHT_PYTHON="$PIPX_VENVS/$PACKAGE/bin/python3"
  fi
else
  warn "pipx not found — falling back to 'pip install --user'. Installing pipx" \
       "instead is recommended (https://pipx.pypa.io) so Screenwright's" \
       "dependencies stay isolated from your other Python environments."
  python3 -m pip install --user "$PACKAGE"
  BIN="screenwright"
fi

if [ "$PLAYWRIGHT_PYTHON" = "python3" ] && ! command -v "$BIN" >/dev/null 2>&1; then
  warn "'$BIN' not found on PATH yet — you may need to open a new shell, or" \
       "add pipx's/pip's user bin directory to PATH, then run:" \
       "'python3 -m playwright install chromium' yourself."
else
  info "Installing the Playwright Chromium browser..."
  "$PLAYWRIGHT_PYTHON" -m playwright install chromium
fi

command -v ffmpeg >/dev/null 2>&1 \
  || warn "ffmpeg not found — optional; only needed if you set record_mp4 = true" \
          "on a flow. Install via your OS package manager (e.g. 'brew install ffmpeg')."

info "Done. Try: screenwright flows examples/basic.toml"
