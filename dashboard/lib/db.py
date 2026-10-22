"""Read-only data access for the domains not yet moved into
dashboard/lib/data: teams, games, advanced metrics, finances and
predictions. Seasons, player stats and the Arcade's tables live in
dashboard/lib/data now; the rest follows, and this module goes away.
Queries are cached by Streamlit."""

from __future__ import annotations

import duckdb
import numpy as np
import pandas as pd
import streamlit as st

from core import paths, teams

from . import franchises

# Module constant for now: tests monkeypatch it.
DB_PATH = paths.warehouse_path()


def warehouse_exists() -> bool:
    return DB_PATH.exists()


@st.cache_data(ttl=600, show_spinner=False)
def q(sql: str, params: tuple = ()) -> pd.DataFrame:
    """Run a read-only query and return a DataFrame (cached on sql+params)."""
    with duckdb.connect(str(DB_PATH), read_only=True) as con:
        return con.execute(sql, list(params)).df()


# --- Teams / games -------------------------------------------------------------


def standings(season: str) -> pd.DataFrame:
    """Standings for one season: record, scoring splits, conference and the
    last-five form string, ordered for playoff seeding.

    Reads dbt's mart_team_standings, which carries a real (if simplified -
    see the model's own comment) head-to-head tiebreak ahead of point
    differential, and its conference comes from the team_codes seed - the
    same file core.teams reads for the fallback below. Falls
    back to computing directly from the staging views - the mart's exact
    logic before it existed - when the mart isn't in the warehouse yet (an
    older published copy, or a local build where dbt hasn't run). This
    function has no marts_available() guard of its own callers, and
    Overview and Teams call it unconditionally, so it must degrade itself
    rather than let a catalog error take either page down.
    """
    try:
        df = q(
            """
            select
                team_id,
                team_abbreviation as team,
                team_name,
                games_played       as gp,
                wins                as w,
                losses              as l,
                win_pct             as pct,
                points_per_game     as ppg,
                opp_points_per_game as opp_ppg,
                net_points          as net,
                conference          as conf,
                form
            from main_marts.mart_team_standings
            where season = ?
            order by win_pct desc, head_to_head desc, net_points desc, team_abbreviation asc
            """,
            (season,),
        )
        return df
    except duckdb.CatalogException:
        pass

    df = q(
        """
        with paired as (
            select t.*, o.points as opp_points
            from main_staging.stg_team_game_logs t
            join main_staging.stg_team_game_logs o
              on t.game_id = o.game_id and t.team_id <> o.team_id
            where t.season = ?
        )
        select
            team_id,
            any_value(team_abbreviation)               as team,
            any_value(team_name)                       as team_name,
            count(*)                                   as gp,
            cast(sum(case when is_win then 1 else 0 end) as int) as w,
            cast(sum(case when is_win then 0 else 1 end) as int) as l,
            round(avg(case when is_win then 1.0 else 0.0 end), 3) as pct,
            round(avg(points), 1)                      as ppg,
            round(avg(opp_points), 1)                  as opp_ppg,
            round(avg(points - opp_points), 1)         as net,
            substr(string_agg(win_loss, '' order by game_date desc), 1, 5) as form
        from paired
        group by team_id
        order by pct desc, net desc
        """,
        (season,),
    )
    df["conf"] = [teams.conference(team, season) for team in df["team"]]
    return df


def team_game_log(team_id: int, season: str) -> pd.DataFrame:
    return q(
        """
        select t.*, o.points as opp_points, o.team_abbreviation as opponent
        from main_staging.stg_team_game_logs t
        join main_staging.stg_team_game_logs o
          on t.game_id = o.game_id and t.team_id <> o.team_id
        where t.team_id = ? and t.season = ?
        order by t.game_date
        """,
        (team_id, season),
    )


