"""Overview - league pulse: KPIs, leaders, standings snapshot, recent games."""

import streamlit as st

from dashboard.lib import db, glossary, media
from dashboard.lib import theme as T

# Shooting-percentage cutoffs for a full season - the same volumes the
# Players page ranks percentiles against, so "qualified" means one thing.
FULL_SEASON_FGA = 300
FULL_SEASON_3PA = 100


def shooting_leaders(stats, pct_col: str, attempts_col: str, full_season_attempts: int,
                     n: int = 5):
    """(top n by pct_col among players with enough attempts, the cutoff used).

    Without a volume floor a bench player who went 3-for-3 leads 3P% at 100%.
    The floor scales with how far into the season the league is, so it isn't
    empty in November."""
    progress = min(1.0, stats["gp"].max() / 82) if len(stats) else 1.0
    floor = max(1, round(full_season_attempts * progress))
    return stats[stats[attempts_col] >= floor].nlargest(n, pct_col), floor


def team_points_per_game(games) -> float | None:
    """What one team scores in an average game. A game's two scores are two
    teams' outputs, so their sum (~231) is not "points per game" to a fan."""
    if not len(games):
        return None
    return float((games.home_pts + games.away_pts).mean() / 2)


def leaders_card(title: str, df, stat: str, help: str = "") -> str:
    rows = []
    for i, r in enumerate(df.itertuples(), 1):
        rows.append(
            f'<div class="bip-row">{T.rank_badge(i)}'
            f'<span class="bip-name">{r.player}</span>'
            f'<span class="bip-team" style="color:{T.team_color(r.team)}">{r.team}</span>'
            f'<span class="bip-val">{getattr(r, stat):.1f}</span></div>'
        )
    return T.card_html(title, "".join(rows), help)


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

    leader = qualified.nlargest(1, "ppg")
    spotlight = ""
    if len(leader):
        top = leader.iloc[0]
        spotlight = (
            f'<div class="bip-hero-spot">'
            f'<div><div class="lbl">Scoring leader</div>'
            f'<div class="name">{top.player}</div>'
            f'<div class="val">{top.ppg:.1f} PPG</div></div>'
            f'{media.avatar_html(int(top.player_id), top.player, size=86, ring=T.team_color(top.team))}'
            f'</div>'
        )
    st.markdown(
        f'<div class="bip-hero">'
        f'<div><div class="bip-hero-title">{season} Regular Season</div>'
        f'<div class="bip-hero-sub">{len(games):,} games &middot; '
        f'{len(stats):,} players &middot; league pulse, leaders and form</div></div>'
        f'{spotlight}</div>',
        unsafe_allow_html=True,
    )

    # One accent color for all four - matching every other page's KPI row
    # (Players, Teams, Finances) instead of a different color per tile with
    # no meaning behind the assignment.
    c1, c2, c3, c4 = st.columns(4)
    c1.markdown(T.kpi("Games", f"{len(games):,}"), unsafe_allow_html=True)
    c2.markdown(T.kpi("Players", f"{len(stats):,}"), unsafe_allow_html=True)
    team_ppg = team_points_per_game(games)
    c3.markdown(T.kpi("Points / game", f"{team_ppg:.1f}" if team_ppg is not None else "-",
                      help=("Average points one team scores in a game this season. "
                            + (f"Both teams together average {team_ppg * 2:.1f}."
                               if team_ppg is not None else ""))),
                unsafe_allow_html=True)
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

    # A second row of stats any fan knows. Efficiency metrics (true shooting,
    # usage, rebound rate) live on the Advanced page, with explanations -
    # they read as jargon on a landing page.
    fg, fga_floor = shooting_leaders(qualified, "fg_pct", "fga_total", FULL_SEASON_FGA)
    tp, tpa_floor = shooting_leaders(qualified, "fg3_pct", "tpa_total", FULL_SEASON_3PA)
    m1, m2, m3, m4 = st.columns(4)
    m1.markdown(leaders_card("Steals", qualified.nlargest(5, "spg"), "spg"),
                unsafe_allow_html=True)
    m2.markdown(leaders_card("Blocks", qualified.nlargest(5, "bpg"), "bpg"),
                unsafe_allow_html=True)
    m3.markdown(leaders_card("FG%", fg, "fg_pct", help=glossary.TERMS["FG%"]),
                unsafe_allow_html=True)
    m4.markdown(leaders_card("3P%", tp, "fg3_pct", help=glossary.TERMS["3P%"]),
                unsafe_allow_html=True)
    st.caption(f"FG% needs {fga_floor}+ shot attempts and 3P% {tpa_floor}+ "
               "three-point attempts, scaled to the season so far. Efficiency "
               "stats like true shooting and usage are on the Advanced page.")

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
