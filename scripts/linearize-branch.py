"""Replay an integration branch onto a base as linear commits, with no merges.

Each first-parent commit of BRANCH becomes one commit on top of BASE carrying
that commit's tree. A merge commit takes the subject of the commits it brought
in. A commit whose tree equals its predecessor's is skipped.

Usage (dry run prints the plan; --apply writes the commits):
    python scripts/linearize-branch.py BRANCH [--base master] [--apply]

--apply only creates commit objects and prints the new tip. It moves no ref;
run `git merge --ff-only <tip>` on BASE once the plan looks right.
"""

import argparse
import subprocess

GIT = "/usr/bin/git"
TRAILER = "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"


def git(*args: str, stdin: str | None = None) -> str:
    result = subprocess.run(
        [GIT, *args], capture_output=True, text=True, input=stdin, check=True
    )
    return result.stdout.strip()


def merge_message(commit: str, base: str, previous: str) -> str:
    """Subject lines of the commits a merge brought in, oldest as the title."""
    second_parent = git("log", "-1", "--format=%P", commit).split()[1]
    subjects = [
        s
        for s in git(
            "log", "--no-merges", "--format=%s", f"{base}..{second_parent}", "--not", previous
        ).splitlines()
        if s
    ]
    if not subjects:
        return git("log", "-1", "--format=%B", commit)
    if len(subjects) == 1:
        return subjects[0]
    body = "\n".join(f"- {s}" for s in reversed(subjects[:-1]))
    return f"{subjects[-1]}\n\n{body}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("branch")
    parser.add_argument("--base", default="master")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    chain = git(
        "log", "--first-parent", "--reverse", "--format=%H", f"{args.base}..{args.branch}"
    ).split()
    new_tip = git("rev-parse", args.base)
    previous = new_tip
    previous_tree = git("rev-parse", f"{args.base}^{{tree}}")

    for commit in chain:
        tree = git("rev-parse", f"{commit}^{{tree}}")
        if tree == previous_tree:
            print(f"{commit[:8]} skipped (empty)")
            continue
        parents = git("log", "-1", "--format=%P", commit).split()
        if len(parents) == 1:
            message = git("log", "-1", "--format=%B", commit)
        else:
            message = merge_message(commit, args.base, previous)
        message = message.rstrip()
        if "Co-Authored-By" not in message:
            message += f"\n\n{TRAILER}"
        print(f"{commit[:8]} {tree[:8]} {message.splitlines()[0][:110]}")
        if args.apply:
            new_tip = git("commit-tree", tree, "-p", new_tip, stdin=message)
        previous_tree = tree
        previous = commit

    if args.apply:
        print(f"TIP {new_tip}")


if __name__ == "__main__":
    main()
