"""The Schedule page (dashboard/views/schedule.py), rendered with AppTest:
the month calendar, the day view, the team filter, "Open game" and the
Games page honouring the game it was sent.

"Today" is injected (monkeypatching schedule.today), so nothing here
depends on the date the tests run. The calendar's counts are checked
against the real 2026-27 schedule, which the CI fixtures carry; finished
and upcoming games come from conftest's synthetic schedule_warehouse,
since the real 2026-27 games turn from upcoming to final as the season
goes on.
"""

import re
from datetime import date, timedelta

import duckdb
import pandas as pd
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from dashboard.lib import nav
from dashboard.lib.data import core as data_core
from dashboard.lib.data import games as game_data
from dashboard.lib.data import schedule as schedule_data
from dashboard.lib.state import GAMES_PICK_KEY, SEASON_KEY
from dashboard.views import games as games_page
from dashboard.views import schedule as page

# The sidebar box from dashboard/app.py, then the page.
SCRIPT = """
import streamlit as st
from dashboard.lib.data import seasons
from dashboard.views import schedule
with st.sidebar:
    st.selectbox("Season", seasons.seasons(), key="season")
schedule.render()
"""

GAMES_SCRIPT = """
import streamlit as st
from dashboard.lib.data import seasons
from dashboard.views import games
with st.sidebar:
    st.selectbox("Season", seasons.seasons(), key="season")
games.render()
"""

REAL_SEASON = "2026-27"
SYNTHETIC_SEASON = "2030-31"  # conftest's schedule_warehouse
PRIOR_SEASON = "2029-30"  # scheduled too, with one game
UNSCHEDULED_SEASON = "2028-29"  # in the sidebar's list, not in the schedule


def _app(monkeypatch, today: date, script: str = SCRIPT, **state) -> AppTest:
    monkeypatch.setattr(page, "today", lambda: today)
    at = AppTest.from_string(script, default_timeout=60)
    for key, value in state.items():
        at.session_state[key] = value
    at.run()
    assert not at.exception, at.exception
    return at


def _day_button(at: AppTest, day: date):
    return at.button(key=f"sched_day_{day.isoformat()}")


def _label(at: AppTest, day: date) -> str:
    """A day button's label as it reads on screen: the italic detail is
    drawn after a middle dot (theme.py's calendar CSS)."""
    return page.plain_label(_day_button(at, day).label)


def _day_keys(at: AppTest) -> list[str]:
    return [b.key for b in at.button if b.key and b.key.startswith("sched_day_")]


def _text(at: AppTest) -> str:
    """Every markdown block's and caption's text, HTML tags dropped."""
    blocks = [m.value for m in at.markdown] + [c.value for c in at.caption]
    return re.sub(r"<[^>]+>", "", " ".join(blocks))


def _html(at: AppTest) -> str:
    return " ".join(m.value for m in at.markdown)


# --- The calendar, on the real 2026-27 schedule ------------------------------------


def test_october_2026_has_the_right_counts(con, monkeypatch):
    at = _app(monkeypatch, date(2026, 10, 28))
    assert "October 2026" in _text(at)
    assert REAL_SEASON in _text(at)  # the season chip
    counts = schedule_data.month_counts(REAL_SEASON, 2026, 10)
    # Every October day has a button, and no other day does.
    assert _day_keys(at) == [f"sched_day_2026-10-{d:02d}" for d in range(1, 32)]
    for d in range(1, 32):
        day = date(2026, 10, d)
        label = _label(at, day).removeprefix(page.TODAY_MARK)
        n = counts.get(day, 0)
        expected = f"{d}" if n == 0 else f"{d} · {n} game{'s' if n != 1 else ''}"
        assert label == expected, (day, label)
    # Known days, written out rather than read back from month_counts.
    assert _label(at, date(2026, 10, 20)) == "20 · 3 games"
    assert _label(at, date(2026, 10, 21)) == "21 · 11 games"
    assert _label(at, date(2026, 10, 23)) == "23 · 12 games"


