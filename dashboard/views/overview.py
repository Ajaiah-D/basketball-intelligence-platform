"""Overview - league pulse: KPIs, leaders, standings snapshot, recent games."""

import streamlit as st

from dashboard.lib import db, media
from dashboard.lib import theme as T


def leaders_card(title: str, df, stat: str) -> str:
    rows = []
    for i, r in enumerate(df.itertuples(), 1):
        rows.append(
            f'<div class="bip-row">{T.rank_badge(i)}'
            f'<span class="bip-name">{r.player} '
            f'<span class="bip-team" style="color:{T.team_color(r.team)}">{r.team}</span></span>'
            f'<span class="bip-val">{getattr(r, stat):.1f}</span></div>'
        )
    return f'<div class="bip-card"><h4>{title}</h4>{"".join(rows)}</div>'


def standings_mini(df) -> str:
    rows = []
    for i, r in enumerate(df.itertuples(), 1):
        rows.append(
            f'<div class="bip-row">{T.rank_badge(i)}'
            f'<span class="bip-name">{T.team_dot(r.team)}{r.team_name}</span>'
            f'<span class="bip-team">{r.w}-{r.l}</span>'
            f'<span class="bip-val">{r.pct:.3f}</span></div>'
        )
    return "".join(rows)


def game_card(r) -> str:
    home_win = r.home_pts > r.away_pts
    aw = "" if home_win else " winner"
    hw = " winner" if home_win else ""
    return (
        f'<div class="bip-game">'
        f'<div class="bip-game-date">{r.game_date:%a, %b %d}</div>'
        f'<div class="bip-game-line"><span class="tm{aw}">{T.team_dot(r.away)}{r.away}</span>'
        f'<span class="sc{aw}">{r.away_pts}</span></div>'
        f'<div class="bip-game-line"><span class="tm{hw}">{T.team_dot(r.home)}{r.home}</span>'
        f'<span class="sc{hw}">{r.home_pts}</span></div>'
        f'</div>'
    )


def render() -> None:
    season = st.session_state.get("season") or db.latest_season()

    games = db.games_list(season)
    stats = db.player_season_stats(season)
    pbp_n = len(db.pbp_game_ids())

    top = stats[stats.gp >= 25].nlargest(1, "ppg").iloc[0]
    tc = T.team_color(top.team)
    st.markdown(
        f'<div class="bip-hero">'
        f'<div><div class="bip-hero-title">{season} Regular Season</div>'
        f'<div class="bip-hero-sub">{len(games):,} games &middot; '
        f'{len(stats):,} players &middot; league pulse, leaders and form</div></div>'
        f'<div class="bip-hero-spot">'
        f'<div><div class="lbl">Scoring leader</div>'
        f'<div class="name">{top.player}</div>'
        f'<div class="val">{top.ppg:.1f} PPG</div></div>'
        f'{media.avatar_html(int(top.player_id), top.player, size=86, ring=tc)}'
        f'</div></div>',
        unsafe_allow_html=True,
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.markdown(T.kpi("Games", f"{len(games):,}", accent=T.SERIES[0]),
                unsafe_allow_html=True)
    c2.markdown(T.kpi("Players", f"{len(stats):,}", accent=T.SERIES[1]),
                unsafe_allow_html=True)
    c3.markdown(T.kpi("Avg points / game", f"{(games.home_pts + games.away_pts).mean():.1f}",
                      accent=T.SERIES[2]), unsafe_allow_html=True)
    c4.markdown(T.kpi("Play-by-play games", f"{pbp_n}", "latest season only",
                      accent=T.SERIES[4]), unsafe_allow_html=True)

    st.markdown("#### League leaders")
    qualified = stats[stats.gp >= 25]
    l1, l2, l3, l4 = st.columns(4)
    l1.markdown(leaders_card("Points", qualified.nlargest(5, "ppg"), "ppg"),
                unsafe_allow_html=True)
    l2.markdown(leaders_card("Rebounds", qualified.nlargest(5, "rpg"), "rpg"),
                unsafe_allow_html=True)
    l3.markdown(leaders_card("Assists", qualified.nlargest(5, "apg"), "apg"),
                unsafe_allow_html=True)
    l4.markdown(leaders_card("3-pointers", qualified.nlargest(5, "tpg"), "tpg"),
                unsafe_allow_html=True)

    st.markdown("#### Standings")
    standings = db.standings(season)
    e, w = st.columns(2)
    with e:
        T.card(st, "Eastern Conference",
               standings_mini(standings[standings.conf == "East"].head(8)))
    with w:
        T.card(st, "Western Conference",
               standings_mini(standings[standings.conf == "West"].head(8)))
    st.caption("Full standings with form and scoring splits on the Teams page.")

    st.markdown("#### Latest games")
    recent = games.head(9)
    cols = st.columns(3)
    for i, r in enumerate(recent.itertuples()):
        cols[i % 3].markdown(game_card(r), unsafe_allow_html=True)
