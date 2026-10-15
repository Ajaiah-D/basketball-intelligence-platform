# Predictions page polish + Arcade "Build a team" mode

Date: 2026-10-14. Decisions made with the user (all recommended options):
both build modes, an 8-man rotation, projection plus one sampled season,
and prediction cards grouped by date.

## Part 1 - Predictions page

The page currently prints a raw dataframe: `game_id`, `win_probability 0.5961`,
`home_team_abbreviation`, and a midnight timestamp.

- **Upcoming games as cards, grouped by date.** Same card language as the
  Games page (`.bip-game`). Each card shows both teams with color dots, the
  tip-off in US Eastern time (from `stg_schedule.tipoff_utc`), and a two-color
  win-probability bar (home vs away, each team's own color, percentages
  printed). The predicted margin reads "BOS by 6".
- **"How these are made" expander.** Elo ratings feed a ridge model; the
  probability comes from the predicted margin; what's not used yet (form and
  rest for future games). Plain English with glossary terms.
- **Track record.**
  - The existing KPI row (Accuracy, Brier, Margin error).
  - A calibration chart once there are 50 or more settled games: predicted
    probability bins vs actual home-win rate, with a diagonal reference line.
  - A recent-results list: matchup, predicted winner and probability, final
    score, ✓/✗.
- **Empty states.** No settled games yet means one friendly line saying when
  the first games tip off. No upcoming games means "next games: …" or the
  off-season note.
- **Data.** `db.upcoming_predictions()` gains `tipoff_utc`.
  `db.recent_settled_predictions(n)` and `db.calibration_bins()` are added,
  computed with pandas/numpy only. The dashboard must not import `ml.*`, since
  sklearn and scipy are dev-only (see `prediction_track_record`).

## Part 2 - Arcade: Build a team

### Player value model (`ml/player_impact.py`, offline)

Prototyped on the real warehouse (2026-10-14):
- **Features.** Per-36 rates relative to each season's league per-36 average:
  points, offensive rebounds, defensive rebounds, assists, steals, blocks,
  turnovers, FGA, FTA, 3PM, fouls. Being relative to the season's league is
  what makes all-time comparisons fair across eras.
- **Target.** The player's on-court plus-minus per 36 minus 0.7 × his team's
  net rating (a crude on/off), fit on player-team-seasons with 500+ minutes,
  1996-97 on (plus-minus exists from then). Ridge regression (alpha 5),
  weighted by minutes. Holdout (last 5 seasons) correlation is about 0.45.
- **Sanity check.** Top player-seasons come out as Curry 2015-16, Jokić,
  Jordan 1988-89, SGA, Wembanyama, Stockton; Rodman is about 1.2. A
  team-aggregate fit was tried first and rejected: it rated rebounding
  specialists (Rodman, Mitchell Robinson, Drummond) as the best players ever,
  because team rebounds are shared.
- **Coverage.** The fitted coefficients are applied to every player-season
  from 1985-86 on (complete box scores), so all-time mode includes the late
  80s.
- **Second stage: team calibration.** Regress real team net rating on
  Σ(minutes share × 5 × impact) per team-season to get scale `a` and offset
  `b`. A drafted team's base net rating is `b + a × Σ w·impact`. The fit is
  reported (R² and MAE), not assumed.
- **Usage overlap (heuristic, documented as such).** Usage proxy =
  (FGA + 0.44·FTA + TOV) per 36, relative to league. When the rotation's
  minutes-weighted usage exceeds the league-normal total, offensive value
  beyond it gets a penalty factor. This is not fitted, because real teams
  never exceed it by construction. It lives in one function and one constant,
  so it can be tuned.
- **Output table `player_impact`.** One row per player-season, 1985-86 on,
  with GP ≥ 40 and MPG ≥ 15. Columns: season, player_id, player, team (team
  path), gp, mpg, ppg, rpg, apg, impact, usage, cost. Written to the
  warehouse by a new `weekly_refresh.py` step after dbt, the same pattern
  `ml.predict` uses. Coefficients and calibration are saved in the table's
  sidecar metadata (a small `player_impact_meta` table).
- **Cost (Build mode).** 1-12 by impact within the eligible pool (all seasons
  together): 1 plus the number of the impact quantiles in
  `ml.player_impact.COST_QUANTILES` a season clears. Cost 1 is the bottom 15%
  (replacement level), 2-10 are evenly spaced in impact (about +0.5 a credit),
  11 is the top 0.5-0.1% and 12 the top 0.1%. (Revised 2026-10-15, tuned with
  the 36-credit budget: flat percentile pricing put the top 5.5% all at 10 and
  made "three 10s plus fillers" the best build.)

### Game simulation (`dashboard/lib/sim.py`, numpy only)

- **Minutes.** The 5 starters get 32 each and the 3 bench players 16 each
  (sums to 240). Rotation order is chosen by the user, or by impact for CPU
  teams.
- **Team net rating.** The calibrated formula plus the usage penalty.
- **One game.** Margin ~ Normal(net_home − net_away + 2.5 home edge, 12.7).
  12.7 is the residual SD this project measured (`ml/train.py`).
- **Season.** 82 games against the opponent set.
  - Build, single season: the opponents are that season's real 30 teams
    (their real net ratings). The schedule weights every team equally, and the
    real teams play each other too, so best-record odds compare against them.
  - Build, all-time: 29 real historical team-seasons drawn at random.
  - Draft: a 6-team league (the user plus 5 CPU teams), balanced round robin
    to 82 games, then playoffs (top 4, best of 7).
- **Projection.** 1,000 simulated seasons, vectorized. Shows the median
  record, the 10th-90th percentile win range, best-record odds and (Draft)
  title odds.
- **Variance.** Projections use a fixed seed derived from the roster, so the
  same team always shows the same projection. "Simulate a season" uses a fresh
  seed and shows one season's record, a win-loss game strip, and (Draft) the
  playoff bracket.

### UI (`dashboard/views/arcade.py`, new "Build a team" tab)

- **Pool selector.** A single season (any from 1985-86) or "All-time".
- **Build mode.** A searchable player picker. Each pick shows the player-season
  card with cost. Budget 36 credits for 8 players (was 40; retuned 2026-10-15). The user orders starters
  and bench, and the team rating card updates live.
- **Draft mode.** A snake draft, user plus 5 CPU teams, user pick slot
  random. The CPU takes the best available impact, adjusted for usage overlap
  with its roster, plus small noise so drafts differ. Picks show as a board.
- **Results.** Projected record card row, the range, odds, and the "Simulate
  a season" button.
- **Explainer.** How the rating works, era adjustment, and that it's a game,
  not a scouting tool.

## Testing

- `ml/player_impact`:
  - Relative-rate math.
  - The model is fit on a fixture and recovers known coefficients.
  - The rankings sanity check runs against the real warehouse (skip in CI).
  - The table schema.
- `sim.py`:
  - Deterministic with a fixed seed.
  - Higher net rating → more expected wins.
  - Win distribution mean ≈ 41 + 2.5 × net, against an average league.
  - Round robin totals 82 games per team.
  - The playoff bracket produces one champion.
  - Budget and roster validation.
- Draft AI: never picks a taken player, fills 8 slots, and is deterministic
  with a seed.
- Pages: AppTest render for Predictions (empty, upcoming-only, settled) and
  the Arcade build tab.

## Out of scope

Positions, injuries, eras as presets (later, per user feedback), trades
within the game, and saving or sharing teams.
