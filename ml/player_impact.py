"""Score every player-season since 1985-86 for the Arcade team builder.

The game needs one number per player-season that says roughly how many
points per 36 minutes a player is worth against an average player, and it
needs that number to be comparable across eras. This module produces it.

How it works:

1. Box-score rates are taken per 36 minutes and made relative to that
   season's league per-36 rate. That is what lets a 1988-89 season sit next
   to a 2015-16 one: a player is measured against the league he played in.
2. The target is the player's on-court plus-minus per 36 minus 0.7 x his
   team's net rating - a crude on/off. Plus-minus only exists from 1996-97,
   so the fit uses player-team-seasons from then on with 500+ minutes, as a
   Ridge(alpha=5) weighted by minutes.
3. The fitted coefficients are then applied to every player-season from
   1985-86 on (complete box scores start there), using his whole-season
   totals across teams.
4. A second stage calibrates impact to real team net rating, so the
   simulator can turn a drafted roster into a team rating with a fit whose
   R^2 and MAE are reported rather than assumed.

A team-aggregate regression (team net rating on summed player rates) was
tried first and rejected: it rated rebounding specialists - Rodman,
Drummond, Mitchell Robinson - as the best players ever, because a team's
rebounds are shared and the regression handed all the credit to whoever
collected them. Fitting per-player on/off does not have that problem.

This is a game rating, not a scouting tool. The holdout correlation is
about 0.45: it orders players sensibly, it does not measure them precisely.

Run:
    python -m ml.player_impact
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

STATS = ["pts", "orb", "drb", "ast", "stl", "blk", "tov", "fga", "fta", "tpm", "pf"]
FEATURES = [f"{s}_r" for s in STATS]

FIRST_SEASON = "1985-86"      # complete box scores start here
FIRST_PM_SEASON = "1996-97"   # plus-minus starts here
MIN_TRAIN_MINUTES = 500
TEAM_NET_WEIGHT = 0.7         # how much of the team's net rating is "not him"
RIDGE_ALPHA = 5.0
HOLDOUT_SEASONS = 5
MIN_GP = 40
MIN_MPG = 15.0
USAGE_LEAGUE_TOTAL = 5.0      # five average players on the floor

# Build-mode prices (1..12). A player-season costs 1 plus the number of these
# impact quantiles (over the whole eligible pool, every season together) it
# clears. Tuned on the 2026-10-15 warehouse against draft.BUDGET (36):
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
COST_QUANTILES = [0.15, 0.32, 0.53, 0.72, 0.85, 0.925, 0.965, 0.985, 0.991,
                  0.995, 0.999]

# One row per player per team per season. plus-minus is summed only when
# every game has it: sum() skips nulls, so a partly-missing season would
# otherwise come back as a confident but wrong total.
TEAM_SEASON_SQL = """
select
    season,
    team_abbreviation,
    player_id,
    arg_max(player_name, game_date)  as player_name,
    min(game_date)                   as first_game,
    count(*)                         as gp,
    sum(minutes_played)              as mins,
    sum(points)                      as pts,
    sum(offensive_rebounds)          as orb,
    sum(defensive_rebounds)          as drb,
    sum(total_rebounds)              as trb,
    sum(assists)                     as ast,
    sum(steals)                      as stl,
    sum(blocks)                      as blk,
    sum(turnovers)                   as tov,
    sum(field_goals_attempted)       as fga,
    sum(free_throws_attempted)       as fta,
    sum(three_pointers_made)         as tpm,
    sum(personal_fouls)              as pf,
    case when count(plus_minus) = count(*) then sum(plus_minus) end as pm
