#!/usr/bin/env bash
# Upgrade an existing Screenwright install to the latest PyPI release, and
# keep the Playwright Chromium build in sync (Playwright pins a specific
# browser build per package version — an upgrade can require a matching
# browser upgrade).
set -euo pipefail

info() { printf '\033[1;34m==>\033[0m %s\n' "$1"; }
warn() { printf '\033[1;33mwarning:\033[0m %s\n' "$1" >&2; }
die()  { printf '\033[1;31merror:\033[0m %s\n' "$1" >&2; exit 1; }

PLAYWRIGHT_PYTHON="python3"

if command -v pipx >/dev/null 2>&1 && pipx list --short 2>/dev/null | grep -q '^screenwright '; then
  info "Upgrading screenwright (pipx)..."
  pipx upgrade screenwright
  # pipx installs into an isolated venv the system python3 can't see, so
  # plain `python3 -m playwright install chromium` below would fail with
  # "No module named 'playwright'" — same gap install.sh has, fixed there
  # the same way: resolve the interpreter that actually has playwright as
  # a dependency, inside that venv.
  PIPX_VENVS="$(pipx environment --value PIPX_LOCAL_VENVS 2>/dev/null || true)"
  if [ -n "$PIPX_VENVS" ] && [ -x "$PIPX_VENVS/screenwright/bin/python3" ]; then
    PLAYWRIGHT_PYTHON="$PIPX_VENVS/screenwright/bin/python3"
  fi
elif python3 -m pip show screenwright >/dev/null 2>&1; then
  info "Upgrading screenwright (pip)..."
  python3 -m pip install --user --upgrade screenwright
else
  die "screenwright doesn't appear to be installed. Run scripts/install.sh first."
fi

info "Syncing the Playwright Chromium browser to the installed version..."
"$PLAYWRIGHT_PYTHON" -m playwright install chromium

if command -v screenwright >/dev/null 2>&1; then
  info "Done. $(screenwright --help | head -1)"
else
  warn "Done, but 'screenwright' isn't on PATH in this shell yet — open a new shell."
fi
