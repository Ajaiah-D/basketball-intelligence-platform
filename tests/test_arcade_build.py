"""Headless checks for the Arcade's "Build a team" tab (dashboard/views/arcade.py).

Same AppTest pattern as test_finances_page.py. The simulator and the draft
rules are unit-tested in test_sim.py and test_draft.py; these tests cover
the page wiring: the old-warehouse notice, the pool picker, a full Build
roster turning into a stable projection, and a Draft reaching its results.

The tab is rendered on its own (arcade.render_build_team) because the other
two Arcade games read tables the tiny fixture warehouse does not have.
"""

import numpy as np
from streamlit.testing.v1 import AppTest

from dashboard.lib import db, draft, media

SCRIPT = """
from dashboard.views import arcade
arcade.render_build_team()
"""

SEASON = "2024-25"
# Player ids 3..10 cost 8+7+...+1 = 36 credits: a valid 8-man roster.
VALID_PICKS = [(pid, SEASON) for pid in range(3, 11)]


def _app(monkeypatch=None, **state) -> AppTest:
    if monkeypatch is not None:
        # Synthetic player ids have no headshot; skip the CDN round trip.
        monkeypatch.setattr(media, "headshot_data_uri", lambda pid: None)
    at = AppTest.from_string(SCRIPT, default_timeout=30)
    for key, value in state.items():
        at.session_state[key] = value
    at.run()
    assert not at.exception, at.exception
    return at


def _markdown(at: AppTest) -> str:
    return " ".join(m.value for m in at.markdown)


def _record_kpi(at: AppTest) -> str:
    """The Projected record KPI's markdown, the determinism check's subject."""
    hits = [m.value for m in at.markdown if "Projected record" in m.value]
    assert hits, "no Projected record KPI on the page"
    return hits[0]


def test_old_warehouse_shows_the_info_line(tmp_warehouse_without_marts):
    at = _app()
    infos = [i.value for i in at.info]
    assert ("Team building needs a newer copy of the data - check back after "
            "the next refresh.") in infos
    assert len(at.dataframe) == 0


def test_build_mode_renders_the_pool_table(warehouse_for_team_builder, monkeypatch):
    at = _app(monkeypatch, tb_mode="Build", tb_pool=SEASON)
    assert len(at.dataframe) == 1
    table = at.dataframe[0].value
    # 60 player-seasons in 2024-25, all shown (the cap is 200).
    assert len(table) == 60
    assert "Credits used" in _markdown(at)
    assert "Projected record" not in _markdown(at)


def test_pool_choices_are_all_time_then_seasons_newest_first(
        warehouse_for_team_builder, monkeypatch):
    at = _app(monkeypatch)
    assert list(at.selectbox(key="tb_pool").options) == ["All-time", "2024-25", "2023-24"]


def test_search_filters_the_pool(warehouse_for_team_builder, monkeypatch):
    at = _app(monkeypatch, tb_pool=SEASON)
    # Every word must match somewhere in name, season or team.
    at.text_input(key="tb_search").input("player 12").run()
    assert not at.exception, at.exception
    assert list(at.dataframe[0].value["Player"]) == ["Player 12"]
    at.text_input(key="tb_search").input("nyk").run()
    assert len(at.dataframe[0].value) == 50


def test_a_full_roster_shows_results_and_the_projection_is_stable(
        warehouse_for_team_builder, monkeypatch):
    first = _app(monkeypatch, tb_mode="Build", tb_pool=SEASON,
                 tb_build_picks=list(VALID_PICKS))
    text = _markdown(first)
    assert "Projected record" in text
    assert "Team rating" in text
    assert "Best-record odds" in text
    record = _record_kpi(first)

    # Same roster in a different pick order, in a fresh session: identical.
    second = _app(monkeypatch, tb_mode="Build", tb_pool=SEASON,
                  tb_build_picks=list(reversed(VALID_PICKS)))
    assert _record_kpi(second) == record
    # And a plain rerun of the first session keeps it too.
    first.run()
    assert _record_kpi(first) == record


