# Finances Clarity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Finances page understandable to a casual fan. It should show:
- one entry per franchise, with full names;
- what the cap, tax and aprons mean;
- where a team stands and which contracts put it there;
- when the salary data was last updated.

It also evens out the height of the Overview KPI cards.

**Architecture:** The scraper keeps the per-player salary rows it already parses, plus a fetch timestamp. dbt turns them into `mart_team_contracts` and adds `payroll_fetched_at_utc` to `mart_team_finances`. Two new pure-Python modules hold the logic:
- `dashboard/lib/franchises.py`: season-aware franchise lineage.
- `dashboard/lib/payroll.py`: brackets and the generated sentences.

`dashboard/views/finances.py` is rebuilt as a top-to-bottom read: league snapshot, how to read it, the team, then its history.

**Tech Stack:** Python 3.12/3.14, pandas, requests, DuckDB, dbt-duckdb, Streamlit 1.58, Plotly, pytest with `streamlit.testing.v1.AppTest`.

## Correction to the spec (found while planning)

The spec assumed Basketball-Reference counts a traded player's salary on every team he played for. A live check showed it doesn't:
- 2022-23: Durant is listed only on PHO, while Bridges and C. Johnson are listed only on BRK.
- 2023-24: Siakam is listed only on IND, and Bruce Brown only on TOR.
- Memphis's 39 rows in 2023-24 are real 10-day and hardship contracts listed at the amount paid.

So the source already reflects the end-of-season roster. The spec's attribution step, matching players to game logs and picking the last team, is **dropped**. The per-player re-scrape stays, because it powers the "biggest contracts" list and the updated date. Tax-team counts will not fall. The page instead explains why nearly every team is over the cap, and says plainly that this is an approximation of the official tax bill.

## Global Constraints

- Commits: human-style messages, **no `Co-Authored-By` trailers**, no emoji.
- Every money figure shown to users goes through `payroll.money()` ("$193.3M" / "$850K").
- Line and bracket colors come from `payroll.LINES` / `payroll.bracket()` only. The same color must mean the same line on both charts and the status card.
- Franchise rule: payroll follows the contracts. A mapping depends on `(code, season)`, never on the code alone.
- Scraping: keep `MIN_SECONDS_BETWEEN_REQUESTS = 3.5`. Never parallelize requests to Basketball-Reference.
- A warehouse published before this change (no `mart_team_contracts`, no `payroll_fetched_at_utc`) must still render the page without errors.
- Run Python with `.venv/Scripts/python.exe`, and set `PYTHONIOENCODING=utf-8` when printing DuckDB tables.

---

### Task 1: Scraper keeps per-player rows and a fetch timestamp

**Files:**
- Modify: `ingestion/team_payroll_ingest.py`
- Test: `tests/test_team_payroll_ingest.py`

**Interfaces:**
- Produces:
  - `parse_salary_table(html) -> list[{"bbref_player_id": str, "player": str, "salary_usd": int}]`
  - `team_season_payroll(code, season) -> {"team_payroll", "player_count", "players"}`
  - `ingest_season(season, codes) -> tuple[totals_df, players_df]`
  - `PLAYERS_DIR`
  - Parquet `data/raw/team_payroll_players/{season}.parquet` with columns `season, team_abbreviation, bbref_player_id, player, salary_usd, fetched_at_utc`
  - The totals parquet gains `fetched_at_utc` (naive UTC timestamp).

- [ ] **Step 1: Update and add the failing tests.** In `tests/test_team_payroll_ingest.py`, make these changes:

```python
# in test_parse_salary_table_extracts_every_player_row, after the existing asserts:
    assert rows[0]["bbref_player_id"] == "piercpa01"
    assert rows[1]["bbref_player_id"] == "allenra02"


def test_parse_salary_table_unescapes_player_names():
    html = ('<table id="salaries2"><tr>'
            '<td class="left" data-append-csv="oneilsh01" data-stat="player" >'
            '<a href="/players/o/oneilsh01.html">Shaquille O&#x27;Neal</a></td>'
            '<td class="right" data-stat="salary" csk="17142000" >$17,142,000</td>'
            '</tr></table>')
    rows = parse_salary_table(html)
    assert rows == [{"bbref_player_id": "oneilsh01", "player": "Shaquille O'Neal",
                     "salary_usd": 17142000}]
```

```python
# test_team_season_payroll_reports_row_count_alongside_total - add:
    assert len(result["players"]) == 14
    assert result["players"][0]["player"] == "Paul Pierce"

# test_team_season_payroll_with_no_salary_table_is_none_not_zero - add:
    assert result["players"] == []

# test_ingest_season_writes_a_row_for_a_team_with_no_data - replace the call line with:
    df, players = team_payroll_ingest.ingest_season("1986-87", ["BOS", "DAL"])
# and add at the end:
    assert len(players) == 14
    assert set(players["team_abbreviation"]) == {"BOS"}
```

Replace `test_ingest_season_columns_include_player_count` and `test_write_season_parquet_round_trips_player_count` with:

```python
TOTAL_COLUMNS = ["season", "team_abbreviation", "team_payroll", "player_count",
                 "fetched_at_utc"]
PLAYER_COLUMNS = ["season", "team_abbreviation", "bbref_player_id", "player",
                  "salary_usd", "fetched_at_utc"]


def test_ingest_season_columns(monkeypatch):
    _fake_pages({"BOS": FIXTURE.read_text(encoding="utf-8")}, monkeypatch)
    df, players = team_payroll_ingest.ingest_season("2009-10", ["BOS"])
    assert list(df.columns) == TOTAL_COLUMNS
    assert list(players.columns) == PLAYER_COLUMNS
    # The two files describe the same scrape, so they must agree to the dollar.
    assert players["salary_usd"].sum() == df["team_payroll"].sum() == 83552174
    assert df["fetched_at_utc"].notna().all()
    assert players["fetched_at_utc"].notna().all()


def test_write_season_parquet_round_trips(tmp_path, monkeypatch):
    _fake_pages({"BOS": FIXTURE.read_text(encoding="utf-8"), "DAL": "<html>x</html>"}, monkeypatch)
    monkeypatch.setattr(team_payroll_ingest, "RAW_DIR", tmp_path / "team_payroll")
    monkeypatch.setattr(team_payroll_ingest, "PLAYERS_DIR", tmp_path / "team_payroll_players")
    team_payroll_ingest.write_season("2009-10", ["BOS", "DAL"])

    df = pd.read_parquet(tmp_path / "team_payroll" / "2009-10.parquet")
    assert list(df.columns) == TOTAL_COLUMNS
    assert set(df["player_count"]) == {0, 14}
    players = pd.read_parquet(tmp_path / "team_payroll_players" / "2009-10.parquet")
    assert list(players.columns) == PLAYER_COLUMNS
    assert len(players) == 14


def test_write_season_refetches_a_season_missing_its_player_file(tmp_path, monkeypatch):
    """Seasons backfilled before per-player rows were kept have only the
    totals file. Skipping them would leave the contracts list empty forever,
    so the skip needs both files present."""
    calls = []

    def fake_fetch(team_code, season):
        calls.append(team_code)
        return FIXTURE.read_text(encoding="utf-8")

    monkeypatch.setattr(team_payroll_ingest, "fetch_team_season_html", fake_fetch)
    monkeypatch.setattr(team_payroll_ingest, "RAW_DIR", tmp_path / "team_payroll")
    monkeypatch.setattr(team_payroll_ingest, "PLAYERS_DIR", tmp_path / "team_payroll_players")
    (tmp_path / "team_payroll").mkdir()
    pd.DataFrame({"season": ["2009-10"]}).to_parquet(tmp_path / "team_payroll" / "2009-10.parquet")

    team_payroll_ingest.write_season("2009-10", ["BOS"])
    assert calls == ["BOS"], "a season without its player file must be re-fetched"

    team_payroll_ingest.write_season("2009-10", ["BOS"])
    assert calls == ["BOS"], "with both files present the season is skipped"
```

- [ ] **Step 2: Run the tests and confirm they fail.**
Run: `.venv/Scripts/python.exe -m pytest tests/test_team_payroll_ingest.py -q`
Expected: FAIL on the new asserts (`KeyError: 'bbref_player_id'`, the tuple unpack, and the missing `PLAYERS_DIR`).

- [ ] **Step 3: Implement.** In `ingestion/team_payroll_ingest.py`:
- Update the module docstring's column list to mention both files.
- Add `import html as html_lib` and `from datetime import datetime, timezone`.
- Add these constants and replace the regex and functions:

```python
RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw" / "team_payroll"
# One row per salary line - the rows team_payroll sums. Kept so the dashboard
# can show which contracts a payroll is made of, not just its total.
PLAYERS_DIR = Path(__file__).resolve().parent.parent / "data" / "raw" / "team_payroll_players"

TOTAL_COLUMNS = ["season", "team_abbreviation", "team_payroll", "player_count",
                 "fetched_at_utc"]
PLAYER_COLUMNS = ["season", "team_abbreviation", "bbref_player_id", "player",
                  "salary_usd", "fetched_at_utc"]

_SALARY_ROW_RE = re.compile(
    r'<td[^>]*data-append-csv="([^"]*)"[^>]*data-stat="player"[^>]*><a[^>]*>([^<]+)</a></td>'
    r'<td[^>]*data-stat="salary"[^>]*csk="(\d+)"',
)


def parse_salary_table(html: str) -> list[dict]:
    """Extract [{'bbref_player_id', 'player', 'salary_usd'}, ...] from a team-season page.

    bbref_player_id is Basketball-Reference's own id (e.g. "piercpa01") - the
    only stable key for a player across teams and seasons, since names repeat
    and change spelling. A player on two 10-day contracts with the same team
    appears twice; that is two real salary lines, not a duplicate.
    """
    salaries_section = html.split('id="salaries2"', 1)
    if len(salaries_section) < 2:
        return []
    table_html = salaries_section[1]
    end = table_html.find("</table>")
    if end != -1:
        table_html = table_html[:end]
    return [
        {"bbref_player_id": player_id, "player": html_lib.unescape(player),
         "salary_usd": int(salary)}
        for player_id, player, salary in _SALARY_ROW_RE.findall(table_html)
    ]
```

