"""The Players page's Compare tab (dashboard/views/players/compare.py),
rendered with AppTest against the real warehouse, and the data layer under
it.

Two player-seasons head to head: a radar of percentiles and the per-game
line. The tab states numbers and never calls a winner.
"""

import json
import shutil

import duckdb
import pytest
from streamlit.testing.v1 import AppTest

from core import paths
from core.text import fold
from dashboard.lib import glossary
from dashboard.lib import theme as T
from dashboard.lib.data import core as data_core
from dashboard.lib.data import diagnosis, players, seasons
from dashboard.views.players import compare

SCRIPT = """
import streamlit as st
from dashboard.lib.data import seasons
from dashboard.views import players
with st.sidebar:
    st.selectbox("Season", seasons.seasons(), key="season")
players.render()
"""

PCT_COLUMNS = [
    "points_per_game",
    "true_shooting_pct",
    "rebound_pct",
    "assist_pct",
    "turnover_pct",
    "steal_pct",
    "block_pct",
    "threes_made_per_game",
]
SPOKE_NAMES = [
    "Scoring",
    "Efficiency",
    "Rebounding",
    "Playmaking",
    "Ball security",
    "Steals",
    "Blocks",
    "3-pt volume",
]
SPOKES = dict(zip(PCT_COLUMNS, SPOKE_NAMES, strict=True))
PCTILES = ", ".join(f"{c}_pctile" for c in PCT_COLUMNS)


def _app() -> AppTest:
    at = AppTest.from_string(SCRIPT, default_timeout=60)
    # The page draws only the active tab.
    at.session_state["players_tab"] = "Compare"
    at.run()
    assert not at.exception, at.exception
    return at


def _caption(at: AppTest) -> str:
    # The Compare tab, found by its label rather than its position.
    tab = next(t for t in at.tabs if t.label == "Compare")
    return " ".join(c.value for c in tab.caption)


def _charts(at: AppTest, kind: str) -> list[dict]:
    return [
        f
        for f in (json.loads(c.proto.spec) for c in at.get("plotly_chart"))
        if f["data"] and f["data"][0]["type"] == kind
    ]


def _radars(at: AppTest) -> list[dict]:
    return _charts(at, "scatterpolar")


def _bars(at: AppTest) -> dict:
    # The per-game line is the bar chart whose first row is points.
    (found,) = (c for c in _charts(at, "bar") if c["data"][0]["y"] == ["PTS"])
    return found


def _top_two(con, season: str) -> list[tuple[int, str]]:
    return con.execute(
        """
        select player_id, player_name
        from main_marts.mart_player_percentiles
        where season = ? and is_qualified
        order by points_per_game desc, player_id
        limit 2
        """,
        [season],
    ).fetchall()


def _pick(season: str, player_id: int, at: AppTest, key: str, search: str) -> None:
    """Search for the player, then choose that season."""
    at.text_input(key=f"{key}_search").set_value(search).run()
    assert not at.exception, at.exception
    at.selectbox(key=key).select(compare.pick_id(season, player_id)).run()
    assert not at.exception, at.exception


# --- Data layer ---------------------------------------------------------------


def test_top_scorers_are_the_qualified_players_by_points(con):
    season = seasons.latest_season()
    top = diagnosis.top_scorers(season, 5)
    assert len(top) == 5
    assert top["points_per_game"].is_monotonic_decreasing
    assert list(zip(top["player_id"][:2], top["player"][:2], strict=True)) == _top_two(con, season)


def test_compare_line_has_the_line_the_percentiles_and_minutes(con):
    season = seasons.latest_season()
    pid = _top_two(con, season)[0][0]
    row = diagnosis.compare_line(season, pid)
    assert row is not None and bool(row["is_qualified"])
    for col in PCT_COLUMNS:
        assert 0 <= row[f"{col}_pctile"] <= 100
    assert row["minutes_per_game"] > 10 and row["games_played"] > 0
    assert diagnosis.compare_line("1800-01", pid) is None


