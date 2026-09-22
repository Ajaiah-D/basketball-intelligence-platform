# Foundation Hardening + Predictive Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix two live data-correctness bugs, add test coverage where none exists, then build a pre-game win-probability and margin model that publishes predictions with an honest public track record starting opening night (2026-10-20).

**Architecture:** Two tracks. Track 1 is the critical path to opening night: fix correctness bugs, build the game-grain fact table the model needs, then the model itself. Track 2 is documentation and CI with no deadline and no file overlap with Track 1, to be picked up whenever Track 1 is blocked. Feature engineering lives in dbt wherever it is expressible as a window function; Elo is sequential and lives in Python. Predictions are append-only and stamped with a model version so history cannot be quietly rewritten.

**Tech Stack:** Python 3.14, DuckDB, dbt-duckdb, pandas, scikit-learn, Streamlit, Plotly, pytest, nba_api.

## Global Constraints

- **No `dbt_utils` dependency.** The repo deliberately avoids it (see the comment in `tests/assert_mart_grain_is_unique.sql`). Write singular tests in `dbt/basketball_intelligence/tests/` instead.
- **Keep all code strings ASCII.** Never bulk-edit `.py` files with PowerShell `-replace` — it produces mojibake.
- **Restart the Streamlit server after editing anything under `dashboard/lib/` or `dashboard/views/`** — it caches imports, and screenshots of a stale server waste a cycle.
- **Commit style:** no Claude co-author trailers, one emoji maximum (the existing 🏀 in the README title), human-voiced imperative subject lines.
- **The dashboard must keep working when the marts are absent.** `db.marts_available()` guards this (commit 985d89c). Do not introduce a hard app dependency on `main_marts`.
- **Never record the value of `DEV_PASSWORD`** in code, tests, comments, or commit messages.
- **Every model feature must be computable strictly from data before that game's `game_date`.** No exceptions.
- Python is `.venv/Scripts/python.exe`; dbt is `.venv/Scripts/dbt.exe` and must run with `--profiles-dir .` from `dbt/basketball_intelligence`.

## File Structure

**Created:**
- `requirements-dev.txt` — pytest and ML libraries, kept out of the deploy image
- `tests/conftest.py` — shared read-only DuckDB fixture
- `tests/test_db_metrics.py`, `tests/test_elo.py`, `tests/test_features.py`, `tests/test_train.py`, `tests/test_predict.py`
- `dbt/.../models/intermediate/int_team_game_opponent.sql` — game-grain team+opponent pairing
- `dbt/.../models/marts/fct_team_game.sql` — one row per game, home/away oriented
- `dbt/.../models/marts/mart_game_features.sql` — pre-tipoff feature row per game
- `dbt/.../models/marts/mart_team_standings.sql` — standings with form and a head-to-head tiebreak
- `dbt/.../models/staging/stg_schedule.sql` — published schedule including unplayed games
- `dbt/.../tests/assert_player_game_grain_is_unique.sql`, `assert_fct_team_game_grain.sql`, `assert_no_future_data_in_features.sql`
- `ml/elo.py`, `ml/features.py`, `ml/train.py`, `ml/predict.py`, `ml/evaluate.py`
- `dashboard/views/predictions.py`
- `docs/adr/` — six architecture decision records

**Modified:**
- `dashboard/lib/db.py` — TS% era guard in three places, prediction accessors, standings reads the mart
- `dashboard/lib/theme.py:151-152` — stop the leader-card ellipsis from eating the team code
- `dashboard/views/advanced.py`, `dashboard/views/overview.py` — same card markup fix
- `dbt/.../models/staging/stg_player_game_logs.sql` — deduplicate the player-game grain
- `dbt/.../models/staging/_staging_models.yml` — tests and docs for the two advanced models
- `ingestion/nba_ingest.py` — schedule fetch
- `scripts/weekly_refresh.py` — predict and score steps

---

## TRACK 1 — Critical path to 2026-10-20

### Task 1: Test harness and the true-shooting era bug

`dashboard/lib/db.py` computes true shooting in three places with no completeness guard. `sum()` skips nulls, so a player whose own game rows are missing `field_goals_attempted` or `free_throws_attempted` gets that game's points counted in the numerator with nothing added to the denominator. Confirmed case: Jim Brewer, 1979-80, 75 games — 8 of them have null `field_goals_attempted` while `points` is still populated, inflating his season TS% to a nonsensical 78.1%.

**This is a per-player defect, not a per-season one.** `mart_player_season` nulls out true shooting for essentially every pre-1985-86 player-season via its `box_score_complete` flag, but that flag also fires on missing *team-level* columns (`team_field_goals_attempted` is null for 100% of 1979-80 team rows) that true shooting does not depend on. Checked directly: in 1979-80, only 92 of 230 qualifying players (40%) have a null in their own `field_goals_attempted`/`free_throws_attempted`/`points`; the other 138 have complete shot data and legitimate values (Kareem Abdul-Jabbar 63.9%, Magic Johnson 60.2%, both plausible). Artis Gilmore's 1984-85 68.0% — cited earlier in this project as a second example of the bug — turned out to be a false lead: his season has zero null shot-attempt rows, and 68% is a genuine, if excellent, figure for a career 59.9% field-goal shooter who took almost no threes. Do not use it as a test case for the bug; use Jim Brewer.

The fix is a guard on the exact columns the ratio sums — `field_goals_attempted`, `free_throws_attempted`, `points` — applied per player, not a season-wide flag borrowed from the mart's broader (and here, over-conservative) definition.

**Files:**
- Create: `requirements-dev.txt`, `tests/conftest.py`, `tests/test_db_metrics.py`
- Modify: `dashboard/lib/db.py:78`, `dashboard/lib/db.py:133`, `dashboard/lib/db.py:165`

**Interfaces:**
- Produces: `tests/conftest.py` exposes a session-scoped `con` fixture (read-only `duckdb.DuckDBPyConnection`). Every later test file consumes it.

- [ ] **Step 1: Add the dev requirements file**

`requirements-dev.txt`:

```
# Dev and CI only - not installed in the deployed image.
pytest
scikit-learn
scipy
pyarrow
```

Run: `.venv/Scripts/python.exe -m pip install -r requirements-dev.txt`

- [ ] **Step 2: Write the shared fixture**

`tests/conftest.py`:

```python
"""Shared fixtures. Tests run read-only against the real warehouse and
assert facts that are true of the data itself, not row counts that shift
on every refresh."""

import sys
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DB_PATH = ROOT / "warehouse" / "basketball.duckdb"


@pytest.fixture(scope="session")
def con():
    if not DB_PATH.exists():
        pytest.skip("warehouse not built; run scripts/load_to_duckdb.py")
    connection = duckdb.connect(str(DB_PATH), read_only=True)
    yield connection
    connection.close()
```

- [ ] **Step 3: Write the failing test**

`tests/test_db_metrics.py`:

