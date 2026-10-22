"""Build a team's projection: the team rating from the impact model, 1,000
simulated seasons against real opponents, the results row, the best-five
hint and one played-out season. Both Build and Draft end here.

The numbers come from lib/sim.py (ratings and seasons) and lib/draft.py
(rotation rules); this module is only the page.
"""

import html

import numpy as np
import pandas as pd
import streamlit as st

from core.constants import COMPLETE_BOX_SCORE_FIRST_SEASON, PLAYERS_ON_FLOOR
from dashboard.lib import draft, glossary, sim
from dashboard.lib import theme as T
from dashboard.lib.data import advanced
from dashboard.lib.data import arcade as arcade_data
from dashboard.views.arcade.team_builder import state as tb_state


def _pct(p: float) -> str:
    if 0 < p < 0.005:
        return "<1%"
    if 0.995 <= p < 1:
        return ">99%"
    return f"{p:.0%}"


def _rating(net: float) -> float:
    """A rating ready for a one-decimal "%+.1f": anything that would round to
    zero becomes exactly 0.0, so it shows as "+0.0", never "-0.0"."""
    net = float(net)
    return 0.0 if abs(net) < 0.05 else net


def _record(wins: int) -> str:
    return f"{int(wins)}-{sim.SEASON_GAMES - int(wins)}"


def _row_keys(rows: pd.DataFrame) -> list[str]:
    """'player_id:season' per row - the same player in two seasons differs."""
    return [f"{int(p)}:{s}" for p, s in zip(rows["player_id"], rows["season"], strict=True)]


def model_meta() -> tuple[float, float, float]:
    """(team_scale, team_offset, usage_league_total) from the impact model."""
    m = arcade_data.player_impact_meta()
    return (
        float(m.get("team_scale", 1.0)),
        float(m.get("team_offset", 0.0)),
        float(m.get("usage_league_total", PLAYERS_ON_FLOOR)),
    )


def _team_net(rows: pd.DataFrame, meta, ordered: bool = False) -> float:
    """Net rating of an 8-man roster. With ordered=True the rows are already
    in rotation order (the first five start); otherwise the best five by
    impact start."""
    rot = rows if ordered else draft.auto_rotation(rows)
    scale, offset, usage_total = meta
    return float(
        sim.team_net_rating(
            rot["impact"], rot["usage"], scale, offset, usage_league_total=usage_total
        )
    )


def _opponents(season: str | None) -> tuple[list[float], list[str], str]:
    """Build mode's league: (net ratings, labels, source).

    source is "season" (that season's real teams), "all-time" (29 real
    team-seasons from 1985-86 on, always the same 29: seed 7; also the
    fallback when a season has no team ratings) or "average" (a placeholder
    average team, for a warehouse with no team ratings at all)."""
    if season is not None:
        teams = advanced.team_advanced(season)
        teams = teams[teams["net_rating"].notna()].sort_values("team_abbreviation")
        if len(teams) >= 2:
            return (
                teams["net_rating"].astype(float).tolist(),
                teams["team_abbreviation"].tolist(),
                "season",
            )
    every = arcade_data.all_team_net_ratings()
    if not len(every):
        return [0.0], ["an average team"], "average"
    idx = np.random.default_rng(7).choice(len(every), size=min(29, len(every)), replace=False)
    drawn = every.iloc[idx]
    return (
        drawn["net_rating"].astype(float).tolist(),
        (drawn["season"] + " " + drawn["team"]).tolist(),
        "all-time",
    )


def _cached(key, compute):
    """Projection cache in session_state; the seed is tied to the roster, so
    a rerun would only recompute the same numbers."""
    cache = st.session_state.setdefault(tb_state.PROJ, {})
    if key not in cache:
        if len(cache) > 32:
            cache.clear()
        cache[key] = compute()
    return cache[key]


def _results_row(
    net: float,
    median: int,
    p10: int,
    p90: int,
    odds_label: str,
    odds: float,
    rating_sub: str = "points per 100 vs. an average team",
) -> None:
    c1, c2, c3, c4 = st.columns(4)
    c1.markdown(
        T.kpi(
            "Team rating",
            f"{_rating(net):+.1f}",
            sub=rating_sub,
            help=glossary.TERMS["Team rating"],
        ),
        unsafe_allow_html=True,
    )
    c2.markdown(
        T.kpi(
            "Projected record",
            _record(median),
            sub="median of 1,000 seasons",
            help=glossary.TERMS["Projected record"],
        ),
        unsafe_allow_html=True,
    )
    c3.markdown(
        T.kpi(
            "Range",
            f"{p10}-{p90} wins",
            sub="10th to 90th percentile",
            help=glossary.TERMS["Win range"],
        ),
        unsafe_allow_html=True,
    )
    c4.markdown(
        T.kpi(
            odds_label, _pct(odds), sub="share of 1,000 seasons", help=glossary.TERMS[odds_label]
        ),
        unsafe_allow_html=True,
    )


