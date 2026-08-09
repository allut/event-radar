#!/usr/bin/env bash
# Runs on every container start (see postStartCommand). Non-fatal throughout.
set -uo pipefail

echo "==> dev servers"
bash "$(dirname "${BASH_SOURCE[0]}")/dev-server.sh" start || true

echo "==> claude CLI"
# The claude-code devcontainer feature pins nothing and its install layer is
# cached, so the image ships whatever was latest at build time. Refresh here.
npm install -g @anthropic-ai/claude-code@latest >/dev/null 2>&1 \
  || sudo -E env "PATH=$PATH" npm install -g @anthropic-ai/claude-code@latest >/dev/null 2>&1 \
  || echo "    update failed -- keeping the installed version"
claude --version || true

echo "==> claude config sync"
bash "$(dirname "${BASH_SOURCE[0]}")/sync-claude-config.sh"

echo "==> gh auth"
# postAttachCommand is the reliable point for this (VS Code writes the
# forwarded credential-helper shim during attach, not start), but run it here
# too so a start without a following attach still gets a shot at it.
bash "$(dirname "${BASH_SOURCE[0]}")/gh-auth.sh"
