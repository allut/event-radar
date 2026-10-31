"""Guard: a production source file over MAX_LINES splits by area or is allowlisted.

Line count only nominates a file; cohesion decides. A long file with one job goes
in STAY_WHOLE with its reason. A file still waiting for its split goes in
PENDING_SPLIT with the issue that removes it. See docs/conventions.md, File Length.
"""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).parent.parent.parent
MAX_LINES = 700

STAY_WHOLE: dict[str, str] = {
    "backend/app/claims/lifecycle.py": "one job, the claim state machine",
    "backend/app/routers/organizer_events.py": "one resource; the Cloudinary upload only serves the submission form",
    "backend/app/ingestion/refetch.py": "one job, refetch and reconcile",
    "backend/app/routers/admin_promotions.py": "one console area; the grant, the lifecycle commands and their bodies share the cap lock and audit helpers",
    "backend/app/routers/auth.py": "one auth track, parallel to organizer_auth.py; splitting breaks the symmetry",
    "frontend/src/routes/OrganizerPromotionRequest/OrganizerPromotionRequest.tsx": "one route, one form; CheckRow is already extracted",
}

PENDING_SPLIT: dict[str, str] = {
    "backend/app/routers/utils.py": "#654",
}


def _is_scanned(rel: Path) -> bool:
    parts = rel.parts
    if "_generated" in parts:
        return False
    if parts[0] == "backend":
        return rel.suffix == ".py"
    if parts[2:3] == ("test",) or rel.name.endswith((".test.ts", ".test.tsx")):
        return False
    return rel.suffix in (".ts", ".tsx")


def count_lines(path: Path) -> int:
    """Physical lines, as `wc -l` counts them."""
    return path.read_bytes().count(b"\n")


def scanned_files(root: Path) -> list[Path]:
    found: list[Path] = []
    for base in ("backend/app", "frontend/src"):
        for path in sorted((root / base).rglob("*")):
            if path.is_file() and _is_scanned(path.relative_to(root)):
                found.append(path)
    return found


def length_violations(
    root: Path,
    stay_whole: dict[str, str],
    pending_split: dict[str, str],
    max_lines: int = MAX_LINES,
) -> list[str]:
    problems: list[str] = []
    allowed = {**stay_whole, **pending_split}
    for name, reason in allowed.items():
        if not reason.strip():
            problems.append(f"{name}: allowlist entry needs a reason")
    for path in scanned_files(root):
        rel = path.relative_to(root).as_posix()
        lines = count_lines(path)
        if lines > max_lines and rel not in allowed:
            problems.append(
                f"{rel}: {lines} lines, over {max_lines}; split by area "
                "or allowlist it with a reason"
            )
    for name in allowed:
        path = root / name
        if not path.is_file():
            problems.append(f"{name}: allowlisted but missing; remove the entry")
        elif count_lines(path) <= max_lines:
            problems.append(f"{name}: allowlisted but at or under {max_lines} lines; remove the entry")
    return problems


def _write(root: Path, rel: str, lines: int) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x\n" * lines)


def test_production_source_is_within_the_length_limit() -> None:
    assert length_violations(REPO, STAY_WHOLE, PENDING_SPLIT) == []


def test_file_over_limit_fails_until_allowlisted(tmp_path: Path) -> None:
    _write(tmp_path, "backend/app/big.py", MAX_LINES + 1)
    _write(tmp_path, "frontend/src/big.tsx", MAX_LINES + 1)
    assert len(length_violations(tmp_path, {}, {})) == 2
    ok = {"backend/app/big.py": "why", "frontend/src/big.tsx": "why"}
    assert length_violations(tmp_path, ok, {}) == []


def test_file_at_limit_passes(tmp_path: Path) -> None:
    _write(tmp_path, "backend/app/edge.py", MAX_LINES)
    assert length_violations(tmp_path, {}, {}) == []


def test_stale_allowlist_entries_fail(tmp_path: Path) -> None:
    _write(tmp_path, "backend/app/short.py", MAX_LINES)
    stale = {"backend/app/short.py": "why", "backend/app/gone.py": "why"}
    assert len(length_violations(tmp_path, stale, {})) == 2
    assert len(length_violations(tmp_path, {}, stale)) == 2


def test_allowlist_entry_needs_a_reason(tmp_path: Path) -> None:
    _write(tmp_path, "backend/app/big.py", MAX_LINES + 1)
    assert length_violations(tmp_path, {"backend/app/big.py": " "}, {}) != []


def test_tests_generated_and_css_are_never_counted(tmp_path: Path) -> None:
    for rel in (
        "backend/app/_generated/c.py",
        "frontend/src/_generated/c.ts",
        "frontend/src/a.test.ts",
        "frontend/src/a.test.tsx",
        "frontend/src/test/utils.tsx",
        "frontend/src/a.module.css",
        "backend/app/data.json",
    ):
        _write(tmp_path, rel, MAX_LINES + 50)
    assert length_violations(tmp_path, {}, {}) == []
