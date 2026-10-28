# 0008. dbt marts as the single source of truth

**Status:** Accepted

## Context

Several numbers on the site were computed twice: once in a dbt mart and
once in SQL inside the dashboard (`dashboard/lib/db.py`, which queried the
staging views directly). The two copies had drifted. The mart counted a
game where a stat wasn't recorded as a zero in that stat's per-game
average, and withheld true shooting when unrelated columns were missing,
not only its own inputs (field goal and free throw attempts, points); the
dashboard's copy got both right. Standings fell
back to a staging query when the mart was missing, and some queries were
built by editing SQL strings. dbt's tests covered the mart, the pytest
suite covered the dashboard's copy, and neither noticed the other was
different. Some dbt "known case" tests also passed when the row they
checked was missing, so a fixture gap made them pass without checking
anything.

## Decision

Every number the site shows is defined once, in a dbt mart, and the
dashboard reads it from there. The pages still read raw-grain rows (play
by play, box scores, one team's games) from the staging and intermediate
views, but never compute a metric of their own.

- `mart_player_season` adopted the dashboard's definitions, the more
  correct ones, and gained every column the pages use, plus `age`.
- New marts replace the dashboard's own aggregation SQL:
  `mart_player_team_season` (a traded player's stint with each team, and
  his team label, such as "CHI → BOS"), `mart_player_career`,
  `mart_league_shooting` (the league benchmarks) and
  `mart_settled_predictions` (each game's first prediction joined to its
  result).
- Two macros, `player_stat_line` and `shooting_pct`, hold the stat
  definitions the season, team-season and career marts share. Shooting
  percentages count only games where both makes and attempts were
  recorded, so none can exceed 100.
- Known-case tests fail when their expected row is missing, a test checks
  that no mart is empty, and the CI fixtures cover every era those tests
  name (`data/fixtures/README.md`).

Because code and data ship separately (code on a push to `main`, data only
when a refresh publishes), warehouse changes follow **expand, then
contract**: add the new model or column, publish it, switch the readers,
and only then remove what they used to read. Never drop or rename a table
or column that code on `main` reads. The rule came from a near miss. The
planned name for `mart_player_season`'s new team column was `team_path`,
but the deployed Advanced page reads that mart with `select *` and then
merges in a `team_path` column of its own; pandas would have named the two
`team_path_x` and `team_path_y`, and the page would have crashed on the
next publish. The column became `team_label`. So "additive" has to be
checked against what the live code does with a table, not only against
what it selects.

`mart_settled_predictions` went through all of it. `ml/evaluate.py` read
the mart from the start, but the published warehouse predated it, so the
dashboard kept an identical copy of its SQL, held equal to the model by a
test. The 2026-10-23 refresh published the mart; the dashboard then
switched to reading it, and the copy and that test were deleted.

Considered and rejected: keeping the metrics in the dashboard, which leaves
the pipeline, the models and the health check unable to share them and
dbt's tests unable to cover them; and a semantic or metrics layer, which
would add a tool for a project with one consumer of the marts.

## Consequences

A metric has one definition, tested by `dbt build` in CI and in every
refresh, and a fix lands everywhere at once. Moving the definitions
corrected a few published numbers: some pre-1985 per-game averages, and FG%
and 3P% for some 1979-80 to 1985-86 player-seasons, which no longer exceed
100. The cost is that a change to a number takes longer to reach the site:
a dbt change, a published warehouse, and for anything that replaces an
existing column, a second release to remove the old one. The pages also
have to keep working against an older warehouse in between, which is what
`objects_exist()` and the pages' notices are for
(`0010-data-access-package-caching-and-connection-per-query.md`).
