"""The Players page's Similar players tab (dashboard/views/players/similar.py),
rendered with AppTest against the real warehouse. The ranking itself is
tested on synthetic pools in test_similarity.py."""

import pandas as pd
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from dashboard.lib import similarity
from dashboard.lib.advanced_metrics import minutes_floor
from dashboard.lib.data import advanced, seasons
from dashboard.lib.state import PLAYERS_PICK_KEY
from dashboard.views.players import similar

SCRIPT = """
import streamlit as st
from dashboard.lib.data import seasons
from dashboard.views import players
with st.sidebar:
    st.selectbox("Season", seasons.seasons(), key="season")
players.render()
"""


def _season() -> str:
    """The newest season with advanced stats."""
    return next(s for s in seasons.seasons() if s in advanced.advanced_seasons())


def _unique(pool: pd.DataFrame) -> pd.DataFrame:
    """`pool` less any player whose name another player in the warehouse
    shares, so a preset by name opens the right one."""
    return pool[~pool["player_name"].duplicated(keep=False)]


def _app(season: str, name: str) -> AppTest:
    """The page on the Similar players tab, with `name` preset at `season`."""
    at = AppTest.from_string(SCRIPT, default_timeout=60)
    at.session_state["season"] = season
    at.session_state[PLAYERS_PICK_KEY] = name
    at.run()
    assert not at.exception, at.exception
    at.session_state["players_tab__next"] = "Similar players"
    at.run()
    assert not at.exception, at.exception
    assert at.session_state["players_tab"] == "Similar players"
    return at


def _qualified_player(con) -> tuple[str, int, str]:
    """(season, player_id, name) of the season's minutes leader."""
    season = _season()
    pool = advanced.player_advanced(season)
    top = _unique(pool).sort_values("minutes", ascending=False).iloc[0]
    return season, int(top["player_id"]), str(top["player_name"])


def _table(at: AppTest, player_id: int, season: str) -> pd.DataFrame:
    """The table as drawn: his own line first, then the matches."""
    return at.dataframe(key=f"{similar.SIMILAR_TABLE_KEY}_{player_id}_{season}").value


def _matches(at: AppTest, player_id: int, season: str) -> pd.DataFrame:
    """The table's matches, without his own line on top."""
    return _table(at, player_id, season).iloc[1:].reset_index(drop=True)


def _captions(at: AppTest) -> str:
    return " ".join(c.value for c in at.caption)


def test_the_list_ranks_others_and_says_how(con):
    season, player_id, name = _qualified_player(con)
    at = _app(season, name)
    table = _table(at, player_id, season)
    assert list(table.columns) == similar.COLUMNS
    # His own line on top, for reference: no rank, no similarity.
    me = table.iloc[0]
    assert me["player_name"] == name
    assert me["rank"] == similar.REFERENCE_RANK
    assert pd.isna(me["similarity"])
    shown = _matches(at, player_id, season)
    assert len(shown) == similar.N_DEFAULT
    assert list(shown["rank"]) == [str(i) for i in range(1, similar.N_DEFAULT + 1)]
    assert name not in set(shown["player_name"])
    assert shown["similarity"].is_monotonic_decreasing
    assert shown["similarity"].between(0, 1).all()
    # The same ranking the module gives.
    pool = advanced.player_advanced(season)
    expected = similarity.rank_similar(pool, player_id, minutes_floor(pool), similar.N_DEFAULT)
    assert list(shown["player_name"]) == list(expected.ranked["player_name"])
    floor = minutes_floor(pool)
    caption = _captions(at)
    assert f"{floor}+ minutes" in caption and "z-score" in caption and "cosine" in caption
    assert all(label in caption for label in similarity.FEATURES.values())
    assert f"Players most like {name}" in " ".join(m.value for m in at.markdown)


def test_the_slider_sets_how_many_are_listed(con):
    season, player_id, name = _qualified_player(con)
    at = _app(season, name)
    slider = at.slider(key=similar.SIMILAR_N_KEY)
    assert (slider.min, slider.max, slider.value) == (similar.N_MIN, similar.N_MAX, 10)
    for n in (5, 25):
        at.slider(key=similar.SIMILAR_N_KEY).set_value(n).run()
        assert not at.exception, at.exception
        assert len(_matches(at, player_id, season)) == n
    # The five are the top five of the 25.
    at.slider(key=similar.SIMILAR_N_KEY).set_value(5).run()
    five = list(_matches(at, player_id, season)["player_name"])
    at.slider(key=similar.SIMILAR_N_KEY).set_value(25).run()
    assert list(_matches(at, player_id, season)["player_name"])[:5] == five