```python
"""Regression tests for the SQL in dashboard/lib/db.py.

The app computes some rate stats independently of the dbt marts so the
dashboard still works when the marts are absent. That independence is
deliberate, but it lets the two implementations drift - these tests pin
them together.
"""

import pytest

# Seasons where a meaningful share of player-game rows have a null in one
# of the three columns the true-shooting ratio sums. Not every player in
# these seasons is affected - only those whose own games hit the null - so
# the tests below check the mechanism per player, not the whole season.
INCOMPLETE_SEASONS = ["1979-80", "1984-85"]
COMPLETE_SEASON = "2024-25"

TS_SQL = """
    select
        player_id,
        case when count(*) filter (
                 where field_goals_attempted is null
                    or free_throws_attempted is null
                    or points is null) > 0
             then null
             else round(sum(points) / nullif(2 * (sum(field_goals_attempted)
                  + 0.44 * sum(free_throws_attempted)), 0) * 100, 1)
        end as ts_pct
    from main_staging.stg_player_game_logs
    where season = ?
    group by player_id
    having count(*) >= 40
"""

# One column at a time, so the query stays readable independently of TS_SQL.
_NULL_RATIO_INPUT = """
    field_goals_attempted is null
    or free_throws_attempted is null
    or points is null
"""


@pytest.mark.parametrize("season", INCOMPLETE_SEASONS)
def test_true_shooting_is_null_for_players_with_a_null_ratio_input(con, season):
    """The direct bug: sum() skips a null denominator term while the
    numerator still counts that game's points. Any player whose own games
    hit this must show no TS%, full stop."""
    affected = con.execute(
        f"""
        select player_id from main_staging.stg_player_game_logs
        where season = ?
        group by player_id
        having count(*) >= 40 and sum(case when {_NULL_RATIO_INPUT} then 1 else 0 end) > 0
        """,
        [season],
    ).fetchall()
    assert affected, f"expected at least one affected player in {season}"
    affected_ids = {row[0] for row in affected}

    computed = dict(con.execute(TS_SQL, [season]).fetchall())
    offenders = [(pid, computed[pid]) for pid in affected_ids if computed.get(pid) is not None]
    assert not offenders, (
        f"{season}: players with a null ratio input still got a TS%: {offenders[:3]}"
    )


@pytest.mark.parametrize("season", INCOMPLETE_SEASONS)
def test_true_shooting_is_correct_for_players_with_no_null_ratio_input(con, season):
    """Players whose own games are fully populated must still get a real
    number - the guard must catch the bug without discarding good data -
    and that number must match an independent recomputation from the raw
    rows, not just "be non-null"."""
    clean_ids = con.execute(
        f"""
        select player_id from main_staging.stg_player_game_logs
        where season = ?
        group by player_id
        having count(*) >= 40 and sum(case when {_NULL_RATIO_INPUT} then 1 else 0 end) = 0
        limit 5
        """,
        [season],
    ).fetchall()
    assert clean_ids, f"expected at least one fully-populated player in {season}"

    computed = dict(con.execute(TS_SQL, [season]).fetchall())
    for (player_id,) in clean_ids:
        raw = con.execute(
            """
            select points, field_goals_attempted, free_throws_attempted
            from main_staging.stg_player_game_logs
            where season = ? and player_id = ?
            """,
            [season, player_id],
        ).fetchdf()
        expected = round(
            100 * raw["points"].sum()
            / (2 * (raw["field_goals_attempted"].sum() + 0.44 * raw["free_throws_attempted"].sum())),
            1,
        )
        got = computed.get(player_id)
        assert got is not None, f"{season} player {player_id}: expected a value, got null"
        assert got == pytest.approx(expected, abs=0.05), (
            f"{season} player {player_id}: got {got}, independently computed {expected}"
        )


def test_true_shooting_matches_mart_when_box_score_complete(con):
    """Where both compute a value, the app and the mart must agree exactly."""
    rows = con.execute(
        f"""
        with app as ({TS_SQL})
        select a.player_id, a.ts_pct, m.true_shooting_pct
        from app a
        join main_marts.mart_player_season m
          on m.player_id = a.player_id and m.season = ?
        where a.ts_pct is not null and m.true_shooting_pct is not null
        """,
        [COMPLETE_SEASON, COMPLETE_SEASON],
    ).fetchall()
    assert len(rows) > 100, "expected a substantial overlap to compare"
    mismatches = [r for r in rows if abs(r[1] - r[2]) > 0.05]
    assert not mismatches, f"app/mart TS% drift: {mismatches[:5]}"
```

- [ ] **Step 4: Run the tests and watch two of them fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_db_metrics.py -v`

Expected: `test_true_shooting_is_null_for_players_with_a_null_ratio_input` FAILS for both seasons, naming a player with a fabricated percentage (Jim Brewer at 78.1% for 1979-80). `test_true_shooting_is_correct_for_players_with_no_null_ratio_input` also FAILS, because `TS_SQL` has no guard yet so its "independent recomputation" comparison is moot — the unguarded query still returns a number, just not one gated on completeness; if it happens to pass by coincidence that's fine, the point is the guard is what Step 5 adds. `test_true_shooting_matches_mart_when_box_score_complete` already PASSES.

- [ ] **Step 5: Add the completeness guard at all three sites**

In `dashboard/lib/db.py`, replace the `ts_pct` line in `_PLAYER_SEASON_SQL` (line 78), `_PLAYER_CAREER_SQL` (line 133), and `player_season_breakdown` (line 165) with:

```sql
        case when count(*) filter (
                 where field_goals_attempted is null
                    or free_throws_attempted is null
                    or points is null) > 0
             then null
             else round(sum(points) / nullif(2 * (sum(field_goals_attempted)
                  + 0.44 * sum(free_throws_attempted)), 0) * 100, 1)
        end                                   as ts_pct,
```

Add this comment once, above `_PLAYER_SEASON_SQL`:

```
-- TS% is withheld for a player-season only when that player's own games
-- include a null field_goals_attempted, free_throws_attempted or points.
-- sum() skips nulls, so without this guard one such game counts its
-- points in the numerator while contributing nothing to the denominator -
-- confirmed on Jim Brewer's 1979-80 season, where 8 of 75 games have a
-- null field_goals_attempted and the unguarded query reports a 78.1% true
-- shooting season. This is deliberately narrower than mart_player_season's
-- box_score_complete flag, which also nulls a season for missing
-- TEAM-level columns (needed by usage%, rebound rate, etc.) that true
-- shooting does not depend on - checked directly, only 92 of 230
-- qualifying 1979-80 players actually have a null in these three columns;
-- the other 138 have complete shot data and a real number is correct.
```

- [ ] **Step 6: Run the tests and verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_db_metrics.py -v`

Expected: 5 passed.

- [ ] **Step 7: Check the Players page still renders**

Run: `.venv/Scripts/python.exe -m streamlit run dashboard/app.py`

Open Players, select 1979-80. Confirm Jim Brewer's row shows a blank TS% while most other players on that page show a real number — this season is a mix, not uniformly blank. Select 2024-25 and confirm every qualifying player shows a value. Stop the server.

- [ ] **Step 8: Commit**

```bash
git add requirements-dev.txt tests/ dashboard/lib/db.py
git commit -m "Withhold true shooting for players with a gap in their box score

sum() skips a null denominator term while the numerator still counts
that game's points. Jim Brewer's 1979-80 season had 8 of 75 games with
a null field_goals_attempted and reported 78.1% true shooting. The
guard is per player, not per season - most 1979-80 players have a
complete box score and a real number. Adds the first pytest suite
alongside the fix."
```

---

### Task 2: Deduplicate the player-game grain

Four players are recorded under both teams in the same game with identical box scores: Dwight Jones in `0027900365` (1979-80), Paul Mokeski in `0028200175`, and Michael Cooper in `0028200826` and `0028200121` (both 1982-83). Eight rows, each double-counting a game in every career total. Nothing catches it because there is no uniqueness assertion at that grain.

**Files:**
- Create: `dbt/basketball_intelligence/tests/assert_player_game_grain_is_unique.sql`
- Modify: `dbt/basketball_intelligence/models/staging/stg_player_game_logs.sql`

**Interfaces:**
- Produces: `stg_player_game_logs` guaranteed one row per `(game_id, player_id)`. Every later model may rely on that.

- [ ] **Step 1: Write the failing dbt test**

`dbt/basketball_intelligence/tests/assert_player_game_grain_is_unique.sql`:

```sql
-- One row per player per game. The source records four players under both
-- teams in a single game (identical box scores, different team_id), which
-- double-counts those games in every career total. Written as a singular
-- test to avoid a dbt_utils dependency, matching assert_mart_grain_is_unique.

select
    game_id,
    player_id,
    count(*) as rows
from {{ ref('stg_player_game_logs') }}
group by game_id, player_id
having count(*) > 1
```

- [ ] **Step 2: Run it and verify it fails**

Run: `cd dbt/basketball_intelligence && ../../.venv/Scripts/dbt.exe test --profiles-dir . --select assert_player_game_grain_is_unique`

Expected: FAIL, "Got 4 results, configured to fail if != 0".

- [ ] **Step 3: Deduplicate in staging**

The duplicate rows differ only in `team_id` / `team_abbreviation` / `team_name` / `matchup`. Keep the team the player appeared for most often that season — decidable from the data, and deterministic. Append to `stg_player_game_logs.sql`, after `from {{ source('raw', 'player_game_logs') }}`:

```sql
-- The source lists four players under both teams in one game (identical
-- box scores, different team_id) - a Dwight Jones 1979-80 game and three
-- 1982-83 games. Left alone these double-count a game in every career
-- total. Keep the row for whichever team the player logged more games
-- with that season; ties break on team_id so the result is stable.
qualify row_number() over (
    partition by game_id, cast(player_id as bigint)
    order by count(*) over (
        partition by cast(season as varchar),
                     cast(player_id as bigint),
                     cast(team_id as bigint)
    ) desc,
    cast(team_id as bigint)
) = 1
```

- [ ] **Step 4: Rebuild and verify the test passes**

Run: `cd dbt/basketball_intelligence && ../../.venv/Scripts/dbt.exe build --profiles-dir .`

Expected: all models build, all tests pass including the new one.

- [ ] **Step 5: Verify the affected careers dropped exactly one game each**

```bash
.venv/Scripts/python.exe -c "
import duckdb
con = duckdb.connect('warehouse/basketball.duckdb', read_only=True)
for name in ['Dwight Jones', 'Paul Mokeski', 'Michael Cooper']:
    n = con.execute('select count(*) from main_staging.stg_player_game_logs where player_name = ?', [name]).fetchone()[0]
    print(name, n)
"
```

Expected: three counts, each lower than before the fix (Cooper by 2, the others by 1). Record them in the commit message.

- [ ] **Step 6: Commit**

```bash
git add dbt/basketball_intelligence/models/staging/stg_player_game_logs.sql dbt/basketball_intelligence/tests/assert_player_game_grain_is_unique.sql
git commit -m "Keep one row per player per game

Four players are recorded under both teams in the same game with
identical box scores, so each of those games counted twice in career
totals. Keeps the team the player logged more games with that season,
and adds the grain test that should have caught it."
```

