"""Alembic chain guard: one head, and every docstring's "Revises" matches the code."""

import re
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

ALEMBIC_DIR = Path(__file__).parent.parent / "alembic"
REVISES_LINE = re.compile(r"^Revises:[ \t]*(.*)$", re.MULTILINE)


def _script_dir() -> ScriptDirectory:
    config = Config()
    config.set_main_option("script_location", str(ALEMBIC_DIR))
    return ScriptDirectory.from_config(config)


def test_exactly_one_head() -> None:
    heads = _script_dir().get_heads()
    assert len(heads) == 1, f"Alembic has {len(heads)} heads: {heads}"


def test_docstring_revises_matches_down_revision() -> None:
    mismatches = []
    for rev in _script_dir().walk_revisions():
        match = REVISES_LINE.search(rev.longdoc or "")
        assert match, f"{rev.revision}: docstring has no 'Revises:' line"
        documented = match.group(1).strip()
        actual = rev.down_revision or ""
        assert not isinstance(actual, tuple), f"{rev.revision}: merge revision, check by hand"
        if documented != actual:
            mismatches.append(f"{rev.revision}: docstring '{documented}' vs down_revision '{actual}'")
    assert not mismatches, "\n".join(mismatches)
