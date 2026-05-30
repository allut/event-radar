"""Drift guard: verify _generated files are in sync with shared/*.json.

If this test fails, run `python scripts/generate_shared.py` and commit.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).parent.parent.parent
BACKEND_GEN = REPO / "backend" / "app" / "_generated"
FRONTEND_GEN = REPO / "frontend" / "src" / "_generated"


def test_generated_files_match_shared_json(tmp_path: Path) -> None:
    """Run the generator into a temp dir and assert committed output is identical."""
    _run_generator_into(tmp_path)
    _check_dir(BACKEND_GEN, tmp_path / "backend" / "app" / "_generated")
    _check_dir(FRONTEND_GEN, tmp_path / "frontend" / "src" / "_generated")


def _run_generator_into(dest: Path) -> None:
    """Run generate_shared.py with overridden output dirs via a wrapper script."""
    dest.mkdir(parents=True, exist_ok=True)
    wrapper = dest / "_run_gen.py"
    gen_script = REPO / "scripts" / "generate_shared.py"
    backend_out = dest / "backend" / "app" / "_generated"
    frontend_out = dest / "frontend" / "src" / "_generated"
    wrapper.write_text(
        f"""\
import importlib.util, pathlib
spec = importlib.util.spec_from_file_location(
    "generate_shared",
    r"{gen_script}",
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
mod.BACKEND_GEN = pathlib.Path(r"{backend_out}")
mod.FRONTEND_GEN = pathlib.Path(r"{frontend_out}")
mod.main()
""",
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, str(wrapper)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"Generator failed:\n{result.stdout}\n{result.stderr}"
    )


def _check_dir(committed: Path, generated: Path) -> None:
    committed_names = {f.name for f in committed.iterdir() if f.suffix in (".py", ".ts")}
    generated_names = {f.name for f in generated.iterdir() if f.suffix in (".py", ".ts")}
    assert committed_names == generated_names, (
        f"Generated file set mismatch in {committed}.\n"
        f"  Only in committed: {committed_names - generated_names}\n"
        f"  Only in generated: {generated_names - committed_names}\n"
        "shared/ changed — run `python scripts/generate_shared.py` and commit."
    )
    for committed_file in sorted(committed_names):
        committed_text = (committed / committed_file).read_text(encoding="utf-8")
        generated_text = (generated / committed_file).read_text(encoding="utf-8")
        assert committed_text == generated_text, (
            f"Generated file out of sync: {committed / committed_file}\n"
            "shared/ changed — run `python scripts/generate_shared.py` and commit."
        )