def test_today_is_marked_and_selected_by_default(con, monkeypatch):
    at = _app(monkeypatch, date(2026, 10, 28))
    today = _day_button(at, date(2026, 10, 28))
    assert today.label.startswith(page.TODAY_MARK)
    assert today.proto.type == "primary"
    other = _day_button(at, date(2026, 10, 23))
    assert not other.label.startswith(page.TODAY_MARK)
    assert other.proto.type == "secondary"
    assert "Wednesday, October 28" in _text(at)


def test_the_team_filter_changes_the_cell_labels(con, monkeypatch):
    at = _app(monkeypatch, date(2026, 10, 28))
    at.selectbox(key=page.TEAM_BOX_KEY).select("BOS").run()
    assert not at.exception, at.exception
    bos = schedule_data.team_schedule(REAL_SEASON, "BOS")
    october = bos[bos["game_date"].dt.month == 10]
    playing = {
        g.game_date.date(): f"{'vs' if g.is_home else '@'} {g.opponent}"
        for g in october.itertuples()
    }
    assert _label(at, date(2026, 10, 23)) == "23 · vs NYK"
    for d in range(1, 32):
        day = date(2026, 10, d)
        label = _label(at, day).removeprefix(page.TODAY_MARK)
        expected = f"{d} · {playing[day]}" if day in playing else f"{d}"
        assert label == expected, (day, label)
    # Below the day view, the team's whole season.
    assert "BOS schedule" in _text(at)
    team_table = next(
        m.value for m in at.markdown if "bip-table" in m.value and "Record" in m.value
    )
    assert team_table.count("<tr>") == len(bos) + 1  # plus the header row


def test_a_month_out_of_season_opens_on_the_first_month(con, monkeypatch):
    # August, before opening night: the coming season, from its first month.
    at = _app(monkeypatch, date(2026, 8, 15))
    assert REAL_SEASON in _text(at)
    assert "October 2026" in _text(at)
    assert at.button(key="sched_prev").disabled
    assert not at.button(key="sched_next").disabled
    # No day is today, and the first day with games is the one shown.
    first = min(schedule_data.month_counts(REAL_SEASON, 2026, 10))
    assert _day_button(at, first).proto.type == "primary"
    assert not any(b.label.startswith(page.TODAY_MARK) for b in at.button)


def test_the_arrows_stop_at_the_seasons_last_month(con, monkeypatch):
    at = _app(monkeypatch, date(2026, 10, 28))
    last = schedule_data.schedule_seasons().set_index("season").loc[REAL_SEASON, "last_day"]
    for _ in range(12):
        if at.button(key="sched_next").disabled:
            break
        at.button(key="sched_next").click().run()
        assert not at.exception, at.exception
    assert f"{last:%B %Y}" in _text(at)
    assert at.button(key="sched_next").disabled
    assert not at.button(key="sched_prev").disabled


def test_an_empty_day_says_no_games(con, monkeypatch):
    at = _app(monkeypatch, date(2026, 10, 28))
    empty = next(
        date(2026, 10, d)
        for d in range(1, 32)
        if date(2026, 10, d) not in schedule_data.month_counts(REAL_SEASON, 2026, 10)
    )
    _day_button(at, empty).click().run()
    assert not at.exception, at.exception
    assert "No games." in _text(at)


# --- The day view, on the synthetic season -----------------------------------------


def test_clicking_a_day_shows_its_finished_games(schedule_warehouse, monkeypatch):
    at = _app(monkeypatch, date(2030, 10, 20))
    # Opening day is today: BOS beat NYK, Able and Zulu tied on 30.
    assert "NYK 105 @ BOS 112 · Final · Able 30" in _text(at)
    _day_button(at, date(2030, 10, 22)).click().run()
    assert not at.exception, at.exception
    text = _text(at)
    assert "BOS 99 @ NYK 100 · Final · Cole 41" in text
    # The neutral-site game, scored from the schedule's home side.
    assert "DAL 90 @ MIA 95 · Final · Eck 22" in text
    assert "NYK 105 @ BOS 112" not in text
    assert at.button(key="sched_open_0023000002").label == "Open game"
    assert at.button(key="sched_open_0023000003").label == "Open game"


