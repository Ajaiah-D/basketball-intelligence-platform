"""mart_player_game and data.players.player_games: one player's games with
the result beside each. Runs against the real warehouse via the `con`
fixture; 2024-25 is in the CI fixtures too."""

import pytest

from dashboard.lib.data import players

SEASON = "2024-25"


def _busiest_player(con) -> tuple[int, int]:
    """(player_id, games) of the player with the most games in SEASON."""
    row = con.execute(
        """
        select player_id, games_played from main_marts.mart_player_season
        where season = ? order by games_played desc, points_per_game desc limit 1
        """,
        [SEASON],
    ).fetchone()
    assert row, f"no players in {SEASON}"
    return int(row[0]), int(row[1])


def test_every_game_log_row_is_in_the_mart(con):
    stg, mart = con.execute(
        """
        select
            (select count(*) from main_staging.stg_player_game_logs where season = ?),
            (select count(*) from main_marts.mart_player_game where season = ?)
        """,
        [SEASON, SEASON],
    ).fetchone()
    assert mart == stg > 0


def test_player_games_lists_his_season_oldest_first(con):
    player_id, games = _busiest_player(con)
    df = players.player_games(player_id, SEASON)
    assert len(df) == games
    assert df["game_date"].is_monotonic_increasing
    for col in ("opp", "is_away", "is_win", "team_pts", "opp_pts", "min", "pts", "reb"):
        assert col in df.columns, col
    # A modern season's team logs have every game, so every score is there.
    assert df["team_pts"].notna().all() and df["opp_pts"].notna().all()
    # The result follows the score.
    assert (df["is_win"] == (df["team_pts"] > df["opp_pts"])).all()


def test_the_score_is_the_one_fct_team_game_records(con):
    bad = con.execute(
        """
        select count(*)
        from main_marts.mart_player_game g
        join main_marts.fct_team_game f using (game_id)
        where g.season = ?
          and not (
              (g.team_id = f.home_team_id and g.team_points = f.home_points
                   and g.opp_points = f.away_points)
              or (g.team_id = f.away_team_id and g.team_points = f.away_points
                   and g.opp_points = f.home_points)
          )
        """,
        [SEASON],
    ).fetchone()[0]
    assert bad == 0


def test_per_game_true_shooting_adds_up_to_the_season_figure(con):
    # Averaged over shot volume, the per-game values give back the season's
    # true shooting (to the rounding of each game's value).
    rows = con.execute(
        """
        select s.true_shooting_pct,
               sum(g.true_shooting_pct * g.shot_poss) / sum(g.shot_poss)
        from main_marts.mart_player_game g
        join main_marts.mart_player_season s using (season, player_id)
        where g.season = ? and s.fga_total >= 300
        group by s.player_id, s.true_shooting_pct
        """,
        [SEASON],
    ).fetchall()
    assert rows
    for season_ts, weighted in rows:
        assert weighted == pytest.approx(season_ts, abs=0.1)


def test_no_shots_means_no_true_shooting(con):
    bad = con.execute(
        """
        select count(*) from main_marts.mart_player_game
        where season = ? and (shot_poss = 0) <> (true_shooting_pct is null)
        """,
        [SEASON],
    ).fetchone()[0]
    assert bad == 0
