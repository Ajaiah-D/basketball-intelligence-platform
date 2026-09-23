# Team Payroll & Cap History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A new "Finances" dashboard page showing each team's total payroll by season (1984-85 →
present) plotted against the league salary cap, luxury tax line, and (2023-24 on) first/second
apron thresholds.

**Architecture:** New ingestion (`ingestion/team_payroll_ingest.py`, scraping Basketball-Reference
team-season salary pages) + a hand-curated dbt seed for league-wide thresholds → new dbt
staging/mart layer (`stg_team_payroll`, `mart_team_finances`) → new `dashboard/views/finances.py`
page wired into the existing nav. Matches this repo's existing raw-parquet → `load_to_duckdb.py`
→ dbt → dashboard pipeline shape exactly; no new pipeline stage type is introduced.

**Tech Stack:** Python (`requests`, stdlib `re` for HTML extraction — no new dependency), DuckDB,
dbt-duckdb (first use of a dbt **seed** in this project), Streamlit, Plotly (already a dependency).

## Global Constraints

- Full history target: **1984-85 season through the current season** (the salary cap's entire
  existence) — confirmed achievable against the real source, see Task 2.
- Data source for team payroll: **Basketball-Reference only** — not Spotrac, not RealGM (see
  `docs/contracts-salary-cap-data-sources.md` for the ToS reasoning). Confirmed real page
  structure below; do not substitute a different source without updating this plan.
- No `Co-Authored-By: Claude` trailer on any commit (repeat offender in this repo's history —
  double check every commit message before running `git commit`).
- Every new pytest test that hits network-shaped logic runs against a **saved fixture file**, not
  a live request — CI has no network access to Basketball-Reference, matching the existing
  `nba_api` fixture pattern in `.github/workflows/tests.yml`.
- Basketball-Reference's own published rate limit is 20 requests/minute; this plan throttles to
  **1 request per 3.5 seconds** (~17/min) with margin, mirroring `ingestion/nba_ingest.py`'s
  existing `MIN_SECONDS_BETWEEN_REQUESTS` pattern (that file uses 1.5s for a different, faster-
  limited source — do not copy that constant, use 3.5 here).
- Every dbt mart in this project uses `main_marts` as its dbt-duckdb schema and `main_staging`
  for staging models when queried from `dashboard/lib/db.py` — follow the exact pattern already
  used by `mart_team_standings` (see `standings()` in `db.py`).

---

## Confirmed source facts (verified 2026-09-23 against live pages, not assumed)

- **URL:** `https://www.basketball-reference.com/teams/{BBREF_CODE}/{END_YEAR}.html`, where
  `END_YEAR` is the season's second calendar year (season `"1984-85"` → `1985`). One request per
  team-season. Confirmed working for 1985 (earliest cap season) and 2010.
- **Table:** `id="salaries2"`, caption "Salaries Table". Each player row looks like:
  `<tr><th ...>1</th><td ...data-stat="player"...><a href="/players/b/birdla01.html">Larry Bird</a></td><td class="right " data-stat="salary" csk="1800000" >$1,800,000</td></tr>`
  — the `csk` attribute on the `data-stat="salary"` cell carries the raw integer dollar amount;
  no currency-string parsing is needed, just read that attribute.
- **No team-totals footer row exists on this table** — team payroll for a season is the sum of
  that table's player rows, computed by the ingestion script.
- **Team-code mapping** — Basketball-Reference's codes match this project's existing nba_api-
  derived historical codes (already present across 42 distinct values in
  `raw.team_game_logs`/`fct_team_game`, not just the 30 current franchises in `raw.teams`)
  **except** four pre-1996-97 legacy codes:
  | nba_api code (this project) | Basketball-Reference code |
  |---|---|
  | `SAN` (Spurs, pre-1996-97) | `SAS` |
  | `GOS` (Warriors, pre-1996-97) | `GSW` |
  | `UTH` (Jazz, pre-1996-97) | `UTA` |
  | `PHL` (76ers, pre-1996-97) | `PHI` |
  All other historical codes match directly, confirmed for the trickier relocation cases too:
  `SDC` (San Diego Clippers, →1983-84), `KCK` (Kansas City Kings, →1984-85), `SEA` (Seattle,
  →2007-08), `VAN` (Vancouver, 1995-96→2000-01), `NJN` (New Jersey Nets, →2011-12), `CHH`
  (original Charlotte Hornets, 1988-89→2001-02), `NOH` (New Orleans Hornets, most of 2002-03→
  2012-13), and `NOK` (the Katrina-relocation "New Orleans/Oklahoma City Hornets" seasons
  2005-06/2006-07 — Basketball-Reference splits these out under `NOK` too, not folded into `NOH`).
- **League-wide salary cap figures for all 43 seasons (1984-85 → 2026-27), verified against
  Basketball-Reference's own `contracts/salary-cap-history.html` page**, used directly in Task 1:
  ```
  season,salary_cap
  1984-85,3600000
  1985-86,4233000
  1986-87,4945000
  1987-88,6164000
  1988-89,7232000
  1989-90,9802000
  1990-91,11871000
  1991-92,12500000
  1992-93,14000000
  1993-94,15175000
  1994-95,15964000
  1995-96,23000000
  1996-97,24363000
  1997-98,26900000
  1998-99,30000000
  1999-00,34000000
  2000-01,35500000
  2001-02,42500000
  2002-03,40271000
  2003-04,43840000
  2004-05,43870000
  2005-06,49500000
  2006-07,53135000
  2007-08,55630000
  2008-09,58680000
  2009-10,57700000
  2010-11,58044000
  2011-12,58044000
  2012-13,58044000
  2013-14,58679000
  2014-15,63065000
  2015-16,70000000
  2016-17,94143000
  2017-18,99093000
  2018-19,101869000
  2019-20,109140000
  2020-21,109140000
  2021-22,112414000
  2022-23,123655000
  2023-24,136021000
  2024-25,140588000
  2025-26,154647000
  2026-27,164961000
  ```