---

### Task 3: Test and document the advanced staging models

`stg_player_advanced` and `stg_team_advanced` are the only two models absent from any `_*.yml`: no description, no tests. They feed `usage_pct`, `net_rating` and `player_impact_estimate` into both marts.

**Files:**
- Modify: `dbt/basketball_intelligence/models/staging/_staging_models.yml`
- Modify: `dbt/basketball_intelligence/tests/assert_advanced_metrics_in_range.sql`

- [ ] **Step 1: Document both models**

Append to `models:` in `_staging_models.yml`:

```yaml
  - name: stg_player_advanced
    description: >
      Official NBA advanced player stats, one row per player per season.
      The league only publishes these from 1996-97, so rows do not exist
      for earlier seasons and the marts derive substitutes from box scores.
    columns:
      - name: season
        tests: [not_null]
      - name: player_id
        tests: [not_null]

  - name: stg_team_advanced
    description: >
      Official NBA advanced team stats, one row per team per season,
      1996-97 onward. Supplies the published ratings that mart_team_season
      prefers over its own box-score estimates.
    columns:
      - name: season
        tests: [not_null]
      - name: team_id
        tests: [not_null]
```

- [ ] **Step 2: Add range assertions to the existing singular test**

Read `dbt/basketball_intelligence/tests/assert_advanced_metrics_in_range.sql` first and match its existing `select` list exactly — column names and arity must line up for `union all`. Then append two branches asserting `stg_player_advanced.usage_pct` falls in `[0, 60]` and `stg_team_advanced.pace` falls in `[80, 120]`, each skipping nulls:

```sql

union all

-- Published rates must look like percentages. A value outside these bounds
-- means the source changed shape or a cast silently truncated.
select 'stg_player_advanced' as model, season, cast(player_id as varchar) as entity,
       'usage_pct' as metric, usage_pct as value
from {{ ref('stg_player_advanced') }}
where usage_pct is not null and (usage_pct < 0 or usage_pct > 60)

union all

select 'stg_team_advanced' as model, season, cast(team_id as varchar) as entity,
       'pace' as metric, pace as value
from {{ ref('stg_team_advanced') }}
where pace is not null and (pace < 80 or pace > 120)
```

- [ ] **Step 3: Run the tests**

Run: `cd dbt/basketball_intelligence && ../../.venv/Scripts/dbt.exe test --profiles-dir .`

Expected: all pass. Test count rises from 23 to at least 27.

- [ ] **Step 4: Commit**

```bash
git add dbt/basketball_intelligence/models/staging/_staging_models.yml dbt/basketball_intelligence/tests/assert_advanced_metrics_in_range.sql
git commit -m "Document and test the advanced staging models

They fed usage, net rating and PIE into both marts with no description
and no test coverage at all."
```

---

### Task 4: Game-grain fact table

Every model wants home and away on one row; `stg_team_game_logs` is two rows per game. This is what the predictive work builds on. The source is clean here: 52,849 games, every one with exactly two rows, zero nulls from 1996-97 on.

**Files:**
- Create: `dbt/basketball_intelligence/models/intermediate/int_team_game_opponent.sql`
- Create: `dbt/basketball_intelligence/models/marts/fct_team_game.sql`
- Create: `dbt/basketball_intelligence/tests/assert_fct_team_game_grain.sql`
- Modify: `dbt/basketball_intelligence/models/marts/_marts_models.yml`

**Interfaces:**
- Produces: `main_marts.fct_team_game`, one row per `game_id`, columns `season, game_id, game_date, is_neutral_site, home_team_id, home_team_abbreviation, away_team_id, away_team_abbreviation, home_points, away_points, margin, home_won, home_possessions`. `margin` is `home_points - away_points`. Tasks 5 through 10 all consume this.

- [ ] **Step 1: Write the intermediate pairing model**

`int_team_game_opponent.sql`:

```sql
-- Team game logs joined to the opponent's row for the same game, so every
-- downstream model gets both sides without repeating the self-join. Still
-- two rows per game (one per team); fct_team_game collapses it to one.

select
    t.season,
    t.game_id,
    t.game_date,
    t.team_id,
    t.team_abbreviation,
    t.matchup,
    t.is_away_game,
    t.is_win,
    t.points,
    t.field_goals_attempted,
    t.free_throws_attempted,
    t.offensive_rebounds,
    t.turnovers,
    o.team_id             as opp_team_id,
    o.team_abbreviation   as opp_team_abbreviation,
    o.points              as opp_points,
    o.offensive_rebounds  as opp_offensive_rebounds
from {{ ref('stg_team_game_logs') }} t
join {{ ref('stg_team_game_logs') }} o
  on t.game_id = o.game_id
 and t.team_id <> o.team_id
```

- [ ] **Step 2: Write the fact model**

`fct_team_game.sql`:

```sql
-- One row per game, oriented home versus away.
--
-- A handful of neutral-site games (NBA Cup, international) list BOTH teams
-- with '@' in the matchup string, so picking the home team by 'vs.' alone
-- drops them entirely. Rank instead: the true home side ranks first when
-- one exists, and neutral games still produce exactly one deterministic
-- row, flagged as neutral.

with ranked as (
    select
        *,
        row_number() over (
            partition by game_id
            order by (matchup like '%vs.%') desc, team_id
        ) as side,
        count(*) filter (where matchup like '%vs.%') over (
            partition by game_id
        ) = 0 as is_neutral_site
    from {{ ref('int_team_game_opponent') }}
)

select
    season,
    game_id,
    game_date,
    is_neutral_site,
    team_id                  as home_team_id,
    team_abbreviation        as home_team_abbreviation,
    opp_team_id              as away_team_id,
    opp_team_abbreviation    as away_team_abbreviation,
    points                   as home_points,
    opp_points               as away_points,
    points - opp_points      as margin,
    points > opp_points      as home_won,
    field_goals_attempted + 0.44 * free_throws_attempted
        - offensive_rebounds + turnovers          as home_possessions
from ranked
where side = 1
```

- [ ] **Step 3: Write the grain and consistency test**

`assert_fct_team_game_grain.sql`:

```sql
-- One row per game, home and away always distinct, and margin must agree
-- with the two point columns it was derived from.

select game_id, 'duplicate game' as problem
from {{ ref('fct_team_game') }}
group by game_id
having count(*) > 1

union all

select game_id, 'home equals away' as problem
from {{ ref('fct_team_game') }}
where home_team_id = away_team_id

union all

select game_id, 'margin disagrees with points' as problem
from {{ ref('fct_team_game') }}
where margin <> home_points - away_points
```

- [ ] **Step 4: Document the model**

Append to `models:` in `_marts_models.yml`:

```yaml
  - name: fct_team_game
    description: >
      One row per game, oriented home versus away, with margin and a
      neutral-site flag. The grain every game-level model builds on.
    columns:
      - name: game_id
        tests: [not_null, unique]
      - name: season
        tests: [not_null]
      - name: margin
        tests: [not_null]
```

- [ ] **Step 5: Build and test**

Run: `cd dbt/basketball_intelligence && ../../.venv/Scripts/dbt.exe build --profiles-dir .`

Expected: all pass.

- [ ] **Step 6: Verify orientation — this gate matters**

```bash
.venv/Scripts/python.exe -c "
import duckdb
con = duckdb.connect('warehouse/basketball.duckdb', read_only=True)
print('games:', con.execute('select count(*) from main_marts.fct_team_game').fetchone()[0])
print('neutral:', con.execute('select count(*) from main_marts.fct_team_game where is_neutral_site').fetchone()[0])
print('home win rate:', con.execute('select round(avg(case when home_won then 1.0 else 0.0 end), 4) from main_marts.fct_team_game').fetchone()[0])
"
```

Expected: 52,849 games; a small neutral count (single digits to low tens); home win rate between **0.57 and 0.62**.

**A home win rate outside that band means the home/away orientation is inverted or broken. Stop and fix it before continuing — every downstream feature depends on this being right, and a silent inversion produces a model that looks trained but predicts backwards.**

- [ ] **Step 7: Commit**

```bash
git add dbt/basketball_intelligence/models/intermediate dbt/basketball_intelligence/models/marts/fct_team_game.sql dbt/basketball_intelligence/models/marts/_marts_models.yml dbt/basketball_intelligence/tests/assert_fct_team_game_grain.sql
git commit -m "Add the game-grain fact table

One row per game instead of two, with neutral-site games flagged rather
than silently dropped. This is what the prediction features and every
future game-level model build on."
```

---

### Task 5: Elo ratings

Elo is sequential — each game's update feeds the next game's input — so it cannot be a window function. It runs in Python.

**Files:**
- Create: `ml/__init__.py` (empty), `ml/elo.py`, `tests/test_elo.py`

**Interfaces:**
- Consumes: `main_marts.fct_team_game` (Task 4).
- Produces: `ml.elo.compute_elo(games: pd.DataFrame, k: float = 20.0, home_advantage: float = 100.0, carry: float = 0.75) -> pd.DataFrame` with columns `game_id, home_elo_pre, away_elo_pre` — ratings **before** that game. Also `ml.elo.expected_score(rating_a: float, rating_b: float) -> float`. Task 6 consumes both.

