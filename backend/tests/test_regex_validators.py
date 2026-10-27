"""Validator regexes refuse what they look like they refuse.

A regex written `^...$` and called with `match()` passes a trailing newline,
since `$` also matches just before one; `\\d` and `\\w` take any Unicode digit
or letter. Both let a value through to a stored column or an outbound URL that
the pattern seems to forbid. The rule: write a whole-string pattern unanchored
and call `fullmatch()`, and spell digits `[0-9]` (or pass `re.ASCII`). Needs no
database.
"""

import ast
import importlib
import re
from pathlib import Path

import app

APP_DIR = Path(app.__file__).parent


def _modules() -> list[tuple[str, ast.Module]]:
    found = []
    for path in sorted(APP_DIR.rglob("*.py")):
        name = ".".join(("app", *path.relative_to(APP_DIR).with_suffix("").parts))
        found.append((name.removesuffix(".__init__"), ast.parse(path.read_text(encoding="utf-8"))))
    return found


MODULES = _modules()


def _called_patterns(method: str) -> list[tuple[str, re.Pattern[str]]]:
    """Every module-level compiled pattern some module calls ``.<method>()`` on."""
    found = []
    for module_name, tree in MODULES:
        names = {
            node.func.value.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == method
            and isinstance(node.func.value, ast.Name)
        }
        if not names:
            continue
        module = importlib.import_module(module_name)
        for name in sorted(names):
            pattern = getattr(module, name, None)
            if isinstance(pattern, re.Pattern):
                found.append((f"{module_name}.{name}", pattern))
    return found


FULLMATCH_PATTERNS = _called_patterns("fullmatch")
MATCH_PATTERNS = _called_patterns("match")


def test_fullmatch_patterns_found() -> None:
    # Guards the scan itself: the registry-code, invoice-reference and <br> patterns today.
    assert len({name.rsplit(".", 1)[1] for name, _ in FULLMATCH_PATTERNS}) >= 3


def test_no_whole_string_anchored_pattern() -> None:
    offenders = [
        f"{module_name}:{node.lineno} {node.value!r}"
        for module_name, tree in MODULES
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and len(node.value) > 1
        and node.value.startswith("^")
        and node.value.endswith("$")
        and not node.value.endswith("\\$")
    ]
    assert not offenders, (
        "`^...$` passes a trailing newline under match(); drop the anchors and "
        "call fullmatch():\n" + "\n".join(offenders)
    )


def test_match_patterns_leave_the_end_unanchored() -> None:
    # match() already anchors the start; a `$` end means a whole-string check.
    offenders = [
        f"{name} {pattern.pattern!r}"
        for name, pattern in MATCH_PATTERNS
        if pattern.pattern.endswith("$") and not pattern.pattern.endswith("\\$")
    ]
    assert not offenders, (
        "match() with a `$` end passes a trailing newline; call fullmatch():\n"
        + "\n".join(offenders)
    )


def test_fullmatch_patterns_take_ascii_only() -> None:
    offenders = [
        f"{name} {pattern.pattern!r}"
        for name, pattern in FULLMATCH_PATTERNS
        if re.search(r"(?<!\\)\\[dw]", pattern.pattern) and not pattern.flags & re.ASCII
    ]
    assert not offenders, (
        "A validator's \\d or \\w takes Unicode digits and letters; spell the "
        "class ([0-9], [A-Za-z0-9_]) or pass re.ASCII:\n" + "\n".join(offenders)
    )
