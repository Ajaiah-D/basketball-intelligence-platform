# 0007. Python 3.12 and locked dependencies

**Status:** Accepted

## Context

Until October 2026 the project ran on three Python versions at once: 3.14
on the development machine, 3.12 in CI, and whatever Streamlit Community
Cloud was given when the app was created. `requirements.txt` listed package
names without versions, so every install resolved its own set: the live app
could run a different pandas, DuckDB or Streamlit from the one the tests
had passed on, and nothing recorded which. 3.14 also needed a workaround,
because the `mashumaro` version dbt-core pins doesn't import on it, so a
fresh setup failed until you upgraded it past the pin by hand. There was no
linter, formatter or type checker, so style and simple type errors were
caught in review or not at all.

## Decision

Run one Python version everywhere: 3.12. It is declared in
`.python-version` and `pyproject.toml` (`requires-python = ">=3.12,<3.13"`),
and used by CI (`actions/setup-python`), the Docker image
(`python:3.12-slim`), the devcontainer image and the Streamlit Cloud app
(chosen at deploy time; `DEPLOYMENT.md`, "Python version on Streamlit
Cloud"). 3.12 was already what CI ran, and dbt-core, Streamlit Cloud and the
scientific packages all support it without workarounds.

Lock every dependency with pip-tools. `requirements.in` and
`requirements-dev.in` hold the direct dependencies, and `pip-compile`
writes every package, with exact versions, into `requirements.txt` and
`requirements-dev.txt`. The dev lock is constrained by the runtime one
(`-c requirements.txt`), so the two never disagree on a shared package.
DuckDB is held below 2.0, because a major version can change the file
format the live app downloads. `CONTRIBUTING.md` has the commands.

Add ruff (lint and format), mypy (gradual: unannotated functions are
checked but nothing is forced to carry annotations) and pre-commit, all
configured in `pyproject.toml`. CI runs ruff, `ruff format --check` and
mypy before `dbt build` and pytest.

Considered and rejected: staying on 3.14 locally, which keeps the
mismatch that let local and CI behaviour differ; Poetry or uv, which would
add a second tool and lock format while Streamlit Cloud, Docker and CI all
read a plain `requirements.txt` already; and minimum-version pins
(`pandas>=2`), which document a floor but still let each install pick
different versions.

## Consequences

Development, CI, the Docker image and the live app install the same
versions, so a passing test run says something about production. Upgrades
are deliberate: recompile, read the lock diff, run the tests, and commit
the change on its own. The cost is that security fixes don't arrive by
themselves; someone has to recompile (`pip-audit` against the lock says
when). The locks are compiled on Windows and installed on Linux by CI, so a
platform-specific package would show up there first. Moving to a newer
Python later means changing all five places together and, on Streamlit
Cloud, deleting and redeploying the app, since its Python version can't be
changed in place.