def _tb_best_five(order: list[tuple[int, str]], mode: str) -> None:
    if mode == "draft":
        st.session_state[tb_state.PICK]["picks"] = list(order)
    else:
        st.session_state[tb_state.BUILD_SLOTS] = list(order)


def _tb_sim_build(key, net: float, opp_nets: list[float], names: list[str]) -> None:
    st.session_state[tb_state.BUILD_SEASON] = {
        "key": key,
        "names": names,
        "result": sim.simulate_season_once(net, opp_nets, np.random.default_rng()),
    }


def _streaks(results: list[bool]) -> tuple[int, int]:
    """(longest winning streak, longest losing streak)."""
    best = worst = run = 0
    prev = None
    for won in results:
        run = run + 1 if won == prev else 1
        prev = won
        if won:
            best = max(best, run)
        else:
            worst = max(worst, run)
    return best, worst


def _season_card(season: dict) -> str:
    res, names = season["result"], season["names"]
    dots = []
    for k, (opp, home, margin, won) in enumerate(res["games"]):
        title = (
            f"Game {k + 1}: {'vs' if home else 'at'} {names[opp]} - "
            f"{'won' if won else 'lost'} by {max(1, round(abs(margin)))}"
        )
        dots.append(
            f'<span class="dot {"dot-w" if won else "dot-l"}" '
            f'title="{html.escape(title, quote=True)}" style="border-radius:1px;'
            f'width:10px;height:10px;margin:0 2px 3px 0"></span>'
        )
    best, worst = _streaks([g[3] for g in res["games"]])
    body = (
        f'<div class="bip-kpi-value">{res["wins"]}-{res["losses"]}</div>'
        f'<div style="display:flex;flex-wrap:wrap;margin:.6rem 0 .45rem">'
        f"{''.join(dots)}</div>"
        f'<div class="bip-kpi-sub">Longest winning streak <b>{best}</b> &middot; '
        f"longest losing streak <b>{worst}</b> &middot; green is a win, red a loss; "
        f"hover a square for the game</div>"
    )
    return T.card_html("One simulated season", body)


def build_results(
    rows: pd.DataFrame, season: str | None, choice: str, meta, mode: str = "build"
) -> None:
    """Projection for a full roster against real teams (both modes); `rows`
    are in spot order, so the first five are the starters."""
    keys = _row_keys(rows)
    starters, bench = keys[: sim.STARTERS], keys[sim.STARTERS :]
    # The linear calibration would rate a roster of eight star seasons far
    # past any real team; past +10 the soft ceiling keeps it near the best
    # ever (anything up to +10 is left as is).
    net = sim.soft_cap(_team_net(rows, meta, ordered=True))
    opp_nets, opp_names, source = _opponents(season)
    # Order within the starters (or the bench) doesn't change the minutes.
    cache_key = (mode, choice, tuple(sorted(starters)), tuple(sorted(bench)))

    def project() -> dict:
        res = sim.simulate_vs_league(net, opp_nets, np.random.default_rng(sim.roster_seed(keys)))
        return {k: res[k] for k in ("median", "p10", "p90", "best_record_odds")}

    proj = _cached(cache_key, project)
    st.markdown("#### Projection")
    _results_row(
        net, proj["median"], proj["p10"], proj["p90"], "Best-record odds", proj["best_record_odds"]
    )
    _best_five_hint(rows, net, meta, mode)
    if source == "season":
        against = (
            f"82 games against {season}'s {len(opp_nets)} real teams, each at its real net rating."
        )
    elif source == "all-time":
        lead = f"{season} has no team ratings, so it's " if season is not None else ""
        against = (
            f"{lead}82 games against {len(opp_nets)} real team-seasons drawn "
            f"from {COMPLETE_BOX_SCORE_FIRST_SEASON} on, each at its real net rating."
        )
    else:
        against = (
            "82 games against an average team - this copy of the data has no team ratings yet."
        )
    st.caption(against)
    st.button(
        "Simulate a season",
        key="tb_build_sim",
        type="primary",
        on_click=_tb_sim_build,
        args=(cache_key, net, opp_nets, opp_names),
    )
    played = st.session_state.get(tb_state.BUILD_SEASON)
    if played and played["key"] == cache_key:
        st.markdown(_season_card(played), unsafe_allow_html=True)


def _best_five_hint(rows: pd.DataFrame, net: float, meta, mode: str) -> None:
    """One-click fix when starting the five best impacts would rate higher."""
    best = draft.auto_rotation(rows)
    best_net = sim.soft_cap(_team_net(best, meta, ordered=True))
    gain = best_net - net
    if gain < 0.05:
        return
    c1, c2 = st.columns([1, 4], vertical_alignment="center")
    c1.button(
        "Start the best five",
        key="tb_best_five",
        width="stretch",
        on_click=_tb_best_five,
        args=(
            [(int(p), str(s)) for p, s in zip(best["player_id"], best["season"], strict=True)],
            mode,
        ),
    )
    c2.caption(
        f"Some of your best players are on the bench. Starting the five "
        f"highest impacts would raise the team rating by {gain:.1f}."
    )