def test_player_seasons_matching_lists_every_season_newest_first(con):
    season = seasons.latest_season()
    pid, name = _top_two(con, season)[0]
    found = players.player_seasons_matching(name)
    assert season in set(found[found["player_id"] == pid]["season"])
    assert found["season"].is_monotonic_decreasing
    assert len(players.player_seasons_matching("a", limit=7)) == 7
    assert players.player_seasons_matching("zzzzqqq").empty


def test_player_seasons_matching_ignores_case_and_accents(con):
    accented = con.execute(
        "select distinct player_name from main_marts.mart_player_season "
        "where player_name <> strip_accents(player_name) limit 1"
    ).fetchone()
    assert accented, "the warehouse should hold an accented name"
    name = accented[0]
    assert name in set(players.player_seasons_matching(fold(name).upper())["player"])


# --- The tab ---------------------------------------------------------------------


def test_it_opens_on_the_sidebars_two_top_scorers_with_a_radar_and_the_line(con):
    at = _app()
    season = at.selectbox(key="season").value
    (a_id, a_name), (b_id, b_name) = _top_two(con, season)
    assert at.selectbox(key=compare.A_KEY).value == compare.pick_id(season, a_id)
    assert at.selectbox(key=compare.B_KEY).value == compare.pick_id(season, b_id)
    assert at.selectbox(key=compare.A_KEY).options[0].startswith(f"{a_name} · {season} · ")

    (radar,) = _radars(at)
    assert [t["name"] for t in radar["data"]] == [f"{a_name} {season}", f"{b_name} {season}"]
    assert radar["data"][0]["theta"][:-1] == SPOKE_NAMES
    assert radar["layout"]["polar"]["radialaxis"]["range"] == [0, 100]
    hover = radar["data"][0]["customdata"][1]
    assert hover.startswith("TS% ") and hover.endswith(" percentile")

    bars = _bars(at)
    assert [t["y"][0] for t in bars["data"]][::2] == [label for label, _ in compare.STAT_LINE]
    assert compare.METHOD in _caption(at)


def _oklab(hex_color: str) -> tuple[float, float, float]:
    h = hex_color.lstrip("#")
    lin = []
    for i in (0, 2, 4):
        c = int(h[i : i + 2], 16) / 255
        lin.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    r, g, b = lin
    lms = (
        (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3),
        (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3),
        (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3),
    )
    return (
        0.2104542553 * lms[0] + 0.7936177850 * lms[1] - 0.0040720468 * lms[2],
        1.9779984951 * lms[0] - 2.4285922050 * lms[1] + 0.4505937099 * lms[2],
        0.0259040371 * lms[0] + 0.7827717662 * lms[1] - 0.8086757660 * lms[2],
    )


def _distance(a: str, b: str) -> float:
    """Perceptual distance, OKLab x 100 (the dataviz validator's scale)."""
    return 100 * sum((x - y) ** 2 for x, y in zip(_oklab(a), _oklab(b), strict=True)) ** 0.5


def _side_colours(at: AppTest) -> tuple[list[str], list[str]]:
    """The radar's two outline colours and the per-game line's first row's
    two bar colours, A first."""
    (radar,) = _radars(at)
    bars = _bars(at)
    return (
        [t["line"]["color"] for t in radar["data"]],
        [t["marker"]["color"] for t in bars["data"][:2]],
    )


def test_the_side_colours_are_a_fixed_pair_far_apart():
    a, b = compare.SIDE_COLORS
    assert (a, b) == (T.SERIES[0], T.SERIES[1])
    # The dataviz normal-vision floor is 15; the pair measures about 32.
    assert _distance(a, b) >= 15
    # Why not team colours: the Heat's and the Lakers' are a few points apart,
    # so LeBron's two teams drew two golds.
    assert _distance(T.team_color("MIA"), T.team_color("LAL")) < 15


def test_each_side_wears_its_side_colour_even_with_one_player_on_both(con):
    at = _app()
    season = at.selectbox(key="season").value
    pair = list(compare.SIDE_COLORS)
    assert _side_colours(at) == (pair, pair)
    # The same player and team on both sides keeps the two colours apart.
    a_id, a_name = _top_two(con, season)[0]
    _pick(season, a_id, at, compare.B_KEY, a_name)
    assert at.selectbox(key=compare.A_KEY).value == at.selectbox(key=compare.B_KEY).value
    assert _side_colours(at) == (pair, pair)