In `team_season_payroll`, add `players` to both returns and add a sentence to the docstring: "`players` is the parsed salary rows the total was summed from."

```python
    if not rows:
        return {"team_payroll": None, "player_count": 0, "players": []}
    return {"team_payroll": sum(r["salary_usd"] for r in rows),
            "player_count": len(rows), "players": rows}
```

Replace `ingest_season` and `write_season`:

```python
def ingest_season(season: str, team_codes: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Fetch payroll for every team active in `season`.

    Returns (totals, players): one totals row per team, always - a team with
    no salary data still gets a row (null payroll, player_count 0) rather than
    being dropped, because a downstream completeness flag can only fire for a
    team-season that actually exists - and one players row per salary line.

    fetched_at_utc is stamped per team at fetch time (naive UTC), so the
    dashboard can say when its salary figures were last refreshed.
    """
    records, player_records = [], []
    for code in team_codes:
        result = team_season_payroll(code, season)
        fetched_at = datetime.now(timezone.utc).replace(tzinfo=None)
        if result["player_count"] == 0:
            log.warning("No salary data for %s %s - writing a null-payroll row", code, season)
        records.append({
            "season": season,
            "team_abbreviation": code,
            "team_payroll": result["team_payroll"],
            "player_count": result["player_count"],
            "fetched_at_utc": fetched_at,
        })
        for row in result["players"]:
            player_records.append({"season": season, "team_abbreviation": code,
                                   **row, "fetched_at_utc": fetched_at})
    df = pd.DataFrame.from_records(records, columns=TOTAL_COLUMNS)
    # Nullable Int64, not the float64 pandas would infer from the None rows -
    # payroll stays an exact integer in the parquet instead of picking up a
    # float type (and float formatting) just because some seasons have gaps.
    df["team_payroll"] = df["team_payroll"].astype("Int64")
    df["player_count"] = df["player_count"].astype("int64")
    df["fetched_at_utc"] = pd.to_datetime(df["fetched_at_utc"])

    players = pd.DataFrame.from_records(player_records, columns=PLAYER_COLUMNS)
    players["salary_usd"] = players["salary_usd"].astype("int64")
    players["fetched_at_utc"] = pd.to_datetime(players["fetched_at_utc"])
    return df, players


def write_season(season: str, team_codes: list[str], force: bool = False) -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    PLAYERS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RAW_DIR / f"{season}.parquet"
    players_path = PLAYERS_DIR / f"{season}.parquet"
    # Skip only when BOTH files exist: a season backfilled before per-player
    # rows were kept has the totals file alone and must be fetched again.
    if out_path.exists() and players_path.exists() and not force:
        log.info("%s already ingested, skipping (use --force to redo)", season)
        return
    df, players = ingest_season(season, team_codes)
    df.to_parquet(out_path, index=False)
    players.to_parquet(players_path, index=False)
    empty = int((df["player_count"] == 0).sum())
    log.info("Wrote %s and %s (%d teams, %d salary lines, %d teams with no salary data)",
             out_path.name, players_path, len(df), len(players), empty)
```

- [ ] **Step 4: Run the tests and confirm they pass.**
Run: `.venv/Scripts/python.exe -m pytest tests/test_team_payroll_ingest.py -q`
Expected: all pass.

- [ ] **Step 5: Commit.**

```bash
git add ingestion/team_payroll_ingest.py tests/test_team_payroll_ingest.py
git commit -m "Keep per-player salary rows and a fetch timestamp when scraping payroll"
```

---

### Task 2: Re-backfill every season (operational, about 70 minutes)

**Files:**
- Writes (gitignored): `data/raw/team_payroll/*.parquet`, `data/raw/team_payroll_players/*.parquet`
- Create: `data/fixtures/team_payroll_players/1984-85.parquet`, `data/fixtures/team_payroll_players/2024-25.parquet`
- Modify: `data/fixtures/team_payroll/1984-85.parquet`, `data/fixtures/team_payroll/2024-25.parquet`

- [ ] **Step 1: Record the pre-backfill totals.** These are used for the before/after comparison.

```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -c "
import duckdb; c=duckdb.connect('warehouse/basketball.duckdb', read_only=True)
c.sql(\"select season, team_abbreviation, team_payroll, player_count from raw.team_payroll\").df().to_parquet('$TEMP/payroll_before.parquet')"
```

- [ ] **Step 2: Run the backfill in the background.** Every season lacks its player file, so `write_season` re-fetches it without `--force`.
Run: `.venv/Scripts/python.exe scripts/backfill_team_payroll.py` (`run_in_background`, timeout 7200000).
Expected: the log ends with `Backfill complete.`, and `data/raw/team_payroll_players/` holds one file per season, 1984-85 through 2025-26.

- [ ] **Step 3: Verify the new totals match the old ones.** The same source should give the same numbers.

```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -c "
import pandas as pd, glob
before = pd.read_parquet('$TEMP/payroll_before.parquet')
after = pd.concat(pd.read_parquet(p) for p in glob.glob('data/raw/team_payroll/*.parquet'))
players = pd.concat(pd.read_parquet(p) for p in glob.glob('data/raw/team_payroll_players/*.parquet'))
m = before.merge(after, on=['season','team_abbreviation'], suffixes=('_b','_a'))
diff = m[(m.team_payroll_b.fillna(-1) != m.team_payroll_a.fillna(-1))]
print('rows', len(before), len(after), 'changed', len(diff))
print(diff.head(20).to_string())
s = players.groupby(['season','team_abbreviation']).salary_usd.sum().rename('lines').reset_index()
chk = after.merge(s, on=['season','team_abbreviation'], how='left')
bad = chk[chk.team_payroll.notna() & (chk.team_payroll != chk.lines)]
print('totals != sum of lines:', len(bad))"
```

Expected: `totals != sum of lines: 0`, and very few or no changed rows. Basketball-Reference can revise a recent season, so changes concentrated in 2025-26 are fine. Report the counts. If more than a handful of older seasons changed, stop and investigate before continuing.

- [ ] **Step 4: Refresh the CI fixtures from the real files.** The existing fixtures are byte-for-byte copies of the real 1984-85 and 2024-25 files.

```bash
mkdir -p data/fixtures/team_payroll_players
cp data/raw/team_payroll/1984-85.parquet data/raw/team_payroll/2024-25.parquet data/fixtures/team_payroll/
cp data/raw/team_payroll_players/1984-85.parquet data/raw/team_payroll_players/2024-25.parquet data/fixtures/team_payroll_players/
```

- [ ] **Step 5: Reload the warehouse.**
Run: `.venv/Scripts/python.exe scripts/load_to_duckdb.py`
Expected: the log includes the line `raw.team_payroll_players`.

- [ ] **Step 6: Commit the fixtures.**

```bash
git add data/fixtures/team_payroll data/fixtures/team_payroll_players
git commit -m "Refresh payroll fixtures with per-player rows and fetch timestamps"
```

---

### Task 3: dbt - contracts mart and payroll freshness

**Files:**
- Create: `dbt/basketball_intelligence/models/staging/stg_team_payroll_players.sql`
- Create: `dbt/basketball_intelligence/models/marts/mart_team_contracts.sql`
- Create: `dbt/basketball_intelligence/tests/assert_team_contracts_grain.sql`
- Create: `dbt/basketball_intelligence/tests/assert_team_contracts_sum_to_payroll.sql`
- Modify: `dbt/basketball_intelligence/models/staging/stg_team_payroll.sql`
- Modify: `dbt/basketball_intelligence/models/marts/mart_team_finances.sql`
- Modify: `dbt/basketball_intelligence/models/staging/_sources.yml`, `_staging_models.yml`, `models/marts/_marts_models.yml`

**Interfaces:**
- Produces:
  - `main_marts.mart_team_contracts(season, team_abbreviation, bbref_player_id, player, salary_usd, salary_rank, share_of_payroll)`
  - `main_marts.mart_team_finances.payroll_fetched_at_utc` (timestamp, null for rows from an old scrape)

- [ ] **Step 1: Write the singular tests.** These are the failing tests for this task.

`tests/assert_team_contracts_grain.sql`:

```sql
-- One row per player per team-season. Two 10-day contracts with the same
-- team are two salary lines in the source; the mart sums them into one row,
-- so the contracts list never shows a player twice.
select season, team_abbreviation, bbref_player_id, count(*) as n
from {{ ref('mart_team_contracts') }}
group by 1, 2, 3
having count(*) > 1
```

`tests/assert_team_contracts_sum_to_payroll.sql`:

```sql
-- The contracts list and the payroll figure come from the same scrape of the
-- same salary rows, so for every team-season with player rows they must
-- agree to the dollar. A mismatch means the two raw files came from
-- different scrapes and the page would show a list that doesn't add up.
select f.season, f.team_abbreviation, f.team_payroll, c.total
from {{ ref('mart_team_finances') }} f
join (
    select season, team_abbreviation, sum(salary_usd) as total
    from {{ ref('mart_team_contracts') }}
    group by 1, 2
) c using (season, team_abbreviation)
where f.team_payroll <> c.total
```

- [ ] **Step 2: Run them and confirm they fail.**
Run (in `dbt/basketball_intelligence`): `../../.venv/Scripts/dbt.exe test --profiles-dir . --select assert_team_contracts_grain`
Expected: ERROR, because `mart_team_contracts` is not found.

- [ ] **Step 3: Write the models.**

`models/staging/stg_team_payroll_players.sql`:

