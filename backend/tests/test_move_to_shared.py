"""scripts/move_to_shared.py: a move into shared/ on a throwaway repo, checked file by file.

Each test builds a small repo in tmp_path: a copy of the real shared/,
frontend/package.json and generator, plus fixture constants files and their
consumers in both stacks.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent.parent
_spec = importlib.util.spec_from_file_location(
    "move_to_shared", REPO / "scripts" / "move_to_shared.py"
)
assert _spec is not None and _spec.loader is not None
mover = importlib.util.module_from_spec(_spec)
sys.modules["move_to_shared"] = mover  # dataclasses look their module up here
_spec.loader.exec_module(mover)

BACKEND_CONSTANTS = "backend/app/constants/fixture.py"
FRONTEND_CONSTANTS = "frontend/src/constants/fixture.ts"


def _write(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(text).lstrip("\n"), encoding="utf-8")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    shutil.copytree(REPO / "shared", tmp_path / "shared")
    (tmp_path / "frontend").mkdir()
    shutil.copy(REPO / "frontend" / "package.json", tmp_path / "frontend")
    (tmp_path / "scripts").mkdir()
    shutil.copy(REPO / "scripts" / "generate_shared.py", tmp_path / "scripts")
    _write(tmp_path, {".gitignore": "backend/scripts/_*\n"})
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    return tmp_path


def _run(repo: Path, *args: str) -> int:
    return mover.main(["--root", str(repo), *args])


def _read(repo: Path, rel: str) -> str:
    return (repo / rel).read_text(encoding="utf-8")


def _scalars(repo: Path) -> dict:
    return json.loads(_read(repo, "shared/app-config.json"))["scalars"]


def test_int_moves_to_scalars_and_backend_importer_is_repointed(repo: Path) -> None:
    _write(repo, {
        BACKEND_CONSTANTS: '''
            """Fixture domain."""

            # Rows on one fixture page.
            FIXTURE_PAGE_SIZE: int = 25
            FIXTURE_LOCAL_ONLY = 3
        ''',
        "backend/app/consumer.py": """
            from app.constants.fixture import FIXTURE_LOCAL_ONLY, FIXTURE_PAGE_SIZE

            print(FIXTURE_LOCAL_ONLY, FIXTURE_PAGE_SIZE)
        """,
    })

    assert _run(repo, "fixture", "FIXTURE_PAGE_SIZE") == 0

    assert _scalars(repo)["FIXTURE_PAGE_SIZE"] == 25
    assert _read(repo, BACKEND_CONSTANTS) == textwrap.dedent('''\
        """Fixture domain."""

        # Rows on one fixture page.
        FIXTURE_LOCAL_ONLY = 3
    ''')
    assert _read(repo, "backend/app/consumer.py") == textwrap.dedent("""\
        from app._generated.shared_constants import FIXTURE_PAGE_SIZE
        from app.constants.fixture import FIXTURE_LOCAL_ONLY

        print(FIXTURE_LOCAL_ONLY, FIXTURE_PAGE_SIZE)
    """)
    assert "FIXTURE_PAGE_SIZE: int = 25" in _read(repo, "backend/app/_generated/shared_constants.py")
    assert "export const FIXTURE_PAGE_SIZE = 25;" in _read(repo, "frontend/src/_generated/sharedConstants.ts")


def test_backend_imports_merge_keep_aliases_and_keep_their_scope(repo: Path) -> None:
    _write(repo, {
        BACKEND_CONSTANTS: """
            FIXTURE_PAGE_SIZE: int = 25
            FIXTURE_LABEL = "fixture"
        """,
        "backend/app/merges.py": """
            from app._generated.shared_constants import (
                ADMIN_CLAIMS_QUEUE_PAGE_SIZE,
                ADMIN_REPORTS_QUEUE_PAGE_SIZE,
            )
            from app.constants.fixture import FIXTURE_LABEL as _LABEL, FIXTURE_PAGE_SIZE
        """,
        "backend/tests/test_local.py": """
            def test_local() -> None:
                from app.constants.fixture import FIXTURE_PAGE_SIZE  # noqa: F401
        """,
    })

    assert _run(repo, "fixture", "FIXTURE_PAGE_SIZE", "FIXTURE_LABEL") == 0

    assert _read(repo, "backend/app/merges.py") == textwrap.dedent("""\
        from app._generated.shared_constants import (
            ADMIN_CLAIMS_QUEUE_PAGE_SIZE,
            ADMIN_REPORTS_QUEUE_PAGE_SIZE,
            FIXTURE_LABEL as _LABEL,
            FIXTURE_PAGE_SIZE,
        )
    """)
    assert _read(repo, "backend/tests/test_local.py") == textwrap.dedent("""\
        def test_local() -> None:
            from app._generated.shared_constants import FIXTURE_PAGE_SIZE  # noqa: F401
    """)


def test_frontend_copy_is_removed_and_its_importers_repointed(repo: Path) -> None:
    _write(repo, {
        BACKEND_CONSTANTS: """
            FIXTURE_PAGE_SIZE: int = 25
            FIXTURE_KINDS = ("alpha", "beta")
        """,
        FRONTEND_CONSTANTS: """
            import { BROWSE_PAGE_SIZE } from '../_generated/sharedConstants.js';

            // Rows on one fixture page.
            export const FIXTURE_PAGE_SIZE = 25;

            export const FIXTURE_KINDS = [
              'alpha',
              'beta',
            ] as const;

            export const FIXTURE_DOUBLE = FIXTURE_PAGE_SIZE * 2;
            export const FIXTURE_BROWSE = BROWSE_PAGE_SIZE;
        """,
        "frontend/src/constants/other.ts": """
            import { FIXTURE_KINDS } from './fixture.js';

            export const OTHER = FIXTURE_KINDS;
        """,
        "frontend/src/routes/Thing.tsx": """
            import { FIXTURE_DOUBLE, FIXTURE_PAGE_SIZE } from '../constants/fixture';

            export const thing = [FIXTURE_DOUBLE, FIXTURE_PAGE_SIZE];
        """,
        "frontend/src/lib/merge.ts": """
            import {
              BROWSE_PAGE_SIZE,
            } from '../_generated/sharedConstants';
            import {
              FIXTURE_KINDS,
              FIXTURE_PAGE_SIZE,
            } from '../constants/fixture';

            export const all = [BROWSE_PAGE_SIZE, FIXTURE_KINDS, FIXTURE_PAGE_SIZE];
        """,
        "frontend/functions/api/thing.ts": """
            import { FIXTURE_KINDS } from '../../src/constants/fixture.js';

            export const kinds = FIXTURE_KINDS;
        """,
    })

    assert _run(repo, "fixture", "FIXTURE_PAGE_SIZE", "FIXTURE_KINDS") == 0

    assert _scalars(repo)["FIXTURE_KINDS"] == ["alpha", "beta"]
    assert _read(repo, FRONTEND_CONSTANTS) == textwrap.dedent("""\
        import { BROWSE_PAGE_SIZE, FIXTURE_PAGE_SIZE } from '../_generated/sharedConstants.js';

        // Rows on one fixture page.

        export const FIXTURE_DOUBLE = FIXTURE_PAGE_SIZE * 2;
        export const FIXTURE_BROWSE = BROWSE_PAGE_SIZE;
    """)
    assert _read(repo, "frontend/src/constants/other.ts") == textwrap.dedent("""\
        import { FIXTURE_KINDS } from '../_generated/sharedConstants.js';

        export const OTHER = FIXTURE_KINDS;
    """)
    assert _read(repo, "frontend/src/routes/Thing.tsx") == textwrap.dedent("""\
        import { FIXTURE_DOUBLE } from '../constants/fixture';
        import { FIXTURE_PAGE_SIZE } from '../_generated/sharedConstants';

        export const thing = [FIXTURE_DOUBLE, FIXTURE_PAGE_SIZE];
    """)
    assert _read(repo, "frontend/src/lib/merge.ts") == textwrap.dedent("""\
        import {
          BROWSE_PAGE_SIZE,
          FIXTURE_KINDS,
          FIXTURE_PAGE_SIZE,
        } from '../_generated/sharedConstants';

        export const all = [BROWSE_PAGE_SIZE, FIXTURE_KINDS, FIXTURE_PAGE_SIZE];
    """)
    assert _read(repo, "frontend/functions/api/thing.ts") == textwrap.dedent("""\
        import { FIXTURE_KINDS } from '../../src/_generated/sharedConstants.js';

        export const kinds = FIXTURE_KINDS;
    """)


def _snapshot(repo: Path) -> dict[str, bytes]:
    return {
        p.relative_to(repo).as_posix(): p.read_bytes()
        for p in sorted(repo.rglob("*"))
        if p.is_file() and ".git" not in p.relative_to(repo).parts
    }


@pytest.mark.parametrize(
    ("files", "name", "reason"),
    [
        ({BACKEND_CONSTANTS: "FIXTURE_X = frozenset({'a'})\n"}, "FIXTURE_X", "FIXTURE_X: not a literal"),
        ({BACKEND_CONSTANTS: "FIXTURE_X = {'a', 'b'}\n"}, "FIXTURE_X", "FIXTURE_X: a set"),
        ({BACKEND_CONSTANTS: "FIXTURE_X = True\n"}, "FIXTURE_X", "FIXTURE_X: a bool"),
        ({BACKEND_CONSTANTS: "FIXTURE_X = ()\n"}, "FIXTURE_X", "FIXTURE_X: an empty list"),
        ({BACKEND_CONSTANTS: "FIXTURE_Y = 1\n"}, "FIXTURE_X", "FIXTURE_X: not defined"),
        (
            {BACKEND_CONSTANTS: "ADMIN_REPORTS_QUEUE_PAGE_SIZE = 10\n"},
            "ADMIN_REPORTS_QUEUE_PAGE_SIZE",
            "ADMIN_REPORTS_QUEUE_PAGE_SIZE: scalars already holds 50, not 10",
        ),
        (
            {BACKEND_CONSTANTS: "FIXTURE_X = 1\nFIXTURE_Y = FIXTURE_X + 1\n"},
            "FIXTURE_X",
            f"{BACKEND_CONSTANTS}:2: FIXTURE_X is used in its own constants file",
        ),
        (
            {
                BACKEND_CONSTANTS: "FIXTURE_X = 1\n",
                "backend/tests/test_attr.py": "from app.constants import fixture\n\nassert fixture.FIXTURE_X\n",
            },
            "FIXTURE_X",
            "backend/tests/test_attr.py:3: FIXTURE_X is read as a module attribute",
        ),
        (
            {
                BACKEND_CONSTANTS: "FIXTURE_X = 1\n",
                "backend/app/attr.py": "import app.constants.fixture\n\nprint(app.constants.fixture.FIXTURE_X)\n",
            },
            "FIXTURE_X",
            "backend/app/attr.py:3: FIXTURE_X is read as a module attribute",
        ),
        (
            {
                BACKEND_CONSTANTS: "FIXTURE_X = 1\n",
                "backend/app/c.py": "from app.constants.fixture import (\n    FIXTURE_X,  # why\n)\n",
            },
            "FIXTURE_X",
            "backend/app/c.py:2: a comment inside the import",
        ),
        (
            {
                BACKEND_CONSTANTS: "FIXTURE_X = 1\n",
                "backend/tests/test_patch.py": 'from unittest import mock\n\nmock.patch("app.constants.fixture.FIXTURE_X", 2)\n',
            },
            "FIXTURE_X",
            "backend/tests/test_patch.py:3: FIXTURE_X is named in a string",
        ),
        (
            {
                BACKEND_CONSTANTS: "FIXTURE_X = 1\n",
                "backend/tests/test_set.py": 'from app.constants import fixture\n\n\ndef test(monkeypatch):\n    monkeypatch.setattr(fixture, "FIXTURE_X", 2)\n',
            },
            "FIXTURE_X",
            "backend/tests/test_set.py:5: FIXTURE_X is named in a string",
        ),
        (
            {
                BACKEND_CONSTANTS: "FIXTURE_X = 1\n",
                "backend/app/constants/other.py": "from app.constants.fixture import FIXTURE_X\n\nOTHER = FIXTURE_X\n",
                "backend/app/user.py": "from app.constants.other import FIXTURE_X\n",
            },
            "FIXTURE_X",
            "backend/app/user.py:1: FIXTURE_X is imported through app.constants.other",
        ),
        (
            {
                BACKEND_CONSTANTS: "FIXTURE_X = 1\n",
                FRONTEND_CONSTANTS: "export const FIXTURE_X = 1;\n",
                "frontend/src/constants/index.ts": "export { FIXTURE_X } from './fixture.js';\n",
            },
            "FIXTURE_X",
            "frontend/src/constants/index.ts:1: FIXTURE_X is re-exported",
        ),
        (
            {
                BACKEND_CONSTANTS: "FIXTURE_X = 1\n",
                FRONTEND_CONSTANTS: "export const FIXTURE_X = 1;\n",
                "frontend/src/a.ts": "import * as C from './constants/fixture';\n\nexport const a = C.FIXTURE_X;\n",
            },
            "FIXTURE_X",
            "frontend/src/a.ts:1: FIXTURE_X is read through a namespace import",
        ),
        (
            {
                BACKEND_CONSTANTS: "FIXTURE_X = 1\n",
                FRONTEND_CONSTANTS: "export const FIXTURE_X = 1;\n",
                "frontend/src/b.ts": "import D, { FIXTURE_X } from './constants/fixture';\n",
            },
            "FIXTURE_X",
            "frontend/src/b.ts:1: FIXTURE_X is imported alongside a default import",
        ),
        (
            {BACKEND_CONSTANTS: "FIXTURE_X = 1\n", FRONTEND_CONSTANTS: "export const FIXTURE_X = 2;\n"},
            "FIXTURE_X",
            f"{FRONTEND_CONSTANTS}:1: FIXTURE_X is 2 here, 1 in the backend",
        ),
        (
            {BACKEND_CONSTANTS: "FIXTURE_X = 1\n", FRONTEND_CONSTANTS: "export const FIXTURE_X = ONE + 0;\n"},
            "FIXTURE_X",
            f"{FRONTEND_CONSTANTS}:1: FIXTURE_X is not a literal",
        ),
    ],
)
def test_refusal_names_the_problem_and_writes_nothing(
    repo: Path, capsys: pytest.CaptureFixture[str], files: dict[str, str], name: str, reason: str
) -> None:
    _write(repo, files)
    before = _snapshot(repo)

    assert _run(repo, "fixture", name) == 1

    assert reason in capsys.readouterr().err
    assert _snapshot(repo) == before


FULL_MOVE = {
    BACKEND_CONSTANTS: """
        # Rows on one fixture page.
        FIXTURE_PAGE_SIZE: int = 25
        FIXTURE_KINDS = ("alpha", "beta")
    """,
    "backend/app/consumer.py": "from app.constants.fixture import FIXTURE_KINDS, FIXTURE_PAGE_SIZE\n",
    "backend/scripts/_wizard.py": "from app.constants.fixture import FIXTURE_PAGE_SIZE\n",
    FRONTEND_CONSTANTS: """
        export const FIXTURE_PAGE_SIZE = 25;
        export const FIXTURE_ROWS = 25;
    """,
    "frontend/src/routes/Thing.tsx": "import { FIXTURE_PAGE_SIZE } from '../constants/fixture';\n",
}


def test_report_lists_changes_flags_ignored_files_comments_and_renames(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write(repo, FULL_MOVE)

    assert _run(repo, "fixture", "FIXTURE_PAGE_SIZE", "FIXTURE_KINDS") == 0

    out = capsys.readouterr().out
    assert f"  {BACKEND_CONSTANTS}:1: # Rows on one fixture page." in out
    for rel in (
        "shared/app-config.json",
        BACKEND_CONSTANTS,
        "backend/app/consumer.py",
        FRONTEND_CONSTANTS,
        "frontend/src/routes/Thing.tsx",
        "backend/app/_generated/shared_constants.py",
        "frontend/src/_generated/sharedConstants.ts",
    ):
        assert f"  {rel}\n" in out
    assert "  backend/scripts/_wizard.py  (gitignored)\n" in out
    assert f"  {FRONTEND_CONSTANTS}:2: FIXTURE_ROWS has the value of FIXTURE_PAGE_SIZE" in out


def test_dry_run_prints_the_plan_and_writes_nothing(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write(repo, FULL_MOVE)
    before = _snapshot(repo)

    assert _run(repo, "fixture", "FIXTURE_PAGE_SIZE", "--dry-run") == 0

    out = capsys.readouterr().out
    assert "-FIXTURE_PAGE_SIZE: int = 25\n" in out
    assert "+from app._generated.shared_constants import FIXTURE_PAGE_SIZE\n" in out
    assert "  backend/scripts/_wizard.py  (gitignored)\n" in out
    assert _snapshot(repo) == before


def test_second_run_with_the_same_names_changes_nothing(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write(repo, FULL_MOVE)
    assert _run(repo, "fixture", "FIXTURE_PAGE_SIZE", "FIXTURE_KINDS") == 0
    after_first = _snapshot(repo)
    capsys.readouterr()

    assert _run(repo, "fixture", "FIXTURE_PAGE_SIZE", "FIXTURE_KINDS") == 0

    assert _snapshot(repo) == after_first
    assert "already in shared/ scalars: FIXTURE_PAGE_SIZE, FIXTURE_KINDS" in capsys.readouterr().out


def test_failed_regeneration_restores_every_edited_file(repo: Path) -> None:
    _write(repo, {
        BACKEND_CONSTANTS: "FIXTURE_X = 1\n",
        "backend/app/consumer.py": "from app.constants.fixture import FIXTURE_X\n",
        "scripts/generate_shared.py": "import sys\nsys.exit(1)\n",
    })
    before = _snapshot(repo)

    assert _run(repo, "fixture", "FIXTURE_X") == 1

    assert _snapshot(repo) == before


def test_numeric_separators_count_as_a_literal_copy(repo: Path) -> None:
    _write(repo, {
        BACKEND_CONSTANTS: "FIXTURE_X = 50_000\n",
        FRONTEND_CONSTANTS: "export const FIXTURE_X = 50_000;\nexport const FIXTURE_OTHER = 1;\n",
        "frontend/src/constants/fixture.test.ts": "export const FIXTURE_X = 7;\n",
    })

    assert _run(repo, "fixture", "FIXTURE_X") == 0

    assert _read(repo, FRONTEND_CONSTANTS) == "export const FIXTURE_OTHER = 1;\n"
    assert _read(repo, "frontend/src/constants/fixture.test.ts") == "export const FIXTURE_X = 7;\n"


def test_new_key_lands_after_the_last_key_sharing_its_longest_name_prefix(repo: Path) -> None:
    config = json.loads(_read(repo, "shared/app-config.json"))
    config["scalars"] = {
        "ADMIN_A_PAGE_SIZE": 1,
        "ADMIN_B_PAGE_SIZE": 2,
        "OTHER_LIST": ["x", "y"],
        "PROMO_X": "p",
    }
    (repo / "shared/app-config.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    _write(repo, {
        BACKEND_CONSTANTS: """
            ADMIN_FIXTURE_PAGE_SIZE = 3
            OTHER_EXTRA = "e"
            ZED_NEW = 4
        """,
    })

    assert _run(repo, "fixture", "ADMIN_FIXTURE_PAGE_SIZE", "OTHER_EXTRA", "ZED_NEW") == 0

    assert list(_scalars(repo)) == [
        "ADMIN_A_PAGE_SIZE",
        "ADMIN_B_PAGE_SIZE",
        "ADMIN_FIXTURE_PAGE_SIZE",
        "OTHER_LIST",
        "OTHER_EXTRA",
        "PROMO_X",
        "ZED_NEW",
    ]


def test_hand_copies_are_same_named_literals_in_both_stacks(repo: Path) -> None:
    _write(repo, {
        BACKEND_CONSTANTS: """
            FIXTURE_COPIED = 25
            FIXTURE_DRIFTED = "a"
            FIXTURE_DERIVED = 3
            FIXTURE_SET = frozenset({"x"})
        """,
        FRONTEND_CONSTANTS: """
            import { BROWSE_PAGE_SIZE } from '../_generated/sharedConstants.js';

            export const FIXTURE_COPIED = 25;
            export const FIXTURE_DRIFTED = 'b';
            export const FIXTURE_DERIVED = BROWSE_PAGE_SIZE;
            export const FIXTURE_SET = new Set(['x']);
        """,
        "frontend/src/constants/fixture.test.ts": "export const FIXTURE_COPIED = 25;\n",
    })

    copies = mover.find_hand_copies(repo)

    assert [(c.name, c.backend, c.frontend, c.backend_value, c.frontend_value) for c in copies] == [
        ("FIXTURE_COPIED", BACKEND_CONSTANTS, f"{FRONTEND_CONSTANTS}:3", 25, 25),
        ("FIXTURE_DRIFTED", BACKEND_CONSTANTS, f"{FRONTEND_CONSTANTS}:4", "a", "b"),
    ]


# A same-named literal that stays in both stacks, with the reason it stays.
_DERIVED_IN_FILE = "its backend constants file derives another value from it, so move_to_shared.py refuses the move"
HAND_COPIES_ALLOWED: dict[str, str] = {
    "LOCALE_ET": _DERIVED_IN_FILE,  # LOCALE_URL_PREFIX_CODES
    "PROMOTION_RESTRICTION_NONE": _DERIVED_IN_FILE,  # VALID_PROMOTION_RESTRICTION_VALUES
}


def test_no_constant_is_copied_by_hand_across_stacks() -> None:
    copies = [c for c in mover.find_hand_copies(REPO) if c.name not in HAND_COPIES_ALLOWED]

    assert copies == [], (
        "a literal defined under the same name in both stacks; move it into shared/ with "
        "`python scripts/move_to_shared.py <domain> NAME`, or allowlist it in HAND_COPIES_ALLOWED with the reason:\n"
        + "\n".join(f"  {c.name}: {c.backend} = {c.backend_value!r}, {c.frontend} = {c.frontend_value!r}" for c in copies)
    )
