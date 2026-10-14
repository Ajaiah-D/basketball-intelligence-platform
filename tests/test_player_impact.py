"""The Arcade player model. The rate math and the fit are checked on synthetic
data; the rankings are checked against the real warehouse, because "the best
player-seasons look like the best player-seasons" is the property the game
actually depends on."""

import json

import duckdb
import numpy as np
import pandas as pd
import pytest

from ml.player_impact import STATS, build, fit_impact, relative_rates, write


def _zero_stats(n):
    return {s: [0] * n for s in STATS}


def test_relative_rates_subtract_the_season_league_per_36():
    df = pd.DataFrame({**_zero_stats(2), "season": ["A", "A"], "mins": [360, 360]})
    df["pts"] = [100, 20]
    out = relative_rates(df)
    # League per-36 = 120 / 720 * 36 = 6.0
    assert out["pts_r"].tolist() == pytest.approx([4.0, -4.0])
    assert out["tov_r"].tolist() == pytest.approx([0.0, 0.0])


def test_relative_rates_use_each_season_separately():
    df = pd.DataFrame({**_zero_stats(3), "season": ["A", "A", "B"],
                       "mins": [360, 360, 360]})
    df["pts"] = [100, 20, 50]
    out = relative_rates(df)
    # Season B has one player, so he is the league average.
    assert out["pts_r"].tolist() == pytest.approx([4.0, -4.0, 0.0])


def test_fit_impact_recovers_known_coefficients():
    rng = np.random.default_rng(0)
    n = 400
    df = pd.DataFrame({f"{s}_r": rng.normal(0, 3, n) for s in STATS})
    df["mins"] = rng.uniform(500, 3000, n)
    df["rel_pm"] = 1.5 * df["pts_r"] - 2.0 * df["tov_r"] + rng.normal(0, 0.1, n)
    coef, intercept = fit_impact(df)
    assert len(coef) == len(STATS)
    assert coef[STATS.index("pts")] == pytest.approx(1.5, abs=0.2)
    assert coef[STATS.index("tov")] == pytest.approx(-2.0, abs=0.2)
    assert intercept == pytest.approx(0.0, abs=0.2)


def _tiny_impact():
    return pd.DataFrame({
        "season": ["2015-16"], "player_id": [201939], "player": ["Stephen Curry"],
        "team": ["GSW"], "gp": [79], "mpg": [34.2], "ppg": [30.1], "rpg": [5.4],
        "apg": [6.7], "impact": [9.5], "usage": [1.6], "cost": [10],
    })


def _tiny_meta():
    return {"fitted_at": pd.Timestamp("2026-10-14 12:00:00"), "n_train": 100,
            "holdout_corr": 0.45, "team_scale": 1.0, "team_offset": 0.0,
            "team_r2": 0.8, "team_mae": 2.0, "usage_league_total": 5.0,
            "coef_json": json.dumps({"intercept": 0.1, "pts": 0.5})}


def test_write_creates_both_tables_with_the_exact_schema():
    con = duckdb.connect(":memory:")
    write(con, _tiny_impact(), _tiny_meta())
    write(con, _tiny_impact(), _tiny_meta())  # replaces, does not append
    types = dict(con.execute(
        "select column_name, data_type from information_schema.columns "
        "where table_schema = 'main' and table_name = 'player_impact' "
        "order by ordinal_position").fetchall())
    assert types == {
        "season": "VARCHAR", "player_id": "BIGINT", "player": "VARCHAR",
        "team": "VARCHAR", "gp": "INTEGER", "mpg": "DOUBLE", "ppg": "DOUBLE",
        "rpg": "DOUBLE", "apg": "DOUBLE", "impact": "DOUBLE", "usage": "DOUBLE",
        "cost": "INTEGER",
    }
    meta_types = dict(con.execute(
        "select column_name, data_type from information_schema.columns "
        "where table_schema = 'main' and table_name = 'player_impact_meta' "
        "order by ordinal_position").fetchall())
    assert meta_types == {
        "fitted_at": "TIMESTAMP", "n_train": "INTEGER", "holdout_corr": "DOUBLE",
        "team_scale": "DOUBLE", "team_offset": "DOUBLE", "team_r2": "DOUBLE",
        "team_mae": "DOUBLE", "usage_league_total": "DOUBLE",
        "coef_json": "VARCHAR",
    }
    assert con.execute("select count(*) from player_impact").fetchone()[0] == 1
    assert con.execute("select count(*) from player_impact_meta").fetchone()[0] == 1


# --- Real warehouse ------------------------------------------------------------

@pytest.fixture(scope="module")
def built(con):
    return build(con)


def test_the_best_seasons_are_recognisable_stars(built):
    impact, _ = built
    top10 = impact.nlargest(10, "impact")["player"].tolist()
    stars = {"Stephen Curry", "Nikola Jokić", "Michael Jordan", "LeBron James"}
    assert stars & set(top10), f"no all-time star in the top 10: {top10}"


def test_rebounding_specialists_are_not_rated_the_best_ever(built):
    impact, _ = built
    top50 = impact.nlargest(50, "impact")["player"].tolist()
    assert "Dennis Rodman" not in top50


def test_team_calibration_explains_real_net_rating(built):
    _, meta = built
    # Measured at 0.68 on the 2026-10-14 warehouse (1,177 team-seasons, MAE
    # 2.24). Team strength rebuilt from individual impacts can't explain
    # everything (coaching, fit, depth past the rotation), so 0.6 is the bar
    # for "the calibration still works", not the expected value.
    assert meta["team_r2"] > 0.6
    assert meta["usage_league_total"] == 5.0
    coefs = json.loads(meta["coef_json"])
    assert set(coefs) == {"intercept", *STATS}
    assert all(isinstance(v, float) for v in coefs.values())


def test_pool_is_eligible_and_costs_are_in_range(built):
    impact, _ = built
    assert impact["cost"].between(1, 10).all()
    assert (impact["gp"] >= 40).all()
    assert (impact["mpg"] >= 15).all()
    assert impact["season"].min() == "1985-86"
    assert not impact.duplicated(["season", "player_id"]).any()