def test_an_upcoming_day_shows_the_tipoff_and_the_models_pick(schedule_warehouse, monkeypatch):
    at = _app(monkeypatch, date(2030, 10, 20))
    _day_button(at, date(2030, 10, 25)).click().run()
    assert not at.exception, at.exception
    assert "7:00 PM ET" in _text(at)
    assert "MIA @ BOS · 65%" in _text(at)
    assert ">BOS</b>" in _html(at)  # the favourite, bold
    assert not [b for b in at.button if b.key and b.key.startswith("sched_open_")]


def test_open_game_presets_the_games_page(schedule_warehouse, monkeypatch):
    sent: list = []
    monkeypatch.setattr(nav, "_PAGES", {"games": "games-page"})
    monkeypatch.setattr(st, "switch_page", sent.append)
    at = _app(monkeypatch, date(2030, 10, 20))
    at.button(key="sched_open_0023000001").click().run()
    assert not at.exception, at.exception
    assert at.session_state[GAMES_PICK_KEY] == "0023000001"
    assert at.session_state[SEASON_KEY] == SYNTHETIC_SEASON
    assert sent == ["games-page"]


def test_no_schedule_tables_is_one_notice(tmp_warehouse_without_marts, monkeypatch):
    monkeypatch.setattr(page, "today", lambda: date(2026, 10, 28))
    at = AppTest.from_string("from dashboard.views import schedule\nschedule.render()")
    at.run()
    assert not at.exception, at.exception
    assert len(at.info) == 1
    assert not at.button


# --- Pending results: a past game with no result is not "upcoming" ------------------


def test_a_past_game_without_a_result_is_pending_not_upcoming(schedule_warehouse, monkeypatch):
    # The 25th was scheduled, has a model pick, and never got a result.
    at = _app(monkeypatch, date(2030, 10, 28))
    _day_button(at, date(2030, 10, 25)).click().run()
    assert not at.exception, at.exception
    text = _text(at)
    assert "Result pending" in text
    assert "7:00 PM ET" not in text
    # What the model said before the game stays.
    assert "MIA @ BOS · 65%" in text
    assert ">BOS</b>" in _html(at)


def _team_table(at: AppTest) -> str:
    return next(m.value for m in at.markdown if "bip-table" in m.value and "Record" in m.value)


def test_past_games_without_results_are_pending_in_the_team_season_too(
    schedule_warehouse, monkeypatch
):
    at = _app(monkeypatch, date(2030, 11, 5))
    at.selectbox(key=page.TEAM_BOX_KEY).select("BOS").run()
    assert not at.exception, at.exception
    table = _team_table(at)
    # The 25th (no result) and the 2 Nov game recorded 0-0; neither reads as a tip-off.
    assert table.count("Result pending") == 2
    assert "PM ET" not in table


def test_a_game_still_to_come_keeps_its_tipoff(schedule_warehouse, monkeypatch):
    at = _app(monkeypatch, date(2030, 10, 20))
    at.selectbox(key=page.TEAM_BOX_KEY).select("BOS").run()
    assert not at.exception, at.exception
    table = _team_table(at)
    assert "7:00 PM ET" in table  # the 25th, not yet played
    assert table.count("Result pending") == 0


# --- The team filter and the month it opens on ----------------------------------------

LEAVE_SCRIPT = """
import streamlit as st
from dashboard.lib.data import seasons
from dashboard.views import schedule
with st.sidebar:
    st.selectbox("Season", seasons.seasons(), key="season")
if st.session_state.get("elsewhere"):
    st.write("another page")
else:
    schedule.render()
"""


def test_the_team_survives_a_visit_to_another_page(schedule_warehouse, monkeypatch):
    at = _app(monkeypatch, date(2030, 10, 20), LEAVE_SCRIPT)
    at.selectbox(key=page.TEAM_BOX_KEY).select("MIA").run()
    assert "MIA schedule" in _text(at)
    at.session_state["elsewhere"] = True
    at.run()
    assert not at.exception, at.exception
    assert page.TEAM_BOX_KEY not in [s.key for s in at.selectbox]  # the widget is gone
    at.session_state["elsewhere"] = False
    at.run()
    assert not at.exception, at.exception
    assert at.selectbox(key=page.TEAM_BOX_KEY).value == "MIA"
    assert "MIA schedule" in _text(at)