```sql
-- One row per salary line on a team's Basketball-Reference season page,
-- typed. A player can appear twice for one team-season (two 10-day
-- contracts); mart_team_contracts sums those.
select
    cast(season as varchar)            as season,
    cast(team_abbreviation as varchar) as team_abbreviation,
    cast(bbref_player_id as varchar)   as bbref_player_id,
    cast(player as varchar)            as player,
    cast(salary_usd as bigint)         as salary_usd,
    cast(fetched_at_utc as timestamp)  as fetched_at_utc
from {{ source('raw', 'team_payroll_players') }}
```

`models/staging/stg_team_payroll.sql`: add the line `cast(fetched_at_utc as timestamp)  as fetched_at_utc` to the select list, after `player_count`, with a comma on the previous line.

`models/marts/mart_team_contracts.sql`:

```sql
-- One row per player per team-season: what the team paid him that season,
-- where that ranks on its payroll, and his share of the total. Feeds the
-- Finances page's "biggest contracts" list - the answer to "why is this team
-- over the tax" that a payroll total alone can't give.
with lines as (
    select
        season,
        team_abbreviation,
        bbref_player_id,
        any_value(player) as player,
        sum(salary_usd)   as salary_usd
    from {{ ref('stg_team_payroll_players') }}
    group by 1, 2, 3
)

select
    season,
    team_abbreviation,
    bbref_player_id,
    player,
    salary_usd,
    row_number() over (partition by season, team_abbreviation
                       order by salary_usd desc, player) as salary_rank,
    round(salary_usd / sum(salary_usd) over (partition by season, team_abbreviation), 4)
                                                         as share_of_payroll
from lines
```

`models/marts/mart_team_finances.sql`: add `p.fetched_at_utc as payroll_fetched_at_utc,` directly after `p.player_count,` in the final select. Add this to the header comment:

```sql
-- payroll_fetched_at_utc is when this team-season's page was last scraped,
-- so the dashboard can say how current its salary figures are. Null for a
-- row scraped before timestamps were recorded.
```

- [ ] **Step 4: Update the YAML.** Add this to `_sources.yml` under the `raw` tables, after `team_payroll`:

```yaml
      - name: team_payroll_players
        description: >
          One row per salary line on a team's Basketball-Reference season page
          (the salaries2 table), 1984-85 on - the rows team_payroll sums,
          written by ingestion/team_payroll_ingest.py from the same fetch.
          Basketball-Reference lists the players a team finished the season
          with plus anyone on 10-day contracts along the way (at the amount
          paid); a traded player appears only on the team he ended with.
```

Add to `team_payroll`'s description: `fetched_at_utc is when the page was scraped (naive UTC).`

Add to `_staging_models.yml`:

```yaml
  - name: stg_team_payroll_players
    description: One row per salary line per team-season, typed.
    columns:
      - name: bbref_player_id
        tests: [not_null]
      - name: salary_usd
        tests: [not_null]
```

Add to `_marts_models.yml`:

```yaml
  - name: mart_team_contracts
    description: >
      One row per player per team-season: salary paid by that team, its rank
      on the team's payroll (1 = biggest) and its share of the payroll.
      Sums to mart_team_finances.team_payroll for every team-season with
      player rows (see assert_team_contracts_sum_to_payroll).
    columns:
      - name: player
        tests: [not_null]
      - name: salary_usd
        tests: [not_null]
      - name: salary_rank
        tests: [not_null]
```

Under `mart_team_finances` columns, add:

```yaml
      - name: payroll_fetched_at_utc
        description: When this team-season's salary page was last scraped (naive UTC).
```

- [ ] **Step 5: Build and test against the real warehouse.**
Run (in `dbt/basketball_intelligence`): `../../.venv/Scripts/dbt.exe seed --profiles-dir . && ../../.venv/Scripts/dbt.exe run --profiles-dir . && ../../.venv/Scripts/dbt.exe test --profiles-dir .`
Expected: everything passes, and both new singular tests return 0 rows.

- [ ] **Step 6: Simulate CI against the fixtures.** Keep the real files safe while doing this.

```bash
mv data/raw "$TEMP/raw_real" && mv warehouse/basketball.duckdb "$TEMP/real.duckdb"
mkdir -p data/raw && cp -r data/fixtures/* data/raw/ && .venv/Scripts/python.exe scripts/load_to_duckdb.py
(cd dbt/basketball_intelligence && ../../.venv/Scripts/dbt.exe seed --profiles-dir . && ../../.venv/Scripts/dbt.exe run --profiles-dir . && ../../.venv/Scripts/dbt.exe test --profiles-dir .)
CI=true .venv/Scripts/python.exe -m pytest tests -q
rm -rf data/raw warehouse/basketball.duckdb && mv "$TEMP/raw_real" data/raw && mv "$TEMP/real.duckdb" warehouse/basketball.duckdb
```

Expected: dbt and pytest both pass on the fixtures. The real data is restored afterwards. Confirm with `ls data/raw/team_payroll_players | wc -l`, which should show 42.

- [ ] **Step 7: Commit.**

```bash
git add dbt/basketball_intelligence
git commit -m "Add a per-player contracts mart and a payroll fetch date"
```

---

### Task 4: Franchise lineage that follows the contracts

**Files:**
- Create: `dashboard/lib/franchises.py`
- Modify: `dashboard/lib/db.py:480-531` (remove `MERGED_FRANCHISES`, `_LEGACY_TO_MODERN`, `franchise_codes`, `display_code`, `franchise_options`, and change `team_payroll_history`)
- Create: `tests/test_franchises.py`
- Modify: `tests/test_db_metrics.py`

**Interfaces:**
- Produces:
  - `franchises.FRANCHISE_NAMES: dict[str, str]`
  - `franchises.FRANCHISE_NOTES: dict[str, str]`
  - `franchises.franchise_of(code, season) -> str`
  - `franchises.era_name(code, season) -> str`
  - `franchises.franchise_name(key) -> str`
  - `franchises.annotate(df) -> df` (adds the `franchise` and `era_name` columns)
  - `franchises.era_spans(team_df) -> list[tuple[str, str, str]]`, as `(first_season, last_season, era_name)`
  - `db.team_payroll_history(franchise: str | None = None)`

- [ ] **Step 1: Write the failing tests** in `tests/test_franchises.py`:

```python
"""Franchise lineage for the Finances page: payroll follows the contracts,
and the mapping is by (code, season), never by code alone."""

import pandas as pd
import pytest

from dashboard.lib import franchises


@pytest.mark.parametrize("code,season,franchise,name", [
    ("SEA", "2007-08", "OKC", "Seattle SuperSonics"),
    ("OKC", "2008-09", "OKC", "Oklahoma City Thunder"),
    ("VAN", "2000-01", "MEM", "Vancouver Grizzlies"),
    ("NJN", "2011-12", "BKN", "New Jersey Nets"),
    ("KCK", "1984-85", "SAC", "Kansas City Kings"),
    # The original Hornets' contracts moved to New Orleans in 2002.
    ("CHH", "2001-02", "NOP", "Charlotte Hornets"),
    ("NOH", "2012-13", "NOP", "New Orleans Hornets"),
    ("NOK", "2005-06", "NOP", "New Orleans/Oklahoma City Hornets"),
    ("NOP", "2013-14", "NOP", "New Orleans Pelicans"),
    # Today's Hornets start as the 2004 Bobcats.
    ("CHA", "2004-05", "CHA", "Charlotte Bobcats"),
    ("CHA", "2013-14", "CHA", "Charlotte Bobcats"),
    ("CHA", "2014-15", "CHA", "Charlotte Hornets"),
    ("WAS", "1996-97", "WAS", "Washington Bullets"),
    ("WAS", "1997-98", "WAS", "Washington Wizards"),
    ("GOS", "1995-96", "GSW", "Golden State Warriors"),
    ("PHL", "1995-96", "PHI", "Philadelphia 76ers"),
    ("SAN", "1995-96", "SAS", "San Antonio Spurs"),
    ("UTH", "1995-96", "UTA", "Utah Jazz"),
    ("BOS", "2023-24", "BOS", "Boston Celtics"),
])
def test_franchise_and_era_name(code, season, franchise, name):
    assert franchises.franchise_of(code, season) == franchise
    assert franchises.era_name(code, season) == name


def test_a_future_seattle_team_is_not_folded_into_oklahoma_city():
    """An expansion team reusing SEA starts fresh: new contracts, no payroll
    history. Only the 1984-2008 SuperSonics belong to OKC's money history."""
    assert franchises.franchise_of("SEA", "2028-29") == "SEA"
    assert franchises.franchise_name("SEA") == "SEA"


def test_every_franchise_key_in_use_has_a_full_name():
    keys = {era.franchise for era in franchises.ERAS}
    assert keys <= set(franchises.FRANCHISE_NAMES)
    assert len(franchises.FRANCHISE_NAMES) == 30


def test_annotate_and_era_spans():
    df = pd.DataFrame({
        "season": ["2006-07", "2007-08", "2008-09", "2009-10"],
        "team_abbreviation": ["SEA", "SEA", "OKC", "OKC"],
    })
    out = franchises.annotate(df)
    assert out["franchise"].tolist() == ["OKC"] * 4
    assert franchises.era_spans(out) == [
        ("2006-07", "2007-08", "Seattle SuperSonics"),
        ("2008-09", "2009-10", "Oklahoma City Thunder"),
    ]
    assert "franchise" not in df.columns, "annotate must not mutate its input"


def test_every_code_in_the_real_mart_maps_to_a_named_franchise(con):
    rows = con.execute(
        "select distinct team_abbreviation, season from main_marts.mart_team_finances"
    ).fetchall()
    unnamed = {(c, s) for c, s in rows
               if franchises.franchise_of(c, s) not in franchises.FRANCHISE_NAMES}
    assert not unnamed, f"codes with no franchise name: {sorted(unnamed)[:10]}"
```

- [ ] **Step 2: Run them and confirm they fail.**
Run: `.venv/Scripts/python.exe -m pytest tests/test_franchises.py -q`
Expected: FAIL with `ImportError: cannot import name 'franchises'`.