def games_list(season: str) -> pd.DataFrame:
    # A handful of neutral-site games (NBA Cup, international) list both
    # teams as away ('@'), so rank rows per game instead of filtering on
    # 'vs.': the true home team ranks first when one exists, otherwise the
    # pick is deterministic and the game still appears exactly once.
    return q(
        """
        with ranked as (
            select *, row_number() over (
                partition by game_id
                order by (matchup like '%vs.%') desc, team_abbreviation
            ) as rn
            from main_staging.stg_team_game_logs
            where season = ?
        )
        select
            h.game_id,
            h.game_date,
            a.team_abbreviation as away, a.points as away_pts,
            h.team_abbreviation as home, h.points as home_pts
        from ranked h
        join ranked a on h.game_id = a.game_id and a.rn = 2
        where h.rn = 1
        order by h.game_date desc, h.game_id
        """,
        (season,),
    )


def pbp_game_ids() -> set[str]:
    return set(q("select distinct game_id from main_staging.stg_play_by_play")["game_id"])


def game_pbp(game_id: str) -> pd.DataFrame:
    return q(
        """
        select * from main_staging.stg_play_by_play
        where game_id = ? order by action_number
        """,
        (game_id,),
    )


def game_box_score(game_id: str) -> pd.DataFrame:
    return q(
        """
        select team_abbreviation as team, team_id, player_name as player,
               minutes_played as min, points as pts, total_rebounds as reb,
               assists as ast, steals as stl, blocks as blk, turnovers as tov,
               field_goals_made as fgm, field_goals_attempted as fga,
               three_pointers_made as tpm, three_pointers_attempted as tpa,
               free_throws_made as ftm, free_throws_attempted as fta,
               plus_minus
        from main_staging.stg_player_game_logs
        where game_id = ?
        order by minutes_played desc, points desc
        """,
        (game_id,),
    )


# --- Advanced metrics ----------------------------------------------------------

# Label -> (column, higher_is_better, help text). Drives the Advanced page so
# the metric list lives in one place instead of being restated per widget.
ADVANCED_METRICS: dict[str, tuple[str, bool, str]] = {
    "TS%": (
        "true_shooting_pct",
        True,
        "True shooting: points per shooting possession, counting 3s and free throws",
    ),
    "eFG%": (
        "effective_fg_pct",
        True,
        "Effective FG%: field goal percentage with 3-pointers weighted 1.5x",
    ),
    "USG%": (
        "usage_pct",
        True,
        "Usage: share of team possessions a player ends while on the floor",
    ),
    "AST%": (
        "assist_pct",
        True,
        "Assist rate: share of teammate field goals a player assisted while on the floor",
    ),
    "REB%": (
        "rebound_pct",
        True,
        "Rebound rate: share of available rebounds a player grabbed while on the floor",
    ),
    "TOV%": (
        "turnover_pct",
        False,
        "Turnover rate: turnovers per 100 individual plays (lower is better)",
    ),
    "STL%": ("steal_pct", True, "Steals per opponent possession while on the floor"),
    "BLK%": ("block_pct", True, "Share of opponent 2-point attempts blocked"),
    "PTS/36": ("points_per_36", True, "Points per 36 minutes, pace of a starter's night"),
    "PTS/100": ("points_per_100", True, "Points per 100 team possessions on the floor"),
    "Game score": (
        "game_score",
        True,
        "Hollinger game score: one-number box score summary, ~10 is average",
    ),
    "Net rating": (
        "net_rating",
        True,
        "Team point differential per 100 possessions with the player on the floor "
        "(official NBA figure, 1996-97 on)",
    ),
    "PIE": (
        "player_impact_estimate",
        True,
        "Player impact estimate: share of the game's total production "
        "(official NBA figure, 1996-97 on)",
    ),
}


@st.cache_data(ttl=600, show_spinner=False)
def marts_available() -> bool:
    """Whether dbt's marts are in the warehouse.

    The advanced views query `main_marts`, and a warehouse published before
    those models existed (or one where dbt has not been run) raises a
    catalog error that propagates out of the page and takes the whole app
    down with it. Callers check this first and show a message instead.
    """
    try:
        with duckdb.connect(str(DB_PATH), read_only=True) as con:
            con.execute("select 1 from main_marts.mart_player_season limit 1")
        return True
    except (duckdb.Error, OSError):
        return False