- **Luxury tax did not exist before 2002-03**; the first/second apron did not exist before
  2023-24. `luxury_tax` is legitimately `NULL` for every season before 2002-03, and
  `first_apron`/`second_apron` are legitimately `NULL` before 2023-24 — these are not missing
  data, they are the correct value (the rule did not exist yet). Task 1 sources and verifies
  real tax/apron figures for every season where the rule *did* exist; a dbt test enforces that
  those cells are never accidentally left null within their applicable era.
- Anchor figures already verified for Task 1 to build from and cross-check against (do not
  re-derive these, they're confirmed): 2005-06 luxury tax **$61,700,000** (Wikipedia, "NBA
  salary cap" article, citing contemporaneous reporting); 2013-14 luxury tax **$71,748,000**
  (same article); 2026-27 luxury tax **$200,428,000**, first apron **$209,015,000**, second
  apron **$221,686,000** (official NBA figures, from this project's own prior research pass —
  see `docs/contracts-salary-cap-data-sources.md`).

---

### Task 1: League-wide cap/tax/apron reference seed

**Files:**
- Create: `dbt/basketball_intelligence/seeds/salary_cap_history.csv`
- Create: `dbt/basketball_intelligence/seeds/_seeds.yml`
- Test: `dbt/basketball_intelligence/tests/assert_salary_cap_history_no_gaps.sql`

**Interfaces:**
- Produces: a dbt seed materialized as `main.salary_cap_history` (dbt-duckdb puts seeds in the
  `main` schema, not `main_staging`/`main_marts` — matches dbt's default seed behavior, no
  custom schema config needed since no other seed exists yet to establish a different
  convention), columns `season varchar, salary_cap bigint, luxury_tax bigint,
  first_apron bigint, second_apron bigint`. Task 4's `mart_team_finances` joins on `season`.

This is the one task in this plan that is pure data-collection, not scraping — league-wide
thresholds are the league publishing its own numbers (see the design doc's risk tiering), so
this is typed-in reference data, not code that fetches anything at runtime.

- [ ] **Step 1: Create the seed CSV with the verified `salary_cap` column already complete**

Create `dbt/basketball_intelligence/seeds/salary_cap_history.csv` with a header row and the 43
`season,salary_cap` pairs given verbatim in "Confirmed source facts" above, plus two more empty
columns for tax/apron that Step 2 fills in:

```csv
season,salary_cap,luxury_tax,first_apron,second_apron
1984-85,3600000,,,
1985-86,4233000,,,
1986-87,4945000,,,
1987-88,6164000,,,
1988-89,7232000,,,
1989-90,9802000,,,
1990-91,11871000,,,
1991-92,12500000,,,
1992-93,14000000,,,
1993-94,15175000,,,
1994-95,15964000,,,
1995-96,23000000,,,
1996-97,24363000,,,
1997-98,26900000,,,
1998-99,30000000,,,
1999-00,34000000,,,
2000-01,35500000,,,
2001-02,42500000,,,
2002-03,40271000,,,
2003-04,43840000,,,
2004-05,43870000,,,
2005-06,49500000,61700000,,
2006-07,53135000,,,
2007-08,55630000,,,
2008-09,58680000,,,
2009-10,57700000,,,
2010-11,58044000,,,
2011-12,58044000,,,
2012-13,58044000,,,
2013-14,58679000,71748000,,
2014-15,63065000,,,
2015-16,70000000,,,
2016-17,94143000,,,
2017-18,99093000,,,
2018-19,101869000,,,
2019-20,109140000,,,
2020-21,109140000,,,
2021-22,112414000,,,
2022-23,123655000,,,
2023-24,136021000,,,
2024-25,140588000,,,
2025-26,154647000,,,
2026-27,164961000,200428000,209015000,221686000
```

Note rows 2005-06, 2013-14 and 2026-27 already carry the verified anchor values from "Confirmed
source facts" — leave those as-is in the next step, they are already correct.

- [ ] **Step 2: Fill in the remaining `luxury_tax` cells (2002-03 through 2025-26) and
      `first_apron`/`second_apron` cells (2023-24 through 2025-26)**

For each season from 2002-03 (luxury tax's first year) through 2025-26, and each season from
2023-24 (the aprons' first year) through 2025-26, find that season's official figure and fill in
the corresponding CSV cell. Sources to use, in order of preference:
1. The official NBA press release announcing that season's cap/tax/apron figures (search
   `"NBA sets" salary cap luxury tax [season]` — the league issues one every June/July).
2. Basketball-Reference's `contracts/salary-cap-history.html` page's own cited figures, or a
   season's `contracts/{TEAM}.html` "over the cap" framing, cross-referenced against (1).
3. Wikipedia's "NBA salary cap" article ("Luxury tax" section), which cites reported figures for
   specific seasons and can corroborate a figure found elsewhere.

Leave 1984-85 through 2001-02 `luxury_tax` blank (tax didn't exist), and 1984-85 through 2022-23
`first_apron`/`second_apron` blank (the apron system didn't exist before the 2023 CBA) — these
are correct empty cells, not gaps to fill. Do not fabricate or interpolate a number you can't
find a source for; if a specific season's exact figure genuinely can't be confirmed, leave it
blank and note which season in your task report — Step 4's test will catch it and this is a
findable, fixable gap, not a silent one.

- [ ] **Step 3: Load the seed and add its dbt config**

Create `dbt/basketball_intelligence/seeds/_seeds.yml`:

```yaml
version: 2

seeds:
  - name: salary_cap_history
    description: >
      League-wide salary cap, luxury tax, and first/second apron thresholds by
      season, 1984-85 (the cap's first season) through present. Hand-curated
      from official NBA announcements, not scraped - see docs/contracts-
      salary-cap-data-sources.md for why. luxury_tax is null before 2002-03
      (the tax didn't exist yet); first_apron/second_apron are null before
      2023-24 (introduced by the 2023 CBA) - both are legitimate values, not
      missing data.
    config:
      column_types:
        season: varchar
        salary_cap: bigint
        luxury_tax: bigint
        first_apron: bigint
        second_apron: bigint
    columns:
      - name: season
        tests: [unique, not_null]
      - name: salary_cap
        tests: [not_null]
```

Run: `dbt seed --profiles-dir .` (from `dbt/basketball_intelligence`)
Expected: `Completed successfully` and a `main.salary_cap_history` table with 43 rows.

Run: `dbt test --select salary_cap_history --profiles-dir .` (from `dbt/basketball_intelligence`)
Expected: PASS (the `unique`/`not_null` tests on `season` and `salary_cap`).

- [ ] **Step 4: Write and run a completeness test for tax/apron era coverage**

Create `dbt/basketball_intelligence/tests/assert_salary_cap_history_no_gaps.sql`:

```sql
-- salary_cap_history must have no unexpected nulls within each rule's
-- applicable era: luxury_tax from 2002-03 on, first/second apron from
-- 2023-24 on. Nulls before those seasons are correct (the rule didn't
-- exist) and are excluded here, not flagged.
select season, 'luxury_tax' as missing_column
from {{ ref('salary_cap_history') }}
where season >= '2002-03' and luxury_tax is null

union all

select season, 'first_apron' as missing_column
from {{ ref('salary_cap_history') }}
where season >= '2023-24' and first_apron is null

union all

select season, 'second_apron' as missing_column
from {{ ref('salary_cap_history') }}
where season >= '2023-24' and second_apron is null
```

Run: `dbt test --select assert_salary_cap_history_no_gaps --profiles-dir .` (from
`dbt/basketball_intelligence`)
Expected: PASS, 0 rows returned. If it fails, the output names the exact season/column still
missing from Step 2 — go fill in that specific cell and re-run.

- [ ] **Step 5: Commit**

```bash
git add dbt/basketball_intelligence/seeds/salary_cap_history.csv \
        dbt/basketball_intelligence/seeds/_seeds.yml \
        dbt/basketball_intelligence/tests/assert_salary_cap_history_no_gaps.sql
git commit -m "Add league-wide salary cap/tax/apron history as a dbt seed"
```

---

### Task 2: Team payroll ingestion script

**Files:**
- Create: `ingestion/team_payroll_ingest.py`
- Test: `tests/test_team_payroll_ingest.py`
- Create fixture: `data/fixtures/bbref_team_salary_page.html`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `parse_salary_table(html: str) -> list[dict]` (each dict has `player` and
  `salary_usd` keys), `bbref_code(nba_code: str, season: str) -> str` (applies the 4-code
  mapping table above, identity otherwise), `season_end_year(season: str) -> int` (e.g.
  `"1984-85"` → `1985`), and a `main()` CLI writing
  `data/raw/team_payroll/{season}.parquet` with columns `season, team_abbreviation,
  team_payroll` (one row per team per season - the summed total, not per-player). Task 4's
  `stg_team_payroll.sql` reads this exact shape from `raw.team_payroll`.

- [ ] **Step 1: Save a real fixture page for deterministic testing**

Run this once, from the repo root, to save a real Basketball-Reference team-season page for
tests to parse against (does not run in CI, this is a one-time local fetch to create a fixture):

```bash
curl -s -A "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36" \
  -o data/fixtures/bbref_team_salary_page.html \
  "https://www.basketball-reference.com/teams/BOS/2010.html"
```

Expected: a ~650KB HTML file saved. This is the real 2009-10 Boston Celtics season page,
confirmed during planning to contain a `salaries2` table with 14 player rows summing to a real
payroll figure - used as the fixture instead of a synthetic HTML snippet so the parser is tested
against actual site markup, not an idealized guess at its structure.

- [ ] **Step 2: Write the failing parser test**

Create `tests/test_team_payroll_ingest.py`:

```python
"""Tests for the Basketball-Reference team payroll scraper."""

from pathlib import Path

import pytest

from ingestion.team_payroll_ingest import bbref_code, parse_salary_table, season_end_year

FIXTURE = Path(__file__).parent.parent / "data" / "fixtures" / "bbref_team_salary_page.html"


def test_parse_salary_table_extracts_every_player_row():
    html = FIXTURE.read_text(encoding="utf-8")
    rows = parse_salary_table(html)
    assert len(rows) == 14  # the 2009-10 Celtics fixture has 14 rostered players with salaries
    assert rows[0]["player"] == "Paul Pierce"
    assert rows[0]["salary_usd"] == 19795712
    assert rows[1]["player"] == "Ray Allen"
    assert rows[1]["salary_usd"] == 18776860


def test_parse_salary_table_total_matches_known_payroll():
    html = FIXTURE.read_text(encoding="utf-8")
    rows = parse_salary_table(html)
    total = sum(r["salary_usd"] for r in rows)
    assert total == 83552174  # verified by hand-summing the fixture's 14 rows
    # (an earlier draft of this plan mis-summed these 14 values by hand as
    # 61,586,674 - Task 2's implementer caught and corrected it against the
    # real fixture; this is the correct total)


def test_parse_salary_table_empty_page_returns_empty_list():
    assert parse_salary_table("<html><body>no table here</body></html>") == []


@pytest.mark.parametrize("season,expected", [
    ("1984-85", 1985),
    ("1999-00", 2000),
    ("2009-10", 2010),
    ("2026-27", 2027),
])
def test_season_end_year(season, expected):
    assert season_end_year(season) == expected


@pytest.mark.parametrize("nba_code,season,expected", [
    ("SAN", "1990-91", "SAS"),   # Spurs, pre-1996-97 legacy code
    ("GOS", "1990-91", "GSW"),   # Warriors, pre-1996-97 legacy code
    ("UTH", "1990-91", "UTA"),   # Jazz, pre-1996-97 legacy code
    ("PHL", "1990-91", "PHI"),   # 76ers, pre-1996-97 legacy code
    ("BOS", "1990-91", "BOS"),   # unaffected code, passes through unchanged
    ("SAS", "2020-21", "SAS"),   # modern code, passes through unchanged
])
def test_bbref_code_maps_legacy_codes(nba_code, season, expected):
    assert bbref_code(nba_code, season) == expected
```

Run: `pytest tests/test_team_payroll_ingest.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ingestion.team_payroll_ingest'`.

- [ ] **Step 3: Implement the parser, code mapper, and season helper**

Create `ingestion/team_payroll_ingest.py`:

```python
"""Ingest historical team payroll totals from Basketball-Reference.

For each team-season, fetches https://www.basketball-reference.com/teams/
{BBREF_CODE}/{END_YEAR}.html, sums the "Salaries Table" (id="salaries2") on
that page, and writes one row per team-season to data/raw/team_payroll/
{season}.parquet.

Basketball-Reference publishes a 20 requests/minute rate limit; this script
throttles to one request per 3.5 seconds (~17/min) to stay comfortably under
it. Do not remove the sleep.

Four pre-1996-97 team codes differ between this project's nba_api-derived
codes and Basketball-Reference's own codes (Spurs, Warriors, Jazz, 76ers) -
see LEGACY_CODE_MAP below. Every other historical code, including relocated
franchises, matches directly.

Usage:
    python ingestion/team_payroll_ingest.py --season 2026-27
    python ingestion/team_payroll_ingest.py --backfill 1984-85   # every season from 1984-85 to now
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
import time
from pathlib import Path

import pandas as pd
import requests

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw" / "team_payroll"

MIN_SECONDS_BETWEEN_REQUESTS = 3.5
REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"

# nba_api uses these four legacy codes for seasons before 1996-97; Basketball-
# Reference uses the modern code for the same franchise throughout its history.
LEGACY_CODE_MAP = {
    "SAN": "SAS",  # Spurs
    "GOS": "GSW",  # Warriors
    "UTH": "UTA",  # Jazz
    "PHL": "PHI",  # 76ers
}

log = logging.getLogger("team_payroll_ingest")
_last_request_at = 0.0

_SALARY_ROW_RE = re.compile(
    r'<td[^>]*data-append-csv="[^"]*"[^>]*data-stat="player"[^>]*><a[^>]*>([^<]+)</a></td>'
    r'<td[^>]*data-stat="salary"[^>]*csk="(\d+)"',
)


def season_end_year(season: str) -> int:
    """'1984-85' -> 1985, '1999-00' -> 2000, '2026-27' -> 2027."""
    start_year = int(season[:4])
    end_suffix = int(season[5:7])
    century = (start_year // 100) * 100
    end_year = century + end_suffix
    if end_year <= start_year:
        end_year += 100
    return end_year


def bbref_code(nba_code: str, season: str) -> str:
    """Map this project's team code to Basketball-Reference's, for the given season."""
    if season_end_year(season) <= 1996 and nba_code in LEGACY_CODE_MAP:
        return LEGACY_CODE_MAP[nba_code]
    return nba_code


def parse_salary_table(html: str) -> list[dict]:
    """Extract [{'player': str, 'salary_usd': int}, ...] from a team-season page."""
    salaries_section = html.split('id="salaries2"', 1)
    if len(salaries_section) < 2:
        return []
    table_html = salaries_section[1]
    end = table_html.find("</table>")
    if end != -1:
        table_html = table_html[:end]
    return [
        {"player": player, "salary_usd": int(salary)}
        for player, salary in _SALARY_ROW_RE.findall(table_html)
    ]


def _throttle() -> None:
    global _last_request_at
    elapsed = time.monotonic() - _last_request_at
    if elapsed < MIN_SECONDS_BETWEEN_REQUESTS:
        time.sleep(MIN_SECONDS_BETWEEN_REQUESTS - elapsed)
    _last_request_at = time.monotonic()


def fetch_team_season_html(team_code: str, season: str) -> str:
    url = f"https://www.basketball-reference.com/teams/{team_code}/{season_end_year(season)}.html"
    for attempt in range(1, MAX_RETRIES + 1):
        _throttle()
        try:
            resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as exc:
            if attempt == MAX_RETRIES:
                raise
            backoff = 2**attempt * 3
            log.warning("%s failed (attempt %d/%d): %s -- retrying in %ds",
                       url, attempt, MAX_RETRIES, exc, backoff)
            time.sleep(backoff)
    raise RuntimeError("unreachable")


def team_season_payroll(nba_code: str, season: str) -> int | None:
    """Total payroll for one team-season, or None if the page has no salary table
    (e.g. a franchise's first partial season, or a season Basketball-Reference has
    no salary data for)."""
    code = bbref_code(nba_code, season)
    html = fetch_team_season_html(code, season)
    rows = parse_salary_table(html)
    if not rows:
        return None
    return sum(r["salary_usd"] for r in rows)


def ingest_season(season: str, team_codes: list[str]) -> pd.DataFrame:
    """Fetch payroll for every team active in `season`, skipping teams with no data."""
    records = []
    for code in team_codes:
        total = team_season_payroll(code, season)
        if total is None:
            log.warning("No salary data for %s %s - skipping", code, season)
            continue
        records.append({"season": season, "team_abbreviation": code, "team_payroll": total})
    return pd.DataFrame.from_records(records, columns=["season", "team_abbreviation", "team_payroll"])


def write_season(season: str, team_codes: list[str], force: bool = False) -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RAW_DIR / f"{season}.parquet"
    if out_path.exists() and not force:
        log.info("%s already ingested, skipping (use --force to redo)", season)
        return
    df = ingest_season(season, team_codes)
    df.to_parquet(out_path, index=False)
    log.info("Wrote %s (%d teams)", out_path, len(df))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S", stream=sys.stdout)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", help="Single season, e.g. 2026-27")
    parser.add_argument("--backfill", metavar="START_SEASON",
                        help="Ingest every season from START_SEASON to the current season")
    parser.add_argument("--force", action="store_true", help="Re-fetch even if already ingested")
    parser.add_argument("--teams", nargs="+", required=True,
                        help="Team codes active this season (this project's nba_api codes)")
    args = parser.parse_args()

    if args.season:
        write_season(args.season, args.teams, force=args.force)
    elif args.backfill:
        raise SystemExit(
            "Per-season --teams differs by era (relocations/expansion) - run the "
            "one-time backfill via scripts/backfill_team_payroll.py (Task 3), not "
            "this flag directly."
        )
    else:
        parser.error("Pass --season or --backfill")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_team_payroll_ingest.py -v`
Expected: all 10 tests (2 parse tests + 1 empty-page test + 4 season_end_year cases + 6
bbref_code cases minus overlaps... exact count from the parametrized cases above) PASS.

If `test_parse_salary_table_extracts_every_player_row` or the total-payroll test fails on the
real fixture, open `data/fixtures/bbref_team_salary_page.html`, search for `id="salaries2"`, and
check whether the row regex needs adjusting to the actual markup saved in Step 1 - the code
above was written against the real page fetched during planning, but re-verify against your own
saved copy rather than assuming it's byte-identical.

- [ ] **Step 5: Commit**

```bash
git add ingestion/team_payroll_ingest.py tests/test_team_payroll_ingest.py \
        data/fixtures/bbref_team_salary_page.html
git commit -m "Add Basketball-Reference team payroll scraper"
```

---

### Task 3: Historical backfill + weekly refresh integration

**Files:**
- Create: `scripts/backfill_team_payroll.py`
- Modify: `scripts/weekly_refresh.py:68-76` (the `steps` list)

**Interfaces:**
- Consumes: `ingestion/team_payroll_ingest.py`'s `write_season(season, team_codes, force)`
  (Task 2).
- Produces: populated `data/raw/team_payroll/*.parquet` files (one per season, 1984-85 through
  the current season) for Task 4's `load_to_duckdb.py` run to pick up - no code interface, this
  task's deliverable is the data itself plus the weekly-refresh wiring for future seasons.

This is the task where "40+ years, 30 teams (fewer in early years)" actually gets fetched. It
reuses the per-team-code-list-per-season problem the same way `ingestion/nba_ingest.py` already
solves it for game logs - by deriving which team codes were active each season from data this
project already has, rather than hardcoding franchise history by hand.

- [ ] **Step 1: Write the backfill driver**

Create `scripts/backfill_team_payroll.py`:

```python
"""One-time historical backfill of team payroll, 1984-85 through the current season.

Derives which team codes were active each season from this project's own
warehouse (raw.team_game_logs), which already carries the full historical
franchise-code history from nba_api ingestion - rather than hand-maintaining
a separate relocation table here.

Usage:
    python scripts/backfill_team_payroll.py
    python scripts/backfill_team_payroll.py --force   # re-fetch already-ingested seasons too
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import duckdb

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "warehouse" / "basketball.duckdb"
FIRST_SEASON = "1984-85"

sys.path.insert(0, str(PROJECT_ROOT))
from ingestion.team_payroll_ingest import write_season  # noqa: E402

log = logging.getLogger("backfill_team_payroll")


def seasons_and_teams() -> dict[str, list[str]]:
    """{season: [team codes active that season]}, derived from raw.team_game_logs,
    restricted to FIRST_SEASON onward (payroll/cap data has no meaning before the
    salary cap existed)."""
    con = duckdb.connect(str(DB_PATH), read_only=True)
    df = con.execute(
        "select distinct season, team_abbreviation from raw.team_game_logs "
        "where season >= ? order by season",
        [FIRST_SEASON],
    ).df()
    con.close()
    out: dict[str, list[str]] = {}
    for season, group in df.groupby("season"):
        out[season] = sorted(group["team_abbreviation"].tolist())
    return out


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S", stream=sys.stdout)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    by_season = seasons_and_teams()
    log.info("Backfilling %d seasons (%s -> %s)",
              len(by_season), min(by_season), max(by_season))
    for season, teams in by_season.items():
        write_season(season, teams, force=args.force)
    log.info("Backfill complete.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the backfill**

Run: `python scripts/backfill_team_payroll.py`
Expected: runs for roughly an hour (≈30 teams × ≈42 seasons at 3.5s/request ≈ 1,260 requests ≈
73 minutes, fewer in early seasons with fewer franchises), logging one line per season written,
ending with `Backfill complete.`. Let it run in the background - this is a one-time historical
load, not something to redo casually given the request volume.

Expected result: `ls data/raw/team_payroll/` shows one `{season}.parquet` per season from
1984-85 through the current season.

- [ ] **Step 3: Spot-check the result against a known real figure**

Run:
```bash
python -c "
import pandas as pd
df = pd.read_parquet('data/raw/team_payroll/2009-10.parquet')
print(df[df.team_abbreviation == 'BOS'])
"
```
Expected: one row, `team_payroll` close to `83552174` (the fixture-verified 2009-10 Celtics
total from Task 2's test) - it may differ slightly if the live page has since been corrected by
Basketball-Reference, but should not be wildly different (e.g. not off by an order of magnitude,
which would indicate a parsing or team-code bug).

- [ ] **Step 4: Wire the current season into weekly refresh**

Modify `scripts/weekly_refresh.py`, adding one step to the existing `steps` list right after
`"ingest"` (only the current season needs re-fetching weekly; the historical backfill from Step
2 is a one-time load):

```python
    steps = [
        ("ingest", [PYTHON, "ingestion/nba_ingest.py", "--force", "--pbp-games", "20"], None),
        ("payroll", [PYTHON, "ingestion/team_payroll_ingest.py", "--force",
                     "--season", CURRENT_SEASON, "--teams", *CURRENT_TEAM_CODES], None),
        ("load_duckdb", [PYTHON, "scripts/load_to_duckdb.py"], None),
        ("dbt_run", [DBT, "run", "--profiles-dir", "."], dbt_dir),
        ("dbt_test", [DBT, "test", "--profiles-dir", "."], dbt_dir),
        ("predict", [PYTHON, "-m", "ml.predict"], None),
        ("score_predictions", [PYTHON, "-m", "ml.evaluate"], None),
        ("write_metadata", [PYTHON, "scripts/write_metadata.py"], None),
    ]
```

This references two names, `CURRENT_SEASON` and `CURRENT_TEAM_CODES`, that need defining near
the top of `scripts/weekly_refresh.py` alongside its existing constants (`PYTHON`, `DBT`,
`RELEASE_TAG` etc. - read that section of the file first to match its existing style exactly).
Derive them the same way Step 1's `seasons_and_teams()` does, from the warehouse's current-season
teams, since weekly refresh already has a live warehouse to query by the time this step runs -
this is intentionally NOT hardcoded as a fixed 30-team list, since a mid-season expansion/
relocation should not require an unrelated code change to this file.

- [ ] **Step 5: Commit**

```bash
git add scripts/backfill_team_payroll.py scripts/weekly_refresh.py
git commit -m "Backfill historical team payroll and wire current season into weekly refresh"
```

---

### Task 4: dbt staging + marts layer

**Files:**
- Create: `dbt/basketball_intelligence/models/staging/stg_team_payroll.sql`
- Modify: `dbt/basketball_intelligence/models/staging/_sources.yml` (add `team_payroll` source)
- Modify: `dbt/basketball_intelligence/models/staging/_staging_models.yml` (add
  `stg_team_payroll` entry)
- Create: `dbt/basketball_intelligence/models/marts/mart_team_finances.sql`
- Modify: `dbt/basketball_intelligence/models/marts/_marts_models.yml` (add
  `mart_team_finances` entry)
- Modify: `dbt/basketball_intelligence/tests/assert_mart_grain_is_unique.sql` (add a 4th branch)
- Create: `dbt/basketball_intelligence/tests/assert_team_finances_known_tax_case.sql`

**Interfaces:**
- Consumes: `raw.team_payroll` (Task 3's parquet output, loaded by the existing
  `scripts/load_to_duckdb.py` with no changes needed - it auto-discovers any `data/raw/*/`
  directory), `main.salary_cap_history` (Task 1's seed).
- Produces: `main_marts.mart_team_finances` with columns `season varchar, team_abbreviation
  varchar, team_payroll bigint, salary_cap bigint, luxury_tax bigint, first_apron bigint,
  second_apron bigint, payroll_pct_of_cap double, over_cap boolean, over_tax boolean,
  over_first_apron boolean, over_second_apron boolean` - one row per team-season. Task 5's
  `dashboard/lib/db.py` queries this exact shape.

- [ ] **Step 1: Add the raw source**

Add to `dbt/basketball_intelligence/models/staging/_sources.yml`, under the existing `tables:`
list (alongside `player_game_logs`, `team_game_logs`, etc. - same indentation level):

```yaml
      - name: team_payroll
        description: >
          Team payroll totals by season, 1984-85 on, scraped from Basketball-
          Reference by ingestion/team_payroll_ingest.py. One row per team per
          season.
```

- [ ] **Step 2: Write the staging model**

Create `dbt/basketball_intelligence/models/staging/stg_team_payroll.sql`:

```sql
-- One row per team per season: total payroll, typed and lightly cleaned.

select
    cast(season as varchar)            as season,
    cast(team_abbreviation as varchar) as team_abbreviation,
    cast(team_payroll as bigint)       as team_payroll
from {{ source('raw', 'team_payroll') }}
where team_payroll > 0
```

Add to `dbt/basketball_intelligence/models/staging/_staging_models.yml` (matching the format of
the existing entries in that file - read one first, e.g. `stg_schedule`'s entry, to match column
test style exactly):

```yaml
  - name: stg_team_payroll
    description: One row per team per season with total payroll.
    columns:
      - name: season
        tests: [not_null]
      - name: team_abbreviation
        tests: [not_null]
      - name: team_payroll
        tests: [not_null]
```

- [ ] **Step 3: Write the mart**

Create `dbt/basketball_intelligence/models/marts/mart_team_finances.sql`:

```sql
-- One row per team per season: payroll against that season's league-wide
-- cap/tax/apron thresholds. luxury_tax/first_apron/second_apron are null
-- for seasons before those rules existed (see salary_cap_history's own
-- description) - the corresponding over_* flag is null for those rows too,
-- not false, since "over a threshold that didn't exist" is not a meaningful
-- false.

with payroll as (
    select * from {{ ref('stg_team_payroll') }}
),

cap_history as (
    select * from {{ ref('salary_cap_history') }}
)

select
    p.season,
    p.team_abbreviation,
    p.team_payroll,
    c.salary_cap,
    c.luxury_tax,
    c.first_apron,
    c.second_apron,
    round(p.team_payroll / c.salary_cap, 3)          as payroll_pct_of_cap,
    p.team_payroll > c.salary_cap                    as over_cap,
    case when c.luxury_tax is not null
         then p.team_payroll > c.luxury_tax end       as over_tax,
    case when c.first_apron is not null
         then p.team_payroll > c.first_apron end      as over_first_apron,
    case when c.second_apron is not null
         then p.team_payroll > c.second_apron end     as over_second_apron
from payroll p
join cap_history c on p.season = c.season
```

Add to `dbt/basketball_intelligence/models/marts/_marts_models.yml` (matching
`mart_team_standings`'s existing entry format in that same file):

```yaml
  - name: mart_team_finances
    description: >
      One row per team per season: payroll vs. that season's salary cap,
      luxury tax, and (2023-24 on) first/second apron thresholds.
    columns:
      - name: season
        tests: [not_null]
      - name: team_abbreviation
        tests: [not_null]
      - name: team_payroll
        tests: [not_null]
      - name: salary_cap
        tests: [not_null]
```

- [ ] **Step 4: Extend the shared grain-uniqueness test**

Read `dbt/basketball_intelligence/tests/assert_mart_grain_is_unique.sql` first - it already has
branches for other marts (added most recently for `mart_team_standings` in this repo's history).
Add a 4th branch following the exact same `union all` structure:

```sql
union all

select 'mart_team_finances' as mart, season || '|' || team_abbreviation as grain_key, count(*)
from {{ ref('mart_team_finances') }}
group by 1, 2
having count(*) > 1
```

(Match the exact column names/aliases the existing branches use - open the file and mirror its
established pattern rather than retyping from scratch, since the outer query this feeds into
depends on consistent column names across all branches.)

- [ ] **Step 5: Write a negative-control-style sanity test against a known real case**

Create `dbt/basketball_intelligence/tests/assert_team_finances_known_tax_case.sql`:

```sql
-- The 2009-10 Boston Celtics are a real, well-documented luxury-tax-paying
-- team (team_payroll ~$83.55M against a $69.92M luxury tax line that season -
-- see docs/superpowers/plans/2026-09-23-team-payroll-cap-history.md's Task 2
-- fixture, which verifies the payroll figure by hand-summing the real page,
-- and Task 1's seed for the tax line).
-- If this row isn't flagged over_tax, either the payroll ingestion or the
-- mart's comparison logic is wrong.
select season, team_abbreviation, team_payroll, luxury_tax, over_tax
from {{ ref('mart_team_finances') }}
where season = '2009-10'
  and team_abbreviation = 'BOS'
  and (over_tax is distinct from true)
```

Run: `dbt seed --profiles-dir .` then `dbt run --select stg_team_payroll mart_team_finances --profiles-dir .` then `dbt test --select stg_team_payroll mart_team_finances assert_mart_grain_is_unique assert_team_finances_known_tax_case --profiles-dir .` (all from `dbt/basketball_intelligence`)
Expected: all PASS, 0 rows from each test query. If `assert_team_finances_known_tax_case` fails,
check Task 1's 2005-06/2013-14/2026-27 anchor rows are intact and Task 3's backfill actually
produced a 2009-10 BOS row before assuming the mart logic itself is wrong.

- [ ] **Step 6: Commit**

```bash
git add dbt/basketball_intelligence/models/staging/stg_team_payroll.sql \
        dbt/basketball_intelligence/models/staging/_sources.yml \
        dbt/basketball_intelligence/models/staging/_staging_models.yml \
        dbt/basketball_intelligence/models/marts/mart_team_finances.sql \
        dbt/basketball_intelligence/models/marts/_marts_models.yml \
        dbt/basketball_intelligence/tests/assert_mart_grain_is_unique.sql \
        dbt/basketball_intelligence/tests/assert_team_finances_known_tax_case.sql
git commit -m "Add mart_team_finances: team payroll vs. cap/tax/apron thresholds"
```

---

### Task 5: Finances dashboard page

**Files:**
- Modify: `dashboard/lib/db.py` (add two query functions)
- Create: `dashboard/lib/viz.py` addition (one new chart function)
- Create: `dashboard/views/finances.py`
- Modify: `dashboard/app.py:93-119` (import + nav entry)
- Test: `tests/test_db_metrics.py` (add coverage for the two new `db.py` functions)

**Interfaces:**
- Consumes: `main_marts.mart_team_finances` (Task 4).
- Produces: nothing further consumes this - it's the top of the stack, the page itself.

- [ ] **Step 1: Add `team_finances_available()` and the two query functions to `db.py`**

Add to `dashboard/lib/db.py`, following the exact `marts_available`/`predictions_available`
pattern already in that file (guard the mart's existence so a warehouse published before this
feature shipped doesn't crash the whole app - same reasoning as those two existing functions):

```python
@st.cache_data(ttl=600, show_spinner=False)
def team_finances_available() -> bool:
    """Whether mart_team_finances exists in the warehouse - same guard pattern
    as marts_available()/predictions_available(), for a warehouse published
    before this feature shipped."""
    try:
        with duckdb.connect(str(DB_PATH), read_only=True) as con:
            con.execute("select 1 from main_marts.mart_team_finances limit 1")
        return True
    except (duckdb.Error, OSError):
        return False


def team_payroll_history(team: str | None = None) -> pd.DataFrame:
    """Payroll vs. cap/tax/apron thresholds, one row per team-season.
    Filters to one team if given, else returns every team-season (for the
    all-teams overview chart)."""
    if team:
        return q(
            "select * from main_marts.mart_team_finances where team_abbreviation = ? "
            "order by season",
            (team,),
        )
    return q("select * from main_marts.mart_team_finances order by season, team_abbreviation")


def salary_cap_history() -> pd.DataFrame:
    """League-wide cap/tax/apron thresholds by season, independent of any team."""
    return q(
        "select season, salary_cap, luxury_tax, first_apron, second_apron "
        "from main.salary_cap_history order by season"
    )
```

- [ ] **Step 2: Add the trend chart to `viz.py`**

Add to `dashboard/lib/viz.py`, following `team_margins`'s existing style (purpose-built function,
not the generic `quick_chart` dev-tool builder):

```python
def team_finances_trend(team_df: pd.DataFrame, cap_df: pd.DataFrame) -> go.Figure:
    """One team's payroll (solid line) against league cap/tax/apron thresholds
    (dashed reference lines) across every season in team_df."""
    fig = go.Figure()
    fig.add_scatter(
        x=team_df["season"], y=team_df["team_payroll"], name="Team payroll",
        mode="lines+markers", line=dict(color=T.ACCENT, width=2),
    )
    thresholds = [
        ("salary_cap", "Salary cap", T.SERIES[1]),
        ("luxury_tax", "Luxury tax", T.SERIES[2]),
        ("first_apron", "First apron", T.SERIES[3]),
        ("second_apron", "Second apron", T.SERIES[4]),
    ]
    merged = cap_df.merge(team_df[["season"]], on="season", how="inner")
    for col, label, color in thresholds:
        if merged[col].notna().any():
            fig.add_scatter(
                x=merged["season"], y=merged[col], name=label,
                mode="lines", line=dict(color=color, width=1.5, dash="dash"),
            )
    fig.update_layout(**_layout(height=420, showlegend=True))
    fig.update_xaxes(title=dict(text="Season", font=dict(color=T.MUTED)), automargin=True)
    fig.update_yaxes(title=dict(text="$", font=dict(color=T.MUTED)), automargin=True)
    return fig
```

- [ ] **Step 3: Write the page**

Create `dashboard/views/finances.py`:

```python
"""Team payroll history vs. the league salary cap, luxury tax, and apron lines."""

import streamlit as st

from dashboard.lib import db
from dashboard.lib import theme as T
from dashboard.lib import viz

EARLY_ERA_CUTOFF = "1996-97"  # Basketball-Reference's own salary data before this era is
                                # acknowledged by them to be partly extrapolated/minimum-filled


def render() -> None:
    st.markdown("## Finances", unsafe_allow_html=True)

    if not db.team_finances_available():
        st.info("Payroll data hasn't been loaded into this warehouse yet.")
        return

    all_seasons = db.team_payroll_history()
    if all_seasons.empty:
        st.info("No payroll data available.")
        return

    teams = sorted(all_seasons["team_abbreviation"].unique())
    default_ix = teams.index("BOS") if "BOS" in teams else 0
    team = st.selectbox("Team", teams, index=default_ix,
                        format_func=lambda t: f"{T.team_dot(t)} {t}", label_visibility="visible")

    team_df = all_seasons[all_seasons["team_abbreviation"] == team]
    cap_df = db.salary_cap_history()

    if (team_df["season"] < EARLY_ERA_CUTOFF).any():
        st.caption(
            "Seasons before 1996-97 use payroll figures Basketball-Reference "
            "itself notes are partly reconstructed for players with missing "
            "records - treat early-era numbers as directionally right, not exact."
        )

    st.plotly_chart(viz.team_finances_trend(team_df, cap_df), use_container_width=True,
                    config=viz.PLOTLY_CONFIG)

    st.dataframe(
        team_df[["season", "team_payroll", "salary_cap", "luxury_tax",
                "first_apron", "second_apron", "payroll_pct_of_cap",
                "over_cap", "over_tax", "over_first_apron", "over_second_apron"]],
        hide_index=True, use_container_width=True,
    )

    st.caption("Payroll data via Basketball-Reference.com. League cap/tax/apron "
              "figures are official NBA announcements.")
```

- [ ] **Step 4: Wire the nav entry**

Modify `dashboard/app.py`, adding `finances` to the existing views import (alphabetical, matches
the existing ordering of `advanced, arcade, dev_lab, games, overview, players, predictions,
teams`):

```python
from dashboard.views import (  # noqa: E402
    advanced,
    arcade,
    dev_lab,
    finances,
    games,
    overview,
    players,
    predictions,
    teams,
)
```

And add a new page to the `nav["Explore"]` list, after the existing `predictions` entry:

```python
        st.Page(predictions.render, title="Predictions", icon=":material/query_stats:",
                url_path="predictions"),
        st.Page(finances.render, title="Finances", icon=":material/payments:",
                url_path="finances"),
```

- [ ] **Step 5: Add pytest coverage for the two new `db.py` functions**

Add to `tests/test_db_metrics.py` (read its existing `predictions_available`-style test first to
match its fixture/connection setup exactly):

```python
def test_team_finances_available_false_before_mart_exists(tmp_warehouse_without_marts):
    assert db.team_finances_available() is False


def test_team_payroll_history_filters_by_team(warehouse_with_finances_mart):
    df = db.team_payroll_history(team="BOS")
    assert (df["team_abbreviation"] == "BOS").all()
    assert len(df) > 0


def test_salary_cap_history_has_no_apron_before_2023_24(warehouse_with_finances_mart):
    df = db.salary_cap_history()
    pre_apron = df[df["season"] < "2023-24"]
    assert pre_apron["first_apron"].isna().all()
```

These reference two fixtures, `tmp_warehouse_without_marts` and `warehouse_with_finances_mart`,
that don't exist yet - check `tests/conftest.py` for the existing `con`/warehouse fixture
pattern used by `test_predictions_page.py` (which solved the identical problem for
`predictions_available()`) and follow that same approach rather than inventing a new one.

Run: `pytest tests/test_db_metrics.py -v`
Expected: all tests PASS, including the three new ones.

- [ ] **Step 6: Manual smoke test in the browser**

Run: `streamlit run dashboard/app.py` (from the repo root)
Open the app, click "Finances" in the nav, select a few different teams including one with a
pre-1996-97 season, and confirm: the chart renders with the payroll line and at least the
salary-cap dashed line, the early-era caption appears for teams whose selected range includes
pre-1996-97 seasons, and the table below shows sane, non-null `salary_cap`/`over_cap` values for
every row.

- [ ] **Step 7: Commit**

```bash
git add dashboard/lib/db.py dashboard/lib/viz.py dashboard/views/finances.py \
        dashboard/app.py tests/test_db_metrics.py
git commit -m "Add Finances page: team payroll vs. cap/tax/apron history"
```

---

## Self-Review Notes

- **Spec coverage:** Task 1 covers the design's "league-wide thresholds, hand-curated" section;
  Task 2 covers the confirmed Basketball-Reference source and code-mapping; Task 3 covers the
  historical backfill and weekly-refresh wiring; Task 4 covers the dbt staging/mart/test layer;
  Task 5 covers the dashboard page, nav placement, and source attribution. All five spec
  sections have a task.
- **Placeholder scan:** the one item that isn't a literal committed value is the 22 remaining
  luxury-tax/apron cells in Task 1 Step 2 - this is deliberately a sourcing task with a defined
  method and a hard completeness test (Step 4), not a vague "TBD," because those exact figures
  require verifying a real citation per season rather than being derivable from anything already
  fetched during planning.
- **Type consistency:** `team_abbreviation` (not `team`/`abbr`) is used consistently from
  `ingestion/team_payroll_ingest.py` through `stg_team_payroll` through `mart_team_finances`
  through `db.py`, matching the existing project-wide convention (`stg_team_game_logs`,
  `mart_team_standings` all use `team_abbreviation`). `season` is a `varchar` end-to-end,
  matching every other season-keyed model in this project.
