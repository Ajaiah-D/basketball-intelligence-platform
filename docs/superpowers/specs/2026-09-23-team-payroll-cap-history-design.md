# Team Payroll & Cap History — Design

**Goal:** A new "Finances" page showing each team's total payroll by season (1984-85 →
present, the full life of the salary cap) plotted against the salary cap, luxury tax line, and
(2023-24 onward) first/second apron thresholds.

**Explicitly out of scope for this pass** (deferred per user decision, see
[[contracts-salary-cap-research]]): the concise rules-by-era reference, the "why did finances
drive this decision" narrative/transaction-tied analysis, and any Spotrac-grade contract
structure (options, bonuses, kickers, dead cap). This pass is payroll totals vs. league
thresholds only.

## Data sourcing (legal-risk-driven — see prior research doc)

Two genuinely different kinds of data, sourced two different ways:

1. **League-wide thresholds** (cap, luxury tax, first apron, second apron) — ~42 seasons of
   well-known, officially-announced figures. **Hand-curated as a small static reference table
   committed to the repo**, not scraped. Zero legal risk (the league publishing its own numbers)
   and zero ongoing scraping burden for ~4 numbers/season. Apron figures only exist from
   2023-24 onward (introduced by the 2023 CBA) — earlier seasons get null apron fields, not
   fabricated values.
2. **Team payroll totals per season** — genuinely needs ingestion. Source: **Basketball-
   Reference** (not Spotrac, not RealGM — see risk tiering in
   [[contracts-salary-cap-research]]). BBRef's exact page layout for team-by-season payroll
   totals has not been confirmed yet in this session — **the first implementation task is a
   short spike to confirm the actual page structure and data shape before any scraper code is
   written**, matching this project's established pattern of verifying assumptions against real
   data rather than building on an unconfirmed guess.

## Ingestion design (matches existing `ingestion/nba_ingest.py` pattern)

- New `ingestion/team_payroll_ingest.py`: scrapes Basketball-Reference team payroll totals,
  respecting their published rate limit (≤20 req/min, so a full 42-season × 30-team backfill is
  throttled and takes real wall-clock time — a one-time run, not something to redo casually).
  Writes one parquet per season to `data/raw/team_payroll/{season}.parquet`, same
  resumable-per-season-file convention as `player_game_logs` — a season already on disk is
  skipped unless `--force`, so a failed mid-backfill run just resumes.
- New `ingestion/salary_cap_history.py` (or a static data file the load step reads directly):
  writes the ~42-row hand-curated cap/tax/apron table to
  `data/raw/salary_cap_history.parquet`. No network calls — this is typed-in reference data,
  reviewed for accuracy against the official figures before being committed.
- `scripts/load_to_duckdb.py` needs no changes — it already auto-discovers any `*.parquet`
  under `data/raw/`, single-file or per-season-directory, and loads it to `raw.<name>`.
- **Weekly refresh**: only the *current* season's payroll changes week to week (trades, signings,
  waives); the other ~41 seasons are static once backfilled. `scripts/weekly_refresh.py` gets one
  new lightweight step that re-fetches only the current season, not a full re-scrape — added
  after `ingest` and before `load_duckdb` in the existing `steps` list.

## dbt layer

- `stg_team_payroll.sql` (staging): light cleanup/typing of `raw.team_payroll`.
- A dbt **seed** (`seeds/salary_cap_history.csv`) for the cap/tax/apron reference table — this
  is dbt's idiomatic mechanism for small, static, hand-maintained reference data, and this repo
  doesn't have a `seeds/` directory yet (this is the first one).
- `mart_team_finances.sql` (marts): joins team-season payroll to that season's cap/tax/apron
  thresholds; computes `over_cap` / `over_tax` / `over_first_apron` / `over_second_apron` boolean
  flags and `payroll_pct_of_cap`. One row per team-season, same grain style as
  `mart_team_standings`.
- dbt tests: grain uniqueness (team + season, extending the existing shared
  `assert_mart_grain_is_unique.sql` the way `mart_team_standings` did), payroll non-negative,
  cap-history seed has exactly one row per season with no gaps 1984-85→present, and a
  negative-control-style sanity test asserting a team/season known to have paid luxury tax
  (a real, verifiable historical fact) is correctly flagged `over_tax = true`.