- [ ] **Step 3: Implement** `dashboard/lib/franchises.py`:

```python
"""Which franchise a team code belongs to, season by season, and what the
team was called then - for the Finances page.

Payroll history follows the contracts. A relocation is the same legal
business moving its contracts, players and staff to a new city, so its
payroll stays one continuous line: the 2008 Thunder carried the SuperSonics'
books, and the 2002 New Orleans Hornets carried Charlotte's. The NBA has
since handed Charlotte its 1988-2002 records and name back (2014), and would
very likely do the same for Seattle if it gets a team again - but that is
about records, not money. FRANCHISE_NOTES says so on the page.

Mapping is by (code, season), never code alone, so a future expansion team
that reuses "SEA" is its own franchise rather than being folded into
Oklahoma City.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

FRANCHISE_NAMES = {
    "ATL": "Atlanta Hawks", "BOS": "Boston Celtics", "BKN": "Brooklyn Nets",
    "CHA": "Charlotte Hornets", "CHI": "Chicago Bulls", "CLE": "Cleveland Cavaliers",
    "DAL": "Dallas Mavericks", "DEN": "Denver Nuggets", "DET": "Detroit Pistons",
    "GSW": "Golden State Warriors", "HOU": "Houston Rockets", "IND": "Indiana Pacers",
    "LAC": "LA Clippers", "LAL": "Los Angeles Lakers", "MEM": "Memphis Grizzlies",
    "MIA": "Miami Heat", "MIL": "Milwaukee Bucks", "MIN": "Minnesota Timberwolves",
    "NOP": "New Orleans Pelicans", "NYK": "New York Knicks",
    "OKC": "Oklahoma City Thunder", "ORL": "Orlando Magic",
    "PHI": "Philadelphia 76ers", "PHX": "Phoenix Suns",
    "POR": "Portland Trail Blazers", "SAC": "Sacramento Kings",
    "SAS": "San Antonio Spurs", "TOR": "Toronto Raptors", "UTA": "Utah Jazz",
    "WAS": "Washington Wizards",
}


@dataclass(frozen=True)
class Era:
    code: str
    franchise: str
    name: str
    last_season: str | None = None  # inclusive; None = every season under this code


# Codes whose franchise or name differs from the default (a code is its own
# franchise, named FRANCHISE_NAMES[code]). Checked in order, first match wins.
# Season strings compare correctly as text ("1999-00" < "2000-01").
ERAS = [
    Era("SEA", "OKC", "Seattle SuperSonics", last_season="2007-08"),
    Era("VAN", "MEM", "Vancouver Grizzlies"),
    Era("NJN", "BKN", "New Jersey Nets"),
    Era("KCK", "SAC", "Kansas City Kings"),
    Era("CHH", "NOP", "Charlotte Hornets", last_season="2001-02"),
    Era("NOH", "NOP", "New Orleans Hornets"),
    Era("NOK", "NOP", "New Orleans/Oklahoma City Hornets"),
    Era("CHA", "CHA", "Charlotte Bobcats", last_season="2013-14"),
    Era("WAS", "WAS", "Washington Bullets", last_season="1996-97"),
    # nba_api's own 1996-97 code renames - same team, same name.
    Era("GOS", "GSW", "Golden State Warriors"),
    Era("PHL", "PHI", "Philadelphia 76ers"),
    Era("SAN", "SAS", "San Antonio Spurs"),
    Era("UTH", "UTA", "Utah Jazz"),
]

FRANCHISE_NOTES = {
    "OKC": ("Includes the Seattle SuperSonics years in this data (1984-85 to "
            "2007-08). Seattle kept the SuperSonics name and history, but the "
            "team's contracts and roster moved to Oklahoma City in 2008, so that "
            "payroll is shown here."),
    "NOP": ("Includes the original Charlotte Hornets (1988-89 to 2001-02). The "
            "NBA credits those seasons' records to today's Charlotte Hornets, but "
            "the contracts and roster moved to New Orleans in 2002, so that "
            "payroll is shown here."),
    "CHA": ("Starts with the Charlotte Bobcats in 2004-05. The NBA credits the "
            "1988-2002 Hornets' records to Charlotte, but those contracts moved "
            "to New Orleans in 2002, so that payroll is shown under the New "
            "Orleans Pelicans."),
}


def _era(code: str, season: str) -> Era | None:
    for era in ERAS:
        if era.code == code and (era.last_season is None or season <= era.last_season):
            return era
    return None


def franchise_of(code: str, season: str) -> str:
    era = _era(code, season)
    return era.franchise if era else code


def era_name(code: str, season: str) -> str:
    era = _era(code, season)
    return era.name if era else FRANCHISE_NAMES.get(code, code)


def franchise_name(franchise: str) -> str:
    return FRANCHISE_NAMES.get(franchise, franchise)


def annotate(df: pd.DataFrame) -> pd.DataFrame:
    """A copy of df (needs team_abbreviation and season) with franchise and
    era_name columns added."""
    out = df.copy()
    pairs = list(zip(out["team_abbreviation"], out["season"]))
    out["franchise"] = [franchise_of(c, s) for c, s in pairs]
    out["era_name"] = [era_name(c, s) for c, s in pairs]
    return out


def era_spans(team_df: pd.DataFrame) -> list[tuple[str, str, str]]:
    """(first_season, last_season, era_name) for each consecutive run of one
    name in an annotated, single-franchise frame, oldest first."""
    spans: list[tuple[str, str, str]] = []
    ordered = team_df.sort_values("season")[["season", "era_name"]]
    for season, name in ordered.itertuples(index=False):
        if spans and spans[-1][2] == name:
            spans[-1] = (spans[-1][0], season, name)
        else:
            spans.append((season, season, name))
    return spans
```

- [ ] **Step 4: Update `db.py`.**
- Delete everything from the `MERGED_FRANCHISES = {` block through `franchise_options`, along with its leading comment block.
- Add `from . import franchises` beside the other imports. Use the same relative style as `viz.py`. If `db.py` uses absolute imports, use `from dashboard.lib import franchises` instead.
- Replace `team_payroll_history`:

```python
def team_payroll_history(franchise: str | None = None) -> pd.DataFrame:
    """Payroll vs. cap/tax/apron thresholds, one row per team-season.

    With a franchise key (see dashboard/lib/franchises.py), returns every
    season of that franchise under any code it has played under - OKC
    includes the 1984-2008 SEA rows, NOP the 1988-2002 CHH rows - annotated
    with franchise and era_name. The franchise mapping is season-aware, which
    a SQL `in (codes)` filter could not express, so it is applied here."""
    df = q("select * from main_marts.mart_team_finances order by season, team_abbreviation")
    if franchise is None:
        return df
    df = franchises.annotate(df)
    return df[df["franchise"] == franchise].reset_index(drop=True)
```

- [ ] **Step 5: Update `tests/test_db_metrics.py`.**
- `test_team_payroll_history_filters_by_team`: change the call to `db.team_payroll_history(franchise="BOS")`.
- `test_team_payroll_history_merges_a_renamed_franchise`: change the call to `db.team_payroll_history(franchise="GSW")`.
- Replace `test_team_payroll_history_does_not_merge_an_unrelated_team` and `test_franchise_options_collapses_only_the_renamed_pairs` with:

```python
def test_team_payroll_history_does_not_merge_an_unrelated_team(warehouse_with_finances_mart):
    """Folding eras into a franchise must not pull in another team's rows."""
    for code in ("BOS", "NYK", "MIA", "DEN"):
        df = db.team_payroll_history(franchise=code)
        assert set(df["team_abbreviation"]) == {code}, code
```

- [ ] **Step 6: Run the tests.**
Run: `.venv/Scripts/python.exe -m pytest tests/test_franchises.py tests/test_db_metrics.py -q`
Expected: the franchise and db tests pass. `tests/test_finances_page.py` is expected to fail until Task 7, because the page still calls the removed functions. Don't run it yet.

- [ ] **Step 7: Commit.**

```bash
git add dashboard/lib/franchises.py dashboard/lib/db.py tests/test_franchises.py tests/test_db_metrics.py
git commit -m "Group relocated teams into one franchise, following the contracts"
```

---

### Task 5: Plain-English payroll text and brackets

**Files:**
- Create: `dashboard/lib/payroll.py`
- Create: `tests/test_payroll_text.py`

**Interfaces:**
- Produces:
  - `payroll.LINES: list[tuple[col, label, color]]`
  - `payroll.bracket(row) -> (label, color)`
  - `payroll.money(v) -> str`
  - `payroll.ordinal(n) -> str`
  - `payroll.reliable(df) -> df`
  - `payroll.league_rank(league_df, code) -> (rank, n) | None`
  - `payroll.position_phrase(row) -> str`
  - `payroll.league_summary(league_df, season) -> str`
  - `payroll.team_summary(row, team_name, rank, contracts) -> str`
  - `payroll.freshness_text(fetched_at, latest_payroll_season, latest_cap_season) -> str`
  - `payroll.HOW_TO_READ: str`
  - `payroll.METHOD_NOTE: str`

- [ ] **Step 1: Write the failing tests** in `tests/test_payroll_text.py`:

```python
"""The sentences the Finances page puts next to its numbers."""

import pandas as pd

from dashboard.lib import payroll
from dashboard.lib import theme as T

CAP, TAX, A1, A2 = 140_588_000, 170_814_000, 178_132_000, 188_931_000


def _row(pay, season="2024-25", code="BOS", flagged=False, tax=TAX, a1=A1, a2=A2):
    return pd.Series({
        "season": season, "team_abbreviation": code, "team_payroll": pay,
        "salary_cap": CAP, "luxury_tax": tax, "first_apron": a1, "second_apron": a2,
        "payroll_likely_incomplete": flagged,
        "over_cap": pay > CAP,
        "over_tax": (pay > tax) if tax else pd.NA,
        "over_first_apron": (pay > a1) if a1 else pd.NA,
        "over_second_apron": (pay > a2) if a2 else pd.NA,
    })


def test_money_and_ordinal():
    assert payroll.money(193_348_445) == "$193.3M"
    assert payroll.money(850_000) == "$850K"
    assert [payroll.ordinal(n) for n in (1, 2, 3, 4, 11, 12, 13, 21, 22)] == \
        ["1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "22nd"]


def test_bracket_picks_the_highest_line_crossed():
    assert payroll.bracket(_row(130e6)) == ("Under cap", T.GOOD)
    assert payroll.bracket(_row(150e6))[0] == "Over cap"
    assert payroll.bracket(_row(175e6))[0] == "Over tax"
    assert payroll.bracket(_row(180e6))[0] == "Over 1st apron"
    assert payroll.bracket(_row(200e6)) == ("Over 2nd apron", T.CRITICAL)
    assert payroll.bracket(_row(200e6, flagged=True))[0] == "Data incomplete"


def test_bracket_handles_pre_apron_nulls():
    row = _row(150e6, season="2010-11", tax=None, a1=None, a2=None)
    assert payroll.bracket(row)[0] == "Over cap"


def test_position_phrase():
    assert payroll.position_phrase(_row(130_588_000)) == "$10.0M under the salary cap"
    assert payroll.position_phrase(_row(150_588_000)) == \
        "$10.0M over the salary cap and $20.2M under the luxury tax line"
    assert payroll.position_phrase(_row(175_814_000)) == \
        "$5.0M over the luxury tax line and $2.3M under the first apron"
    assert payroll.position_phrase(_row(198_931_000)) == "$10.0M over the second apron"
    pre_tax = _row(150_588_000, season="1999-00", tax=None, a1=None, a2=None)
    assert payroll.position_phrase(pre_tax) == "$10.0M over the salary cap"


def _league():
    return pd.DataFrame([_row(p, code=c) for c, p in
                         [("BOS", 193e6), ("PHX", 214e6), ("DET", 141.8e6), ("ORL", 150e6)]]
                        + [_row(2e6, code="XXX", flagged=True)])


def test_league_rank_ignores_unreliable_rows():
    assert payroll.league_rank(_league(), "PHX") == (1, 4)
    assert payroll.league_rank(_league(), "BOS") == (2, 4)
    assert payroll.league_rank(_league(), "XXX") is None


def test_league_summary():
    text = payroll.league_summary(_league(), "2024-25")
    assert text == ("In 2024-25, 4 of 4 teams were over the salary cap, 2 over the "
                    "luxury tax line, 2 over the first apron and 2 over the second "
                    "apron. 1 team has no reliable figure for this season.")


def test_team_summary_with_contracts():
    contracts = pd.DataFrame({
        "player": ["Player One", "Player Two", "Player Three", "Player Four"],
        "salary_usd": [50e6, 30e6, 20e6, 10e6],
        "salary_rank": [1, 2, 3, 4],
        "share_of_payroll": [0.25, 0.15, 0.10, 0.05],
    })
    text = payroll.team_summary(_row(175_814_000), "Boston Celtics", (3, 30), contracts)
    assert text == ("In 2024-25 the Boston Celtics spent $175.8M, the 3rd-highest payroll "
                    "of 30 teams. That's $5.0M over the luxury tax line and $2.3M under "
                    "the first apron. Their three biggest contracts (Player One, Player "
                    "Two and Player Three) made up 50% of the payroll.")


def test_team_summary_top_payroll_and_no_contracts():
    text = payroll.team_summary(_row(214e6), "Phoenix Suns", (1, 30), None)
    assert text.startswith("In 2024-25 the Phoenix Suns spent $214.0M, the highest "
                           "payroll of 30 teams.")
    assert "contracts" not in text


def test_team_summary_unreliable():
    text = payroll.team_summary(_row(2e6, flagged=True), "Denver Nuggets", None, None)
    assert text == "There's no reliable payroll figure for the Denver Nuggets in 2024-25."


def test_freshness_text():
    ts = pd.Timestamp("2026-09-23 20:58:40")
    assert payroll.freshness_text(ts, "2025-26", "2025-26") == \
        "Salary data updated Sep 23, 2026 · covers through 2025-26."
    assert payroll.freshness_text(ts, "2025-26", "2026-27") == \
        ("Salary data updated Sep 23, 2026 · covers through 2025-26. "
         "2026-27 payrolls aren't loaded yet.")
    assert payroll.freshness_text(None, "2025-26", "2025-26") == \
        "Salary data covers through 2025-26 (update date not recorded in this copy)."
```

- [ ] **Step 2: Run them and confirm they fail.**
Run: `.venv/Scripts/python.exe -m pytest tests/test_payroll_text.py -q`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement** `dashboard/lib/payroll.py`:

```python
"""Plain-English reading of payrolls against the league's lines - the words
and colors the Finances page puts next to its numbers.

Pure functions over the mart's rows, no Streamlit, so every sentence the
page can publish is pinned by tests/test_payroll_text.py. The first version
of the page showed bare figures and "Over cap" on 28-30 teams a season with
no word that a soft cap makes that normal; this module exists so no number
reaches the page without the sentence that says what it means.
"""

from __future__ import annotations

import pandas as pd

from . import theme as T

# (mart column, label, color), lowest line first. The same color means the
# same line everywhere: both charts, the status card and the bar colors.
# The cap is neutral on purpose - being over it is normal.
LINES = [
    ("salary_cap", "Salary cap", T.INK_2),
    ("luxury_tax", "Luxury tax", T.SERIES[3]),
    ("first_apron", "First apron", T.SERIES[1]),
    ("second_apron", "Second apron", T.CRITICAL),
]
_LINE_PHRASES = {"salary_cap": "salary cap", "luxury_tax": "luxury tax line",
                 "first_apron": "first apron", "second_apron": "second apron"}

# Highest first: over the second apron is also over everything below it.
_TIERS = [
    ("over_second_apron", "second_apron", "Over 2nd apron"),
    ("over_first_apron", "first_apron", "Over 1st apron"),
    ("over_tax", "luxury_tax", "Over tax"),
    ("over_cap", "salary_cap", "Over cap"),
]
_COLOR = {col: color for col, _, color in LINES}


def _true(value) -> bool:
    # over_tax/over_*_apron are NA, not False, before that line existed -
    # and NA has no truth value.
    return bool(pd.notna(value) and value)


def _unreliable(row) -> bool:
    return _true(row["payroll_likely_incomplete"]) or pd.isna(row["team_payroll"])


def bracket(row) -> tuple[str, str]:
    """(label, color) for the highest line this team-season's payroll crossed."""
    if _unreliable(row):
        return "Data incomplete", T.MUTED
    for flag, col, label in _TIERS:
        if _true(row[flag]):
            return label, _COLOR[col]
    return "Under cap", T.GOOD


def money(value: float) -> str:
    if abs(value) >= 1_000_000:
        return f"${value / 1e6:,.1f}M"
    return f"${value / 1e3:,.0f}K"


def ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def reliable(league_df: pd.DataFrame) -> pd.DataFrame:
    """Rows whose payroll can be published as a real number."""
    # astype(bool): `~` on an object column of Python bools is bitwise int
    # negation (~True == -2), not a boolean NOT.
    flagged = league_df["payroll_likely_incomplete"].fillna(True).astype(bool)
    keep = league_df["team_payroll"].notna() & ~flagged
    return league_df[keep]


def league_rank(league_df: pd.DataFrame, team_abbreviation: str) -> tuple[int, int] | None:
    """(rank, out of) by payroll, highest = 1, among reliable rows only."""
    ok = reliable(league_df).sort_values("team_payroll", ascending=False).reset_index(drop=True)
    hit = ok.index[ok["team_abbreviation"] == team_abbreviation]
    return (int(hit[0]) + 1, len(ok)) if len(hit) else None


def _next_line_up(row, col: str) -> str | None:
    cols = [c for c, _, _ in LINES]
    for higher in cols[cols.index(col) + 1:]:
        if pd.notna(row[higher]):
            return higher
    return None


def position_phrase(row) -> str:
    """How far over the highest line crossed, and how far under the next one."""
    pay = row["team_payroll"]
    for flag, col, _ in _TIERS:
        if _true(row[flag]):
            phrase = f"{money(pay - row[col])} over the {_LINE_PHRASES[col]}"
            higher = _next_line_up(row, col)
            if higher:
                phrase += f" and {money(row[higher] - pay)} under the {_LINE_PHRASES[higher]}"
            return phrase
    return f"{money(row['salary_cap'] - pay)} under the salary cap"


def league_summary(league_df: pd.DataFrame, season: str) -> str:
    ok = reliable(league_df)
    n = len(ok)
    parts = [f"{int(ok['over_cap'].map(_true).sum())} of {n} teams were over the salary cap"]
    for flag, col, phrase in [("over_tax", "luxury_tax", "luxury tax line"),
                              ("over_first_apron", "first_apron", "first apron"),
                              ("over_second_apron", "second_apron", "second apron")]:
        if ok[col].notna().any():
            parts.append(f"{int(ok[flag].map(_true).sum())} over the {phrase}")
    text = f"In {season}, {_join(parts)}."
    missing = len(league_df) - n
    if missing:
        text += (f" {missing} team{'s have' if missing > 1 else ' has'} no reliable "
                 "figure for this season.")
    return text


def team_summary(row, team_name: str, rank: tuple[int, int] | None,
                 contracts: pd.DataFrame | None) -> str:
    if _unreliable(row):
        return f"There's no reliable payroll figure for the {team_name} in {row['season']}."
    text = f"In {row['season']} the {team_name} spent {money(row['team_payroll'])}"
    if rank:
        place = "highest" if rank[0] == 1 else f"{ordinal(rank[0])}-highest"
        text += f", the {place} payroll of {rank[1]} teams"
    text += f". That's {position_phrase(row)}."
    if contracts is not None and len(contracts) >= 3:
        top = contracts.nsmallest(3, "salary_rank")
        text += (f" Their three biggest contracts ({_join(top['player'].tolist())}) "
                 f"made up {top['share_of_payroll'].sum():.0%} of the payroll.")
    return text


def freshness_text(fetched_at, latest_payroll_season: str, latest_cap_season: str) -> str:
    if fetched_at is None or pd.isna(fetched_at):
        text = (f"Salary data covers through {latest_payroll_season} "
                "(update date not recorded in this copy).")
    else:
        ts = pd.Timestamp(fetched_at)
        text = (f"Salary data updated {ts:%b} {ts.day}, {ts.year} · covers through "
                f"{latest_payroll_season}.")
    if latest_cap_season > latest_payroll_season:
        text += f" {latest_cap_season} payrolls aren't loaded yet."
    return text


HOW_TO_READ = """
**Salary cap** - the limit on signing other teams' free agents. It's a *soft*
cap: teams can go over it to re-sign their own players, use exceptions and
add minimum contracts, which is why nearly every team is over it. Being over
the cap is normal.

**Luxury tax line** - where spending starts to cost real money. A team over
it at the end of the regular season pays a tax on every dollar above it,
starting at $1.50 per dollar and climbing the further over it goes, with
higher rates for teams that pay it year after year.

**First apron** (2023-24 on) - a team over it loses roster-building tools,
such as taking back more salary than it sends out in a trade.

**Second apron** (2023-24 on) - the strictest line. A team over it can't
combine salaries in a trade or use its mid-level exception, and its
first-round pick seven years out gets frozen.
"""

METHOD_NOTE = (
    "Payroll is the sum of the salaries Basketball-Reference lists for each team's "
    "season: the players it finished the season with, plus anyone on a 10-day "
    "contract along the way at the amount paid. The NBA's official tax bill also "
    "counts money still owed to waived players and only the part of a traded "
    "player's salary each team actually paid, so a team within a few million of "
    "a line may have finished on the other side of it. League cap, tax and apron "
    "figures are the NBA's own."
)
```

