"""The Arcade player model. The rate math and the fit are checked on synthetic
data; the rankings are checked against the real warehouse, because "the best
player-seasons look like the best player-seasons" is the property the game
actually depends on."""

import json

import duckdb
import numpy as np
import pandas as pd
import pytest

from ml.player_impact import (
    COST_QUANTILES,
    FIRST_PM_SEASON,
    HOLDOUT_SEASONS,
    STATS,
    build,
    costs_from_impact,
    fit_impact,
    relative_rates,
    write,
)


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
    df = pd.DataFrame({**_zero_stats(3), "season": ["A", "A", "B"], "mins": [360, 360, 360]})
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


def test_cost_tiers_run_one_to_twelve():
    assert COST_QUANTILES == [
        0.15,
        0.32,
        0.53,
        0.72,
        0.85,
        0.925,
        0.965,
        0.985,
        0.991,
        0.995,
        0.999,
    ]
    assert sorted(COST_QUANTILES) == COST_QUANTILES
    impact = pd.Series(np.random.default_rng(1).normal(0, 1.5, 20_000))
    cost = costs_from_impact(impact)
    assert cost.dtype.kind == "i"
    assert sorted(cost.unique()) == list(range(1, 13))
    # never cheaper for a better season
    assert cost.loc[impact.sort_values().index].is_monotonic_increasing
    # each tier's share is the gap between its quantiles
    edges = [0.0, *COST_QUANTILES, 1.0]
    expected = np.diff(edges)
    shares = cost.value_counts(normalize=True).sort_index().to_numpy()
    assert shares == pytest.approx(expected, abs=0.002)
    # cost 1 is replacement level (bottom 15%); 12 is the top one in 1,000
    assert (cost == 1).mean() == pytest.approx(0.15, abs=0.002)
    assert (cost == 12).mean() == pytest.approx(0.001, abs=0.0005)


def test_costs_from_impact_keeps_the_index():
    impact = pd.Series([3.0, -1.0, 0.5], index=[10, 20, 30])
    cost = costs_from_impact(impact)
    assert list(cost.index) == [10, 20, 30]
    assert cost[10] == 12 and cost[20] == 1


def _tiny_impact():
    return pd.DataFrame(
        {
            "season": ["2015-16"],
            "player_id": [201939],
            "player": ["Stephen Curry"],
            "team": ["GSW"],
            "gp": [79],
            "mpg": [34.2],
            "ppg": [30.1],
            "rpg": [5.4],
            "apg": [6.7],
            "impact": [9.5],
            "usage": [1.6],
            "cost": [10],
        }
    )


def _tiny_meta():
    return {
        "fitted_at": pd.Timestamp("2026-10-14 12:00:00"),
        "n_train": 100,
        "holdout_corr": 0.45,
        "team_scale": 1.0,
        "team_offset": 0.0,
        "team_r2": 0.8,
        "team_mae": 2.0,
        "usage_league_total": 5.0,
        "coef_json": json.dumps({"intercept": 0.1, "pts": 0.5}),
    }


def test_write_creates_both_tables_with_the_exact_schema():
    con = duckdb.connect(":memory:")
    write(con, _tiny_impact(), _tiny_meta())
    write(con, _tiny_impact(), _tiny_meta())  # replaces, does not append
    types = dict(
        con.execute(
            "select column_name, data_type from information_schema.columns "
            "where table_schema = 'main' and table_name = 'player_impact' "
            "order by ordinal_position"
        ).fetchall()
    )
    assert types == {
        "season": "VARCHAR",
        "player_id": "BIGINT",
        "player": "VARCHAR",
        "team": "VARCHAR",
        "gp": "INTEGER",
        "mpg": "DOUBLE",
        "ppg": "DOUBLE",
        "rpg": "DOUBLE",
        "apg": "DOUBLE",
        "impact": "DOUBLE",
        "usage": "DOUBLE",
        "cost": "INTEGER",
    }
    meta_types = dict(
        con.execute(
            "select column_name, data_type from information_schema.columns "
            "where table_schema = 'main' and table_name = 'player_impact_meta' "
            "order by ordinal_position"
        ).fetchall()
    )
    assert meta_types == {
        "fitted_at": "TIMESTAMP",
        "n_train": "INTEGER",
        "holdout_corr": "DOUBLE",
        "team_scale": "DOUBLE",
        "team_offset": "DOUBLE",
        "team_r2": "DOUBLE",
        "team_mae": "DOUBLE",
        "usage_league_total": "DOUBLE",
        "coef_json": "VARCHAR",
    }
    assert con.execute("select count(*) from player_impact").fetchone()[0] == 1
    assert con.execute("select count(*) from player_impact_meta").fetchone()[0] == 1


# --- Synthetic warehouse: build() end to end, runs in CI ----------------------

META_KEYS = {
    "fitted_at",
    "n_train",
    "holdout_corr",
    "team_scale",
    "team_offset",
    "team_r2",
    "team_mae",
    "usage_league_total",
    "coef_json",
}
TRADED = 99
TRADE_SEASON = "1997-98"