def test_a_remembered_team_the_season_lacks_falls_back_to_all_teams(
    schedule_warehouse, monkeypatch
):
    at = _app(monkeypatch, date(2030, 10, 20), **{page.TEAM_KEY: "ZZZ"})
    assert at.selectbox(key=page.TEAM_BOX_KEY).value == page.ALL_TEAMS


def test_a_month_change_with_a_team_opens_on_the_teams_first_game(con, monkeypatch):
    at = _app(monkeypatch, date(2026, 8, 15))
    november = schedule_data.schedule(REAL_SEASON)
    november = november[november["game_date"].dt.month == 11]
    league_first = november["game_date"].min().date()
    # A team whose first November game is not the league's.
    firsts = {
        t: november[(november["home"] == t) | (november["away"] == t)]["game_date"].min().date()
        for t in sorted(set(november["home"]) | set(november["away"]))
    }
    team, first = next((t, d) for t, d in firsts.items() if d != league_first)
    at.selectbox(key=page.TEAM_BOX_KEY).select(team).run()
    at.button(key="sched_next").click().run()
    assert not at.exception, at.exception
    assert "November 2026" in _text(at)
    assert _day_button(at, first).proto.type == "primary"
    assert _day_button(at, league_first).proto.type == "secondary"
    # With all teams again, the league's first game day.
    at.selectbox(key=page.TEAM_BOX_KEY).select(page.ALL_TEAMS).run()
    at.button(key="sched_prev").click().run()
    at.button(key="sched_next").click().run()
    assert _day_button(at, league_first).proto.type == "primary"


def test_a_month_where_the_team_is_idle_opens_on_the_leagues_first_day(
    schedule_warehouse, monkeypatch
):
    # NYK plays on 10-20 and 10-22 only; November's one game is BOS v DAL.
    at = _app(monkeypatch, date(2030, 10, 20))
    at.selectbox(key=page.TEAM_BOX_KEY).select("NYK").run()
    at.button(key="sched_next").click().run()
    assert not at.exception, at.exception
    assert "November 2030" in _text(at)
    assert _day_button(at, date(2030, 11, 2)).proto.type == "primary"


# --- The season: the sidebar's, with one caption when the schedule lacks it ----------


def test_the_page_has_no_season_box_of_its_own(schedule_warehouse, monkeypatch):
    at = _app(monkeypatch, date(2030, 10, 20))
    assert sorted(s.key for s in at.selectbox) == sorted(["season", page.TEAM_BOX_KEY])


def test_a_scheduled_sidebar_season_is_the_one_shown(schedule_warehouse, monkeypatch):
    at = _app(monkeypatch, date(2030, 10, 20), **{SEASON_KEY: PRIOR_SEASON})
    assert PRIOR_SEASON in _text(at)  # the season chip
    assert "October 2029" in _text(at)
    assert "The schedule covers" not in _text(at)
    # And changing the sidebar changes the page.
    at.selectbox(key="season").select(SYNTHETIC_SEASON).run()
    assert not at.exception, at.exception
    assert "October 2030" in _text(at)
    assert "The schedule covers" not in _text(at)


def test_an_unscheduled_sidebar_season_shows_the_default_with_one_caption(
    schedule_warehouse, monkeypatch
):
    at = _app(monkeypatch, date(2030, 10, 20), **{SEASON_KEY: UNSCHEDULED_SEASON})
    caption = (
        f"The schedule covers {PRIOR_SEASON} and {SYNTHETIC_SEASON}; showing {SYNTHETIC_SEASON}."
    )
    assert [c.value for c in at.caption if "schedule covers" in c.value] == [caption]
    assert "October 2030" in _text(at)
    # The chip names the season on screen, not the sidebar's.
    chip = next(m.value for m in at.markdown if m.value.startswith("## Schedule"))
    assert SYNTHETIC_SEASON in chip
    assert UNSCHEDULED_SEASON not in chip


def test_the_default_season_follows_the_date(schedule_warehouse, monkeypatch):
    # Between the two seasons: the next to start.
    at = _app(monkeypatch, date(2030, 1, 5), **{SEASON_KEY: UNSCHEDULED_SEASON})
    assert "October 2030" in _text(at)
    # Before both: the earlier.
    at = _app(monkeypatch, date(2029, 8, 1), **{SEASON_KEY: UNSCHEDULED_SEASON})
    assert "October 2029" in _text(at)


