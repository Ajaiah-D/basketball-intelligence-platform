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
from datetime import date

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from dashboard.lib import nav
from dashboard.lib.data import games as game_data
from dashboard.lib.data import schedule as schedule_data
from dashboard.lib.data import seasons
from dashboard.lib.state import GAMES_PICK_KEY, SEASON_KEY
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
    at.selectbox(key="sched_team").select("BOS").run()
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


# --- The page season and the sidebar's ----------------------------------------------


@pytest.mark.full_warehouse
def test_the_page_season_and_the_sidebar_follow_each_other(con, monkeypatch):
    """Needs two scheduled seasons; the fixtures schedule only 2026-27."""
    at = _app(monkeypatch, date(2026, 10, 28), **{SEASON_KEY: "2024-25"})
    assert at.selectbox(key="sched_season_box").value == REAL_SEASON
    # The sidebar moving to a scheduled season takes the page with it.
    at.selectbox(key="season").select("2025-26").run()
    assert at.selectbox(key="sched_season_box").value == "2025-26"
    assert "October 2025" in _text(at)
    # And the page's box moves the sidebar, when the sidebar lists the season.
    at.selectbox(key="sched_season_box").select(REAL_SEASON).run()
    assert not at.exception, at.exception
    expected = REAL_SEASON if REAL_SEASON in seasons.seasons() else "2025-26"
    assert at.session_state[SEASON_KEY] == expected
    assert "October 2026" in _text(at)


# --- The Games page honours the preset ------------------------------------------------


def test_the_games_page_opens_the_preset_game(con, monkeypatch):
    season = seasons.latest_season()
    games = game_data.games_list(season)
    # The season's first game: far past the newest 200 the picker lists.
    game = games.iloc[-1]
    at = _app(
        monkeypatch,
        date(2026, 10, 28),
        GAMES_SCRIPT,
        **{SEASON_KEY: season, GAMES_PICK_KEY: game.game_id},
    )
    pick = at.selectbox(key="games_pick").value
    assert f"{game.away} {game.away_pts} @ {game.home} {game.home_pts}" in pick
    assert f"{game.game_date:%b %d}" in pick
    assert GAMES_PICK_KEY not in at.session_state
    # Read once, and the choice holds through another rerun.
    at.run()
    assert not at.exception, at.exception
    assert at.selectbox(key="games_pick").value == pick