- [ ] **Step 4: Run the tests and confirm they pass.**
Run: `.venv/Scripts/python.exe -m pytest tests/test_payroll_text.py -q`
Expected: all pass.

- [ ] **Step 5: Commit.**

```bash
git add dashboard/lib/payroll.py tests/test_payroll_text.py
git commit -m "Add plain-English payroll summaries and one color per cap line"
```

---

### Task 6: Charts and queries - league snapshot, era labels, contracts

**Files:**
- Modify: `dashboard/lib/viz.py`, around `team_finances_trend` (472-559)
- Modify: `dashboard/lib/db.py` (add 2 functions after `salary_cap_history`)
- Modify: `tests/test_viz.py`, `tests/conftest.py`

**Interfaces:**
- Consumes: `payroll.LINES` from Task 5.
- Produces:
  - `viz.league_payroll_snapshot(df, highlight=None) -> go.Figure`. `df` columns: `team_name, team_payroll, bar_color, salary_cap, luxury_tax, first_apron, second_apron`.
  - `viz.team_finances_trend(team_df, cap_df, eras=None)`
  - `db.team_contracts_available() -> bool`
  - `db.team_contracts(season, team_abbreviation) -> df(player, salary_usd, salary_rank, share_of_payroll)`

- [ ] **Step 1: Write the failing tests.** Append to `tests/test_viz.py`:

```python
def test_trend_labels_each_era_and_marks_the_boundary():
    team_df = _team_df([
        {"season": s, "team_payroll": 50_000_000, "payroll_likely_incomplete": False}
        for s in ["2006-07", "2007-08", "2008-09"]
    ])
    eras = [("2006-07", "2007-08", "Seattle SuperSonics"),
            ("2008-09", "2008-09", "Oklahoma City Thunder")]
    fig = viz.team_finances_trend(team_df, _cap_df(team_df["season"].tolist()), eras=eras)
    texts = [a.text for a in fig.layout.annotations]
    assert texts == ["Seattle SuperSonics", "Oklahoma City Thunder"]
    assert len(fig.layout.shapes) == 1 and fig.layout.shapes[0].x0 == "2008-09"


def test_trend_with_one_era_draws_no_labels():
    team_df = _team_df([
        {"season": "2008-09", "team_payroll": 50_000_000, "payroll_likely_incomplete": False},
    ])
    fig = viz.team_finances_trend(team_df, _cap_df(["2008-09"]),
                                  eras=[("2008-09", "2008-09", "Oklahoma City Thunder")])
    assert len(fig.layout.annotations) == 0
    assert len(fig.layout.shapes) == 0


def test_league_snapshot_puts_the_highest_payroll_on_top():
    df = pd.DataFrame({
        "team_name": ["A", "B", "C"], "team_payroll": [150e6, 200e6, 120e6],
        "bar_color": ["#111111"] * 3, "salary_cap": [140e6] * 3,
        "luxury_tax": [170e6] * 3, "first_apron": [None] * 3, "second_apron": [None] * 3,
    })
    fig = viz.league_payroll_snapshot(df, highlight="B")
    bars = fig.data[0]
    # Plotly draws the last category at the top of a horizontal bar chart.
    assert list(bars.y) == ["C", "A", "B"]
    assert {t.name for t in fig.data[1:]} == {"Salary cap", "Luxury tax"}
    assert list(bars.marker.line.width) == [0, 0, 2]


def test_league_snapshot_with_no_rows_says_so():
    empty = pd.DataFrame(columns=["team_name", "team_payroll", "bar_color", "salary_cap",
                                  "luxury_tax", "first_apron", "second_apron"])
    fig = viz.league_payroll_snapshot(empty)
    assert len(fig.data) == 0
    assert "No reliable payroll" in fig.layout.annotations[0].text
```

Append to `tests/test_db_metrics.py`:

```python
def test_team_contracts(warehouse_with_finances_mart):
    assert db.team_contracts_available() is True
    df = db.team_contracts("2023-24", "BOS")
    assert df["salary_rank"].tolist() == [1, 2, 3]
    assert df["player"].iloc[0] == "Player One"


def test_team_contracts_unavailable_on_an_old_warehouse(legacy_finances_warehouse):
    assert db.team_contracts_available() is False
```

- [ ] **Step 2: Update the fixtures** in `tests/conftest.py`.
- In `_reset_finances_cache`, also call `db.team_contracts_available.clear()`.
- In `warehouse_with_finances_mart`:
  - Change the BOS 2023-24 row's payroll to `180000000` and its pct to `1.323`, so its flags (over first apron, not over second) match its number.
  - Before `con.close()`, add:

```python
    # Rows scraped after fetch dates were recorded carry one.
    con.execute("alter table main_marts.mart_team_finances "
                "add column payroll_fetched_at_utc timestamp")
    con.execute("update main_marts.mart_team_finances "
                "set payroll_fetched_at_utc = timestamp '2026-09-23 20:58:40'")
    con.execute("""
        create table main_marts.mart_team_contracts as
        select * from (values
            ('2023-24', 'BOS', 'one01', 'Player One', 45000000, 1, 0.25),
            ('2023-24', 'BOS', 'two01', 'Player Two', 27000000, 2, 0.15),
            ('2023-24', 'BOS', 'three01', 'Player Three', 18000000, 3, 0.10)
        ) t(season, team_abbreviation, bbref_player_id, player, salary_usd,
            salary_rank, share_of_payroll)
    """)
```

Add this fixture after it:

```python
@pytest.fixture
def legacy_finances_warehouse(warehouse_with_finances_mart):
    """The same warehouse as published before per-player salaries existed:
    no contracts mart and no fetch date. The deployed app reads whatever the
    last release published, so the page has to keep working on this."""
    con = duckdb.connect(str(warehouse_with_finances_mart))
    con.execute("drop table main_marts.mart_team_contracts")
    con.execute("alter table main_marts.mart_team_finances drop column payroll_fetched_at_utc")
    con.close()
    _reset_finances_cache()
    yield warehouse_with_finances_mart
```

- [ ] **Step 3: Run the tests and confirm they fail.**
Run: `.venv/Scripts/python.exe -m pytest tests/test_viz.py tests/test_db_metrics.py -q -k "trend or snapshot or contracts"`
Expected: FAIL, because `eras` is an unexpected keyword and `league_payroll_snapshot` / `team_contracts` don't exist.

- [ ] **Step 4: Implement in `db.py`.** Add after `salary_cap_history`:

```python
@st.cache_data(ttl=600, show_spinner=False)
def team_contracts_available() -> bool:
    """Whether mart_team_contracts exists - a warehouse published before
    per-player salaries were scraped has the finances mart but not this."""
    try:
        with duckdb.connect(str(DB_PATH), read_only=True) as con:
            con.execute("select 1 from main_marts.mart_team_contracts limit 1")
        return True
    except (duckdb.Error, OSError):
        return False


def team_contracts(season: str, team_abbreviation: str) -> pd.DataFrame:
    """One team-season's salaries, biggest first."""
    return q(
        "select player, salary_usd, salary_rank, share_of_payroll "
        "from main_marts.mart_team_contracts "
        "where season = ? and team_abbreviation = ? order by salary_rank",
        (season, team_abbreviation),
    )
```

- [ ] **Step 5: Implement in `viz.py`.**
- Add `from . import payroll` under the theme import.
- Replace `_ZONE_COLORS` and `_ZONE_CEILING_COLOR`, so each zone is tinted like the bracket it represents (the cap-to-tax zone is neutral, "over the cap is normal"):

```python
# Each band is tinted like the bracket it represents (payroll.LINES): under
# the cap green, cap-to-tax neutral (over the cap is normal), then tax,
# first apron and second apron in their line colors.
_ZONE_COLORS = ["rgba(12,163,12,0.10)", "rgba(195,194,183,0.06)",
                "rgba(201,133,0,0.14)", "rgba(217,89,38,0.16)"]
_ZONE_CEILING_COLOR = "rgba(208,59,59,0.20)"
```