from main_staging.stg_player_game_logs
where season >= ?
group by season, team_abbreviation, player_id
"""

NET_RATING_SQL = """
select season, team_abbreviation, net_rating
from main_marts.mart_team_season
where net_rating is not null and season >= ?
"""

IMPACT_COLUMNS = ["season", "player_id", "player", "team", "gp", "mpg", "ppg",
                  "rpg", "apg", "impact", "usage", "cost"]


def relative_rates(df: pd.DataFrame) -> pd.DataFrame:
    """Add `<stat>_r`: the row's per-36 rate minus its season's league per-36.

    The league rate is total stat over total minutes for the season, x 36,
    across every row passed in - so pass the whole league, not a filtered
    subset. A row with zero minutes gets NaN rather than an infinite rate.
    """
    out = df.copy()
    mins = out["mins"].astype(float)
    per36 = 36.0 / mins.where(mins > 0)
    totals = out.groupby("season")[STATS + ["mins"]].transform("sum").astype(float)
    for s in STATS:
        league = totals[s] / totals["mins"] * 36.0
        out[f"{s}_r"] = out[s].astype(float) * per36 - league
    return out


def costs_from_impact(impact: pd.Series) -> pd.Series:
    """Build-mode cost (1..12) of each player-season: 1 + how many of the
    COST_QUANTILES thresholds of `impact` it reaches. Pass the whole pool;
    the thresholds are its quantiles. Keeps the index."""
    values = impact.to_numpy(float)
    thresholds = np.quantile(values, COST_QUANTILES)
    cost = 1 + np.searchsorted(thresholds, values, side="right")
    return pd.Series(cost.astype(int), index=impact.index)


def fit_impact(train_df: pd.DataFrame) -> tuple[np.ndarray, float]:
    """Ridge(alpha=5) of `rel_pm` on the `_r` features, weighted by minutes.
    Coefficients come back in STATS order."""
    model = Ridge(alpha=RIDGE_ALPHA).fit(
        train_df[FEATURES].to_numpy(float),
        train_df["rel_pm"].to_numpy(float),
        sample_weight=train_df["mins"].to_numpy(float),
    )
    return np.asarray(model.coef_, dtype=float), float(model.intercept_)


def _predict(df: pd.DataFrame, coef: np.ndarray, intercept: float) -> np.ndarray:
    return df[FEATURES].to_numpy(float) @ coef + intercept


def _training_rows(team_rows: pd.DataFrame, net: pd.DataFrame) -> pd.DataFrame:
    train = team_rows.merge(net, on=["season", "team_abbreviation"], how="inner")
    train = train[(train["season"] >= FIRST_PM_SEASON)
                  & train["pm"].notna()
                  & (train["mins"] >= MIN_TRAIN_MINUTES)].copy()
    train["rel_pm"] = (train["pm"].astype(float) / train["mins"] * 36.0
                       - TEAM_NET_WEIGHT * train["net_rating"])
    return train


def _holdout_corr(train: pd.DataFrame) -> float:
    """Fit on all but the last HOLDOUT_SEASONS seasons, score on those.

    NaN when the warehouse is too short to have both halves (CI's fixture
    warehouse, a fresh partial build) - a missing score, not a crash.
    """
    seasons = sorted(train["season"].unique())
    held = train["season"].isin(seasons[-HOLDOUT_SEASONS:])
    if (~held).sum() == 0 or held.sum() < 2:
        return float("nan")
    coef, intercept = fit_impact(train[~held])
    pred = _predict(train[held], coef, intercept)
    return float(np.corrcoef(pred, train.loc[held, "rel_pm"].to_numpy(float))[0, 1])


def _player_seasons(team_rows: pd.DataFrame) -> pd.DataFrame:
    """Collapse player-team-seasons into whole player-seasons, with the
    team path in order of each stint's first game."""
    ordered = team_rows.sort_values(["season", "player_id", "first_game"])
    sums = ordered.groupby(["season", "player_id"], as_index=False)[
        STATS + ["trb", "mins", "gp"]].sum()
    meta = ordered.groupby(["season", "player_id"], as_index=False).agg(
        team=("team_abbreviation", lambda t: " → ".join(t)),
        player=("player_name", "last"),
    )
    return sums.merge(meta, on=["season", "player_id"])


def _calibrate(team_rows: pd.DataFrame, seasons: pd.DataFrame,
               net: pd.DataFrame) -> dict:
    """Fit team net rating = offset + scale x S, where S is the team's
    minutes-share-weighted sum of its players' season impact (x5 so the
    shares sum to five players on the floor)."""
    rows = team_rows[["season", "team_abbreviation", "player_id", "mins"]].merge(
        seasons[["season", "player_id", "impact"]], on=["season", "player_id"])
    team_total = rows.groupby(["season", "team_abbreviation"])["mins"].transform("sum")
    rows["contrib"] = (rows["mins"] / team_total * 5.0 * rows["impact"]).fillna(0.0)
    s = rows.groupby(["season", "team_abbreviation"], as_index=False)["contrib"].sum()
    s = s.merge(net, on=["season", "team_abbreviation"], how="inner")
    x = s["contrib"].to_numpy(float)
    y = s["net_rating"].to_numpy(float)
    scale, offset = np.polyfit(x, y, 1)
    fitted = offset + scale * x
    r2 = 1.0 - np.sum((y - fitted) ** 2) / np.sum((y - y.mean()) ** 2)
    return {"team_scale": float(scale), "team_offset": float(offset),
            "team_r2": float(r2), "team_mae": float(np.mean(np.abs(y - fitted)))}