@pytest.mark.full_warehouse
def test_one_player_in_two_seasons_on_close_team_colours_gets_both_side_colours(con):
    """The reported case: LeBron's 2012-13 Heat season against his 2019-20
    Lakers season, two teams whose colours are both gold."""
    (pid,) = con.execute(
        "select distinct player_id from main_marts.mart_player_percentiles "
        "where player_name = 'LeBron James'"
    ).fetchone()
    at = _app()
    _pick("2012-13", pid, at, compare.A_KEY, "LeBron James")
    _pick("2019-20", pid, at, compare.B_KEY, "LeBron James")
    pair = list(compare.SIDE_COLORS)
    assert _side_colours(at) == (pair, pair)
    # The legend tells the sides apart in words too.
    (radar,) = _radars(at)
    assert [t["name"] for t in radar["data"]] == ["LeBron James 2012-13", "LeBron James 2019-20"]


def test_changing_both_pickers_changes_both_sides(con):
    at = _app()
    season = at.selectbox(key="season").value
    ids = [pid for pid, _ in _top_two(con, season)]
    (a_id, a_name, a_season), (b_id, b_name, b_season) = con.execute(
        """
        select player_id, player_name, season
        from main_marts.mart_player_percentiles
        where is_qualified and season = (select min(season) from main_marts.mart_player_percentiles
                                         where is_qualified and rebound_pct_pctile is not null)
        order by points_per_game desc, player_id limit 2
        """
    ).fetchall()
    _pick(a_season, a_id, at, compare.A_KEY, a_name)
    assert at.selectbox(key=compare.A_KEY).value == compare.pick_id(a_season, a_id)
    # B did not move.
    assert at.selectbox(key=compare.B_KEY).value == compare.pick_id(season, ids[1])
    _pick(b_season, b_id, at, compare.B_KEY, b_name)
    names = [t["name"] for t in _radars(at)[0]["data"]]
    assert names == [f"{a_name} {a_season}", f"{b_name} {b_season}"]
    assert compare.METHOD in _caption(at)


def test_a_search_with_no_match_says_so_and_clearing_it_returns_to_the_top_scorers(con):
    at = _app()
    default = at.selectbox(key=compare.A_KEY).value
    at.text_input(key=compare.A_SEARCH_KEY).set_value("zzzzqqq").run()
    assert not at.exception, at.exception
    assert 'No player matches "zzzzqqq"' in _caption(at)
    assert any("Pick a player-season on each side" in i.value for i in at.info)
    assert not _radars(at)
    at.text_input(key=compare.A_SEARCH_KEY).set_value("").run()
    assert not at.exception, at.exception
    assert at.selectbox(key=compare.A_KEY).value == default
    assert _radars(at)


def test_a_player_below_the_games_cut_shows_his_line_but_no_radar_trace(con):
    at = _app()
    season = at.selectbox(key="season").value
    pid, name = con.execute(
        """
        select player_id, player_name
        from main_marts.mart_player_percentiles
        where season = ? and not is_qualified
        order by games_played desc, player_id limit 1
        """,
        [season],
    ).fetchone()
    _pick(season, pid, at, compare.A_KEY, name)
    # He is named with the reason, and the other side is traced alone.
    assert any(compare.NOT_QUALIFIED in m.value for m in at.markdown)
    (radar,) = _radars(at)
    assert len(radar["data"]) == 1 and name not in radar["data"][0]["name"]
    # His numbers are still on the bars.
    bars = _bars(at)
    assert len(bars["data"]) == 2 * len(compare.STAT_LINE)
    assert bars["data"][0]["name"] == f"{name} {season}"
    assert bars["data"][0]["text"][0] != "-"


