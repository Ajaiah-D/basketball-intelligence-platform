"""Player stats for the Players, Overview and Teams pages.

Everything reads the dbt player marts (mart_player_season,
mart_player_team_season, mart_player_career, mart_league_shooting), which
hold the season line once for every page. The queries rename the mart
columns to the short names the pages use (ppg, rpg, ts_pct, ...). The
select lists are written out per query rather than assembled from shared
pieces, so each query reads as the SQL that actually runs.

`team` is a player's last team that season; `team_label` is every team in
the order he played for them ("CHI → BOS" when traded mid-season), so the
pages can show a split season instead of filing it under the last team.
"""

from __future__ import annotations

import unicodedata

import pandas as pd

from .core import q


def player_season_stats(season: str, min_games: int = 1) -> pd.DataFrame:
    """One row per player in `season` with min_games+ games: per-game
    averages, attempt totals, shooting percentages, team and team_label."""
    return q(
        """
        select
            player_id,
            player_name           as player,
            team,
            games_played          as gp,
            minutes_per_game      as mpg,
            points_per_game       as ppg,
            rebounds_per_game     as rpg,
            assists_per_game      as apg,
            steals_per_game       as spg,
            blocks_per_game       as bpg,
            threes_made_per_game  as tpg,
            fga_per_game          as fga_pg,
            three_pa_per_game     as tpa_pg,
            fta_per_game          as fta_pg,
            fga_total,
            tpa_total,
            fta_total,
            fg_pct,
            fg3_pct,
            ft_pct,
            true_shooting_pct     as ts_pct,
            assist_to_turnover    as ast_to,
            plus_minus_per_game   as plus_minus,
            team_label
        from main_marts.mart_player_season
        where season = ? and games_played >= ?
        order by player_id
        """,
        (season, min_games),
    )


def team_roster(season: str, team: str, min_games: int = 1) -> pd.DataFrame:
    """One team's players in `season`, each line counting only the games he
    played for that team: a player traded mid-season is on both rosters,
    each with his own stint. team_label is his whole season's path, which
    the Teams page turns into "from CHI" / "to BOS"."""
    return q(
        """
        select
            s.player_id,
            s.player_name           as player,
            s.team_abbreviation     as team,
            s.games_played          as gp,
            s.minutes_per_game      as mpg,
            s.points_per_game       as ppg,
            s.rebounds_per_game     as rpg,
            s.assists_per_game      as apg,
            s.steals_per_game       as spg,
            s.blocks_per_game       as bpg,
            s.threes_made_per_game  as tpg,
            s.fga_per_game          as fga_pg,
            s.three_pa_per_game     as tpa_pg,
            s.fta_per_game          as fta_pg,
            s.fga_total,
            s.tpa_total,
            s.fta_total,
            s.fg_pct,
            s.fg3_pct,
            s.ft_pct,
            s.true_shooting_pct     as ts_pct,
            s.assist_to_turnover    as ast_to,
            s.plus_minus_per_game   as plus_minus,
            p.team_label
        from main_marts.mart_player_team_season s
        left join main_marts.mart_player_season p
               on p.season = s.season and p.player_id = s.player_id
        where s.season = ? and s.team_abbreviation = ? and s.games_played >= ?
        order by s.player_id
        """,
        (season, team, min_games),
    )


def _fold(text: str) -> str:
    """Lower case with accents dropped, so "jokic" finds "Jokić".
    (Task 14 replaces this and the views' copies with core.text.fold.)"""
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


def player_latest_seasons(name: str, min_games: int = 1, limit: int = 30) -> pd.DataFrame:
    """Players whose name contains `name` (case and accents ignored), each
    at his most recent season with min_games+ games: the
    player_season_stats() columns plus season. At most `limit` players,
    newest seasons first (then by player_id).

    contains() takes the text literally, so % and _ are not wildcards.
    """
    needle = _fold(name).strip()
    return q(
        """
        with latest as (
            select player_id, max(season) as season
            from main_marts.mart_player_season
            where contains(strip_accents(lower(player_name)), ?)
              and games_played >= ?
            group by player_id
            order by season desc, player_id
            limit ?
        )
        select
            player_id,
            season,
            player_name           as player,
            team,
            games_played          as gp,
            minutes_per_game      as mpg,
            points_per_game       as ppg,
            rebounds_per_game     as rpg,
            assists_per_game      as apg,
            steals_per_game       as spg,
            blocks_per_game       as bpg,
            threes_made_per_game  as tpg,
            fga_per_game          as fga_pg,
            three_pa_per_game     as tpa_pg,
            fta_per_game          as fta_pg,
            fga_total,
            tpa_total,
            fta_total,
            fg_pct,
            fg3_pct,
            ft_pct,
            true_shooting_pct     as ts_pct,
            assist_to_turnover    as ast_to,
            plus_minus_per_game   as plus_minus,
            team_label
        from main_marts.mart_player_season
        join latest using (player_id, season)
        order by season desc, player_id
        """,
        # An empty needle would match everyone; NUL matches no name.
        (needle or "\x00", int(min_games), int(limit)),
    )


def player_career_stats(min_games: int = 1) -> pd.DataFrame:
    """One row per player pooled across every ingested season. `team` is the
    most recent; percentages are computed from summed makes/attempts."""
    return q(
        """
        select
            player_id,
            player_name           as player,
            team,
            seasons,
            first_season,
            last_season,
            games_played          as gp,
            career_high,
            pts_total,
            wins,
            minutes_per_game      as mpg,
            points_per_game       as ppg,
            rebounds_per_game     as rpg,
            assists_per_game      as apg,
            steals_per_game       as spg,
            blocks_per_game       as bpg,
            threes_made_per_game  as tpg,
            fga_per_game          as fga_pg,
            three_pa_per_game     as tpa_pg,
            fta_per_game          as fta_pg,
            fga_total,
            tpa_total,
            fta_total,
            fg_pct,
            fg3_pct,
            ft_pct,
            true_shooting_pct     as ts_pct,
            plus_minus_per_game   as plus_minus
        from main_marts.mart_player_career
        where games_played >= ?
        order by player_id
        """,
        (min_games,),
    )


def player_season_breakdown(player_id: int) -> pd.DataFrame:
    """Per-season averages for one player, oldest first - drives the career
    trajectory chart.

    `shot_poss` (shooting possessions) is the correct weight for averaging
    TS% across seasons: a games-played weight would treat a low-volume year
    as equal to a high-volume one.
    """
    return q(
        """
        select
            season,
            team,
            games_played          as gp,
            points_per_game       as ppg,
            rebounds_per_game     as rpg,
            assists_per_game      as apg,
            threes_made_per_game  as tpg,
            true_shooting_pct     as ts_pct,
            shot_poss
        from main_marts.mart_player_season
        where player_id = ?
        order by season
        """,
        (player_id,),
    )


def player_game_log(player_id: int, season: str) -> pd.DataFrame:
    """Every game one player played in `season`, oldest first."""
    return q(
        """
        select * from main_staging.stg_player_game_logs
        where player_id = ? and season = ?
        order by game_date
        """,
        (player_id, season),
    )


def league_shooting_averages(season: str) -> pd.Series:
    """League-wide FG%, 3P% and FT% for `season`, volume-weighted (every make
    over every attempt). All null for a season the warehouse doesn't have."""
    df = q(
        """
        select fg_pct, fg3_pct, ft_pct
        from main_marts.mart_league_shooting
        where season = ?
        """,
        (season,),
    )
    if df.empty:
        return pd.Series({col: float("nan") for col in df.columns}, dtype=float)
    return df.iloc[0]
