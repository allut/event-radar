# Python 3.12 to match CI (.github/workflows/tests.yml) and Render.
# Node 20 arrives via the devcontainer "node" feature (see devcontainer.json).
FROM mcr.microsoft.com/devcontainers/python:1-3.12-bookworm

# The base image ships /etc/apt/sources.list.d/yarn.list with a signing key that
# Yarn has since rotated, so every `apt-get update` in this image fails with
# NO_PUBKEY 62D54FD4003F6525. The repo is dead weight here (frontend is npm,
# package-lock.json only), so drop it rather than chase the key.
#
# psql / pg_isready only. Every backend requirement ships manylinux wheels,
# so no compiler and no libpq-dev are needed.
RUN rm -f /etc/apt/sources.list.d/yarn.list \
    && apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        postgresql-client \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Venv OUTSIDE the bind mount: backend/venv/ built on Windows must never shadow
# it, and pip never writes thousands of small files across the Windows mount.
ENV VIRTUAL_ENV=/opt/venv
RUN python -m venv "$VIRTUAL_ENV" && chown -R vscode:vscode "$VIRTUAL_ENV"
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Pre-create the node_modules mount point so the named volume inherits vscode
# ownership on first creation instead of coming up root-owned.
RUN mkdir -p /workspaces/event-radar/frontend/node_modules \
    && chown -R vscode:vscode /workspaces

# Same reasoning for the Claude Code config volume: a named volume with no
# pre-existing mount point comes up root-owned, but `claude` runs as vscode.
RUN mkdir -p /home/vscode/.claude \
    && chown -R vscode:vscode /home/vscode/.claude

# A Windows bind mount reports every path as root:root, but we run as vscode
# (uid 1000), so git's safe.directory check rejects the worktree with "detected
# dubious ownership" and every git command fails -- including step 1 of
# post-create.sh. --system so it is in place before postCreateCommand runs and
# applies to VS Code's git integration too, not just the script.
RUN git config --system --add safe.directory /workspaces/event-radar

# RTK (github.com/rtk-ai/rtk). The host settings.json mirrored in by
# sync-claude-config.sh declares a global PreToolUse hook `rtk hook claude`;
# without the binary the hook exits non-zero and every Bash tool call fails.
# Pinned deliberately -- bump when the host binary is upgraded.
ARG RTK_VERSION=0.45.0
RUN arch="$(dpkg --print-architecture)" \
    && case "$arch" in \
         amd64) \
           curl -fsSL -o /tmp/rtk.deb \
             "https://github.com/rtk-ai/rtk/releases/download/v${RTK_VERSION}/rtk_${RTK_VERSION}-1_amd64.deb" \
           && dpkg -i /tmp/rtk.deb && rm -f /tmp/rtk.deb ;; \
         arm64) \
           curl -fsSL "https://github.com/rtk-ai/rtk/releases/download/v${RTK_VERSION}/rtk-aarch64-unknown-linux-gnu.tar.gz" \
             | tar -xz -C /usr/local/bin rtk ;; \
         *) echo "rtk: no prebuilt package for $arch" >&2; exit 1 ;; \
       esac \
    && rtk --version

# Same reasoning as the .claude mount point above: a named volume with no
# pre-existing directory comes up root-owned. .claude-anvil holds anvil's
# config + ledger DB; .npm is the npm/npx package cache that keeps the
# `npx -y ccstatusline@latest` status line from re-downloading every rebuild.
RUN mkdir -p /home/vscode/.claude-anvil /home/vscode/.npm /home/vscode/.config/ccstatusline \
    && chown -R vscode:vscode /home/vscode/.claude-anvil /home/vscode/.npm /home/vscode/.config