def test_with_neither_player_qualified_there_is_no_radar_but_the_line_stays(con):
    at = _app()
    season = at.selectbox(key="season").value
    rows = con.execute(
        """
        select player_id, player_name
        from main_marts.mart_player_percentiles
        where season = ? and not is_qualified
        order by games_played desc, player_id limit 2
        """,
        [season],
    ).fetchall()
    for key, (pid, name) in zip((compare.A_KEY, compare.B_KEY), rows, strict=True):
        _pick(season, pid, at, key, name)
    assert not _radars(at)
    assert any("no radar" in i.value for i in at.info)
    assert len(_bars(at)["data"]) == 2 * len(compare.STAT_LINE)


def test_a_season_without_advanced_stats_draws_only_the_axes_both_sides_have(con):
    at = _app()
    rows = con.execute(
        f"""
        select player_id, player_name, season, {PCTILES}
        from main_marts.mart_player_percentiles
        where is_qualified and rebound_pct_pctile is null
          and points_per_game_pctile is not null and true_shooting_pct_pctile is not null
          and threes_made_per_game_pctile is not null
        order by points_per_game desc
        limit 1
        """
    ).fetchall()
    assert rows, "the warehouse should hold a season without a rebound rate"
    pid, name, season, *pctiles = rows[0]
    _pick(season, pid, at, compare.A_KEY, name)
    expected = [SPOKES[c] for c, p in zip(PCT_COLUMNS, pctiles, strict=True) if p is not None]
    assert 3 <= len(expected) < 8
    (radar,) = _radars(at)
    # Only the spokes both players have, on both outlines.
    assert radar["data"][0]["theta"][:-1] == expected
    assert radar["data"][1]["theta"][:-1] == expected
    missing = [s for s in SPOKE_NAMES if s not in expected]
    assert f"Not available for {season}: {', '.join(missing)}" in _caption(at)


def test_two_spokes_or_fewer_leave_the_bars_and_one_notice(con):
    at = _app()
    have = " + ".join(f"({c}_pctile is not null)::int" for c in PCT_COLUMNS)
    rows = con.execute(
        f"""
        select player_id, player_name, season
        from main_marts.mart_player_percentiles
        where is_qualified and {have} < 3
        order by points_per_game desc
        limit 1
        """
    ).fetchall()
    assert rows, "the warehouse should hold a qualified season with almost no percentiles"
    pid, name, season = rows[0]
    _pick(season, pid, at, compare.A_KEY, name)
    assert not _radars(at)
    assert any("Too few percentiles" in i.value for i in at.info)
    assert len(_bars(at)["data"]) == 2 * len(compare.STAT_LINE)


def test_the_same_player_season_on_both_sides_renders_with_a_hint(con):
    at = _app()
    at.selectbox(key=compare.B_KEY).select(at.selectbox(key=compare.A_KEY).value).run()
    assert not at.exception, at.exception
    assert "same player-season" in _caption(at)
    (radar,) = _radars(at)
    first, second = (t["line"]["color"] for t in radar["data"])
    assert first != second  # still told apart
    assert radar["data"][0]["r"] == radar["data"][1]["r"]


def test_every_stat_label_has_a_glossary_term():
    for axis in compare.RADAR_AXES:
        assert axis.term in glossary.TERMS and axis.column in compare.METRICS
    for _, column in compare.STAT_LINE:
        assert compare.METRICS[column].term in glossary.TERMS
    assert "Player percentile" in glossary.TERMS


def test_the_page_carries_the_hovers(con):
    at = _app()
    html = " ".join(m.value for m in at.markdown)
    for term in ("Player percentile", "PTS", "MIN", "TS%"):
        assert glossary.TERMS[term][:30] in html


@pytest.fixture
def warehouse_without_percentiles(con, tmp_path):
    """A copy of the real warehouse as published before the percentiles mart."""
    real = paths.warehouse_path()
    path = tmp_path / real.name
    shutil.copyfile(real, path)
    copy = duckdb.connect(str(path))
    copy.execute("drop table main_marts.mart_player_percentiles")
    copy.close()
    with data_core.use_warehouse(path):
        yield path


def test_without_the_percentiles_mart_the_tab_shows_one_notice(warehouse_without_percentiles):
    assert not diagnosis.percentiles_available()
    at = _app()
    assert any("player compare arrives with the next data refresh" in i.value for i in at.info)
    assert not _radars(at)