@st.cache_data(ttl=600, show_spinner=False)
def team_finances_available() -> bool:
    """Whether mart_team_finances exists in the warehouse - same guard pattern
    as marts_available()/predictions_available(), for a warehouse published
    before this feature shipped.

    Also probes main.salary_cap_history: finances.py's render() calls
    salary_cap_history() unconditionally right after this check passes, so
    this guard has to cover both objects the page actually reads, not just
    the mart, or a warehouse missing just the seed would still crash past
    this check."""
    try:
        with duckdb.connect(str(DB_PATH), read_only=True) as con:
            con.execute("select 1 from main_marts.mart_team_finances limit 1")
            con.execute("select 1 from main.salary_cap_history limit 1")
        return True
    except (duckdb.Error, OSError):
        return False


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


def salary_cap_history() -> pd.DataFrame:
    """League-wide cap/tax/apron thresholds by season, independent of any team."""
    return q(
        "select season, salary_cap, luxury_tax, first_apron, second_apron "
        "from main.salary_cap_history order by season"
    )


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
        select l.game_id, l.game_date, s.tipoff_utc, l.win_probability,
               l.predicted_margin,
               s.home_team_abbreviation, s.away_team_abbreviation
        from latest l
        join main_staging.stg_schedule s on s.game_id = l.game_id
        where l.recency = 1 and s.game_status = 1
        order by l.game_date, l.game_id
        limit ?
        """,
        (limit,),
    )


# Same join ml.evaluate.settled_predictions() uses: only the earliest
# prediction per game (grading a later re-run would let a model be scored
# on a prediction made after the result was known), joined to the actual
# result. Duplicated here rather than imported - see prediction_track_record's
# docstring for why.
_SETTLED_PREDICTIONS_SQL = """
    with first_prediction as (
        select *, row_number() over (
            partition by game_id order by predicted_at
        ) as attempt
        from predictions
    )
    select p.game_id, p.game_date, p.predicted_margin, p.win_probability,
           f.margin, f.home_won, f.home_points, f.away_points
    from first_prediction p
    join main_marts.fct_team_game f on f.game_id = p.game_id
    where p.attempt = 1
      -- Same no-contest exclusion the rest of the pipeline applies: a
      -- cancelled game recorded as a 0-0 final is not a result, and
      -- grading a prediction for it would show a miss on the public
      -- track record for a game that never happened.
      and not (f.home_points = 0 and f.away_points = 0)