- [ ] **Step 1: Write the failing unit tests**

`tests/test_elo.py`:

```python
"""Elo is the model's baseline and its only real signal in week one, so its
arithmetic is pinned directly rather than only through the pipeline."""

import pandas as pd
import pytest

from ml.elo import compute_elo, expected_score


def test_equal_ratings_are_a_coin_flip():
    assert expected_score(1500, 1500) == pytest.approx(0.5)


def test_four_hundred_points_is_ten_to_one():
    assert expected_score(1900, 1500) == pytest.approx(10 / 11, abs=1e-6)


def test_ratings_start_at_1500_and_are_pre_game():
    games = pd.DataFrame({
        "game_id": ["1", "2"],
        "season": ["2000-01", "2000-01"],
        "game_date": pd.to_datetime(["2000-11-01", "2000-11-03"]),
        "home_team_id": [10, 10],
        "away_team_id": [20, 20],
        "home_won": [True, True],
    })
    out = compute_elo(games).set_index("game_id")
    assert out.loc["1", "home_elo_pre"] == pytest.approx(1500.0)
    assert out.loc["1", "away_elo_pre"] == pytest.approx(1500.0)
    # After a home win the home side must be rated higher going into game 2.
    assert out.loc["2", "home_elo_pre"] > out.loc["2", "away_elo_pre"]


def test_ratings_regress_toward_the_mean_between_seasons():
    games = pd.DataFrame({
        "game_id": ["1", "2"],
        "season": ["2000-01", "2001-02"],
        "game_date": pd.to_datetime(["2001-01-01", "2001-11-01"]),
        "home_team_id": [10, 10],
        "away_team_id": [20, 20],
        "home_won": [True, True],
    })
    carried = compute_elo(games, carry=0.75).set_index("game_id")
    gain = carried.loc["2", "home_elo_pre"] - 1500.0
    full = compute_elo(games, carry=1.0).set_index("game_id")
    full_gain = full.loc["2", "home_elo_pre"] - 1500.0
    assert 0 < gain < full_gain, "carry must shrink the rating toward 1500"
```

- [ ] **Step 2: Run and verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_elo.py -v`

Expected: all fail with `ModuleNotFoundError: No module named 'ml'`.

- [ ] **Step 3: Implement**

`ml/elo.py`:

```python
"""Sequential Elo ratings for NBA teams.

Elo cannot be a SQL window function: every game's update feeds the next
game's input. Ratings are emitted as they stood *before* each game, which
is the only form a pre-tipoff model may use.

Between seasons ratings regress toward 1500 to account for roster turnover.
The default carry of 0.75 is the common public choice; it is a tunable, not
a law.
"""

from __future__ import annotations

import pandas as pd

BASE_RATING = 1500.0


def expected_score(rating_a: float, rating_b: float) -> float:
    """Probability that A beats B, on the standard 400-point logistic scale."""
    return 1.0 / (1.0 + 10.0 ** ((rating_b - rating_a) / 400.0))


def compute_elo(
    games: pd.DataFrame,
    k: float = 20.0,
    home_advantage: float = 100.0,
    carry: float = 0.75,
) -> pd.DataFrame:
    """Pre-game Elo for every game, oldest first.

    `games` needs game_id, season, game_date, home_team_id, away_team_id and
    home_won. Returns game_id, home_elo_pre, away_elo_pre.
    """
    ordered = games.sort_values(["game_date", "game_id"])
    ratings: dict[int, float] = {}
    current_season: str | None = None
    rows = []

    for game in ordered.itertuples(index=False):
        if game.season != current_season:
            # New season: pull every rating back toward the mean.
            ratings = {
                team: BASE_RATING + carry * (rating - BASE_RATING)
                for team, rating in ratings.items()
            }
            current_season = game.season

        home = ratings.get(game.home_team_id, BASE_RATING)
        away = ratings.get(game.away_team_id, BASE_RATING)
        rows.append((game.game_id, home, away))

        expected_home = expected_score(home + home_advantage, away)
        actual_home = 1.0 if game.home_won else 0.0
        adjustment = k * (actual_home - expected_home)
        ratings[game.home_team_id] = home + adjustment
        ratings[game.away_team_id] = away - adjustment

    return pd.DataFrame(rows, columns=["game_id", "home_elo_pre", "away_elo_pre"])
```

Create an empty `ml/__init__.py`.

- [ ] **Step 4: Run and verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_elo.py -v`

Expected: 4 passed.

- [ ] **Step 5: Sanity-check Elo against real history**

```bash
.venv/Scripts/python.exe -c "
import duckdb
from ml.elo import compute_elo, expected_score
con = duckdb.connect('warehouse/basketball.duckdb', read_only=True)
g = con.execute('select game_id, season, game_date, home_team_id, away_team_id, home_won from main_marts.fct_team_game order by game_date').df()
e = compute_elo(g).merge(g, on='game_id')
e['p'] = [expected_score(h + 100, a) for h, a in zip(e.home_elo_pre, e.away_elo_pre)]
recent = e[e.season >= '1996-97']
acc = ((recent.p > 0.5) == recent.home_won).mean()
print(f'Elo-only accuracy 1996-97+: {acc:.4f} over {len(recent)} games')
"
```

Expected: accuracy between **0.63 and 0.68**. Below 0.60 means the orientation or the update is wrong. This is the number every later model must beat.

- [ ] **Step 6: Commit**

```bash
git add ml/ tests/test_elo.py
git commit -m "Add sequential Elo ratings with between-season regression

Emitted as pre-game ratings only, so nothing downstream can accidentally
read a rating that already contains the result it is predicting."
```

---

### Task 6: Pre-tipoff feature table and the leakage test

**Files:**
- Create: `dbt/basketball_intelligence/models/marts/mart_game_features.sql`
- Create: `dbt/basketball_intelligence/tests/assert_no_future_data_in_features.sql`
- Create: `ml/features.py`, `tests/test_features.py`

**Interfaces:**
- Consumes: `fct_team_game` (Task 4), `compute_elo` (Task 5).
- Produces: `ml.features.build_feature_frame(con) -> pd.DataFrame` — one row per game with the model matrix plus `margin` and `home_won` as targets — and the module constant `ml.features.FEATURE_COLUMNS: list[str]`. Tasks 7 and 9 consume both.

- [ ] **Step 1: Write the dbt feature model**

`mart_game_features.sql`. Every window is bounded `rows between unbounded preceding and 1 preceding`, which is what makes it pre-tipoff:

```sql
-- One row per game with features known before tip-off.
--
-- Every window below excludes the current row. That exclusion is the whole
-- point: a feature that can see its own game's result makes the backtest
-- meaningless, and the error is invisible in the output. The singular test
-- assert_no_future_data_in_features re-derives a sample independently
-- rather than trusting the frames by eye.

with long as (
    -- Back to two rows per game so each team's history is its own window.
    select game_id, season, game_date, home_team_id as team_id,
           away_team_id as opp_team_id, margin as team_margin,
           home_won as team_won, true as at_home
    from {{ ref('fct_team_game') }}
    union all
    select game_id, season, game_date, away_team_id, home_team_id,
           -margin, not home_won, false
    from {{ ref('fct_team_game') }}
),

team_form as (
    select
        game_id,
        team_id,
        at_home,
        count(*) over w                     as games_played_this_season,
        avg(team_margin) over w             as season_margin_avg,
        avg(case when team_won then 1.0 else 0.0 end) over w as season_win_pct,
        avg(team_margin) over w5            as last5_margin_avg,
        avg(team_margin) over w10           as last10_margin_avg,
        game_date - lag(game_date) over (
            partition by season, team_id order by game_date, game_id
        )                                   as days_rest
    from long
    window
        w as (partition by season, team_id order by game_date, game_id
              rows between unbounded preceding and 1 preceding),
        w5 as (partition by season, team_id order by game_date, game_id
               rows between 5 preceding and 1 preceding),
        w10 as (partition by season, team_id order by game_date, game_id
                rows between 10 preceding and 1 preceding)
)

select
    f.game_id,
    f.season,
    f.game_date,
    f.is_neutral_site,
    f.home_team_id,
    f.away_team_id,
    h.games_played_this_season          as home_games_played,
    a.games_played_this_season          as away_games_played,
    h.season_margin_avg                 as home_season_margin,
    a.season_margin_avg                 as away_season_margin,
    h.season_win_pct                    as home_season_win_pct,
    a.season_win_pct                    as away_season_win_pct,
    h.last5_margin_avg                  as home_last5_margin,
    a.last5_margin_avg                  as away_last5_margin,
    h.last10_margin_avg                 as home_last10_margin,
    a.last10_margin_avg                 as away_last10_margin,
    h.days_rest                         as home_days_rest,
    a.days_rest                         as away_days_rest,
    coalesce(h.days_rest = 1, false)    as home_back_to_back,
    coalesce(a.days_rest = 1, false)    as away_back_to_back,
    -- Targets. Never features.
    f.margin,
    f.home_won
from {{ ref('fct_team_game') }} f
join team_form h on h.game_id = f.game_id and h.at_home
join team_form a on a.game_id = f.game_id and not a.at_home
```

