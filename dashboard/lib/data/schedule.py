"""The season schedule for the Schedule page: every regular-season game
with its result, the model's latest prediction and the top scorer; how
many games each day of a month has; and one team's season with its
running record.

Reads only objects every published warehouse has: stg_schedule (the
published schedule, played and unplayed games), fct_team_game (results),
stg_player_game_logs (top scorers) and, when present, the predictions
table. tipoff_utc is returned as stg_schedule has it, a UTC time without a
zone; showing it in Eastern time is the page's job.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from . import predictions
from .core import q

_TEAM_COLUMNS = ["opponent", "is_home", "result", "record"]


def schedule(season: str) -> pd.DataFrame:
    """One row per regular-season game of `season`, in tip-off order:
    game_id, game_date, tipoff_utc, home, away, home_id, away_id,
    home_points, away_points, is_final, win_probability (the home team's),
    predicted_margin, top_scorer and top_points.

    is_final is whether fct_team_game has the result; the points and top
    scorer are null until then. A cancelled game the source records as a
    0-0 final is not one. The prediction is the latest for the game
    (predictions.LATEST_PREDICTIONS_SQL), null when there is none.
    """
    games = q(
        """
        -- The game's highest scorer; a tie goes to the name that sorts first.
        with top_scorers as (
            select game_id, player_name as top_scorer, points as top_points
            from (
                select
                    game_id,
                    player_name,
                    points,
                    row_number() over (
                        partition by game_id order by points desc, player_name
                    ) as place
                from main_staging.stg_player_game_logs
                where season = ? and points is not null
            )
            where place = 1
        )

        select
            s.game_id,
            s.game_date,
            s.tipoff_utc,
            s.home_team_abbreviation as home,
            s.away_team_abbreviation as away,
            s.home_team_id           as home_id,
            s.away_team_id           as away_id,
            -- fct_team_game picks its own home side for a neutral-site
            -- game, which can be the schedule's away team.
            case when f.home_team_id = s.home_team_id
                 then f.home_points else f.away_points end as home_points,
            case when f.home_team_id = s.home_team_id
                 then f.away_points else f.home_points end as away_points,
            f.game_id is not null    as is_final,
            t.top_scorer,
            t.top_points
        from main_staging.stg_schedule s
        left join main_marts.fct_team_game f
               on f.game_id = s.game_id
              and not (f.home_points = 0 and f.away_points = 0)
        left join top_scorers t
               on t.game_id = s.game_id
              and f.game_id is not null
        where s.season = ? and s.is_regular_season
        order by s.tipoff_utc, s.game_id
        """,
        (season, season),
    )
    latest = predictions.latest_predictions()
    games = games.merge(latest, on="game_id", how="left")
    return games[
        [
            "game_id",
            "game_date",
            "tipoff_utc",
            "home",
            "away",
            "home_id",
            "away_id",
            "home_points",
            "away_points",
            "is_final",
            "win_probability",
            "predicted_margin",
            "top_scorer",
            "top_points",
        ]
    ]


def month_counts(season: str, year: int, month: int) -> dict[date, int]:
    """{day: regular-season games} for each day of the month that has any;
    a day without games is absent, and a month without any is {}."""
    df = q(
        """
        select game_date, count(*) as games
        from main_staging.stg_schedule
        where season = ? and is_regular_season
          and year(game_date) = ? and month(game_date) = ?
        group by game_date
        order by game_date
        """,
        (season, int(year), int(month)),
    )
    return {
        day.date(): int(n)
        for day, n in zip(pd.to_datetime(df["game_date"]), df["games"], strict=True)
    }


def team_schedule(season: str, team: str) -> pd.DataFrame:
    """The schedule() rows for `team`'s games, plus opponent, is_home,
    result ("W 112-105", the team's score first; "" before the game) and
    record, the team's wins-losses after each finished game ("" before)."""
    games = schedule(season)
    games = games[(games["home"] == team) | (games["away"] == team)].reset_index(drop=True)
    is_home = games["home"] == team
    games["opponent"] = games["away"].where(is_home, games["home"])
    games["is_home"] = is_home
    points = games["home_points"].where(is_home, games["away_points"])
    allowed = games["away_points"].where(is_home, games["home_points"])
    final = games["is_final"].astype(bool)
    won = final & (points > allowed)
    lost = final & ~won
    wins = won.cumsum()
    losses = lost.cumsum()
    games["result"] = [
        f"{'W' if w else 'L'} {int(p)}-{int(a)}" if f else ""
        for f, w, p, a in zip(final, won, points, allowed, strict=True)
    ]
    games["record"] = [
        f"{w}-{lo}" if f else "" for f, w, lo in zip(final, wins, losses, strict=True)
    ]
    if games.empty:
        for col in _TEAM_COLUMNS:
            games[col] = pd.Series(dtype=object)
    return games
