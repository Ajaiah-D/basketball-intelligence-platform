"""Games - browse results, game detail with box score and game-flow chart."""

import streamlit as st

from dashboard.lib import db
from dashboard.lib import theme as T
from dashboard.lib import viz
from dashboard.views.overview import game_card


def render() -> None:
    season = st.session_state.get("season") or db.latest_season()
    st.markdown(
        f'## Games &nbsp;{T.chip(season)}',
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

    st.caption(f"{len(view):,} games - play-by-play ingested for {len(pbp_ids)} "
               "(newest first)")
    cols = st.columns(3)
    for i, r in enumerate(view.head(12).itertuples()):
        cols[i % 3].markdown(game_card(r), unsafe_allow_html=True)

    st.markdown("#### Game detail")
    view = view.copy()
    view["label"] = view.apply(
        lambda r: f"{r.game_date:%b %d} | {r.away} {r.away_pts} @ {r.home} {r.home_pts}"
                  + ("  [PBP]" if r.game_id in pbp_ids else ""),
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
            st.plotly_chart(viz.game_worm(pbp, g.home, g.away),
                            config=viz.PLOTLY_CONFIG, width="stretch")
        with v2:
            st.markdown("**Shot chart** - every attempt, colored by team")
            st.plotly_chart(viz.shot_chart(pbp, g.home, g.away),
                            config=viz.PLOTLY_CONFIG, width="stretch")
    else:
        st.info("No play-by-play ingested for this game yet - box score only. "
                "Pull more with `python ingestion/nba_ingest.py --pbp-games N`.")

    box = db.game_box_score(g.game_id)
    box["fg"] = box.fgm.astype(str) + "-" + box.fga.astype(str)
    box["tp"] = box.tpm.astype(str) + "-" + box.tpa.astype(str)
    cfg = {
        "player": st.column_config.TextColumn("Player", width="medium"),
        "min": "MIN", "pts": "PTS", "reb": "REB", "ast": "AST",
        "stl": "STL", "blk": "BLK", "fg": "FG", "tp": "3P",
        "plus_minus": st.column_config.NumberColumn("+/-", format="%d"),
    }
    cols_show = ["player", "min", "pts", "reb", "ast", "stl", "blk", "fg", "tp", "plus_minus"]
    b1, b2 = st.columns(2)
    with b1:
        st.markdown(f"**{g.away}** (away)")
        st.dataframe(box[box.team == g.away][cols_show], hide_index=True, column_config=cfg)
    with b2:
        st.markdown(f"**{g.home}** (home)")
        st.dataframe(box[box.team == g.home][cols_show], hide_index=True, column_config=cfg)
