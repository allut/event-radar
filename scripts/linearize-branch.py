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
import re
import subprocess
import sys

GIT = "/usr/bin/git"
ISSUE_REF = re.compile(r"\b(Closes|Refs)\s+#(\d+)", re.IGNORECASE)


def git(*args: str, stdin: str | None = None) -> str:
    result = subprocess.run(
        [GIT, *args], capture_output=True, text=True, input=stdin, check=True
    )
    return result.stdout.strip()


def merge_message(body: str, second_parent: str, base: str, previous: str) -> str:
    """Oldest brought-in commit as the title, with every issue reference they carry."""
    messages = [
        m.strip()
        for m in git(
            "log", "--no-merges", "--format=%B%x1f", f"{base}..{second_parent}", "--not", previous
        ).split("\x1f")
        if m.strip()
    ]
    return "\n\n".join(messages[-1:] + messages[:-1]) if messages else body


def commit_message(message: str) -> str:
    """The subject plus Closes/Refs #N lines, the shape .githooks/commit-msg enforces.

    commit-tree runs no hooks, so the shape is built here. A reference that any
    commit closes stays Closes.
    """
    subject = message.strip().splitlines()[0]
    found: dict[str, str] = {}
    for kind, number in ISSUE_REF.findall(message):
        if found.get(number) != "Closes":
            found[number] = kind.capitalize()
    lines = [f"{kind} #{number}" for number, kind in sorted(found.items(), key=lambda i: int(i[0]))]
    if len(found) > 1:
        print(f"warning: '{subject}' carries {len(found)} issues; reword it", file=sys.stderr)
    return subject + ("\n\n" + "\n".join(lines) if lines else "")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("branch")
    parser.add_argument("--base", default="master")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    # One git call for every commit's hash, tree, parents and message, rather
    # than three or four per commit. NUL splits the fields, RS the commits.
    log = subprocess.run(
        [
            GIT,
            "log",
            "--first-parent",
            "--reverse",
            "--format=%H%x00%T%x00%P%x00%B%x1e",
            f"{args.base}..{args.branch}",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    chain = [record.lstrip("\n").split("\0", 3) for record in log.split("\x1e")]
    new_tip = git("rev-parse", args.base)
    previous = new_tip
    previous_tree = git("rev-parse", f"{args.base}^{{tree}}")

    for commit, tree, parent_list, body in (fields for fields in chain if len(fields) == 4):
        if tree == previous_tree:
            print(f"{commit[:8]} skipped (empty)")
            continue
        parents = parent_list.split()
        if len(parents) == 1:
            message = body
        else:
            message = merge_message(body, parents[1], args.base, previous)
        message = commit_message(message)
        print(f"{commit[:8]} {tree[:8]} {message.splitlines()[0][:110]}")
        if args.apply:
            new_tip = git("commit-tree", tree, "-p", new_tip, stdin=message + "\n")
        previous_tree = tree
        previous = commit

    if args.apply:
        print(f"TIP {new_tip}")


if __name__ == "__main__":
    main()