## Dashboard

- New `dashboard/views/finances.py`, same shape as `dashboard/views/teams.py`: a `render()`
  function using `dashboard/lib/db.py` for data access and `dashboard/lib/theme.py` /
  `dashboard/lib/viz.py` for styling/charts, consistent with every other view.
- New query functions in `dashboard/lib/db.py`: `team_payroll_history(team=None)` and
  `salary_cap_history()`, following the existing function-per-query convention already used
  throughout that file.
- Page content: a payroll-vs-thresholds line chart across all seasons (cap/tax/apron lines
  overlaid), a team selector, and a per-season table. A visible, permanent disclaimer banner on
  early seasons flagging Basketball-Reference's own acknowledged data-quality caveats for that
  era (not a one-time note — matches how the Predictions page already permanently discloses its
  Elo-only limitation rather than implying it's a temporary early-season gap). A source
  attribution line ("Payroll data via Basketball-Reference.com") on the page.
- New nav entry in `dashboard/app.py`'s `nav` dict, following the existing `st.Page(...)`
  pattern used for the Predictions page — standalone top-level page, not folded into Teams (per
  user's explicit choice, revisitable later).

## Testing

- pytest coverage for the new scraper's HTML-parsing logic, run against a **saved fixture page**
  committed to `data/fixtures/`, not a live network call — keeps it deterministic and CI-safe,
  matching the project's existing fixture-based CI pattern (`.github/workflows/tests.yml` already
  runs with no live ingestion step, for the same reason stats.nba.com blocks GitHub-hosted
  runner IPs; Basketball-Reference scraping should not run in CI either, both to respect their
  rate limit and because there's no reason to add a second live-network dependency to CI).
- dbt tests as listed above, verified against real known cases (e.g. a specific team/season that
  actually paid luxury tax) rather than only synthetic data — same verification standard applied
  throughout this project's existing test suite.

## Resolved: Basketball-Reference page structure (confirmed 2026-09-23)

The spike ran during plan-writing, against real fetched pages (not assumed):

- **`/contracts/{TEAM}.html` (the page named in the original research pass) is forward-looking
  only** — current season + up to 5 future years, no historical access via a `?year=` param
  (tested and ignored). Not usable for history; ruled out.
- **The real source is `https://www.basketball-reference.com/teams/{BBREF_CODE}/{END_YEAR}.html`**
  (`END_YEAR` = the season's second calendar year, e.g. season "1984-85" → `1985`) — each
  team-season's own page, confirmed working back to 1985 (Larry Bird's 1984-85 Celtics salary
  is on this exact page, table id `salaries2`, caption "Salaries Table"). One request per
  team-season.
- Each row is `<td data-stat="salary" csk="1800000">$1,800,000</td>` per player — the `csk`
  attribute carries the raw integer, no currency-string parsing needed. **No team-totals footer
  row exists on this table** — team payroll is the sum of that season's player rows, computed
  by the ingestion script, not read off the page.
- **Team-code mapping, verified against the project's own existing historical franchise-code
  list** (already sitting in `raw.team_game_logs`/`fct_team_game` from `nba_api` — 42 distinct
  codes across relocations, not just the 30 current franchises in `raw.teams`): confirmed by
  direct fetch that Basketball-Reference's codes match this project's nba_api-derived codes
  **except** for four pre-1996-97 legacy codes, which need an explicit mapping:
  - `SAN` (nba_api, Spurs pre-1996-97) → `SAS` on Basketball-Reference
  - `GOS` (nba_api, Warriors pre-1996-97) → `GSW`
  - `UTH` (nba_api, Jazz pre-1996-97) → `UTA`
  - `PHL` (nba_api, 76ers pre-1996-97) → `PHI`
  Every other historical code checked matches directly, including the trickier relocation cases
  (`SDC`, `KCK`, `SEA`, `VAN`, `NJN`, `CHH`, `NOH`, and the Katrina-relocation `NOK` seasons,
  which Basketball-Reference also splits out separately rather than folding into `NOH`).

This removes the open unknown from the original design — the ingestion task below is written
against confirmed source behavior, not an assumption.
