"""Drift guard: a top-level name in app/constants.py must be assigned once.

Plain reassignment silently shadows the earlier value and ruff does not flag it.
"""

import ast
from collections import Counter
from pathlib import Path

CONSTANTS_PATH = Path(__file__).resolve().parents[1] / "app" / "constants.py"


def _assigned_names(tree: ast.Module) -> list[str]:
    names: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names.extend(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.append(node.target.id)
    return names


def test_no_constant_assigned_twice() -> None:
    tree = ast.parse(CONSTANTS_PATH.read_text(encoding="utf-8"))
    dupes = sorted(n for n, c in Counter(_assigned_names(tree)).items() if c > 1)
    assert dupes == []
