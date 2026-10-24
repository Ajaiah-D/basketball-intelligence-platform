"""The Players page's game log (dashboard/views/players/game_log.py): the
tint rule and the table it draws. Pure: hand-built games, no warehouse."""

import math

import pandas as pd
import pytest

from dashboard.lib import theme as T
from dashboard.views.players import game_log

AVERAGES = {"PTS": 20.0, "REB": 8.0, "AST": 1.2, "3PM": 2.0, "TS%": 60.0, "+/-": 0.5}


def _games() -> pd.DataFrame:
    """Three games, oldest first, in data.players.player_games' columns."""
    return pd.DataFrame(
        {
            "game_date": pd.to_datetime(["2025-10-22", "2025-10-24", "2025-11-03"]),
            "opp": ["BOS", "OKC", "NYK"],
            "is_away": [False, True, False],
            "is_win": [True, False, True],
            "team_pts": [112, 96, None],
            "opp_pts": [104, 139, None],
            "min": [36, 26, 38],
            "pts": [30, 12, 21],
            "reb": [8, 4, 9],
            "ast": [1, 0, 2],
            "tpm": [2, 1, 3],
            "ts_pct": [70.0, math.nan, 61.0],
            "shot_poss": [21.4, 0.0, 17.2],
            "plus_minus": [3, -25, 4],
        }
    )


@pytest.mark.parametrize(
    ("value", "stat", "expected"),
    [
        (30, "PTS", "above"),  # 50% over his 20
        (22, "PTS", ""),  # within 15%: a normal night
        (16, "PTS", "below"),
        (1, "AST", ""),  # a whole number next to a 1.2 average is normal
        (0, "AST", "below"),
        (2, "AST", "above"),
        (70.0, "TS%", "above"),
        (math.nan, "TS%", ""),  # no shots: nothing to judge against
        # +/- crosses zero, so its band is a fixed 3 points, not a share
        (3, "+/-", ""),
        (4, "+/-", "above"),
        (-3, "+/-", "below"),
    ],
)
def test_tint_against_his_season_average(value, stat, expected):
    assert game_log.tint(value, AVERAGES[stat], stat) == expected


def test_tint_without_a_season_average_is_plain():
    assert game_log.tint(30, math.nan, "PTS") == ""


def _rows(html: str) -> list[str]:
    return html.split("<tr")[2:]  # past the wrapper's header row


def test_the_log_lists_every_game_newest_first():
    html = game_log.game_log_html(_games(), AVERAGES)
    rows = _rows(html)
    assert len(rows) == 3
    assert "Nov 3" in rows[0] and "Oct 22" in rows[2]


def test_opponent_and_result_cells():
    rows = _rows(game_log.game_log_html(_games(), AVERAGES))
    assert "vs NYK" in rows[0] and "@ OKC" in rows[1]
    assert "W 112-104" in rows[2] and "L 96-139" in rows[1]
    # No score on record: the result alone.
    assert ">W<" in rows[0]


def test_stat_cells_are_tinted_but_minutes_never_are():
    rows = _rows(game_log.game_log_html(_games(), AVERAGES))
    oldest = rows[2]
    assert '<td class="above">30</td>' in oldest
    assert "<td>36</td>" in oldest  # minutes: context, not better or worse
    assert '<td class="below">-25</td>' in rows[1]
    assert "<td>-</td>" in rows[1]  # no shots: TS% is a dash and untinted


def test_the_log_scrolls_inside_a_fixed_height():
    assert f'style="max-height:{game_log.LOG_HEIGHT}px"' in game_log.game_log_html(
        _games(), AVERAGES
    )


def test_every_header_has_a_glossary_hover():
    html = game_log.game_log_html(_games(), AVERAGES)
    head = html.split("<tr")[1]
    for label in ("MIN", "PTS", "REB", "AST", "3PM", "TS%", "+/-"):
        assert f'{label}<span class="bip-tip"' in head, label


def test_the_tints_use_the_status_colours():
    assert T.rgba(T.GOOD, 0.18) in T.CSS and T.rgba(T.CRITICAL, 0.18) in T.CSS


def test_a_missing_value_in_a_nullable_column_is_a_plain_dash():
    # DuckDB hands back an integer column with a null as pandas' nullable
    # Int64, whose NA can't be compared (older seasons lack +/-).
    games = _games().astype({"plus_minus": "Int64", "pts": "Int64"})
    games.loc[1, ["plus_minus", "pts"]] = pd.NA
    rows = _rows(game_log.game_log_html(games, AVERAGES))
    assert rows[1].count("<td>-</td>") == 3  # PTS, TS% and +/-