- [ ] **Step 2: Write the leakage test**

`assert_no_future_data_in_features.sql`:

```sql
-- Recompute one feature from scratch with an explicit date filter and
-- compare. If the window frames in mart_game_features ever stop excluding
-- the current row, the stored value starts including the game's own result
-- and this diverges. Sampled to keep the test cheap.
--
-- This re-derives the home team's home games only, so it validates the
-- exclusion rather than the full feature definition - which is exactly
-- what it exists to catch.

with sample as (
    select * from {{ ref('mart_game_features') }}
    where home_games_played >= 5 and season >= '2015-16'
    using sample 500 rows
),

recomputed as (
    select
        s.game_id,
        s.home_season_margin as stored,
        (select avg(f.margin)
         from {{ ref('fct_team_game') }} f
         where f.season = s.season
           and f.home_team_id = s.home_team_id
           and f.game_date < s.game_date) as independent
    from sample s
)

select game_id, stored, independent
from recomputed
where independent is not null
  and abs(stored - independent) > 0.001
```

- [ ] **Step 3: Build and run the test**

Run: `cd dbt/basketball_intelligence && ../../.venv/Scripts/dbt.exe build --profiles-dir . --select mart_game_features+`

Expected: the model builds; the leakage test returns 0 rows.

- [ ] **Step 4: Write the Python assembly layer**

`ml/features.py`:

```python
"""Assemble the model matrix: the dbt feature mart joined to Elo."""

from __future__ import annotations

import pandas as pd

from ml.elo import compute_elo

FEATURE_COLUMNS = [
    "home_elo_pre", "away_elo_pre", "elo_diff",
    "home_season_margin", "away_season_margin",
    "home_season_win_pct", "away_season_win_pct",
    "home_last5_margin", "away_last5_margin",
    "home_last10_margin", "away_last10_margin",
    "home_days_rest", "away_days_rest",
    "home_back_to_back", "away_back_to_back",
    "home_games_played", "away_games_played",
    "is_neutral_site",
]


def build_feature_frame(con) -> pd.DataFrame:
    """One row per game: features, plus margin and home_won as targets."""
    features = con.execute(
        "select * from main_marts.mart_game_features order by game_date, game_id"
    ).df()
    games = con.execute(
        """
        select game_id, season, game_date, home_team_id, away_team_id, home_won
        from main_marts.fct_team_game order by game_date, game_id
        """
    ).df()
    elo = compute_elo(games)
    merged = features.merge(elo, on="game_id", how="left")
    merged["elo_diff"] = merged["home_elo_pre"] - merged["away_elo_pre"]
    for column in ("home_days_rest", "away_days_rest"):
        merged[column] = pd.to_numeric(merged[column], errors="coerce")
    return merged
```

- [ ] **Step 5: Write the feature tests**

`tests/test_features.py`:

```python
"""The feature matrix must contain nothing the model could not know before
tip-off, and must not silently lose games."""

import pytest

from ml.features import FEATURE_COLUMNS, build_feature_frame


@pytest.fixture(scope="module")
def frame(con):
    return build_feature_frame(con)


def test_every_feature_column_is_present(frame):
    missing = [c for c in FEATURE_COLUMNS if c not in frame.columns]
    assert not missing, f"missing feature columns: {missing}"


def test_targets_are_not_features():
    for target in ("margin", "home_won", "home_points", "away_points"):
        assert target not in FEATURE_COLUMNS, f"{target} leaks the result"


def test_one_row_per_game(frame, con):
    assert frame["game_id"].is_unique
    total = con.execute("select count(*) from main_marts.fct_team_game").fetchone()[0]
    assert len(frame) == total


def test_first_game_of_a_season_has_no_prior_form(frame):
    """Opening night is the cold-start case the model must handle, so it has
    to be representable rather than dropped."""
    openers = frame[frame["home_games_played"] == 0]
    assert len(openers) > 0
    assert openers["home_season_margin"].isna().all()


def test_elo_is_populated_for_every_game(frame):
    assert frame["home_elo_pre"].notna().all()
    assert frame["away_elo_pre"].notna().all()
```

- [ ] **Step 6: Run the tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_features.py -v`

Expected: 5 passed.

- [ ] **Step 7: Commit**

```bash
git add dbt/basketball_intelligence/models/marts/mart_game_features.sql dbt/basketball_intelligence/tests/assert_no_future_data_in_features.sql ml/features.py tests/test_features.py
git commit -m "Build the pre-tipoff feature table

Every window excludes the current row, and a singular test re-derives a
sample independently so the exclusion cannot silently break. Opening-night
games are kept with null form rather than dropped - the cold start is the
case the model most needs to handle."
```

---

### Task 7: Walk-forward backtest harness

The harness comes before any real model, because its job is to make an overfit result impossible to report by accident.

**Files:**
- Create: `ml/train.py`, `tests/test_train.py`

**Interfaces:**
- Consumes: `build_feature_frame`, `FEATURE_COLUMNS` (Task 6).
- Produces: `ml.train.walk_forward(frame, model_factory, start_season: str, feature_columns: list[str] | None = None) -> pd.DataFrame` with columns `game_id, season, predicted_margin, win_probability, margin, home_won`; `ml.train.evaluate(predictions) -> dict` with keys `accuracy, log_loss, brier, margin_mae, n`; and `ml.train.margin_to_win_probability(margin, sd)`. Tasks 9 and 10 consume these.

- [ ] **Step 1: Write the failing tests**

`tests/test_train.py`:

```python
"""The harness must train only on the past. These tests are the reason the
backtest can be believed, so they assert the split itself, not the score."""

import numpy as np
import pandas as pd
import pytest

from ml.train import evaluate, walk_forward


class SpyModel:
    """Records the size of each training set so the split can be asserted."""

    seen: list = []

    def fit(self, X, y):
        SpyModel.seen.append(len(X))
        return self

    def predict(self, X):
        return np.zeros(len(X))


def _frame():
    margins = np.linspace(-20, 20, 30)
    return pd.DataFrame({
        "game_id": [str(i) for i in range(30)],
        "season": ["2000-01"] * 10 + ["2001-02"] * 10 + ["2002-03"] * 10,
        "elo_diff": np.linspace(-100, 100, 30),
        "margin": margins,
        "home_won": margins > 0,
    })


def test_training_set_grows_and_never_includes_the_test_season():
    SpyModel.seen = []
    walk_forward(_frame(), SpyModel, start_season="2001-02",
                 feature_columns=["elo_diff"])
    # Predicting 2001-02 trains on the 10 games of 2000-01; predicting
    # 2002-03 trains on 20. Never on its own season.
    assert SpyModel.seen == [10, 20]


def test_every_prediction_is_out_of_sample():
    out = walk_forward(_frame(), SpyModel, start_season="2001-02",
                       feature_columns=["elo_diff"])
    assert set(out["season"]) == {"2001-02", "2002-03"}
    assert len(out) == 20


def test_evaluate_reports_the_metrics_that_matter():
    out = pd.DataFrame({
        "win_probability": [0.9, 0.1, 0.6, 0.4],
        "home_won": [True, False, True, False],
        "predicted_margin": [10.0, -10.0, 2.0, -2.0],
        "margin": [8.0, -12.0, 1.0, -3.0],
    })
    metrics = evaluate(out)
    assert metrics["accuracy"] == pytest.approx(1.0)
    assert metrics["margin_mae"] == pytest.approx(1.5)
    assert 0 < metrics["brier"] < 0.1
    assert metrics["n"] == 4
```

- [ ] **Step 2: Run and verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_train.py -v`

Expected: fail with `ModuleNotFoundError: No module named 'ml.train'`.

- [ ] **Step 3: Implement**

`ml/train.py`:

```python
"""Walk-forward backtesting.

Random cross-validation on game data trains on the future to predict the
past and reports a score that cannot be reproduced live. This module only
ever trains on seasons strictly before the season being predicted, so every
number it reports is out of sample.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import norm
from sklearn.metrics import brier_score_loss, log_loss

from ml.features import FEATURE_COLUMNS

# Margin residuals are close to normal with a standard deviation near this.
# Turning a predicted margin into a win probability needs a spread; refit it
# from the residuals once a real model exists.
MARGIN_SD = 13.5


def margin_to_win_probability(margin, sd: float = MARGIN_SD) -> np.ndarray:
    """P(home wins) = P(margin > 0) under a normal centred on the prediction."""
    return norm.cdf(np.asarray(margin, dtype=float) / sd)


def walk_forward(
    frame: pd.DataFrame,
    model_factory,
    start_season: str,
    feature_columns: list[str] | None = None,
) -> pd.DataFrame:
    """Train on every prior season, predict the next, advance."""
    columns = feature_columns if feature_columns is not None else FEATURE_COLUMNS
    seasons = sorted(frame["season"].unique())
    results = []

    for season in [s for s in seasons if s >= start_season]:
        train = frame[frame["season"] < season]
        test = frame[frame["season"] == season]
        if train.empty or test.empty:
            continue

        X_train = train[columns].astype(float).fillna(0.0)
        X_test = test[columns].astype(float).fillna(0.0)
        model = model_factory().fit(X_train, train["margin"].astype(float))
        predicted = np.asarray(model.predict(X_test), dtype=float)

        results.append(pd.DataFrame({
            "game_id": test["game_id"].to_numpy(),
            "season": season,
            "predicted_margin": predicted,
            "win_probability": margin_to_win_probability(predicted),
            "margin": test["margin"].to_numpy(),
            "home_won": test["home_won"].to_numpy(),
        }))

    return pd.concat(results, ignore_index=True) if results else pd.DataFrame()


def evaluate(predictions: pd.DataFrame) -> dict:
    """Accuracy, calibration and margin error together.

    Accuracy alone hides a miscalibrated model: one that says 90% whenever
    it means 60% still looks fine on accuracy.
    """
    actual = predictions["home_won"].astype(bool).to_numpy()
    probability = predictions["win_probability"].astype(float).to_numpy()
    clipped = np.clip(probability, 1e-6, 1 - 1e-6)
    return {
        "accuracy": float(((probability > 0.5) == actual).mean()),
        "log_loss": float(log_loss(actual, clipped, labels=[False, True])),
        "brier": float(brier_score_loss(actual, clipped)),
        "margin_mae": float(np.abs(
            predictions["predicted_margin"].astype(float)
            - predictions["margin"].astype(float)).mean()),
        "n": int(len(predictions)),
    }
```

- [ ] **Step 4: Run and verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_train.py -v`

Expected: 3 passed.

- [ ] **Step 5: Run the real backtest against the baselines**

```bash
.venv/Scripts/python.exe -c "
import duckdb
from sklearn.linear_model import Ridge
from ml.features import build_feature_frame
from ml.train import walk_forward, evaluate

con = duckdb.connect('warehouse/basketball.duckdb', read_only=True)
frame = build_feature_frame(con)
frame = frame[frame.season >= '1996-97']

out = walk_forward(frame, lambda: Ridge(alpha=1.0), start_season='2005-06')
print('ridge      ', evaluate(out))

elo_only = walk_forward(frame, lambda: Ridge(alpha=1.0), start_season='2005-06',
                        feature_columns=['elo_diff'])
print('elo only   ', evaluate(elo_only))
print('home always', out.home_won.mean())
"
```

Expected, and **record these numbers in the commit message**: home-always 0.58-0.60; elo-only accuracy 0.63-0.66; ridge accuracy **0.64-0.68**, Brier 0.20-0.22, margin MAE 10-11.5.

**If accuracy exceeds 0.75 or margin MAE drops below 8, stop — that is leakage, not success.** Re-run the dbt leakage test and confirm no target column entered `FEATURE_COLUMNS`.

- [ ] **Step 6: Commit**

```bash
git add ml/train.py tests/test_train.py
git commit -m "Add the walk-forward backtest harness

Trains only on seasons before the one being predicted, and the test
asserts the split directly rather than the score. Reports calibration
alongside accuracy because accuracy alone hides a badly calibrated model."
```

---

### Task 8: Ingest the upcoming schedule

Prediction needs games that have not been played. `LeagueGameLog` only returns completed ones. `ScheduleLeagueV2` returns the full published season — verified working on 2026-09-21: 1,274 games for 2026-27, opening 2026-10-20.

**Files:**
- Modify: `ingestion/nba_ingest.py`
- Create: `dbt/basketball_intelligence/models/staging/stg_schedule.sql`
- Modify: `dbt/.../models/staging/_sources.yml`, `_staging_models.yml`

**Interfaces:**
- Produces: `main_staging.stg_schedule` with `season, game_id, game_date, tipoff_utc, home_team_id, home_team_abbreviation, away_team_id, away_team_abbreviation, is_neutral_site, game_status`. `game_status` 1 means scheduled, 3 means final. Task 9 consumes it.

- [ ] **Step 1: Add the fetch function**

In `ingestion/nba_ingest.py`, add `scheduleleaguev2` to the `from nba_api.stats.endpoints import (...)` block, then add alongside the other fetchers:

```python
def fetch_schedule(season: str) -> pd.DataFrame:
    """The full published schedule including unplayed games.

    LeagueGameLog only returns games that have finished, so predicting a
    future slate needs this instead. The NBA publishes the next season's
    schedule in August, so this returns rows before the season starts.
    """
    df = call_endpoint(
        scheduleleaguev2.ScheduleLeagueV2,
        season=season,
        league_id="00",
    )
    log.info("Fetched %d scheduled games for %s", len(df), season)
    return df
```

Wire it into `run()` beside the other per-season fetches, following the existing `needed()` / `write_parquet()` pattern with table name `schedule`. Unlike the game-log tables it must **always** re-fetch the current season — published schedules change through postponements and rescheduling, so `season_done()` must not short-circuit it.

- [ ] **Step 2: Fetch the upcoming season**

Run: `.venv/Scripts/python.exe ingestion/nba_ingest.py --seasons 2026-27 --force`

Expected: `data/raw/schedule/2026-27.parquet` created, around 1,274 rows.

- [ ] **Step 3: Add the source and staging model**

Add `schedule` to the tables list in `_sources.yml`, matching the existing entries. Then `stg_schedule.sql`:

```sql
-- One row per scheduled game, including games not yet played.
-- gameStatus is 1 for scheduled, 2 for in progress, 3 for final.

select
    cast(seasonYear as varchar)            as season,
    cast(gameId as varchar)                as game_id,
    cast(gameDate as date)                 as game_date,
    cast(gameDateTimeUTC as timestamp)     as tipoff_utc,
    cast(homeTeam_teamId as bigint)        as home_team_id,
    cast(homeTeam_teamTricode as varchar)  as home_team_abbreviation,
    cast(awayTeam_teamId as bigint)        as away_team_id,
    cast(awayTeam_teamTricode as varchar)  as away_team_abbreviation,
    coalesce(cast(isNeutral as boolean), false) as is_neutral_site,
    cast(gameStatus as integer)            as game_status
from {{ source('raw', 'schedule') }}
```

Add to `_staging_models.yml`:

```yaml
  - name: stg_schedule
    description: >
      Published schedule including unplayed games, from ScheduleLeagueV2.
      The game-log endpoints only return finished games, so this is the
      only source for a future slate.
    columns:
      - name: game_id
        tests: [not_null, unique]
      - name: home_team_id
        tests: [not_null]
      - name: away_team_id
        tests: [not_null]
```

- [ ] **Step 4: Load and build**

Run: `.venv/Scripts/python.exe scripts/load_to_duckdb.py && cd dbt/basketball_intelligence && ../../.venv/Scripts/dbt.exe build --profiles-dir .`

Expected: all pass.

- [ ] **Step 5: Verify the upcoming slate is visible**

```bash
.venv/Scripts/python.exe -c "
import duckdb
con = duckdb.connect('warehouse/basketball.duckdb', read_only=True)
print(con.execute('''select count(*) games, min(game_date) first_game, max(game_date) last_game
  from main_staging.stg_schedule where season = '2026-27' and game_status = 1''').df().to_string())
"
```

Expected: roughly 1,230 regular-season games, first game 2026-10-20.

- [ ] **Step 6: Commit**

```bash
git add ingestion/nba_ingest.py dbt/basketball_intelligence/models/staging/stg_schedule.sql dbt/basketball_intelligence/models/staging/_sources.yml dbt/basketball_intelligence/models/staging/_staging_models.yml
git commit -m "Ingest the published schedule

LeagueGameLog only returns finished games, so a future slate needs
ScheduleLeagueV2. Always re-fetched for the current season because
published schedules change."
```

---

### Task 9: Write predictions, append-only

**Files:**
- Create: `ml/predict.py`, `tests/test_predict.py`

**Interfaces:**
- Consumes: `stg_schedule` (Task 8), `build_feature_frame` (Task 6), `walk_forward` / `margin_to_win_probability` (Task 7).
- Produces: table `main.predictions` — `prediction_id, model_version, predicted_at, game_id, season, game_date, home_team_id, away_team_id, predicted_margin, win_probability`. Task 10 consumes it. **Never updated or deleted; a re-run inserts a new row with a new `predicted_at`.**

- [ ] **Step 1: Write the failing test**

`tests/test_predict.py`:

```python
"""Predictions are the public record. The properties that make that record
credible - written before tip-off, never rewritten - are asserted here."""

import duckdb
import pandas as pd
import pytest

from ml.predict import MODEL_VERSION, write_predictions


@pytest.fixture
def memory_db():
    con = duckdb.connect(":memory:")
    con.execute("""
        create table predictions (
            prediction_id varchar, model_version varchar,
            predicted_at timestamp, game_id varchar, season varchar,
            game_date date, home_team_id bigint, away_team_id bigint,
            predicted_margin double, win_probability double
        )
    """)
    return con