def _synthetic_warehouse(n_seasons):
    """Two teams, five regulars each, 50 head-to-head games a season. Player
    99 plays every game; in TRADE_SEASON he starts on BBB and is traded to
    AAA halfway through, so his path must read "BBB → AAA" even though AAA
    sorts first."""
    rng = np.random.default_rng(7)
    seasons = [f"{1996 + i}-{(97 + i) % 100:02d}" for i in range(n_seasons)]
    roster = {"AAA": [1, 2, 3, 4, 5], "BBB": [6, 7, 8, 9, 10]}
    skill = {p: rng.uniform(0.6, 1.6) for p in [*range(1, 11), TRADED]}
    rows = []
    for season in seasons:
        start = pd.Timestamp(f"{season[:4]}-11-01")
        for g in range(50):
            day = start + pd.Timedelta(days=2 * g)
            traded_team = "BBB" if season == TRADE_SEASON and g < 25 else "AAA"
            for team, players in roster.items():
                lineup = players + ([TRADED] if team == traded_team else [])
                for pid in lineup:
                    k = skill[pid]
                    rows.append(
                        {
                            "season": season,
                            "player_id": pid,
                            "player_name": f"Player {pid}",
                            "team_abbreviation": team,
                            "game_date": day.date(),
                            "minutes_played": 30,
                            "points": rng.poisson(14 * k),
                            "offensive_rebounds": rng.poisson(2),
                            "defensive_rebounds": rng.poisson(4),
                            "total_rebounds": 0,
                            "assists": rng.poisson(3 * k),
                            "steals": rng.poisson(1),
                            "blocks": rng.poisson(0.6),
                            "turnovers": rng.poisson(2),
                            "field_goals_attempted": rng.poisson(11 * k),
                            "free_throws_attempted": rng.poisson(4),
                            "three_pointers_made": rng.poisson(1.5 * k),
                            "personal_fouls": rng.poisson(2.5),
                            "plus_minus": int(rng.normal(8 * (k - 1.1), 10)),
                        }
                    )
    logs = pd.DataFrame(rows)
    logs["total_rebounds"] = logs["offensive_rebounds"] + logs["defensive_rebounds"]
    teams = pd.DataFrame(
        [
            {"season": s, "team_abbreviation": t, "net_rating": rng.normal(0, 5)}
            for s in seasons
            for t in roster
        ]
    )
    con = duckdb.connect(":memory:")
    con.execute("create schema main_staging")
    con.execute("create schema main_marts")
    con.register("_logs", logs)
    con.register("_teams", teams)
    con.execute("create table main_staging.stg_player_game_logs as select * from _logs")
    con.execute("create table main_marts.mart_team_season as select * from _teams")
    return con


def test_build_runs_end_to_end_on_a_synthetic_warehouse():
    impact, meta = build(_synthetic_warehouse(8))

    assert set(meta) == META_KEYS
    assert np.isfinite(meta["holdout_corr"])
    assert set(json.loads(meta["coef_json"])) == {"intercept", *STATS}

    # Everyone here is eligible, so the minutes-weighted usage of the pool
    # is the whole league's: exactly 1.0 each season.
    mins = impact["gp"] * impact["mpg"]
    weighted = (impact["usage"] * mins).groupby(impact["season"]).sum() / mins.groupby(
        impact["season"]
    ).sum()
    assert weighted.tolist() == pytest.approx([1.0] * 8)

    assert impact["cost"].between(1, 12).all()
    by_impact = impact.sort_values("impact")
    assert by_impact["cost"].is_monotonic_increasing

    traded = impact[impact["player_id"] == TRADED].set_index("season")["team"]
    assert traded[TRADE_SEASON] == "BBB → AAA"
    assert traded["1996-97"] == "AAA"
    assert (
        impact.loc[
            (impact["player_id"] == TRADED) & (impact["season"] == TRADE_SEASON), "gp"
        ].item()
        == 50
    )


def test_build_survives_a_warehouse_too_short_for_a_holdout():
    _, meta = build(_synthetic_warehouse(3))
    assert np.isnan(meta["holdout_corr"])


# --- Real warehouse ------------------------------------------------------------


@pytest.fixture(scope="module")
def built(con):
    n = con.execute(
        "select count(distinct season) from main_staging.stg_player_game_logs where season >= ?",
        [FIRST_PM_SEASON],
    ).fetchone()[0]
    if n < HOLDOUT_SEASONS + 1:
        # CI's fixture warehouse has a single post-1996 season. The rankings
        # and calibration checks below only mean anything on the full one,
        # so they are marked full_warehouse and CI deselects them; this skip
        # is for a partial local warehouse.
        pytest.skip(f"needs the full warehouse ({n} plus-minus seasons here)")
    return build(con)


@pytest.mark.full_warehouse
def test_the_best_seasons_are_recognisable_stars(built):
    impact, _ = built
    top10 = impact.nlargest(10, "impact")["player"].tolist()
    stars = {"Stephen Curry", "Nikola Jokić", "Michael Jordan", "LeBron James"}
    assert stars & set(top10), f"no all-time star in the top 10: {top10}"


@pytest.mark.full_warehouse
def test_rebounding_specialists_are_not_rated_the_best_ever(built):
    impact, _ = built
    top50 = impact.nlargest(50, "impact")["player"].tolist()
    assert "Dennis Rodman" not in top50


@pytest.mark.full_warehouse
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


@pytest.mark.full_warehouse
def test_pool_is_eligible_and_costs_are_in_range(built):
    impact, _ = built
    assert impact["cost"].between(1, 12).all()
    assert (impact["gp"] >= 40).all()
    assert (impact["mpg"] >= 15).all()
    assert impact["season"].min() == "1985-86"
    assert not impact.duplicated(["season", "player_id"]).any()
