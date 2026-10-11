"""Drift guard: a top-level name in app/constants/ must be assigned exactly once.

Plain reassignment silently shadows the earlier value and ruff does not flag it,
and the same name defined in two domain files lets importers disagree.
"""

import ast
from collections import Counter
from pathlib import Path

CONSTANTS_DIR = Path(__file__).resolve().parents[1] / "app" / "constants"


def _assigned_names(tree: ast.Module) -> list[str]:
    names: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names.extend(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.append(node.target.id)
    return names


def test_no_constant_assigned_twice() -> None:
    names: list[str] = []
    for path in sorted(CONSTANTS_DIR.glob("*.py")):
        names.extend(_assigned_names(ast.parse(path.read_text(encoding="utf-8"))))
    dupes = sorted(n for n, c in Counter(names).items() if c > 1)
    assert dupes == []

