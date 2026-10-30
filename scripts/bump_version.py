"""Bump the app version, then commit, tag and push it.

Usage:
    python scripts/bump_version.py [patch|minor|major] [--dry-run] [--no-push]

The version lives in frontend/package.json. The script runs `npm version` in
frontend/, which rewrites package.json and both package-lock.json fields, then
regenerates the _generated/ files, commits them as `Update app version to
X.Y.Z`, tags the commit vX.Y.Z and pushes master and the tag to origin in one
atomic push. Local commits not yet on origin go out with it. The pre-commit hook
runs as usual.

It fetches origin, then refuses to start off master, behind origin/master, with
anything staged, with uncommitted changes under BUMP_PATHS, or when the tag
already exists. --dry-run runs those checks, prints the old and new versions and
changes no file. --no-push stops after the tag. The master -> release merge stays
manual.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PACKAGE_JSON = "frontend/package.json"
BUMPED_FILES = (
    PACKAGE_JSON,
    "frontend/package-lock.json",
    "backend/app/_generated/shared_constants.py",
    "frontend/src/_generated/sharedConstants.ts",
)
# The generator reads all of shared/ and rewrites every _generated/ file, so an
# uncommitted edit there would leak into the bump commit.
BUMP_PATHS = (*BUMPED_FILES, "shared", "backend/app/_generated", "frontend/src/_generated")
BRANCH = "master"
REMOTE = "origin"
PARTS = ("patch", "minor", "major")
SEMVER = re.compile(r"(\d+)\.(\d+)\.(\d+)")


class Refused(Exception):
    pass


def _git(*args: str) -> str:
    result = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True)
    if result.returncode != 0:
        raise Refused(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def _current_version() -> str:
    return str(json.loads((REPO / PACKAGE_JSON).read_text(encoding="utf-8")).get("version"))


def _next_version(version: str, part: str) -> str:
    match = SEMVER.fullmatch(version)
    if match is None:
        raise Refused(f"{PACKAGE_JSON} version {version!r} is not X.Y.Z")
    major, minor, patch = (int(n) for n in match.groups())
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def _check_tree(tag: str) -> int:
    """Refuse an unsafe tree; return how many local commits the push carries."""
    branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    if branch != BRANCH:
        raise Refused(f"on {branch}, not {BRANCH}")
    if _git("diff", "--cached", "--name-only"):
        raise Refused("something is already staged; commit or unstage it first")
    dirty = _git("status", "--porcelain", "--", *BUMP_PATHS)
    if dirty:
        raise Refused(f"uncommitted changes the bump would pick up:\n{dirty}")
    _git("fetch", "--quiet", "--tags", REMOTE, BRANCH)
    behind = _git("rev-list", "--count", f"{BRANCH}..{REMOTE}/{BRANCH}")
    if behind != "0":
        raise Refused(f"{BRANCH} is {behind} commit(s) behind {REMOTE}/{BRANCH}; pull first")
    if _git("tag", "--list", tag):
        raise Refused(f"tag {tag} already exists")
    return int(_git("rev-list", "--count", f"{REMOTE}/{BRANCH}..{BRANCH}"))


def _run(*cmd: str, cwd: Path = REPO) -> None:
    """Run a step whose output the user should see, such as the pre-commit hook."""
    if subprocess.run(cmd, cwd=cwd).returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)} failed")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bump the app version, commit, tag and push it.")
    parser.add_argument("part", nargs="?", choices=PARTS, default="patch")
    parser.add_argument("--dry-run", action="store_true", help="run the checks and print the versions; change no file")
    parser.add_argument("--no-push", action="store_true", help="commit and tag, but leave the push to you")
    args = parser.parse_args(argv)

    try:
        old = _current_version()
        new = _next_version(old, args.part)
        tag = f"v{new}"
        ahead = _check_tree(tag)
    except Refused as exc:
        print(f"refused, nothing written: {exc}", file=sys.stderr)
        return 1

    print(f"{old} -> {new}")
    if ahead:
        print(f"{BRANCH} is {ahead} commit(s) ahead of {REMOTE}/{BRANCH}; they are pushed with the bump")
    if args.dry_run:
        return 0

    try:
        _run("npm", "version", new, "--no-git-tag-version", cwd=REPO / "frontend")
        _run(sys.executable, str(REPO / "scripts" / "generate_shared.py"))
        _run("git", "add", "--", *BUMPED_FILES)
        _run("git", "commit", "--quiet", "-m", f"Update app version to {new}")
    except RuntimeError as exc:
        print(f"error: {exc}; the bump is left staged. Fix and commit it, or drop it with:\n"
              f"  git restore --staged --worktree -- {' '.join(BUMPED_FILES)}", file=sys.stderr)
        return 1
    try:
        _run("git", "tag", tag)
    except RuntimeError as exc:
        print(f"error: {exc}; the bump is committed but untagged", file=sys.stderr)
        return 1
    print(f"committed and tagged {tag}")
    if args.no_push:
        print(f"push with: git push --atomic {REMOTE} {BRANCH} {tag}")
        return 0

    try:
        _run("git", "push", "--atomic", REMOTE, BRANCH, tag)
    except RuntimeError:
        print(f"error: push failed; {tag} is committed and tagged locally, nothing reached {REMOTE}.\n"
              f"If {REMOTE}/{BRANCH} moved, re-tag after the rebase:\n"
              f"  git tag -d {tag} && git pull --rebase && git tag {tag}\n"
              f"Then: git push --atomic {REMOTE} {BRANCH} {tag}", file=sys.stderr)
        return 1
    print(f"pushed {BRANCH} and {tag} to {REMOTE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
