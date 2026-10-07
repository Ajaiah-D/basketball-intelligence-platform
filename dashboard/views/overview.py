"""Overview - league pulse: KPIs, leaders, standings snapshot, recent games."""

import pandas as pd
import streamlit as st

from dashboard.lib import db, glossary, media
from dashboard.lib import theme as T

# Assist-to-turnover only means something for players who actually run an
# offense: a center with 40 assists and 8 turnovers would otherwise lead.
AST_TO_MIN_APG = 3.0
CLOSE_GAME_MARGIN = 5


def ast_to_leaders(stats, n: int = 5):
    """Top n by assists per turnover among players averaging 3+ assists."""
    return stats[stats["apg"] >= AST_TO_MIN_APG].nlargest(n, "ast_to")


def close_game_share(games) -> float | None:
    """Share of games decided by CLOSE_GAME_MARGIN points or fewer."""
    if not len(games):
        return None
    margin = (games.home_pts - games.away_pts).abs()
    return float((margin <= CLOSE_GAME_MARGIN).mean())


def best_record_spot(standings) -> str:
    """The banner's right side: the team with the league's best record."""
    if standings.empty:
        return ""
    top = standings.iloc[0]  # db.standings() is already ordered best record first
    color = T.team_color(top.team)
    return (
        f'<div class="bip-hero-spot">'
        f'<div><div class="lbl">Best record</div>'
        f'<div class="name">{top.team_name}</div>'
        f'<div class="val" style="color:{color}">{top.w}-{top.l}</div></div>'
        f'{media.team_logo_html(int(top.team_id), top.team, size=86, color=color)}'
        f'</div>'
    )


def leaders_card(title: str, df, stat: str, help: str = "", fmt: str = "{:.1f}") -> str:
    rows = []
    for i, r in enumerate(df.itertuples(), 1):
        rows.append(
            f'<div class="bip-row">{T.rank_badge(i)}'
            f'<span class="bip-name">{r.player}</span>'
            f'<span class="bip-team" style="color:{T.team_color(r.team)}">{r.team}</span>'
            f'<span class="bip-val">{fmt.format(getattr(r, stat))}</span></div>'
        )
    return T.card_html(title, "".join(rows), help)


def adv_leaders_card(title: str, df, stat: str) -> str:
    """Same card as leaders_card, for the advanced mart's column names."""
    rows = []
    for i, r in enumerate(df.itertuples(), 1):
        rows.append(
            f'<div class="bip-row">{T.rank_badge(i)}'
            f'<span class="bip-name">{r.player_name}</span>'
            f'<span class="bip-team" style="color:{T.team_color(r.team_abbreviation)}">'
            f'{r.team_abbreviation}</span>'
            f'<span class="bip-val">{getattr(r, stat):.1f}</span></div>'
        )
    return T.card_html(title, "".join(rows), glossary.TERMS.get(title, ""))


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

    # Early in a live season nobody has played enough games for a fixed cut,
    # so the threshold scales with the season's progress (see db).
    min_gp = db.qualification_threshold(stats)
    qualified = stats[stats.gp >= min_gp]

    standings = db.standings(season)
    st.markdown(
        f'<div class="bip-hero">'
        f'<div><div class="bip-hero-title">{season} Regular Season</div>'
        f'<div class="bip-hero-sub">{len(games):,} games &middot; '
        f'{len(stats):,} players &middot; league pulse, leaders and form</div></div>'
        f'{best_record_spot(standings)}</div>',
        unsafe_allow_html=True,
    )

    # One accent color for all four - matching every other page's KPI row
    # (Players, Teams, Finances) instead of a different color per tile with
    # no meaning behind the assignment.
    c1, c2, c3, c4 = st.columns(4)
    c1.markdown(T.kpi("Games", f"{len(games):,}"), unsafe_allow_html=True)
    c2.markdown(T.kpi("Players", f"{len(stats):,}"), unsafe_allow_html=True)
    close = close_game_share(games)
    c3.markdown(T.kpi("Close games", f"{close:.0%}" if close is not None else "-",
                      help=glossary.TERMS["Close games"]), unsafe_allow_html=True)
    c4.markdown(T.kpi("Play-by-play games", f"{pbp_n}", note="latest season only"),
                unsafe_allow_html=True)

    st.markdown("#### League leaders")
    l1, l2, l3, l4 = st.columns(4)
    l1.markdown(leaders_card("Points", qualified.nlargest(5, "ppg"), "ppg"),
                unsafe_allow_html=True)
    l2.markdown(leaders_card("Rebounds", qualified.nlargest(5, "rpg"), "rpg"),
                unsafe_allow_html=True)
    l3.markdown(leaders_card("Assists", qualified.nlargest(5, "apg"), "apg"),
                unsafe_allow_html=True)
    l4.markdown(leaders_card("3-pointers", qualified.nlargest(5, "tpg"), "tpg"),
                unsafe_allow_html=True)
    st.caption(f"Per-game averages, minimum {min_gp} games played.")

    # Counting stats alone reward volume, so give efficiency its own row.
    # Skipped silently when the warehouse has no marts: this is a bonus
    # section, not a reason for the landing page to fail.
    adv = db.player_advanced(season) if db.marts_available() else pd.DataFrame()
    if not adv.empty:
        floor = min(500, max(50, int(adv["minutes"].max() * 0.3)))
        eff = adv[adv.minutes >= floor]
        if len(eff) >= 5:
            st.markdown("#### Efficiency leaders")
            e1, e2, e3, e4 = st.columns(4)
            e1.markdown(adv_leaders_card("True shooting",
                                         eff.nlargest(5, "true_shooting_pct"),
                                         "true_shooting_pct"), unsafe_allow_html=True)
            e2.markdown(adv_leaders_card("Usage", eff.nlargest(5, "usage_pct"),
                                         "usage_pct"), unsafe_allow_html=True)
            e3.markdown(adv_leaders_card("Game score", eff.nlargest(5, "game_score"),
                                         "game_score"), unsafe_allow_html=True)
            # Assist-to-turnover replaces rebound rate here: a playmaking
            # efficiency most fans already read, where rebound rate was jargon.
            e4.markdown(leaders_card("AST/TO", ast_to_leaders(qualified), "ast_to",
                                     help=glossary.TERMS["AST/TO"], fmt="{:.2f}"),
                        unsafe_allow_html=True)
            st.caption(f"True shooting, usage and game score: minimum {floor} minutes. "
                       f"AST/TO: players averaging {AST_TO_MIN_APG:.0f}+ assists. "
                       "Full detail on the Advanced page.")

    st.markdown("#### Standings")
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
