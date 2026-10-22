# Test fixtures

CI can't reach stats.nba.com, so it builds its warehouse from these files:
`.github/workflows/tests.yml` copies everything here into `data/raw/`, runs
`scripts/load_to_duckdb.py` and `dbt build`, then
`pytest -m "not full_warehouse"`. The layout mirrors `data/raw/` (one parquet
per season under each dataset). Every file is cut from the real ingested data.
Whole seasons are copied byte for byte, and the payroll slices keep only the
team-seasons named below. Keep each file under about 2 MB.

| Files | What they let CI test |
|---|---|
| `players.parquet`, `teams.parquet` | the player and team dimensions |
| `player_game_logs/`, `team_game_logs/` `1979-80`, `1984-85` | the incomplete-box-score era: percentages and ratings that must stay null or be withheld |
| `player_game_logs/`, `team_game_logs/` `1990-91` | a complete pre-1996-97 season: the "estimated from box score" ratings in `mart_team_season`, the derived usage in `mart_player_season`, and ages counted back from 1996-97 |
| `player_game_logs/`, `team_game_logs/` `2024-25` | a modern season: official advanced stats, game features, standings |
| `player_advanced/`, `team_advanced/` `1996-97` | the first official advanced season, which gives 1990-91 players their age (the Arcade's ages test) |
| `player_advanced/`, `team_advanced/` `2024-25` | the official advanced stats beside the 2024-25 box scores |
| `team_payroll/`, `team_payroll_players/` `1984-85`, `2024-25` | two whole payroll seasons (all 23 and 30 teams), so `assert_marts_not_empty` sees a full league |
| `team_payroll/`, `team_payroll_players/` `1986-87` (DEN, GOS), `1988-89` (MIA), `1989-90` (BOS), `1998-99` (HOU), `2009-10` (BOS), `2023-24` (the eight taxpayers) | exactly the team-seasons the `assert_team_finances_*` known-case tests name, so each test finds its rows. 1986-87 GOS has no salary rows at all |
| `play_by_play/2025-26.parquet` | shot charts and the play-by-play grain test |
| `schedule/2026-27.parquet` | upcoming games for the predictions |
| `bbref_team_salary_page.html` | one Basketball-Reference team page, for the payroll parser tests |

If you add a known-case dbt test that names a team-season, add that
team-season's payroll rows here too. Otherwise CI can't find the row and the
test fails.
