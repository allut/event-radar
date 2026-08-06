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

# A Windows bind mount reports every path as root:root, but we run as vscode
# (uid 1000), so git's safe.directory check rejects the worktree with "detected
# dubious ownership" and every git command fails -- including step 1 of
# post-create.sh. --system so it is in place before postCreateCommand runs and
# applies to VS Code's git integration too, not just the script.
RUN git config --system --add safe.directory /workspaces/event-radar