- In `team_finances_trend`:
  - Change the signature to `def team_finances_trend(team_df, cap_df, eras=None) -> go.Figure:`.
  - Add to its docstring: "`eras` is franchises.era_spans() output; with more than one era, each gets a label at its first season and a dotted line marks every change."
  - Replace the `thresholds = [...]` list and its loop header with `for col, label, color in payroll.LINES:`. The loop body is unchanged.
  - Before `fig.update_layout(...)`, insert:

```python
    if eras and len(eras) > 1:
        for i, (first, _last, name) in enumerate(eras):
            if i:
                fig.add_vline(x=first, line=dict(color=T.MUTED, width=1, dash="dot"))
            fig.add_annotation(x=first, y=0.98, xref="x", yref="paper", text=name,
                               showarrow=False, xanchor="left", yanchor="top",
                               font=dict(color=T.MUTED, size=11))
```

- Add after `team_finances_trend`:

```python
def league_payroll_snapshot(df: pd.DataFrame, highlight: str | None = None) -> go.Figure:
    """Every team's payroll for one season as a horizontal bar, highest at the
    top, against that season's cap/tax/apron lines.

    df: team_name, team_payroll, bar_color (payroll.bracket's color), and the
    season's salary_cap/luxury_tax/first_apron/second_apron, the same on every
    row. Rows without a reliable payroll should already be dropped -
    plotting them would show a source gap as a cheap team. `highlight` is a
    team_name to outline.
    """
    if df.empty:
        return _empty("No reliable payroll figures for this season.")
    d = df.sort_values("team_payroll")  # Plotly draws the last row at the top
    fig = go.Figure()
    fig.add_bar(
        x=d["team_payroll"], y=d["team_name"], orientation="h",
        marker=dict(color=d["bar_color"].tolist(),
                    line=dict(color=T.INK,
                              width=[2 if n == highlight else 0 for n in d["team_name"]])),
        hovertemplate="%{y}<br>$%{x:,.0f}<extra></extra>", showlegend=False,
    )
    first = d.iloc[0]
    ends = [d["team_name"].iloc[0], d["team_name"].iloc[-1]]
    for col, label, color in payroll.LINES:
        value = first[col]
        if pd.notna(value):
            # A two-point line from the bottom bar to the top bar: a real
            # legend entry, which add_vline can't have.
            fig.add_scatter(x=[value, value], y=ends, mode="lines", name=label,
                            line=dict(color=color, width=1.5, dash="dash"),
                            hovertemplate=f"{label}<br>$%{{x:,.0f}}<extra></extra>")
    fig.update_layout(**_layout(height=max(320, 22 * len(d) + 80), showlegend=True,
                                bargap=0.25))
    fig.update_xaxes(tickprefix="$", automargin=True)
    fig.update_yaxes(type="category", automargin=True)
    return fig
```

- [ ] **Step 6: Run the tests and confirm they pass.**
Run: `.venv/Scripts/python.exe -m pytest tests/test_viz.py tests/test_db_metrics.py -q`
Expected: all pass.

- [ ] **Step 7: Commit.**

```bash
git add dashboard/lib/viz.py dashboard/lib/db.py tests/test_viz.py tests/test_db_metrics.py tests/conftest.py
git commit -m "Add a league payroll snapshot chart, era labels and a contracts query"
```

---

### Task 7: Rebuild the Finances page

**Files:**
- Modify: `dashboard/views/finances.py` (full rewrite of `render`; `_render_incomplete_caption` and its constants stay as they are)
- Modify: `tests/test_finances_page.py`

**Interfaces:**
- Consumes: everything from Tasks 4-6.

- [ ] **Step 1: Rewrite the page tests.** Replace `tests/test_finances_page.py` from the `_run` helper down. Keep the module docstring, the `SCRIPT` constant, `_captions` and `test_renders_without_a_warehouse`.

```python
def _run(team: str | None = None, season: str | None = None) -> AppTest:
    """selectbox[0] is the season, selectbox[1] the team (a franchise key;
    the widget shows full names via format_func)."""
    at = AppTest.from_string(SCRIPT)
    at.run()
    assert not at.exception, at.exception
    if season is not None:
        at.selectbox[0].select(season).run()
        assert not at.exception, at.exception
    if team is not None:
        at.selectbox[1].select(team).run()
        assert not at.exception, at.exception
    return at


def _markdown(at: AppTest) -> str:
    return " ".join(m.value for m in at.markdown)


def test_renders_a_team_with_no_flagged_seasons(warehouse_with_finances_mart):
    at = _run("BOS")
    assert len(at.get("dataframe")) == 1
    captions = _captions(at)
    assert "No reliable payroll total" not in captions
    assert "unusually low" not in captions


def test_says_when_the_salary_data_was_updated(warehouse_with_finances_mart):
    at = _run()
    assert "Salary data updated Sep 23, 2026 · covers through 2023-24." in _captions(at)


def test_team_summary_explains_the_number_and_its_cause(warehouse_with_finances_mart):
    at = _run("BOS")
    text = _markdown(at)
    assert "In 2023-24 the Boston Celtics spent $180.0M, the highest payroll of 2 teams." in text
    assert "$7.7M over the first apron and $2.8M under the second apron" in text
    assert "(Player One, Player Two and Player Three) made up 50% of the payroll" in text
    assert "Biggest contracts" in text


def test_league_summary_and_explainer_render(warehouse_with_finances_mart):
    at = _run()
    text = _markdown(at)
    assert "In 2023-24, 2 of 2 teams were over the salary cap" in text
    assert "soft" in text  # the how-to-read explainer


def test_old_warehouse_without_contracts_or_dates_still_renders(legacy_finances_warehouse):
    at = _run("BOS")
    assert "update date not recorded" in _captions(at)
    assert "Biggest contracts" not in _markdown(at)
    assert "the highest payroll of 2 teams" in _markdown(at)


def test_a_team_with_no_row_that_season_says_so(warehouse_with_finances_mart):
    at = _run("DEN")  # the fixture's DEN has 1986-87 and 1995-96 only
    assert any("No payroll data for the Denver Nuggets in 2023-24" in i.value
               for i in at.get("info"))


def test_renders_a_source_gap_team_and_says_the_source_is_missing_rows(
        warehouse_with_finances_mart):
    """DEN's 1986-87 is 'sparse_source_data' - one salary row on record.
    That one really is Basketball-Reference missing the roster, so the
    strong sentence is the correct one here."""
    at = _run("DEN", season="1986-87")
    captions = _captions(at)
    assert "No reliable payroll total exists for 1986-87" in captions
    assert "salary records for that season are missing" in captions
    assert "There's no reliable payroll figure for the Denver Nuggets in 1986-87." \
        in _markdown(at)


def test_a_real_but_cheap_roster_is_not_called_a_missing_source(
        warehouse_with_finances_mart):
    """MIA's 1988-89 is flagged only for being under half the cap, and it is
    a complete 13-player inaugural expansion roster. The caption must say the
    number is low - not that the data is absent."""
    at = _run("MIA")
    captions = _captions(at)
    assert "1988-89" in captions
    assert "unusually low relative to" in captions
    assert "records for that season are missing" not in captions


def test_merged_franchise_renders_both_codes_as_one_history(warehouse_with_finances_mart):
    """GSW must include the GOS seasons, and the selector lists full names,
    never a legacy code."""
    at = _run()
    options = at.selectbox[1].options
    assert "Golden State Warriors" in options
    assert "GOS" not in options and "GSW" not in options
    at.selectbox[1].select("GSW").run()
    assert not at.exception, at.exception
    table = at.get("dataframe")[0].value
    assert table["Season"].tolist() == ["1995-96", "1996-97"]


@pytest.mark.parametrize("team", ["BOS", "NYK", "DEN", "MIA", "GSW"])
def test_every_team_in_the_fixture_renders(warehouse_with_finances_mart, team):
    _run(team)
```

- [ ] **Step 2: Run them and confirm they fail.**
Run: `.venv/Scripts/python.exe -m pytest tests/test_finances_page.py -q`
Expected: FAIL, because the page still calls the removed `db.franchise_options`.

- [ ] **Step 3: Rewrite `dashboard/views/finances.py`.**
- Replace the module docstring and imports.
- Delete `_STATUS_TIERS` and `_status`.
- Keep `EARLY_ERA_CUTOFF`, `_SOURCE_GAP_REASONS` and `_render_incomplete_caption` exactly as they are.
- Replace `render` and add the helpers:

```python
"""Finances - what teams spend, against the league's salary cap, luxury tax
and apron lines.

Reads top to bottom as three questions: how did the league spend that
season, what do the lines mean, and where does one team sit and why (its
biggest contracts) - with the franchise's whole history below. Every number
has a sentence next to it (dashboard/lib/payroll.py): the first version of
this page showed bare figures and "Over cap" on nearly every team, with no
word that a soft cap makes that normal.
"""

import html

import pandas as pd
import streamlit as st

from dashboard.lib import db, franchises, payroll
from dashboard.lib import theme as T
from dashboard.lib import viz
```