def test_over_budget_roster_shows_the_validation_message(
        warehouse_for_team_builder, monkeypatch):
    # Ids 1..8 cost 10+9+...+3 = 52 credits.
    picks = [(pid, SEASON) for pid in range(1, 9)]
    at = _app(monkeypatch, tb_pool=SEASON, tb_build_picks=picks)
    warnings = " ".join(w.value for w in at.warning)
    assert "Over budget: 52 of 40 credits." in warnings
    assert "Projected record" not in _markdown(at)


def test_all_time_build_with_the_same_player_twice(warehouse_for_team_builder, monkeypatch):
    # 10 + 10 credits for the two Player 1 seasons, 1 each for six more.
    picks = [(1, "2023-24"), (1, "2024-25")] + [(pid, "2024-25") for pid in range(11, 17)]
    at = _app(monkeypatch, tb_pool="All-time", tb_build_picks=picks)
    assert "Projected record" in _markdown(at)


def test_simulate_a_season_shows_a_record_and_the_game_strip(
        warehouse_for_team_builder, monkeypatch):
    at = _app(monkeypatch, tb_pool=SEASON, tb_build_picks=list(VALID_PICKS))
    at.button(key="tb_build_sim").click().run()
    assert not at.exception, at.exception
    text = _markdown(at)
    assert text.count("dot-w") + text.count("dot-l") == 82
    assert "Longest winning streak" in text


def test_remove_button_frees_a_slot(warehouse_for_team_builder, monkeypatch):
    at = _app(monkeypatch, tb_pool=SEASON, tb_build_picks=list(VALID_PICKS))
    at.button(key="tb_rm_3_2024-25").click().run()
    assert not at.exception, at.exception
    assert (3, SEASON) not in [tuple(p) for p in at.session_state["tb_build_picks"]]
    assert "Projected record" not in _markdown(at)


def test_changing_the_pool_resets_the_build(warehouse_for_team_builder, monkeypatch):
    at = _app(monkeypatch, tb_pool=SEASON, tb_build_picks=list(VALID_PICKS))
    at.selectbox(key="tb_pool").select("2023-24").run()
    assert not at.exception, at.exception
    assert at.session_state["tb_build_picks"] == []
    assert "Projected record" not in _markdown(at)


def test_draft_runs_to_the_users_turn_then_shows_league_results(
        warehouse_for_team_builder, monkeypatch):
    at = _app(monkeypatch, tb_mode="Draft", tb_pool=SEASON)
    at.button(key="tb_draft_start").click().run()
    assert not at.exception, at.exception
    state = at.session_state["tb_draft"]
    # The CPU ran up to the user's first pick.
    assert state["order"][state["pick_no"]] == state["user_team"]
    assert "On the clock" in _markdown(at)
    assert len(at.dataframe) == 1  # the pick table

    # Finish the draft programmatically: user takes the best available.
    pool = db.player_impact_pool(SEASON)
    rng = np.random.default_rng(0)
    while state["pick_no"] < len(state["order"]):
        best = pool.loc[~pool.index.isin(state["taken"])].index[0]
        draft.apply_pick(state, best)
        draft.run_cpu_until_user(state, pool, rng)
    at.session_state["tb_draft"] = state
    at.run()
    assert not at.exception, at.exception
    text = _markdown(at)
    assert "Title odds" in text and "Projected record" in text
    standings = at.dataframe[0].value
    assert len(standings) == 6
    assert "Your team" in set(standings["Team"])

    at.button(key="tb_draft_sim").click().run()
    assert not at.exception, at.exception
    text = _markdown(at)
    assert "Round 1:" in text and "Final:" in text and "Champion" in text


def test_all_team_net_ratings(warehouse_for_team_builder):
    df = db.all_team_net_ratings()
    assert list(df.columns) == ["season", "team", "net_rating"]
    assert df["net_rating"].notna().all()
    assert set(df["season"]) == {"2023-24", "2024-25"}  # 1984-85 left out
    assert len(df) == 10  # LAL has no net rating in either season
