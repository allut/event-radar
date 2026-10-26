"""Drift guards for CLAUDE.md Code Quality Rules that ruff can't express.

Each check scans `app/` source text or its AST, so it needs no database.
"""

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
