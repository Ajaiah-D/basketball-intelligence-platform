"""Numbers shared across the pipeline, the models and the dashboard, defined once."""

# --- Season boundaries ----------------------------------------------------------

# The NBA publishes its official advanced stats (ratings, usage, PIE) from
# this season on, and the game logs carry plus-minus from the same season:
# both come from its play-by-play era. Earlier seasons return no rows.
ADVANCED_STATS_FIRST_SEASON = "1996-97"

# Box scores are complete from this season on. Before it whole columns are
# missing (1979-80 has no field goal attempts, rebounds or assists), so the
# Arcade's impact pool and its all-time opponents start here. dbt finds the
# same boundary from the data itself (box_score_complete), not from this.
COMPLETE_BOX_SCORE_FIRST_SEASON = "1985-86"

# current_season() rolls over to the new season on the 1st of this month,
# about three weeks before opening night.
SEASON_START_MONTH = 10

# --- Elo ------------------------------------------------------------------------

# compute_elo and current_ratings both default to these, so a prediction is
# served with ratings computed the way the model's training ratings were.
ELO_K = 20.0
ELO_HOME_ADVANTAGE = 100.0  # Elo points, not game points
# Share of a rating's distance from 1500 kept over the summer, for roster
# turnover. 0.75 is the common public choice; a tunable, not a law.
ELO_SEASON_CARRY = 0.75

# --- Game margins ---------------------------------------------------------------
#
# Two spreads, on purpose: they answer different questions and are measured
# differently, so they are not merged.
#
# PREDICTION_MARGIN_SD turns the prediction model's forecast margin into a
# published win probability. Its spread has to cover the model's own error
# about how good the teams are as well as the game's noise, and the right
# value is the one that calibrates the probabilities on games the model has
# not seen. Measured 2026-10-22 on the walk-forward backtest from 2005-06
# (25,268 games, Ridge on the served Elo columns): residual SD 12.84,
# log-loss-optimal 12.03, Brier-optimal 12.11. 13.5 costs 0.0008 log loss
# against that optimum (0.6168 vs 0.6160); accuracy and margin error do not
# depend on it. Changing it changes every published probability, so that is
# its own decision, with a new model_version, not a side effect of a refactor.
PREDICTION_MARGIN_SD = 13.5

# GAME_MARGIN_SD is the Arcade simulator's game-to-game noise around a known
# rating gap: margin ~ Normal(net_a - net_b + HOME_EDGE_POINTS, GAME_MARGIN_SD).
# Both teams' strengths are given, so there is no model error to cover.
# 12.7 is kept from the simulator's original measurement. Re-measured
# 2026-10-22 as the SD of real margins around each game's full-season net
# rating gap plus the home edge: 12.29 from 2005-06, 12.99 from 2015-16 and
# 11.83 from 1985-86 (the Arcade's whole range), so 12.7 sits within the
# measured range.
GAME_MARGIN_SD = 12.7

# Points the home side adds to the simulator's expected margin. Real margins
# around the net rating gap put it at 2.56 from 2005-06 and 2.15 from 2015-16.
HOME_EDGE_POINTS = 2.5

# --- Arcade economy -------------------------------------------------------------

# A Build-mode roster's credits. Tuned together with COST_QUANTILES.
ARCADE_BUDGET = 36

# Build-mode prices (1..MAX_COST). A player-season costs 1 plus the number of
# these impact quantiles (over the whole eligible pool, every season
# together) it clears. Tuned on the 2026-10-15 warehouse against
# ARCADE_BUDGET:
#   - cost 1 is replacement level, the bottom 15% (impact below about -0.9),
#     so eight of them make a bad team (about -11), not a .500 one;
#   - costs 2..10 are evenly spaced in impact, about +0.5 a credit, so no
#     price band is a bargain next to its neighbours;
#   - 11 is the top 0.5% down to 0.1% and 12 the top 0.1% (+4.3 and up): an
#     all-time great season costs about a third of the budget, so three of
#     them plus fillers no longer fits.
# With those, the best 36-credit build in the all-time, 2024-25 and 2015-16
# pools rates about +12 to +14 (not pinned at the +16 ceiling), eight
# cost-4 players about +4 to +5, and eight cost-1 players below -10.
COST_QUANTILES = [0.15, 0.32, 0.53, 0.72, 0.85, 0.925, 0.965, 0.985, 0.991, 0.995, 0.999]
MAX_COST = len(COST_QUANTILES) + 1

# Minutes shares are scaled to sum to this, both in the impact model's team
# calibration and in the simulator's rotation; and since each player's usage
# is relative to the league's per-player rate, a league-average lineup
# carries this much usage.
PLAYERS_ON_FLOOR = 5

# --- Ingestion ------------------------------------------------------------------

# The most play-by-play games one ingest run will fetch (one API call each, at
# least 1.5s apart). A busy NBA week has about 100 games, so 120 lets a run
# catch up a whole week with room for some retries, and the first run of a
# season backfills over a few weeks instead of one multi-hour fetch.
PBP_MAX_NEW_GAMES_PER_RUN = 120

# --- Health check ---------------------------------------------------------------

# The stretch with no regular-season games, when stale data and an idle
# refresh job are the correct state. It starts after OFFSEASON_AFTER (month,
# day) and ends LATEST_GAME_MAX_AGE_DAYS after the next season's opening
# night, read from the warehouse's schedule (the weekly refresh can take
# that long to load the first games). When the schedule doesn't have that
# season yet, OFFSEASON_FALLBACK_END stands in for opening night: every
# opening night since 2006-07 has fallen between October 16 and 31, apart
# from the 2011 lockout and the 2020 pandemic seasons, which opened in
# December.
OFFSEASON_AFTER = (4, 20)
OFFSEASON_FALLBACK_END = (SEASON_START_MONTH, 31)
WAREHOUSE_MAX_AGE_DAYS = 14  # the warehouse file: a weekly build plus a week of slack
LATEST_GAME_MAX_AGE_DAYS = 7  # in season games land every 1-3 days
LAST_RUN_MAX_AGE_DAYS = 10  # the weekly refresh plus a few days
