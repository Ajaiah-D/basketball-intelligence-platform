"""The Arcade's player card (Higher or Lower, Mystery Player) and the ages
db.arcade_pool attaches to it."""

import pandas as pd
import pytest

from dashboard.lib import db, media
from dashboard.views import arcade


def _row(**kw) -> pd.Series:
    base = {
        "player_id": 1,
        "player": "Ann <Example>",
        "season": "1988-89",
        "team": "CHI",
        "age": 26,
    }
    base.update(kw)
    return pd.Series(base)


@pytest.fixture(autouse=True)
def _no_headshots(monkeypatch):
    monkeypatch.setattr(media, "headshot_data_uri", lambda pid: None)


def test_card_puts_season_team_and_age_on_one_line_under_the_name():
    out = arcade.player_card(_row())
    meta = out[out.index('class="bip-pc-meta"') :]
    assert meta.index("1988-89") < meta.index("CHI") < meta.index("age <b>26</b>")
    assert "Ann &lt;Example&gt;" in out


@pytest.mark.parametrize("age", [None, pd.NA, float("nan")])
def test_card_leaves_out_an_unknown_age(age):
    assert "age" not in arcade.player_card(_row(age=age)).split('class="bip-pc-meta"')[1]


def test_stat_html_shows_value_and_label():
    out = arcade.stat_html("6.2", "RPG", "#0ca30c")
    assert ">6.2<" in out and ">RPG<" in out and "#0ca30c" in out


def test_ages_count_back_from_the_first_known_age(con):
    if not db.player_ages_available():
        pytest.skip("warehouse built before stg_player_advanced had age")
    pool = db.arcade_pool()
    known = pool.dropna(subset=["age"])
    assert len(known) and known["age"].between(17, 45).all()
    # Within one player's career, age rises exactly one year per season.
    years = known["season"].str[:4].astype(int)
    drift = (known["age"] - years).groupby(known["player_id"]).agg(["min", "max", "count"])
    # Only a player with two or more aged seasons can drift, so without one
    # the check below is vacuous. CI's fixtures have them: 1984-85 and
    # 1990-91 counted back from 1996-97's official ages.
    assert (drift["count"] >= 2).any(), "no player has two seasons with a known age"
    assert ((drift["max"] - drift["min"]) <= 1).all()


def test_old_warehouse_pool_has_an_empty_age_column(con, monkeypatch):
    monkeypatch.setattr(db, "player_ages_available", lambda: False)
    pool = db.arcade_pool()
    assert "age" in pool.columns and pool["age"].isna().all()


# --- Mystery Player: the age is part of the first clue -----------------------


def _mystery_row(**kw) -> pd.Series:
    base = {
        "player_id": 1,
        "player": "Ann Example",
        "season": "1994-95",
        "team": "CHI",
        "age": 27,
        "gp": 70,
        "ppg": 26.0,
        "rpg": 6.0,
        "apg": 5.0,
        "spg": 1.5,
        "bpg": 0.5,
        "tpg": 1.0,
        "tpa_pg": 3.0,
        "fg_pct": 48.0,
        "ft_pct": 80.0,
    }
    base.update(kw)
    return pd.Series(base)


def test_mystery_first_clue_includes_the_age():
    opener = arcade.my_clues(_mystery_row())[0]
    assert opener.startswith("A <b>27-year-old</b> <b>1990s</b>")


@pytest.mark.parametrize("age", [None, pd.NA])
def test_mystery_first_clue_without_a_known_age(age):
    opener = arcade.my_clues(_mystery_row(age=age))[0]
    assert opener.startswith("A <b>1990s</b>") and "year-old" not in opener