def _rows():
    return pd.DataFrame({
        "game_id": ["0022600001"],
        "season": ["2026-27"],
        "game_date": pd.to_datetime(["2026-10-20"]).date,
        "home_team_id": [1610612738],
        "away_team_id": [1610612747],
        "predicted_margin": [3.5],
        "win_probability": [0.61],
    })


def test_writing_twice_appends_rather_than_overwrites(memory_db):
    write_predictions(memory_db, _rows())
    write_predictions(memory_db, _rows())
    total = memory_db.execute("select count(*) from predictions").fetchone()[0]
    assert total == 2, "a re-run must not erase the earlier prediction"


def test_every_row_carries_the_model_version(memory_db):
    write_predictions(memory_db, _rows())
    versions = memory_db.execute(
        "select distinct model_version from predictions").fetchall()
    assert versions == [(MODEL_VERSION,)]


def test_win_probability_stays_a_probability(memory_db):
    write_predictions(memory_db, _rows())
    bad = memory_db.execute(
        "select count(*) from predictions where win_probability not between 0 and 1"
    ).fetchone()[0]
    assert bad == 0
```

- [ ] **Step 2: Run and verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_predict.py -v`

Expected: `ModuleNotFoundError: No module named 'ml.predict'`.

- [ ] **Step 3: Implement**

`ml/predict.py`:

```python
"""Predict the upcoming slate and append the results.

The predictions table is append-only on purpose. A public track record is
only worth anything if the predictions in it cannot be revised after the
games are played, so a re-run inserts new rows rather than replacing old
ones, and every row carries the model version that produced it.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pandas as pd

MODEL_VERSION = "ridge-v1"

CREATE_TABLE = """
create table if not exists predictions (
    prediction_id    varchar,
    model_version    varchar,
    predicted_at     timestamp,
    game_id          varchar,
    season           varchar,
    game_date        date,
    home_team_id     bigint,
    away_team_id     bigint,
    predicted_margin double,
    win_probability  double
)
"""


def upcoming_slate(con, through: date) -> pd.DataFrame:
    """Scheduled, not-yet-played games up to and including `through`."""
    return con.execute(
        """
        select season, game_id, game_date, home_team_id, away_team_id,
               is_neutral_site
        from main_staging.stg_schedule
        where game_status = 1 and game_date <= ?
        order by game_date, game_id
        """,
        [through],
    ).df()


def write_predictions(con, rows: pd.DataFrame) -> int:
    """Append predictions. Returns the number of rows written."""
    if rows.empty:
        return 0
    con.execute(CREATE_TABLE)
    stamped = rows.copy()
    stamped["prediction_id"] = [str(uuid.uuid4()) for _ in range(len(stamped))]
    stamped["model_version"] = MODEL_VERSION
    stamped["predicted_at"] = datetime.now(timezone.utc).replace(tzinfo=None)
    stamped = stamped[[
        "prediction_id", "model_version", "predicted_at", "game_id", "season",
        "game_date", "home_team_id", "away_team_id", "predicted_margin",
        "win_probability",
    ]]
    con.register("_incoming", stamped)
    con.execute("insert into predictions select * from _incoming")
    con.unregister("_incoming")
    return len(stamped)
```

- [ ] **Step 4: Run and verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_predict.py -v`

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add ml/predict.py tests/test_predict.py
git commit -m "Write predictions append-only

A track record is only worth reading if the predictions in it cannot be
revised after the games are played, so re-running inserts new rows and
every row carries the model version that produced it."
```

---

### Task 10: Score the record and show it

**Files:**
- Create: `ml/evaluate.py`, `dashboard/views/predictions.py`, `tests/test_predictions_page.py`
- Modify: `dashboard/app.py`, `scripts/weekly_refresh.py`

**Interfaces:**
- Consumes: the `predictions` table (Task 9), `fct_team_game` (Task 4), `evaluate` (Task 7).
- Produces: `ml.evaluate.track_record(con) -> dict`, `ml.evaluate.calibration_table(con, bins: int = 10) -> pd.DataFrame` with columns `bucket, predicted, observed, n`.

- [ ] **Step 1: Write the scorer**

`ml/evaluate.py`:

```python
"""Score settled predictions against what actually happened.

Only the earliest prediction per game counts. Later re-runs for the same
game exist in the table, but grading the latest one would let a model be
scored on a prediction made after the result was known.
"""

from __future__ import annotations

import pandas as pd

from ml.train import evaluate

SETTLED_SQL = """
with first_prediction as (
    select *, row_number() over (
        partition by game_id order by predicted_at
    ) as attempt
    from predictions
)
select p.game_id, p.model_version, p.game_date, p.predicted_margin,
       p.win_probability, f.margin, f.home_won
from first_prediction p
join main_marts.fct_team_game f on f.game_id = p.game_id
where p.attempt = 1
"""


def settled_predictions(con) -> pd.DataFrame:
    return con.execute(SETTLED_SQL).df()


def track_record(con) -> dict:
    settled = settled_predictions(con)
    if settled.empty:
        return {"n": 0}
    return evaluate(settled)


def calibration_table(con, bins: int = 10) -> pd.DataFrame:
    """Predicted probability against observed frequency, for a reliability plot."""
    settled = settled_predictions(con)
    if settled.empty:
        return pd.DataFrame(columns=["bucket", "predicted", "observed", "n"])
    settled["bucket"] = (settled["win_probability"] * bins).astype(int).clip(0, bins - 1)
    return settled.groupby("bucket").agg(
        predicted=("win_probability", "mean"),
        observed=("home_won", "mean"),
        n=("game_id", "size"),
    ).reset_index()
```

- [ ] **Step 2: Add the availability guard to the query layer**

Append to `dashboard/lib/db.py`, next to `marts_available()`:

```python
@st.cache_data(ttl=600, show_spinner=False)
def predictions_available() -> bool:
    """Whether any predictions have been written yet.

    The table only exists after ml/predict.py has run at least once. A
    warehouse published before that raises a catalog error that would take
    the whole app down, so the page checks first - same pattern as
    marts_available().
    """
    try:
        with duckdb.connect(str(DB_PATH), read_only=True) as con:
            con.execute("select 1 from predictions limit 1")
        return True
    except (duckdb.Error, OSError):
        return False


def upcoming_predictions(limit: int = 30) -> pd.DataFrame:
    """The most recent prediction for each not-yet-played game."""
    return q(
        """
        with latest as (
            select *, row_number() over (
                partition by game_id order by predicted_at desc
            ) as recency
            from predictions
        )
        select l.game_id, l.game_date, l.win_probability, l.predicted_margin,
               s.home_team_abbreviation, s.away_team_abbreviation
        from latest l
        join main_staging.stg_schedule s on s.game_id = l.game_id
        where l.recency = 1 and s.game_status = 1
        order by l.game_date, l.game_id
        limit ?
        """,
        (limit,),
    )
```

Note the deliberate asymmetry: the *display* of an upcoming game uses the newest prediction, while *scoring* in `ml/evaluate.py` uses the earliest. Showing a stale number helps nobody, but grading against a late one would flatter the record.

- [ ] **Step 3: Add the page**

`dashboard/views/predictions.py`:

```python
"""Upcoming game predictions and the model's public track record."""

import streamlit as st

from dashboard.lib import db
from dashboard.lib import theme as T


def render() -> None:
    st.markdown(T.section_header("Predictions"), unsafe_allow_html=True)

    if not db.predictions_available():
        st.info(
            "No predictions have been published yet. They are written once a "
            "week, before the games are played."
        )
        return

    upcoming = db.upcoming_predictions()
    if upcoming.empty:
        st.info("No upcoming games on the schedule right now.")
    else:
        st.caption(
            "Win probability is for the home team. Early in a season no team "
            "has current-season form yet, so these lean almost entirely on "
            "carried-over ratings and are correspondingly less reliable."
        )
        st.dataframe(upcoming, hide_index=True, use_container_width=True)

    st.markdown(T.section_header("Track record"), unsafe_allow_html=True)
    record = db.prediction_track_record()
    if record.get("n", 0) == 0:
        st.info("No predictions have been settled yet. Check back after the "
                "first games are played.")
        return

    c1, c2, c3 = st.columns(3)
    c1.markdown(T.kpi("Accuracy", f"{record['accuracy'] * 100:.1f}%",
                      f"over {record['n']} games"), unsafe_allow_html=True)
    c2.markdown(T.kpi("Brier score", f"{record['brier']:.3f}",
                      "lower is better; 0.25 is a coin flip"),
                unsafe_allow_html=True)
    c3.markdown(T.kpi("Margin error", f"{record['margin_mae']:.1f}",
                      "average points off"), unsafe_allow_html=True)
```

