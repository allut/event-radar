"""List the tests a base ref has that HEAD has lost.

A pure split moves tests without changing them, so every test name on the base
must still exist on HEAD, in whatever file. Names are counted, not just listed:
two tests sharing a name in two files must both survive. Python tests count by
function name, frontend tests by their `it`/`test` title.

Usage: python scripts/compare-test-names.py BASE [HEAD]
Exit 1 when a name is missing, so a deliberate deletion shows up for review.
"""

import ast
import re
import subprocess
import sys
from collections import Counter

GIT = "/usr/bin/git"
TS_TEST = re.compile(r"""\b(?:it|test)(?:\.\w+)?\(\s*(["'`])((?:(?!\1).)+)\1""")
PY_TEST_ROOT = "backend/tests/"
TS_TEST_SUFFIXES = (".test.ts", ".test.tsx")


def git(*args: str, stdin: str | None = None) -> str:
    return subprocess.run(
        [GIT, *args], capture_output=True, text=True, check=True, input=stdin
    ).stdout


def test_files(ref: str) -> dict[str, str]:
    """Path to source for every test file at the ref, read in one cat-file call."""
    paths = [
        p
        for p in git("ls-tree", "-r", "--name-only", ref).splitlines()
        if (p.startswith(PY_TEST_ROOT) and p.endswith(".py"))
        or (p.startswith("frontend/") and p.endswith(TS_TEST_SUFFIXES))
    ]
    out = subprocess.run(
        [GIT, "cat-file", "--batch"],
        input="".join(f"{ref}:{p}\n" for p in paths).encode(),
        capture_output=True,
        check=True,
    ).stdout
    sources: dict[str, str] = {}
    pos = 0
    for path in paths:
        header_end = out.index(b"\n", pos)
        size = int(out[pos:header_end].split()[2])
        sources[path] = out[header_end + 1 : header_end + 1 + size].decode()
        pos = header_end + 1 + size + 1
    return sources


def test_names(ref: str) -> Counter[str]:
    names: Counter[str] = Counter()
    for path, source in test_files(ref).items():
        if path.endswith(".py"):
            names.update(
                node.name
                for node in ast.walk(ast.parse(source))
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name.startswith("test_")
            )
        else:
            names.update(f"ts: {m.group(2)}" for m in TS_TEST.finditer(source))
    return names


def main() -> int:
    if len(sys.argv) not in (2, 3):
        print(__doc__)
        return 2
    head_ref = sys.argv[2] if len(sys.argv) == 3 else "HEAD"
    base = test_names(sys.argv[1])
    head = test_names(head_ref)
    lost = {name: count - head[name] for name, count in base.items() if count > head[name]}
    for name, count in sorted(lost.items()):
        print(f"missing x{count}: {name}")
    print(f"{len(base)} distinct names on {sys.argv[1]}, {len(lost)} lost on {head_ref}")
    return 1 if lost else 0


if __name__ == "__main__":
    sys.exit(main())
