"""The two import rules the deployed app depends on, read from the source.

The dashboard never imports ml, scripts or ingestion: scikit-learn and scipy
are dev-only and absent on the deployed app, and nba_api is not installed
there either, so one such import crashes the page that reaches it (it has
happened: see dashboard/lib/data/predictions.py). And core, which both sides
share, imports only the standard library and python-dotenv, plus pandas and
pyarrow in core/io.py alone. Every import counts, including the ones inside
functions, since those fail just the same when they finally run.
"""

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DASHBOARD_FORBIDDEN = {"ml", "scripts", "ingestion"}
CORE_ALLOWED = set(sys.stdlib_module_names) | {"core", "dotenv"}
CORE_ALLOWED_EXTRA = {"io.py": {"pandas", "pyarrow"}}


def imported_packages(path: Path) -> set[str]:
    """The top-level package of every absolute import in a file. Relative
    imports stay inside the package they are in, so they are left out."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module.split(".")[0])
    return found


def _rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


DASHBOARD_FILES = sorted((ROOT / "dashboard").rglob("*.py"))
CORE_FILES = sorted((ROOT / "core").glob("*.py"))


def test_both_packages_have_files_to_check():
    # A moved folder would otherwise leave the tests below checking nothing.
    assert len(DASHBOARD_FILES) > 20
    assert (ROOT / "core" / "io.py") in CORE_FILES


def test_the_dashboard_never_imports_the_pipeline():
    offenders = {
        _rel(path): sorted(found)
        for path in DASHBOARD_FILES
        if (found := imported_packages(path) & DASHBOARD_FORBIDDEN)
    }
    assert offenders == {}


def test_core_imports_only_the_standard_library_and_dotenv():
    offenders = {
        _rel(path): sorted(found)
        for path in CORE_FILES
        if (
            found := imported_packages(path)
            - CORE_ALLOWED
            - CORE_ALLOWED_EXTRA.get(path.name, set())
        )
    }
    assert offenders == {}


def test_imported_packages_sees_imports_inside_functions(tmp_path):
    source = tmp_path / "sample.py"
    source.write_text(
        "import os.path\n"
        "from . import sibling\n"
        "def f():\n"
        "    from ml.train import evaluate\n"
        "    import scripts.weekly_refresh as wr\n",
        encoding="utf-8",
    )
    assert imported_packages(source) == {"os", "ml", "scripts"}