def test_the_list_size_survives_a_visit_to_another_tab(con):
    season, player_id, name = _qualified_player(con)
    at = _app(season, name)
    at.slider(key=similar.SIMILAR_N_KEY).set_value(15).run()
    at.session_state["players_tab__next"] = "Player"
    at.run()
    at.session_state["players_tab__next"] = "Similar players"
    at.run()
    assert not at.exception, at.exception
    assert at.slider(key=similar.SIMILAR_N_KEY).value == 15
    assert len(_matches(at, player_id, season)) == 15


def test_a_player_under_the_minutes_floor_gets_no_list(con):
    season = _season()
    pool = advanced.player_advanced(season)
    floor = minutes_floor(pool)
    under = _unique(pool[(pool["minutes"] < floor) & (pool["minutes"] > 0)])
    if under.empty:
        pytest.skip("nobody under the floor")
    name = str(under.sort_values("minutes").iloc[0]["player_name"])
    at = _app(season, name)
    assert "too few to compare" in _captions(at)
    assert not at.dataframe


def test_a_season_before_complete_box_scores_gets_no_list(con):
    old = seasons.seasons()[-1]
    if old in advanced.advanced_seasons():
        pytest.skip("the warehouse's oldest season has advanced stats")
    row = con.execute(
        """
        select player_name from main_marts.mart_player_season
        where season = ? and games_played >= 25 and player_name in (
            select player_name from main_marts.mart_player_season
            group by player_name having count(distinct player_id) = 1
        )
        order by points_per_game desc limit 1
        """,
        [old],
    ).fetchone()
    at = _app(old, row[0])
    assert "start in" in _captions(at)
    assert not at.dataframe


def test_selecting_a_row_opens_that_player(monkeypatch):
    # Row clicks can't be made through AppTest; this is the table's
    # on_select, fed the selection Streamlit would hand it.
    rows = pd.DataFrame({"player_id": [11, 22], "season": "2024-25"})
    key = "players_similar_table_1_2024-25"
    monkeypatch.setattr(
        st, "session_state", {key: {"selection": {"rows": [1]}}, similar.SIMILAR_ROWS_KEY: rows}
    )
    opened = []
    monkeypatch.setattr(similar, "open_player", lambda *a, **k: opened.append(a))
    similar._on_select(key)
    assert opened == [(22, "2024-25")]
    st.session_state[key] = {"selection": {"rows": [], "cells": [(0, "player_name")]}}
    similar._on_select(key)
    assert opened[-1] == (11, "2024-25")
    st.session_state[key] = {"selection": {"rows": [], "cells": []}}
    similar._on_select(key)
    assert len(opened) == 2


def _ranked() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "rank": [1, 2],
            "player_id": [22, 33],
            "player_name": ["B", "C"],
            "similarity": [0.8, 0.6],
            "points_per_game": [20.0, 15.0],
        }
    )


def test_his_line_is_pinned_above_the_matches():
    me = pd.Series({"player_id": 11, "player_name": "A", "points_per_game": 18.0})
    columns = ["rank", "player_name", "points_per_game", "similarity"]
    table = similar.with_reference_row(me, _ranked(), columns)
    assert list(table["player_name"]) == ["A", "B", "C"]
    assert list(table["rank"]) == [similar.REFERENCE_RANK, "1", "2"]
    assert pd.isna(table["similarity"].iloc[0])
    assert list(table["points_per_game"]) == [18.0, 20.0, 15.0]


def test_an_older_warehouse_without_turnovers_drops_tov_instead_of_failing():
    with_tov = pd.DataFrame(columns=[c for c in similar.COLUMNS if c not in ("rank", "similarity")])
    assert similar.shown_columns(with_tov) == similar.COLUMNS
    without = with_tov.drop(columns=["turnovers_per_game"])
    assert similar.shown_columns(without) == [
        c for c in similar.COLUMNS if c != "turnovers_per_game"
    ]
