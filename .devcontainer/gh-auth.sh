#!/usr/bin/env bash
# Authenticates `gh` from the credential helper VS Code forwards into the
# container. Non-fatal, idempotent -- safe to run on every attach.
set -uo pipefail

if ! command -v gh >/dev/null 2>&1; then
  echo "    gh not installed -- skipping auth"
  exit 0
fi

# post-start.sh and postAttachCommand both call this script and can overlap
# (attach firing right after start), which would race two concurrent
# `gh auth login --with-token` writes to ~/.config/gh/hosts.yml. Serialize.
exec 9>/tmp/.gh-auth.lock
flock -w 20 9 || { echo "    another gh-auth run in progress -- skipping"; exit 0; }

if [ -n "${GH_TOKEN:-}" ] || [ -n "${GITHUB_TOKEN:-}" ]; then
  echo "    GH_TOKEN/GITHUB_TOKEN already set -- gh will use it"
  exit 0
fi

if gh auth status --hostname github.com >/dev/null 2>&1; then
  echo "    already authenticated"
  exit 0
fi

# Do NOT run `gh auth setup-git` here or anywhere else in this script -- it
# rewrites credential.https://github.com.helper and would displace VS Code's
# forwarded helper, breaking `git push`.
if printf 'protocol=https\nhost=github.com\n\n' \
    | timeout 20 git credential fill 2>/dev/null \
    | sed -n 's/^password=//p' \
    | timeout 20 gh auth login --hostname github.com --git-protocol https --with-token >/dev/null 2>&1; then
  echo "    authenticated via forwarded git credential"
else
  echo "    could not derive a token -- run: gh auth login"
fi

exit 0