def build(con) -> tuple[pd.DataFrame, dict]:
    """Fit the model and score every eligible player-season. Read-only."""
    team_rows = con.execute(TEAM_SEASON_SQL, [FIRST_SEASON]).df()
    net = con.execute(NET_RATING_SQL, [FIRST_SEASON]).df()

    # Training rows are player-team-seasons; the league rates come from all
    # of them before any filter, so "relative to the league" means the whole
    # league, not the 500-minute subset.
    train = _training_rows(relative_rates(team_rows), net)
    holdout_corr = _holdout_corr(train)
    coef, intercept = fit_impact(train)

    seasons = relative_rates(_player_seasons(team_rows))
    seasons["impact"] = _predict(seasons, coef, intercept)

    calibration = _calibrate(team_rows, seasons, net)

    usage_num = seasons["fga"] + 0.44 * seasons["fta"] + seasons["tov"]
    mins = seasons["mins"].astype(float)
    usage_raw = usage_num / mins.where(mins > 0) * 36.0
    league = (usage_num.groupby(seasons["season"]).transform("sum")
              / mins.groupby(seasons["season"]).transform("sum") * 36.0)
    seasons["usage"] = usage_raw / league

    seasons["mpg"] = mins / seasons["gp"]
    seasons["ppg"] = seasons["pts"] / seasons["gp"]
    seasons["rpg"] = seasons["trb"] / seasons["gp"]
    seasons["apg"] = seasons["ast"] / seasons["gp"]

    pool = seasons[(seasons["gp"] >= MIN_GP) & (seasons["mpg"] >= MIN_MPG)].copy()
    pool["cost"] = costs_from_impact(pool["impact"])

    impact_df = (pool[IMPACT_COLUMNS]
                 .sort_values(["season", "impact"], ascending=[True, False])
                 .reset_index(drop=True))
    meta = {
        "fitted_at": datetime.now(timezone.utc).replace(tzinfo=None),
        "n_train": int(len(train)),
        "holdout_corr": holdout_corr,
        **calibration,
        "usage_league_total": USAGE_LEAGUE_TOTAL,
        "coef_json": json.dumps({"intercept": intercept,
                                 **{s: float(c) for s, c in zip(STATS, coef)}}),
    }
    return impact_df, meta


def write(con, impact_df: pd.DataFrame, meta: dict) -> None:
    """Replace main.player_impact and main.player_impact_meta."""
    meta_df = pd.DataFrame([meta])
    con.register("_player_impact_src", impact_df[IMPACT_COLUMNS])
    con.register("_player_impact_meta_src", meta_df)
    try:
        con.execute("begin")
        con.execute("""
            create or replace table main.player_impact as
            select cast(season as varchar)    as season,
                   cast(player_id as bigint)  as player_id,
                   cast(player as varchar)    as player,
                   cast(team as varchar)      as team,
                   cast(gp as integer)        as gp,
                   cast(mpg as double)        as mpg,
                   cast(ppg as double)        as ppg,
                   cast(rpg as double)        as rpg,
                   cast(apg as double)        as apg,
                   cast(impact as double)     as impact,
                   cast(usage as double)      as usage,
                   cast(cost as integer)      as cost
            from _player_impact_src
        """)
        con.execute("""
            create or replace table main.player_impact_meta as
            select cast(fitted_at as timestamp)         as fitted_at,
                   cast(n_train as integer)             as n_train,
                   cast(holdout_corr as double)         as holdout_corr,
                   cast(team_scale as double)           as team_scale,
                   cast(team_offset as double)          as team_offset,
                   cast(team_r2 as double)              as team_r2,
                   cast(team_mae as double)             as team_mae,
                   cast(usage_league_total as double)   as usage_league_total,
                   cast(coef_json as varchar)           as coef_json
            from _player_impact_meta_src
        """)
        con.execute("commit")
    except Exception:
        con.execute("rollback")
        raise
    finally:
        con.unregister("_player_impact_src")
        con.unregister("_player_impact_meta_src")


def main() -> None:
    import duckdb

    db_path = Path(__file__).resolve().parent.parent / "warehouse" / "basketball.duckdb"
    con = duckdb.connect(str(db_path))
    try:
        impact_df, meta = build(con)
        write(con, impact_df, meta)
    finally:
        con.close()
    print(f"Wrote {len(impact_df)} player-seasons to player_impact.")
    for key, value in meta.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