```python
def _contracts_card(contracts: pd.DataFrame) -> str:
    rows = [
        f'<div class="bip-row">{T.rank_badge(int(r.salary_rank))}'
        f'<span class="bip-name">{html.escape(str(r.player))}</span>'
        f'<span class="bip-team">{r.share_of_payroll:.0%}</span>'
        f'<span class="bip-val">{payroll.money(r.salary_usd)}</span></div>'
        for r in contracts.head(5).itertuples()
    ]
    return f'<div class="bip-card"><h4>Biggest contracts</h4>{"".join(rows)}</div>'


def _render_team_season(team_df: pd.DataFrame, league: pd.DataFrame,
                        team_name: str, season: str) -> None:
    row_df = team_df[team_df["season"] == season]
    if row_df.empty:
        st.info(f"No payroll data for the {team_name} in {season}.")
        return
    row = row_df.iloc[0]
    contracts = (db.team_contracts(season, row["team_abbreviation"])
                 if db.team_contracts_available() else None)
    rank = payroll.league_rank(league, row["team_abbreviation"])
    st.markdown(payroll.team_summary(row, row["era_name"], rank, contracts))

    label, color = payroll.bracket(row)
    reliable = label != "Data incomplete"
    k1, k2, k3 = st.columns(3)
    k1.markdown(T.kpi("Payroll", payroll.money(row["team_payroll"]) if reliable else "N/A"),
                unsafe_allow_html=True)
    k2.markdown(T.kpi("League rank",
                      f"{payroll.ordinal(rank[0])} of {rank[1]}" if rank else "N/A"),
                unsafe_allow_html=True)
    k3.markdown(T.kpi("Status", label, accent=color), unsafe_allow_html=True)
    if contracts is not None and len(contracts) and reliable:
        st.markdown(_contracts_card(contracts), unsafe_allow_html=True)


def render() -> None:
    st.markdown("## Finances", unsafe_allow_html=True)

    if not db.team_finances_available():
        st.info("Payroll data hasn't been loaded into this warehouse yet.")
        return

    all_seasons = db.team_payroll_history()
    if all_seasons.empty:
        st.info("No payroll data available.")
        return
    all_seasons = franchises.annotate(all_seasons)
    cap_df = db.salary_cap_history()

    fetched = (all_seasons["payroll_fetched_at_utc"].max()
               if "payroll_fetched_at_utc" in all_seasons else None)
    st.caption(payroll.freshness_text(fetched, all_seasons["season"].max(),
                                      cap_df["season"].max()))

    seasons = sorted(all_seasons["season"].unique(), reverse=True)
    teams = sorted(all_seasons["franchise"].unique(), key=franchises.franchise_name)
    f1, f2 = st.columns(2)
    season = f1.selectbox("Season", seasons, index=0)
    team = f2.selectbox("Team", teams, index=teams.index("BOS") if "BOS" in teams else 0,
                        format_func=franchises.franchise_name)
    team_name = franchises.franchise_name(team)
    team_df = all_seasons[all_seasons["franchise"] == team].sort_values("season")
    league = all_seasons[all_seasons["season"] == season]

    # --- The league that season ---------------------------------------------
    st.markdown(f"### The league in {season}")
    st.markdown(payroll.league_summary(league, season))
    snapshot = payroll.reliable(league).copy()
    snapshot["team_name"] = snapshot["era_name"]
    snapshot["bar_color"] = [payroll.bracket(r)[1] for _, r in snapshot.iterrows()]
    this_season = team_df[team_df["season"] == season]
    highlight = this_season["era_name"].iloc[0] if len(this_season) else None
    st.plotly_chart(viz.league_payroll_snapshot(snapshot, highlight=highlight),
                    width="stretch", config=viz.PLOTLY_CONFIG)

    with st.expander("How to read this", expanded=True):
        st.markdown(payroll.HOW_TO_READ)

    # --- The team -------------------------------------------------------------
    st.markdown(f"### {team_name}")
    note = franchises.FRANCHISE_NOTES.get(team)
    if note:
        st.caption(note)
    _render_team_season(team_df, league, team_name, season)

    st.markdown("#### Payroll history")
    if (team_df["season"] < EARLY_ERA_CUTOFF).any():
        st.caption(
            "Seasons before 1996-97 use payroll figures Basketball-Reference "
            "itself notes are partly reconstructed for players with missing "
            "records - treat early-era numbers as directionally right, not exact."
        )
    st.plotly_chart(viz.team_finances_trend(team_df, cap_df,
                                            eras=franchises.era_spans(team_df)),
                    width="stretch", config=viz.PLOTLY_CONFIG)
    _render_incomplete_caption(team_df)

    display_df = team_df[["season", "era_name", "team_payroll", "salary_cap", "luxury_tax",
                          "first_apron", "second_apron", "payroll_pct_of_cap"]].copy()
    # Stored as a ratio (1.23 = 123% of cap); NumberColumn's printf format
    # doesn't scale for us.
    display_df["payroll_pct_of_cap"] = display_df["payroll_pct_of_cap"] * 100
    display_df["status"] = [payroll.bracket(r)[0] for _, r in team_df.iterrows()]
    display_df = display_df.rename(columns={
        "season": "Season", "era_name": "Team", "team_payroll": "Payroll",
        "salary_cap": "Salary cap", "luxury_tax": "Luxury tax",
        "first_apron": "1st apron", "second_apron": "2nd apron",
        "payroll_pct_of_cap": "% of cap", "status": "Status",
    })
    money_col = st.column_config.NumberColumn(format="$%,.0f")
    with st.expander("Show full season-by-season table"):
        st.dataframe(
            display_df, hide_index=True, width="stretch",
            column_config={
                "Payroll": money_col, "Salary cap": money_col, "Luxury tax": money_col,
                "1st apron": money_col, "2nd apron": money_col,
                "% of cap": st.column_config.NumberColumn(format="%.0f%%"),
            },
        )

    st.caption(payroll.METHOD_NOTE)
```

The table columns are renamed in the DataFrame itself, because AppTest's `dataframe.value` exposes the frame's own column names. That's why the GSW test reads `table["Season"]`.

- [ ] **Step 4: Run the tests and confirm they pass.**
Run: `.venv/Scripts/python.exe -m pytest tests/test_finances_page.py -q`
Expected: all pass. If an AppTest selectbox `.options` returns raw keys rather than formatted names in this Streamlit version, adjust only that assertion to `"GSW" in options and "GOS" not in options`, and note it in the report.

- [ ] **Step 5: Commit.**

```bash
git add dashboard/views/finances.py tests/test_finances_page.py
git commit -m "Rebuild the Finances page around plain-English answers"
```

---

### Task 8: Equal-height Overview KPI cards

**Files:**
- Modify: `dashboard/lib/theme.py`, the `kpi()` function (236-240) and the KPI CSS (142-147)
- Modify: `dashboard/views/overview.py:106`
- Create: `tests/test_theme.py`

- [ ] **Step 1: Write the failing test** in `tests/test_theme.py`:

```python
from dashboard.lib import theme as T


def test_kpi_note_sits_in_the_label_row_not_a_new_line():
    """A short qualifier ("latest season") rides on the label line so the
    card stays the same height as its neighbours; `sub` is the extra line."""
    html = T.kpi("Play-by-play games", "20", note="latest season")
    assert '<span class="bip-kpi-note">latest season</span>' in html
    assert "bip-kpi-sub" not in html
```

- [ ] **Step 2: Run it and confirm it fails.**
Run: `.venv/Scripts/python.exe -m pytest tests/test_theme.py -q`
Expected: FAIL with `TypeError: unexpected keyword 'note'`.

- [ ] **Step 3: Implement.** In `theme.py`, replace `kpi`:

```python
def kpi(label: str, value: str, sub: str = "", accent: str = ACCENT, note: str = "") -> str:
    # `note` is a short qualifier on the label's own line (keeps the card the
    # same height as its neighbours); `sub` adds a line under the value.
    note_html = f'<span class="bip-kpi-note">{note}</span>' if note else ""
    sub_html = f'<div class="bip-kpi-sub">{sub}</div>' if sub else ""
    return (f'<div class="bip-card bip-kpi" style="border-left-color:{accent}">'
            f'<div class="bip-kpi-label">{label}{note_html}</div>'
            f'<div class="bip-kpi-value">{value}</div>{sub_html}</div>')
```

In the CSS, replace the `.bip-kpi-label` rule and add the note rule:

```css
.bip-kpi-label {{ font-size: .72rem; text-transform: uppercase; letter-spacing: .08em;
                  color: {MUTED}; font-weight: 600;
                  display: flex; justify-content: space-between; gap: .5rem; }}
.bip-kpi-note  {{ text-transform: none; letter-spacing: 0; font-weight: 500;
                  color: {MUTED}; white-space: nowrap; }}
```

In `overview.py:106`, change the call to `T.kpi("Play-by-play games", f"{pbp_n}", note="latest season")`.

- [ ] **Step 4: Run the tests and confirm they pass.**
Run: `.venv/Scripts/python.exe -m pytest tests/test_theme.py -q`
Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add dashboard/lib/theme.py dashboard/views/overview.py tests/test_theme.py
git commit -m "Keep the play-by-play KPI card the same height as its row"
```

---

### Task 9: Full verification and a visual check

- [ ] **Step 1: Run the full test suite.**
Run: `.venv/Scripts/python.exe -m pytest tests -q`, then in `dbt/basketball_intelligence` run `../../.venv/Scripts/dbt.exe test --profiles-dir .`
Expected: everything passes. Report the counts.

- [ ] **Step 2: Take screenshots.**
- Start `.venv/Scripts/python.exe -m streamlit run dashboard/app.py --server.port 8599 --server.headless true` in the background.
- Use Playwright with `channel="msedge"` and a 1600x1000 viewport, waiting for network idle.
- Screenshot the Overview KPI row. All four cards must be the same height.
- Screenshot the Finances page for each of:
  - BOS 2025-26
  - OKC in a 2005-06 season (Sonics era label and note)
  - NOP (Charlotte era band)
  - CHA (note about 1988-2002)
  - DEN 1986-87 (no-reliable-figure path)
- Look at every screenshot. Check for overlapping era labels, unreadable bar labels, and legend collisions, and fix anything found before moving on.
- Stop the server afterwards and confirm the port is free.

- [ ] **Step 3: Sanity-check the real numbers.** For 2023-24 and 2024-25, print the tax and apron team counts and BOS's summary sentence. Report them as they are.

- [ ] **Step 4: Stop and report.** Don't push, merge or republish `data-v1` without the user's go-ahead. The live app only gets the new contracts mart after a `scripts/weekly_refresh.py` run republishes the warehouse.