"""


def prediction_track_record() -> dict:
    """The model's public accuracy record: accuracy, Brier score, margin
    MAE and n, computed directly here with plain pandas/numpy.

    Deliberately does NOT import ml.evaluate or ml.train, even though
    ml.evaluate.track_record() computes the identical numbers. ml.train
    imports scipy and sklearn at module level, and those are dev-only
    dependencies (see requirements-dev.txt) - Streamlit Community Cloud's
    build only installs requirements.txt, which does not have them. This
    module previously imported ml.evaluate here, which meant the app
    crashed with ModuleNotFoundError the moment a real predictions table
    existed in a warehouse published to the cloud deploy - the exact
    "must degrade gracefully" case this function exists for. The three
    lines of metric math below are cheap enough to duplicate rather than
    drag a training-dependency import into a dashboard image for.

    Returns {"n": 0} when nothing has settled yet, including when the
    predictions table (or a mart it joins against) does not exist - the
    page must degrade the same gentle way predictions_available() does
    rather than let a catalog error escape. Only catches CatalogException
    (the real "table doesn't exist" condition) - a BinderException from
    schema drift, a ConversionException, or an IOException from a
    truncated download must still surface as a real error rather than
    silently reading as "no predictions yet".
    """
    if not predictions_available():
        return {"n": 0}
    try:
        settled = q(_SETTLED_PREDICTIONS_SQL)
    except duckdb.CatalogException:
        return {"n": 0}
    if settled.empty:
        return {"n": 0}

    home_won = settled["home_won"].astype(bool).to_numpy()
    win_probability = settled["win_probability"].astype(float).to_numpy()
    predicted_margin = settled["predicted_margin"].astype(float).to_numpy()
    margin = settled["margin"].astype(float).to_numpy()

    # A coin flip (exactly 0.5) counts as a home pick, the same rule the
    # page's cards and recent-results grid use.
    return {
        "accuracy": float(((win_probability >= 0.5) == home_won).mean()),
        "brier": float(np.mean((win_probability - home_won.astype(float)) ** 2)),
        "margin_mae": float(np.mean(np.abs(predicted_margin - margin))),
        "n": len(settled),
    }


def recent_settled_predictions(n: int = 20) -> pd.DataFrame:
    """The latest graded predictions, newest first: who played, the final
    score, what the model said and whether it called the winner. Uses the same
    earliest-prediction-per-game join as the track record. Empty when nothing
    has settled (or the warehouse predates the tables it needs)."""
    cols = [
        "game_date",
        "home",
        "away",
        "home_pts",
        "away_pts",
        "win_probability",
        "predicted_margin",
        "correct",
    ]
    if not predictions_available():
        return pd.DataFrame(columns=cols)
    try:
        df = q(
            f"""
            select s.game_date, s.home_team_abbreviation as home,
                   s.away_team_abbreviation as away,
                   t.home_points as home_pts, t.away_points as away_pts,
                   t.win_probability, t.predicted_margin,
                   (t.win_probability >= 0.5) = t.home_won as correct
            from ({_SETTLED_PREDICTIONS_SQL}) t
            join main_staging.stg_schedule s on s.game_id = t.game_id
            order by s.game_date desc, t.game_id
            limit ?
            """,
            (n,),
        )
    except duckdb.CatalogException:
        return pd.DataFrame(columns=cols)
    df["correct"] = df["correct"].astype(bool)
    return df


def calibration_bins(bins: int = 10) -> pd.DataFrame:
    """Does "70%" mean 70%? Settled games bucketed by predicted home-win
    probability into equal-width bins on [0, 1]; per bin the mean predicted
    probability, the share the home team actually won, and the game count.
    Empty bins are dropped, and nothing is returned below 50 settled games
    because a bin of three games is noise, not calibration."""
    cols = ["bin_mid", "predicted_mean", "actual_rate", "n"]
    if not predictions_available():
        return pd.DataFrame(columns=cols)
    try:
        settled = q(_SETTLED_PREDICTIONS_SQL)
    except duckdb.CatalogException:
        return pd.DataFrame(columns=cols)
    if len(settled) < 50:
        return pd.DataFrame(columns=cols)

    prob = settled["win_probability"].astype(float).to_numpy()
    won = settled["home_won"].astype(bool).astype(float).to_numpy()
    # p == 1.0 belongs in the top bin, not a phantom eleventh.
    idx = np.minimum((prob * bins).astype(int), bins - 1)
    frame = pd.DataFrame({"bin": idx, "p": prob, "won": won})
    out = (
        frame.groupby("bin")
        .agg(predicted_mean=("p", "mean"), actual_rate=("won", "mean"), n=("p", "size"))
        .reset_index()
    )
    out["bin_mid"] = (out["bin"] + 0.5) / bins
    return out[cols]


def player_advanced(season: str, min_minutes: int = 0) -> pd.DataFrame:
    """Advanced metrics for one season. Rate stats are meaningless on tiny
    samples (one made three is a 150% TS%), so callers pass a minutes floor."""
    return q(
        """
        select * from main_marts.mart_player_season
        where season = ? and minutes >= ?
        """,
        (season, min_minutes),
    )


def player_advanced_career(player_id: int) -> pd.DataFrame:
    """Every season of advanced metrics for one player, oldest first."""
    return q(
        """
        select * from main_marts.mart_player_season
        where player_id = ? order by season
        """,
        (player_id,),
    )


def team_advanced(season: str) -> pd.DataFrame:
    return q(
        """
        select * from main_marts.mart_team_season
        where season = ? order by net_rating desc nulls last
        """,
        (season,),
    )


def advanced_seasons() -> list[str]:
    """Seasons where the box score is complete enough for advanced metrics
    (1985-86 on). Earlier seasons are missing whole columns at the source."""
    return q(
        """
        select distinct season from main_marts.mart_player_season
        where box_score_complete order by 1 desc
        """
    )["season"].tolist()
