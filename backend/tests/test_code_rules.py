"""Drift guards for CLAUDE.md Code Quality Rules that ruff can't express.

Each check scans `app/` source text or its AST, so it needs no database.
"""

import ast
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "app"


def _app_modules() -> list[Path]:
    return sorted(p for p in APP_DIR.rglob("*.py") if "_generated" not in p.parts)


def _rel(path: Path) -> str:
    return path.relative_to(APP_DIR.parent).as_posix()


def test_resend_client_built_in_one_place() -> None:
    """Every Resend sender opens its client through `resend_http_client()`.

    A second factory or an inline `httpx.AsyncClient(timeout=RESEND_TIMEOUT_SECONDS)`
    is the same helper with two homes.
    """
    allowed = {"app/email/resend.py", "app/constants/email.py"}
    hits = [
        _rel(path)
        for path in _app_modules()
        if "RESEND_TIMEOUT_SECONDS" in path.read_text(encoding="utf-8")
        and _rel(path) not in allowed
    ]
    assert hits == []


def _call_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def test_llm_calls_pass_a_prefetched_cache() -> None:
    """An `llm_json`/`llm_json_or_none` call names `prefetched_cache=`.

    Without it `llm_json` runs its own cache SELECT on the caller's session, and
    a fan-out of those under `asyncio.gather` shares one `AsyncSession`, which
    refuses concurrent queries. Build the map with `prefetch_llm_cache()` first.
    The allowlist holds callers that make a single call per request, never fanned out.
    """
    single_call = {"app/llm/router.py", "app/llm/newsletter_extractor.py"}
    hits = [
        f"{_rel(path)}:{node.lineno}"
        for path in _app_modules()
        if _rel(path) not in single_call
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Call)
        and _call_name(node) in {"llm_json", "llm_json_or_none"}
        and all(kw.arg != "prefetched_cache" for kw in node.keywords)
    ]
    assert hits == []


_COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)


def _awaits_db_in_loops(node: ast.AST, in_loop: bool = False) -> list[int]:
    """Lines of an `await` on `db.<method>(...)`, or on a call taking `db`
    positionally, that run once per item of a loop in the same function. A
    loop's own iterable runs once, so it counts as outside the loop."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        in_loop = False
    lines: list[int] = []
    if in_loop and isinstance(node, ast.Await) and isinstance(node.value, ast.Call):
        func, args = node.value.func, node.value.args
        on_db = isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "db"
        if on_db or any(isinstance(a, ast.Name) and a.id == "db" for a in args):
            lines.append(node.lineno)
    if isinstance(node, (ast.For, ast.AsyncFor)):
        once: list[ast.AST] = [node.iter]
    elif isinstance(node, _COMPREHENSIONS):
        once = [node.generators[0].iter]
    elif isinstance(node, ast.While):
        once = []
    else:
        for child in ast.iter_child_nodes(node):
            lines += _awaits_db_in_loops(child, in_loop)
        return lines
    for child in ast.iter_child_nodes(node):
        if child in once:
            lines += _awaits_db_in_loops(child, in_loop)
        elif isinstance(child, ast.comprehension) and child.iter in once:
            lines += _awaits_db_in_loops(child.iter, in_loop)
            for part in (child.target, *child.ifs):
                lines += _awaits_db_in_loops(part, True)
        else:
            lines += _awaits_db_in_loops(child, True)
    return lines


def test_routers_query_outside_loops() -> None:
    """A router awaits no `db` query, and no helper taking `db`, per loop item.

    A request's query count stays fixed whatever the row count: load with one
    `WHERE col IN (...)` before the loop and look rows up in a dict inside it.
    """
    hits = [
        f"{_rel(path)}:{line}"
        for path in sorted((APP_DIR / "routers").glob("*.py"))
        for line in _awaits_db_in_loops(ast.parse(path.read_text(encoding="utf-8")))
    ]
    assert hits == []


def _is_str_literal(node: ast.expr) -> bool:
    return isinstance(node, ast.JoinedStr) or (
        isinstance(node, ast.Constant) and isinstance(node.value, str)
    )


def test_routers_name_their_limits_and_error_details() -> None:
    """A length bound or error detail in a router is a constant first.

    An int-literal `max_length`/`min_length` above 1 drifts from its sibling
    fields, and a literal `HTTPException` detail from the `ERROR_*` constants.
    """
    hits: list[str] = []
    for path in sorted((APP_DIR / "routers").glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            name = _call_name(node)
            where = f"{_rel(path)}:{node.lineno}"
            if name in {"Field", "Query", "Path", "Body", "Form"}:
                hits.extend(
                    f"{where} {name}({kw.arg}={kw.value.value})"
                    for kw in node.keywords
                    if kw.arg in {"max_length", "min_length"}
                    and isinstance(kw.value, ast.Constant)
                    and isinstance(kw.value.value, int)
                    and kw.value.value > 1
                )
            elif name == "HTTPException":
                details = [kw.value for kw in node.keywords if kw.arg == "detail"]
                details += node.args[1:2]
                if any(_is_str_literal(d) for d in details):
                    hits.append(f"{where} HTTPException(detail=<literal>)")
    assert hits == []
