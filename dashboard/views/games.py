"""Games - browse results, game detail with box score and game-flow chart."""

import html

import pandas as pd
import streamlit as st

from dashboard.lib import db, glossary, media, tables
from dashboard.lib import theme as T
from dashboard.lib import viz
from dashboard.lib.tables import Col
from dashboard.views.overview import game_card


def _made(made, att) -> str:
    return f"{int(made)}-{int(att)}"


def _foot_pct(made, att) -> str:
    pct = f"{made / att:.1%}" if att else "-"
    return f'{_made(made, att)}<div class="pct">{pct}</div>'


def box_score_html(rows: pd.DataFrame, team: str, side: str, pts: int, won: bool) -> str:
    """One team's box score card: logo, score, a row per player who played
    (most minutes first), team totals, and who didn't play."""
    played = rows[rows["min"].fillna(0) > 0].copy()
    dnp = rows.loc[rows["min"].fillna(0) <= 0, "player"].tolist()
    for col, m, a in (("fg", "fgm", "fga"), ("tp", "tpm", "tpa"), ("ft", "ftm", "fta")):
        played[col] = [_made(x, y) for x, y in zip(played[m], played[a])]
    top = played["pts"].max() if len(played) else None
    cols = [
        Col("player", "Player", left=True, css=lambda v: "name"),
        Col("min", "MIN"),
        Col("pts", "PTS", css=lambda v: "hi" if v == top else ""),
        Col("reb", "REB"),
        Col("ast", "AST"),
        Col("stl", "STL"),
        Col("blk", "BLK"),
        Col("tov", "TO"),
        Col("fg", "FG", help="Field goals made-attempted."),
        Col("tp", "3P", help="Three-pointers made-attempted."),
        Col("ft", "FT", help="Free throws made-attempted."),
        Col("plus_minus", "+/-", fmt=tables.signed, help=glossary.TERMS["+/-"], css=tables.pos_neg),
    ]
    sums = played[
        ["min", "pts", "reb", "ast", "stl", "blk", "tov", "fgm", "fga", "tpm", "tpa", "ftm", "fta"]
    ].sum()
    # No minutes total: each player's minutes are rounded, so they rarely add
    # up to exactly 240 and a "241" would read as an error.
    foot = {k: f"{int(sums[k])}" for k in ("pts", "reb", "ast", "stl", "blk", "tov")}
    foot.update(
        player="Team",
        fg=_foot_pct(sums.fgm, sums.fga),
        tp=_foot_pct(sums.tpm, sums.tpa),
        ft=_foot_pct(sums.ftm, sums.fta),
    )
    color = T.team_color(team)
    team_id = rows["team_id"].iloc[0] if len(rows) else None
    logo = (
        media.team_logo_html(int(team_id), team, size=34, color=color)
        if team_id is not None
        else T.team_dot(team)
    )
    head = (
        f'<div class="bip-box-head">{logo}<span class="tm">{html.escape(team)}</span>'
        f'<span class="side">{side}</span>'
        f'<span class="sc{" winner" if won else ""}">{pts}</span></div>'
    )
    dnp_html = (
        f'<div class="bip-box-dnp">Did not play: {html.escape(", ".join(dnp))}</div>' if dnp else ""
    )
    return (
        f'<div class="bip-card" style="border-top:3px solid {color}">{head}'
        f"{tables.html_table(played, cols, foot=foot)}{dnp_html}</div>"
    )


def render() -> None:
    season = st.session_state.get("season") or db.latest_season()
    st.markdown(
        f"## Games &nbsp;{T.chip(season)}",
        unsafe_allow_html=True,
    )

    games = db.games_list(season)
    pbp_ids = db.pbp_game_ids()

    teams = ["All teams"] + sorted(set(games.home) | set(games.away))
    f1, f2 = st.columns([2, 3])
    team = f1.selectbox("Team", teams, label_visibility="collapsed")
    only_pbp = f2.toggle("Only games with play-by-play", value=False)

    view = games
    if team != "All teams":
        view = view[(view.home == team) | (view.away == team)]
    if only_pbp:
        view = view[view.game_id.isin(pbp_ids)]

    st.caption(f"{len(view):,} games - play-by-play ingested for {len(pbp_ids)} (newest first)")
    cols = st.columns(3)
    for i, r in enumerate(view.head(12).itertuples()):
        cols[i % 3].markdown(game_card(r), unsafe_allow_html=True)

    st.markdown("#### Game detail")
    view = view.copy()
    view["label"] = view.apply(
        lambda r: (
            f"{r.game_date:%b %d} | {r.away} {r.away_pts} @ {r.home} {r.home_pts}"
            + ("  [PBP]" if r.game_id in pbp_ids else "")
        ),
        axis=1,
    )
    pick = st.selectbox("Game", view["label"].head(200), label_visibility="collapsed")
    if not pick:
        return
    g = view[view.label == pick].iloc[0]

    if g.game_id in pbp_ids:
        pbp = db.game_pbp(g.game_id)
        v1, v2 = st.columns([3, 2])
        with v1:
            st.markdown("**Game flow** - score margin over time")
            st.plotly_chart(
                viz.game_worm(pbp, g.home, g.away), config=viz.PLOTLY_CONFIG, width="stretch"
            )
        with v2:
            st.markdown("**Shot chart** - every attempt, colored by team")
            st.plotly_chart(
                viz.shot_chart(pbp, g.home, g.away), config=viz.PLOTLY_CONFIG, width="stretch"
            )
    else:
        st.info(
            "No play-by-play ingested for this game yet - box score only. "
            "Pull more with `python ingestion/nba_ingest.py --pbp-games N`."
        )

    box = db.game_box_score(g.game_id)
    st.markdown("#### Box score")
    home_won = g.home_pts > g.away_pts
    for team, side, pts, won in (
        (g.away, "Away", g.away_pts, not home_won),
        (g.home, "Home", g.home_pts, home_won),
    ):
        st.markdown(
            box_score_html(box[box.team == team], team, side, int(pts), won), unsafe_allow_html=True
        )
