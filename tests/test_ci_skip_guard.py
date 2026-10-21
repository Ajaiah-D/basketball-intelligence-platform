"""The CI skip guard in conftest.py: with CI set a skipped test fails the
run, a deselected one does not, and locally skips stay allowed.

Each case runs a throwaway pytest session (pytester) whose conftest borrows
the real guard hook from tests/conftest.py."""

from pathlib import Path

import pytest

pytest_plugins = ["pytester"]

CONFTEST = Path(__file__).with_name("conftest.py")

INNER_CONFTEST = f"""
import importlib.util

_spec = importlib.util.spec_from_file_location("bip_tests_conftest", {str(CONFTEST)!r})
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
pytest_sessionfinish = _mod.pytest_sessionfinish
"""

INNER_TESTS = """
import pytest

def test_runs():
    pass

def test_skips():
    pytest.skip("no data for this")

@pytest.mark.full_warehouse
def test_needs_everything():
    pytest.skip("partial warehouse")
"""


@pytest.fixture
def inner(pytester):
    pytester.makeconftest(INNER_CONFTEST)
    pytester.makeini("[pytest]\nmarkers =\n    full_warehouse: test marker\n")
    pytester.makepyfile(test_inner=INNER_TESTS)
    return pytester


def test_a_skip_fails_the_run_in_ci(inner, monkeypatch):
    monkeypatch.setenv("CI", "1")
    result = inner.runpytest()
    result.assert_outcomes(passed=1, skipped=2)
    assert result.ret == pytest.ExitCode.TESTS_FAILED
    result.stdout.fnmatch_lines(
        [
            "*CI is set: 2 skipped test(s) fail the run*",
            "test_inner.py::test_skips: Skipped: no data for this",
        ]
    )


def test_deselected_tests_do_not_count_as_skips(inner, monkeypatch):
    monkeypatch.setenv("CI", "1")
    inner.makepyfile(test_inner=INNER_TESTS.replace('pytest.skip("no data for this")', "pass"))
    result = inner.runpytest("-m", "not full_warehouse")
    result.assert_outcomes(passed=2, deselected=1)
    assert result.ret == pytest.ExitCode.OK


def test_skips_are_allowed_locally(inner, monkeypatch):
    monkeypatch.delenv("CI", raising=False)
    result = inner.runpytest()
    result.assert_outcomes(passed=1, skipped=2)
    assert result.ret == pytest.ExitCode.OK
    assert "CI is set" not in result.stdout.str()
