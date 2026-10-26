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



GENERATED_MODULE = "app._generated.shared_constants"
APP_DIR = CONSTANTS_DIR.parent


def _generated_imports(tree: ast.Module) -> list[ast.alias]:
    return [
        alias
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module == GENERATED_MODULE
        for alias in node.names
    ]


def test_constants_do_not_reexport_generated_values() -> None:
    """`X as X` turns a domain file into a facade over the generated module.

    An aliased-private import (`X as _X_SHARED`) that derives a local value stays allowed.
    """
    reexports = sorted(
        f"{path.name}:{alias.name}"
        for path in CONSTANTS_DIR.glob("*.py")
        for alias in _generated_imports(ast.parse(path.read_text(encoding="utf-8")))
        if alias.asname == alias.name
    )
    assert reexports == []


def test_generated_values_not_imported_through_constants() -> None:
    """A plain import in a constants file is still reachable as an implicit re-export."""
    generated_by_module: dict[str, set[str]] = {}
    for path in CONSTANTS_DIR.glob("*.py"):
        names = {
            alias.asname or alias.name
            for alias in _generated_imports(ast.parse(path.read_text(encoding="utf-8")))
        }
        generated_by_module[f"app.constants.{path.stem}"] = names
    hits: list[str] = []
    for path in sorted(APP_DIR.rglob("*.py")):
        if "_generated" in path.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.module in generated_by_module:
                hits.extend(
                    f"{path.relative_to(APP_DIR.parent)}:{node.lineno}:{alias.name}"
                    for alias in node.names
                    if alias.name in generated_by_module[node.module]
                )
    assert hits == []