# --- The Games page honours the preset ------------------------------------------------


def _assert_games_page_opens(at: AppTest, game) -> None:
    pick = at.selectbox(key="games_pick").value
    assert f"{game.away} {game.away_pts} @ {game.home} {game.home_pts}" in pick
    assert f"{game.game_date:%b %d}" in pick
    assert GAMES_PICK_KEY not in at.session_state
    # Read once, and the choice holds through another rerun.
    at.run()
    assert not at.exception, at.exception
    assert at.selectbox(key="games_pick").value == pick


@pytest.mark.full_warehouse
def test_the_games_page_opens_a_preset_game_beyond_the_picker(con, monkeypatch):
    # A full season (the fixtures hold none, so this one is local only): its
    # first game sits far past the newest PICKER_GAMES the picker lists.
    season = "2025-26"
    games = game_data.games_list(season)
    game = games.iloc[-1]
    assert games.index[games["game_id"] == game.game_id][0] >= games_page.PICKER_GAMES
    at = _app(
        monkeypatch,
        date(2026, 10, 28),
        GAMES_SCRIPT,
        **{SEASON_KEY: season, GAMES_PICK_KEY: game.game_id},
    )
    _assert_games_page_opens(at, game)


@pytest.fixture
def long_season_warehouse(tmp_path):
    """A season of PICKER_GAMES + 20 games, for the Games page's preset beyond
    the picker. The CI fixtures have no full season, so this keeps that
    branch covered there."""
    path = tmp_path / "long.duckdb"
    start = date(2030, 10, 20)
    rows = [
        {
            "season": SYNTHETIC_SEASON,
            "game_id": f"00230{i:05d}",
            "game_date": pd.Timestamp(start + timedelta(days=i)),
            "home_team_id": 1,
            "home_team_abbreviation": "BOS",
            "away_team_id": 2,
            "away_team_abbreviation": "NYK",
            "home_points": 100 + i % 7,
            "away_points": 90 + i % 5,
        }
        for i in range(games_page.PICKER_GAMES + 20)
    ]
    con = duckdb.connect(str(path))
    for schema in ("main_staging", "main_marts"):
        con.execute(f"create schema {schema}")
    for name, df in (
        ("main_marts.fct_team_game", pd.DataFrame(rows)),
        ("main_staging.stg_team_game_logs", pd.DataFrame({"season": [SYNTHETIC_SEASON]})),
        ("main_staging.stg_play_by_play", pd.DataFrame({"game_id": ["0"]})),
    ):
        con.register("df_view", df)
        con.execute(f"create table {name} as select * from df_view")
        con.unregister("df_view")
    # The box score of the chosen game: no rows is enough for the page.
    con.execute(
        "create table main_staging.stg_player_game_logs ("
        "game_id varchar, team_abbreviation varchar, team_id integer, player_name varchar,"
        " player_id integer, minutes_played double, points integer, total_rebounds integer,"
        " assists integer, steals integer, blocks integer, turnovers integer,"
        " field_goals_made integer, field_goals_attempted integer,"
        " three_pointers_made integer, three_pointers_attempted integer,"
        " free_throws_made integer, free_throws_attempted integer, plus_minus double)"
    )
    con.close()
    with data_core.use_warehouse(path):
        yield path


def test_the_games_page_opens_a_preset_game_beyond_the_picker_in_a_long_season(
    long_season_warehouse, monkeypatch
):
    games = game_data.games_list(SYNTHETIC_SEASON)
    game = games.iloc[-1]  # the season's first game
    assert games.index[games["game_id"] == game.game_id][0] >= games_page.PICKER_GAMES
    at = _app(
        monkeypatch,
        date(2031, 6, 1),
        GAMES_SCRIPT,
        **{SEASON_KEY: SYNTHETIC_SEASON, GAMES_PICK_KEY: game.game_id},
    )
    _assert_games_page_opens(at, game)
    # It was added to the list: first of PICKER_GAMES + 1 options.
    picker = at.selectbox(key="games_pick")
    assert picker.options[0] == picker.value
    assert len(picker.options) == games_page.PICKER_GAMES + 1