Add a `db.prediction_track_record()` wrapper that calls `ml.evaluate.track_record()` against a read-only connection and returns `{"n": 0}` when the table is missing. Match the exact `theme` helper names in use — read `dashboard/lib/theme.py` and `dashboard/views/advanced.py` first; `T.kpi` and `T.section_header` are the names used elsewhere but confirm before relying on them.

Register the page in `dashboard/app.py` alongside the others.

- [ ] **Step 4: Test the page headlessly**

`tests/test_predictions_page.py` using `streamlit.testing.v1.AppTest.from_string` wrapping `predictions.render()`. Assert the page renders without exception in both states: when the `predictions` table exists and when it does not. Remember `segmented_control` surfaces as `at.get("button_group")` and tables as `at.get("dataframe")`.

Run: `.venv/Scripts/python.exe -m pytest tests/ -v`

Expected: the whole suite passes.

- [ ] **Step 5: Add module entry points**

Give `ml/predict.py` and `ml/evaluate.py` each an `if __name__ == "__main__":` block that opens `warehouse/basketball.duckdb` read-write, runs the coming week's slate (or scores settled predictions), and prints a one-line summary.

- [ ] **Step 6: Wire into the weekly refresh**

Add two entries to the `steps` list in `scripts/weekly_refresh.py`, after `dbt_test` and before the release publish:

```python
        ("predict", [PYTHON, "-m", "ml.predict"], None),
        ("score_predictions", [PYTHON, "-m", "ml.evaluate"], None),
```

- [ ] **Step 7: Dry run the whole path**

Run: `.venv/Scripts/python.exe -m ml.predict`

Expected: before 2026-10-20 it writes 0 rows and says so; once the slate falls inside the window it writes the week's games. Either outcome is a pass — a crash is not.

- [ ] **Step 8: Commit**

```bash
git add ml/evaluate.py dashboard/views/predictions.py dashboard/app.py scripts/weekly_refresh.py tests/
git commit -m "Publish predictions and score them in the open

Scores only the first prediction made for each game, so a later re-run
cannot improve the record retroactively. The page shows calibration next
to accuracy because a confident wrong model looks fine on accuracy alone."
```

---

## TRACK 2 — No deadline

**Tasks 11, 12 and 13 touch files Track 1 never opens** — `.github/`, `.gitignore`, `data/fixtures/`, `README.md`, `docs/adr/`. They can run on a separate branch at any time, including concurrently with Track 1 and with each other.

**Task 14 is the exception.** It modifies `dashboard/lib/db.py`, which Task 10 also modifies. Do not run them concurrently. Either finish Task 10 first, or do Task 14 before Track 1 reaches Task 10 — but not both at once, and not in parallel worktrees that merge later.

### Task 11: CI for tests only

Cheap now that Tasks 1-10 created a test suite; it was expensive only while the tests did not exist.

**Files:** Create `.github/workflows/tests.yml` and `data/fixtures/` (one season of parquet, about 900 KB); modify `.gitignore`.

The blocker that killed `.github/workflows/refresh-data.yml` (added `22f7850`, deleted `94a69ea`) was the ingest step alone — stats.nba.com blocks datacenter IPs, per `DEPLOYMENT.md:72-78`. `load_to_duckdb.py`, `dbt build` and pytest make no external calls, so this workflow is unaffected.

Commit the 2024-25 parquet files as fixtures (add a negation rule to `.gitignore`, which currently excludes `data/raw/**/*.parquet`), build a small warehouse in CI from them, then run `dbt build` and pytest. **Do not add an ingest step.** Note that `tests/conftest.py` skips when the warehouse is absent, so CI must build the fixture warehouse before pytest runs or the suite will silently pass with everything skipped — assert a nonzero collected count.

### Task 12: README rewrite

**Files:** Modify `README.md`; commit `site_pictures/` and `docs/`.

Add the live link and the six screenshots already sitting in `site_pictures/`. Fix the page list to include Advanced. Replace "(eventually) serve a public dashboard" (line 4) and "the placeholder dashboard" (line 124) with what actually shipped. Drop or explicitly park the natural-language-Q&A and contracts vision. Name the data source for net rating and PIE.

Reconcile the release tag: the deleted workflow published to `data-latest` while `DEPLOYMENT.md` documents `data-v1`. Pick one and correct the other.

### Task 13: Architecture decision records

**Files:** Create `docs/adr/0001-duckdb-over-postgres.md` through `0006-known-limitations.md`.

One record per decision: DuckDB over Postgres; Streamlit over a custom frontend (cross-reference `docs/frontend-migration-options.md`, which already holds the measurements and the deferral rationale); GitHub Release asset for data distribution; local Task Scheduler over GitHub Actions (cite the IP-block evidence in `DEPLOYMENT.md:72-78`); the 1979-80 start date (the full three-point era); and known limitations — single-desktop dependency for the refresh, and monetization blocked on data licensing.

### Task 14: Standings mart and the two UI fixes

These are grouped because the standings tiebreak and the standings mart touch the same query — splitting them guarantees a conflict.

**Note on `fct_player_season`:** the original change list proposed one. `mart_player_season` already is it — one row per player per season with every rate metric, era-guarded. No new model is needed; the only player-grain work was consolidating the app's duplicated TS%, done in Task 1.

**Files:**
- Create: `dbt/basketball_intelligence/models/marts/mart_team_standings.sql`
- Modify: `dashboard/lib/db.py` (`standings()`), `dashboard/lib/theme.py:151-152`, `dashboard/views/advanced.py:61-72`, `dashboard/views/overview.py:22`

**Interfaces:**
- Produces: `main_marts.mart_team_standings` — `season, team_id, team_abbreviation, conference, games_played, wins, losses, win_pct, points_per_game, opp_points_per_game, net_points, form`.

- [ ] **Step 1: Move the conference map into dbt**

`dashboard/lib/db.py` hardcodes `EAST` and `WEST` sets at module level (lines 18-22) including historical abbreviations. Port those sets into the new mart as a `case` expression so conference assignment has one home, and have `db.standings()` read the column instead of calling `df["team"].map(conference)`. Keep `db.conference()` exported — other callers may use it — but make the mart the source of truth.

- [ ] **Step 2: Write the mart**

`mart_team_standings.sql` reproduces the logic currently in `db.standings()`: wins, losses, win percentage, points for and against, net points, and the last-five form string via `substr(string_agg(win_loss, '' order by game_date desc), 1, 5)`. Build it on `int_team_game_opponent` from Task 4 rather than repeating the self-join.

- [ ] **Step 3: Add a real tiebreak**

The current ordering is `order by pct desc, net desc`, which breaks ties on point differential alone. The NBA's actual first tiebreaker is head-to-head record. Implement head-to-head first, then point differential, and **document in the model comment that this is a simplification** — the official rules then go to division record, conference record, and several further steps that this does not model. Do not claim it implements the official tiebreakers.

- [ ] **Step 4: Test the mart**

Add a singular test asserting that within each season and conference no two teams share an identical `(win_pct, net_points, head_to_head)` ordering key without a deterministic final fallback, and that `wins + losses = games_played` for every row.

Run: `cd dbt/basketball_intelligence && ../../.venv/Scripts/dbt.exe build --profiles-dir .`

- [ ] **Step 5: Fix the truncated leader-card names**

`.bip-name` at `dashboard/lib/theme.py:151-152` sets `white-space: nowrap; overflow: hidden; text-overflow: ellipsis`. The team abbreviation span is nested *inside* `.bip-name`, so on a long name like "Shai Gilgeous-Alexander" the ellipsis eats the team code entirely — the worse half of the bug.

Move `.bip-team` out of `.bip-name` so it is a sibling flex child that never clips, and add `min-width: 0` to `.bip-name` so it shrinks properly inside the flex row. Apply the same change to `adv_leaders_card` in `dashboard/views/overview.py:22`, which builds the same markup.

- [ ] **Step 6: Verify at both widths**

Screenshot the Overview and Advanced pages with Playwright (`channel="msedge"`) at desktop width and at `viewport 390x844, is_mobile=True, has_touch=True`. Confirm the longest current name renders with its team code intact at both sizes. Restart the Streamlit server first — it caches `lib` imports.

- [ ] **Step 7: Commit**

```bash
git add dbt/basketball_intelligence/models/marts/mart_team_standings.sql dbt/basketball_intelligence/tests dashboard/lib/db.py dashboard/lib/theme.py dashboard/views/advanced.py dashboard/views/overview.py
git commit -m "Move standings into a tested mart and stop clipping team codes

Standings logic and the conference map lived only in the app query.
Adds a head-to-head tiebreak ahead of point differential, documented as
a simplification of the official rules. The leader cards nested the team
abbreviation inside the ellipsised name span, so long names lost their
team code entirely."
```

---

## Execution order

Tasks 1-10 in order. Tasks 1 and 2 first because they are shipping bugs. Tasks 11-14 whenever Track 1 is blocked or waiting.

**If the window closes before Task 10:** Tasks 1-7 stand alone as a complete, valuable unit — two bug fixes, real test coverage, a documented game-grain fact table, and a validated backtest. Launching mid-season instead of on opening night costs nothing structural; the track record simply starts later.
