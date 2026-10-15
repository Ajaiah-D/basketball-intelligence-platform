"""Arcade - games built on 47 seasons of real NBA data.

Higher or Lower: two player-seasons from any era, guess who averaged more.
Mystery Player: identify a notable player-season from progressive clues.
Build a team: pick eight player-seasons under a budget (Build) or snake-draft
against five CPU teams (Draft), then simulate seasons (lib/sim.py).

Build a team keeps all of its state in st.session_state under "tb_" keys:
  tb_mode          "Build" | "Draft" (the segmented control)
  tb_pool          "All-time" | a season like "2024-25" (the selectbox)
  tb_search        the pool table's search text
  tb_nonce         int, part of the pool table's widget key; bumped after a
                   pick so the table's row selection starts empty again
  tb_build_picks   Build roster: list of (player_id, season) pairs, pick
                   order (display order is by impact, so order is cosmetic)
  tb_build_season  {"key": roster key, "result": sim.simulate_season_once,
                   "names": opponent labels} - the last "Simulate a season"
  tb_draft         Draft state from draft.new_draft (rosters hold index labels
                   of db.player_impact_pool(season) - its RangeIndex) plus
                   "pool": the pool choice the draft was started with
  tb_draft_season  {"key": league key, "result": sim.simulate_league_once}
  tb_proj          {roster/league key: projection dict} - projections are
                   seeded from the roster, so they are cached per roster
Changing the mode or the pool, or "Start over", clears every one of the game
keys (tb_build_*, tb_draft*, tb_proj) and the search.
"""

import html
import random
import unicodedata
import zlib

import numpy as np
import pandas as pd
import streamlit as st

from dashboard.lib import db, draft, glossary, media, sim
from dashboard.lib import theme as T

STATS = {
    "ppg": ("points", "PPG"),
    "rpg": ("rebounds", "RPG"),
    "apg": ("assists", "APG"),
    "tpg": ("threes made", "3PM/game"),
}


def _pool():
    return db.arcade_pool()


def player_card(r, value_html: str = "") -> str:
    tc = T.team_color(r.team)
    return (
        f'<div class="bip-card" style="text-align:center;'
        f'border-top:3px solid {tc}">'
        f'<div style="margin-bottom:.45rem">'
        f'{media.avatar_html(int(r.player_id), r.player, size=76, ring=tc)}</div>'
        f'<div class="bip-kpi-label">{r.season} &middot; '
        f'<span style="color:{tc}">{r.team}</span></div>'
        f'<div class="bip-kpi-value" style="font-size:1.35rem">{r.player}</div>'
        f'{value_html}</div>'
    )


# --- Higher or Lower ------------------------------------------------------------

def hl_new_round() -> None:
    pool = _pool()
    stat = random.choice(list(STATS))
    # pick two seasons with meaningfully different values so rounds are fair
    for _ in range(50):
        pair = pool.sample(2)
        a, b = pair.iloc[0], pair.iloc[1]
        if abs(a[stat] - b[stat]) >= 0.6:
            break
    st.session_state.hl = {"a": a, "b": b, "stat": stat, "phase": "guess",
                           "correct": None}


def hl_pick(side: str) -> None:
    g = st.session_state.hl
    a, b, stat = g["a"], g["b"], g["stat"]
    picked, other = (a, b) if side == "a" else (b, a)
    correct = picked[stat] >= other[stat]
    g["phase"] = "reveal"
    g["correct"] = correct
    if correct:
        st.session_state.hl_streak = st.session_state.get("hl_streak", 0) + 1
        st.session_state.hl_best = max(st.session_state.get("hl_best", 0),
                                       st.session_state.hl_streak)
    else:
        st.session_state.hl_streak = 0


def render_higher_lower() -> None:
    if "hl" not in st.session_state:
        hl_new_round()
    g = st.session_state.hl
    a, b, stat = g["a"], g["b"], g["stat"]
    noun, label = STATS[stat]

    s1, s2, _ = st.columns([1, 1, 3])
    s1.markdown(T.kpi("Streak", str(st.session_state.get("hl_streak", 0))),
                unsafe_allow_html=True)
    s2.markdown(T.kpi("Best", str(st.session_state.get("hl_best", 0))),
                unsafe_allow_html=True)

    st.markdown(f"#### Who averaged more **{noun}** ({label})?")
    c1, c2 = st.columns(2)
    if g["phase"] == "guess":
        with c1:
            st.markdown(player_card(a), unsafe_allow_html=True)
            st.button(f"Pick {a.player}", key="hl_a", width="stretch",
                      on_click=hl_pick, args=("a",))
        with c2:
            st.markdown(player_card(b), unsafe_allow_html=True)
            st.button(f"Pick {b.player}", key="hl_b", width="stretch",
                      on_click=hl_pick, args=("b",))
    else:
        winner_is_a = a[stat] >= b[stat]
        for col, r, won in ((c1, a, winner_is_a), (c2, b, not winner_is_a)):
            val_color = "#0ca30c" if won else "#898781"
            col.markdown(player_card(
                r, f'<div style="font-size:1.6rem;font-weight:700;'
                   f'color:{val_color}">{r[stat]:.1f} {label}</div>'),
                unsafe_allow_html=True)
        if g["correct"]:
            st.success(f"Correct! Streak: {st.session_state.hl_streak}")
        else:
            st.error(f"Wrong - streak over. Best this session: "
                     f"{st.session_state.get('hl_best', 0)}")
        st.button("Next matchup", type="primary", on_click=hl_new_round)


# --- Mystery Player -------------------------------------------------------------

MAX_GUESSES = 6
DIFFICULTIES = {
    "Legends (easier)": 24.0,   # superstar seasons only - famous names
    "All-Stars (harder)": 18.0,
}


def my_new_game() -> None:
    pool = _pool()
    min_ppg = DIFFICULTIES[st.session_state.get("my_difficulty",
                                                "Legends (easier)")]
    stars = pool[pool.ppg >= min_ppg]
    st.session_state.my = {"row": stars.sample(1).iloc[0], "guesses": [],
                           "done": False, "won": False}


def archetype(r) -> str:
    """Rough stat-profile label so the opening clue narrows the field."""
    if r.bpg >= 1.8 or (r.rpg >= 10 and r.apg < 4):
        role = "big man"
    elif r.apg >= 6.5:
        role = "playmaker"
    elif r.rpg >= 6.5:
        role = "do-it-all forward"
    else:
        role = "scoring guard/wing"
    volume = "high-volume three-point shooter" if r.tpa_pg == r.tpa_pg and r.tpa_pg >= 6 \
        else ("rarely shot threes" if r.tpa_pg != r.tpa_pg or r.tpa_pg < 1.5
              else "moderate three-point volume")
    return f"{role}, {volume}"


def my_clues(r) -> list[str]:
    """Clue strings are rendered inside raw HTML cards, so emphasis must be
    HTML tags - markdown syntax like **bold** is NOT processed there."""
    decade = f"{r.season[:3]}0s"
    tier = ('30+' if r.ppg >= 30 else '25+' if r.ppg >= 25
            else '20+' if r.ppg >= 20 else 'under 20')
    opener = (f"A <b>{decade}</b> {db.conference(r.team)} player &middot; "
              f"profile: <b>{archetype(r)}</b> &middot; scored "
              f"<b>{tier} a game</b> that season")
    box = (f"Stat line: <b>{r.ppg:.1f} pts / {r.rpg:.1f} reb / {r.apg:.1f} ast</b> "
           f"in {r.gp} games")
    three = (f"Threes: <b>{r.tpg:.1f} made on {r.tpa_pg:.1f} attempts/game</b>"
             if r.tpa_pg == r.tpa_pg else "Threes: barely attempted any")
    splits = (f"Shooting: <b>{r.fg_pct:.1f} FG% / {r.ft_pct:.1f} FT%</b> &middot; "
              f"defense: {r.spg:.1f} stl, {r.bpg:.1f} blk")
    team = f"Team: <b>{r.team}</b> &middot; exact season: <b>{r.season}</b>"
    letter = f"Last name starts with <b>{r.player.split()[-1][0]}</b>"
    return [opener, box, three, splits, team, letter]


def my_guess() -> None:
    g = st.session_state.my
    name = st.session_state.get("my_pick", "")
    if g["done"] or not name:
        return
    g["guesses"].append(name)
    if name == g["row"].player:
        g["done"], g["won"] = True, True
    elif len(g["guesses"]) >= MAX_GUESSES:
        g["done"] = True


def render_mystery() -> None:
    if "my" not in st.session_state:
        my_new_game()
    g = st.session_state.my
    r = g["row"]
    clues = my_clues(r)
    wrong = len([x for x in g["guesses"] if x != r.player])

    st.markdown("#### Guess the player-season")
    d1, _ = st.columns([2, 3])
    d1.segmented_control("Difficulty", list(DIFFICULTIES), key="my_difficulty",
                         default="Legends (easier)", label_visibility="collapsed",
                         on_change=my_new_game)
    st.caption(f"A notable season from any year since 1979-80. Each wrong guess "
               f"reveals another clue - {MAX_GUESSES} guesses total. "
               f"Legends mode sticks to famous superstar seasons.")

    shown = clues[: wrong + 1]
    st.markdown(
        '<div class="bip-card">' +
        "".join(f'<div class="bip-row"><span class="bip-rank">{i}</span>'
                f'<span class="bip-name" style="white-space:normal">{c}</span></div>'
                for i, c in enumerate(shown, 1)) +
        "</div>",
        unsafe_allow_html=True,
    )

    if g["guesses"]:
        st.caption("Guesses: " + "  |  ".join(
            ("~~" + x + "~~" if x != r.player else "**" + x + "**")
            for x in g["guesses"]))

    if not g["done"]:
        names = sorted(_pool()["player"].unique())
        st.selectbox("Your guess", [""] + names, key="my_pick",
                     label_visibility="collapsed",
                     placeholder="Type to search players...")
        c1, c2, _ = st.columns([1, 1, 3])
        c1.button("Guess", type="primary", width="stretch", on_click=my_guess)
        c2.button("Give up", width="stretch",
                  on_click=lambda: st.session_state.my.update(done=True))
    else:
        st.markdown(player_card(r), unsafe_allow_html=True)
        if g["won"]:
            st.success(f"Got it in {len(g['guesses'])} - **{r.player}**, "
                       f"{r.season} {r.team}: {r.ppg:.1f}/{r.rpg:.1f}/{r.apg:.1f}")
            st.balloons()
        else:
            st.error(f"It was **{r.player}** - {r.season} {r.team}: "
                     f"{r.ppg:.1f}/{r.rpg:.1f}/{r.apg:.1f}")
        st.button("New mystery", type="primary", on_click=my_new_game)


# --- Build a team ---------------------------------------------------------------
#
# The numbers come from lib/sim.py (ratings and seasons) and lib/draft.py
# (budget rules and the CPU drafter); this section is only the page. Its
# session_state keys are listed in the module docstring.

ALL_TIME = "All-time"
MODES = ["Build", "Draft"]
DRAFT_TEAMS = 6
POOL_ROWS = 200  # the pool grid shows the best 200 matches by impact
_GAME_KEYS = ("tb_build_picks", "tb_build_season", "tb_draft",
              "tb_draft_season", "tb_proj")


def _tb_bump() -> None:
    """New key for the pool grid, so its row selection starts empty."""
    st.session_state["tb_nonce"] = st.session_state.get("tb_nonce", 0) + 1


def _tb_reset() -> None:
    """Clear the game (mode and pool stay as chosen). No confirm step."""
    for key in _GAME_KEYS:
        st.session_state.pop(key, None)
    st.session_state["tb_build_picks"] = []
    st.session_state["tb_search"] = ""
    _tb_bump()


def _fold(text) -> str:
    """Lower-case, accents dropped, so "jokic" finds "Jokić"."""
    return (unicodedata.normalize("NFKD", str(text))
            .encode("ascii", "ignore").decode().lower())


def _last_team(path: str) -> str:
    """'CHI → BOS' -> 'BOS', the team he finished the season with."""
    return str(path).split("→")[-1].strip()


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


def _ordinal(n: int) -> str:
    suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10 if n > 20 else n, "th")
    return f"{n}{suffix}"


def _row_keys(rows: pd.DataFrame) -> list[str]:
    """'player_id:season' per row - the same player in two seasons differs."""
    return [f"{int(p)}:{s}" for p, s in zip(rows["player_id"], rows["season"])]


def _meta() -> tuple[float, float, float]:
    """(team_scale, team_offset, usage_league_total) from the impact model."""
    m = db.player_impact_meta()
    return (float(m.get("team_scale", 1.0)), float(m.get("team_offset", 0.0)),
            float(m.get("usage_league_total", 5.0)))


def _team_net(rows: pd.DataFrame, meta) -> float:
    """Net rating of an 8-man roster, best five by impact starting."""
    rot = draft.auto_rotation(rows)
    scale, offset, usage_total = meta
    return float(sim.team_net_rating(rot["impact"], rot["usage"], scale, offset,
                                     usage_league_total=usage_total))


def _opponents(season: str | None) -> tuple[list[float], list[str], str]:
    """Build mode's league: (net ratings, labels, source).

    source is "season" (that season's real teams), "all-time" (29 real
    team-seasons from 1985-86 on, always the same 29: seed 7; also the
    fallback when a season has no team ratings) or "average" (a placeholder
    average team, for a warehouse with no team ratings at all)."""
    if season is not None:
        teams = db.team_advanced(season)
        teams = teams[teams["net_rating"].notna()].sort_values("team_abbreviation")
        if len(teams) >= 2:
            return (teams["net_rating"].astype(float).tolist(),
                    teams["team_abbreviation"].tolist(), "season")
    every = db.all_team_net_ratings()
    if not len(every):
        return [0.0], ["an average team"], "average"
    idx = np.random.default_rng(7).choice(len(every), size=min(29, len(every)),
                                          replace=False)
    drawn = every.iloc[idx]
    return (drawn["net_rating"].astype(float).tolist(),
            (drawn["season"] + " " + drawn["team"]).tolist(), "all-time")


def _cached(key, compute):
    """Projection cache in session_state; the seed is tied to the roster, so
    a rerun would only recompute the same numbers."""
    cache = st.session_state.setdefault("tb_proj", {})
    if key not in cache:
        if len(cache) > 32:
            cache.clear()
        cache[key] = compute()
    return cache[key]


def _results_row(net: float, median: int, p10: int, p90: int,
                 odds_label: str, odds: float,
                 rating_sub: str = "points per 100 vs. an average team") -> None:
    c1, c2, c3, c4 = st.columns(4)
    c1.markdown(T.kpi("Team rating", f"{_rating(net):+.1f}", sub=rating_sub,
                      help=glossary.TERMS["Team rating"]), unsafe_allow_html=True)
    c2.markdown(T.kpi("Projected record", _record(median), sub="median of 1,000 seasons",
                      help=glossary.TERMS["Projected record"]), unsafe_allow_html=True)
    c3.markdown(T.kpi("Range", f"{p10}-{p90} wins", sub="10th to 90th percentile",
                      help=glossary.TERMS["Win range"]), unsafe_allow_html=True)
    c4.markdown(T.kpi(odds_label, _pct(odds), sub="share of 1,000 seasons",
                      help=glossary.TERMS[odds_label]), unsafe_allow_html=True)


def _pool_table(pool: pd.DataFrame, exclude):
    """Search box, an empty slot for the caller's action button, and the pool
    grid. Returns (selected row's pool index label or None, the slot). Rows
    in `exclude` (index labels) are left out."""
    query = st.text_input("Search the pool", key="tb_search",
                          placeholder="Search a name, season or team",
                          label_visibility="collapsed")
    bar = st.container()
    avail = pool.loc[~pool.index.isin(list(exclude))]
    tokens = _fold(query).split()
    if tokens:
        hay = (avail["player"] + " " + avail["season"] + " " + avail["team"]).map(_fold)
        mask = pd.Series(True, index=avail.index)
        for tok in tokens:
            mask &= hay.str.contains(tok, regex=False)
        avail = avail[mask]
    shown = avail.head(POOL_ROWS)
    if not len(shown):
        st.caption("No players match that search.")
        return None, bar
    view = pd.DataFrame({
        "Player": shown["player"], "Season": shown["season"], "Team": shown["team"],
        "GP": shown["gp"], "PTS": shown["ppg"], "REB": shown["rpg"],
        "AST": shown["apg"], "Impact": shown["impact"], "Cost": shown["cost"],
    })
    cc = st.column_config
    key = (f"tb_table_{st.session_state.get('tb_nonce', 0)}_"
           f"{zlib.crc32(query.encode('utf-8'))}")
    event = st.dataframe(
        view, key=key, on_select="rerun", selection_mode="single-row",
        hide_index=True, width="stretch", row_height=38,
        height=min(420, 38 * (len(view) + 1) + 3),
        column_config={
            "GP": cc.NumberColumn(format="%d", **glossary.described("GP")),
            "PTS": cc.NumberColumn(format="%.1f", help="Points per game."),
            "REB": cc.NumberColumn(format="%.1f", help="Rebounds per game."),
            "AST": cc.NumberColumn(format="%.1f", help="Assists per game."),
            "Impact": cc.NumberColumn(format="%+.2f", **glossary.marked("Impact")),
            "Cost": cc.NumberColumn(format="%d", help="Credits he costs in Build "
                                    "mode, 1-12 by impact."),
        },
    )
    more = f" of {len(avail):,}" if len(avail) > len(shown) else ""
    st.caption(f"Showing {len(shown)}{more} by impact. Click a row to select it.")
    rows = list(event.selection.rows) if event is not None else []
    if rows and rows[0] < len(shown):
        return shown.index[rows[0]], bar
    return None, bar


def _slot_html(label: str, r) -> str:
    if r is None:
        body = (f'<div style="min-height:76px;display:flex;align-items:center;'
                f'color:{T.MUTED};font-size:.85rem">Empty</div>')
        return T.card_html(label, body)
    team = _last_team(r.team)
    tc = T.team_color(team)
    body = (
        f'<div style="min-height:76px">'
        f'<div style="display:flex;gap:.7rem;align-items:center">'
        f'{media.avatar_html(int(r.player_id), r.player, size=46, ring=tc)}'
        f'<div style="min-width:0">'
        f'<div class="bip-name" style="font-size:.95rem">{html.escape(r.player)}</div>'
        f'<div class="bip-kpi-sub">{r.season} &middot; '
        f'<span style="color:{tc};font-weight:700">{html.escape(team)}</span></div>'
        f'</div></div>'
        f'<div style="display:flex;justify-content:space-between;margin-top:.5rem;'
        f'font-size:.8rem;color:{T.INK_2}">'
        f'<span>Impact <b style="color:{T.INK}">{r.impact:+.2f}</b></span>'
        f'<span>Cost <b style="color:{T.INK}">{int(r.cost)}</b></span></div></div>'
    )
    return T.card_html(label, body)


def _roster_grid(rows: pd.DataFrame, removable: bool) -> None:
    """Five Starter slots, then three Bench, filled best impact first."""
    recs = list(draft.auto_rotation(rows).itertuples()) if len(rows) else []
    for start, count, label in ((0, sim.STARTERS, "Starter"),
                                (sim.STARTERS, sim.ROSTER_SIZE - sim.STARTERS, "Bench")):
        cols = st.columns(sim.STARTERS)
        for i in range(count):
            r = recs[start + i] if start + i < len(recs) else None
            with cols[i]:
                st.markdown(_slot_html(label, r), unsafe_allow_html=True)
                if removable and r is not None:
                    st.button("× Remove", key=f"tb_rm_{int(r.player_id)}_{r.season}",
                              type="tertiary", on_click=_tb_remove,
                              args=((int(r.player_id), str(r.season)),))


def _build_picks() -> list[tuple[int, str]]:
    return [(int(p[0]), str(p[1])) for p in st.session_state.get("tb_build_picks", [])]


def _tb_add(key: tuple[int, str]) -> None:
    picks = _build_picks()
    if key not in picks and len(picks) < sim.ROSTER_SIZE:
        picks.append(key)
    st.session_state["tb_build_picks"] = picks
    _tb_bump()


def _tb_remove(key: tuple[int, str]) -> None:
    st.session_state["tb_build_picks"] = [p for p in _build_picks() if p != key]
    _tb_bump()


def _tb_sim_build(key, net: float, opp_nets: list[float], names: list[str]) -> None:
    st.session_state["tb_build_season"] = {
        "key": key, "names": names,
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
        title = (f"Game {k + 1}: {'vs' if home else 'at'} {names[opp]} - "
                 f"{'won' if won else 'lost'} by {max(1, round(abs(margin)))}")
        dots.append(f'<span class="dot {"dot-w" if won else "dot-l"}" '
                    f'title="{html.escape(title, quote=True)}" style="border-radius:1px;'
                    f'width:10px;height:10px;margin:0 2px 3px 0"></span>')
    best, worst = _streaks([g[3] for g in res["games"]])
    body = (
        f'<div class="bip-kpi-value">{res["wins"]}-{res["losses"]}</div>'
        f'<div style="display:flex;flex-wrap:wrap;margin:.6rem 0 .45rem">'
        f'{"".join(dots)}</div>'
        f'<div class="bip-kpi-sub">Longest winning streak <b>{best}</b> &middot; '
        f'longest losing streak <b>{worst}</b> &middot; green is a win, red a loss; '
        f'hover a square for the game</div>'
    )
    return T.card_html("One simulated season", body)


def _build_results(rows: pd.DataFrame, season: str | None, choice: str, meta) -> None:
    keys = _row_keys(rows)
    # The linear calibration would rate a roster of eight star seasons far
    # past any real team; past +10 the soft ceiling keeps it near the best
    # ever (anything up to +10 is left as is).
    net = sim.soft_cap(_team_net(rows, meta))
    opp_nets, opp_names, source = _opponents(season)
    cache_key = ("build", choice, tuple(sorted(keys)))

    def project() -> dict:
        res = sim.simulate_vs_league(net, opp_nets,
                                     np.random.default_rng(sim.roster_seed(keys)))
        return {k: res[k] for k in ("median", "p10", "p90", "best_record_odds")}

    proj = _cached(cache_key, project)
    st.markdown("#### Projection")
    _results_row(net, proj["median"], proj["p10"], proj["p90"],
                 "Best-record odds", proj["best_record_odds"])
    if source == "season":
        against = (f"82 games against {season}'s {len(opp_nets)} real teams, "
                   f"each at its real net rating.")
    elif source == "all-time":
        lead = (f"{season} has no team ratings, so it's " if season is not None
                else "")
        against = (f"{lead}82 games against {len(opp_nets)} real team-seasons drawn "
                   f"from 1985-86 on, each at its real net rating.")
    else:
        against = ("82 games against an average team - this copy of the data has "
                   "no team ratings yet.")
    st.caption(against)
    st.button("Simulate a season", key="tb_build_sim", type="primary",
              on_click=_tb_sim_build, args=(cache_key, net, opp_nets, opp_names))
    played = st.session_state.get("tb_build_season")
    if played and played["key"] == cache_key:
        st.markdown(_season_card(played), unsafe_allow_html=True)


def _render_build(pool: pd.DataFrame, season: str | None, choice: str, meta) -> None:
    picks = set(_build_picks())
    cand = pool[pool["player_id"].isin([p for p, _ in picks])]
    rows = cand[[(int(p), s) in picks
                 for p, s in zip(cand["player_id"], cand["season"])]]
    problems = draft.validate_build(rows)
    full = len(rows) >= sim.ROSTER_SIZE
    count_msg = problems[0] if len(rows) != sim.ROSTER_SIZE and problems else ""
    others = problems[1:] if count_msg else problems

    st.caption(f"Pick {sim.ROSTER_SIZE} player-seasons with {draft.BUDGET} credits to "
               f"spend; better players cost more (1-12). The five best by impact start.")
    used = int(rows["cost"].sum()) if len(rows) else 0
    left = draft.BUDGET - used
    k1, k2, _ = st.columns([1, 1, 3])
    k1.markdown(T.kpi("Credits used", f"{used} / {draft.BUDGET}",
                      sub=f"{left} left" if left >= 0 else f"{-left} over"),
                unsafe_allow_html=True)
    k2.markdown(T.kpi("Players", f"{len(rows)} / {sim.ROSTER_SIZE}",
                      sub="5 starters, 3 bench"), unsafe_allow_html=True)
    _roster_grid(rows, removable=True)
    for msg in others:
        st.warning(msg)

    if not problems:
        _build_results(rows, season, choice, meta)
    if not full:
        st.markdown("#### Add players")
        label, bar = _pool_table(pool, exclude=rows.index)
        with bar:
            c1, c2 = st.columns([1, 4], vertical_alignment="center")
            if label is not None:
                r = pool.loc[label]
                note = (f"Selected: **{r.player}**, {r.season} "
                        f"({int(r.cost)} credits). {count_msg}")
                key = (int(r.player_id), str(r.season))
            else:
                note, key = f"Select a row in the table, then add him. {count_msg}", None
            c1.button("Add to team", key="tb_add", type="primary", width="stretch",
                      disabled=key is None, on_click=_tb_add, args=(key,))
            c2.caption(note)


# Draft mode

def _team_names(state: dict) -> list[str]:
    """'Your team' for the user, 'CPU 1'..'CPU 5' for the rest in pick order."""
    names, cpu = [], 0
    for t in range(len(state["rosters"])):
        if t == state["user_team"]:
            names.append("Your team")
        else:
            cpu += 1
            names.append(f"CPU {cpu}")
    return names


def _tb_start_draft(season: str | None, choice: str) -> None:
    if st.session_state.get("tb_draft") is not None:
        return  # a draft is already running; "Start over" clears it first
    pool = db.player_impact_pool(season)
    state = draft.new_draft(DRAFT_TEAMS, sim.ROSTER_SIZE, random.randrange(DRAFT_TEAMS))
    state["pool"] = choice
    draft.run_cpu_until_user(state, pool, np.random.default_rng(),
                             usage_league_total=_meta()[2])
    st.session_state["tb_draft"] = state
    st.session_state.pop("tb_draft_season", None)
    _tb_bump()


def _tb_draft_pick(season: str | None, label) -> None:
    state = st.session_state.get("tb_draft")
    if (state is None or label in state["taken"]
            or state["pick_no"] >= len(state["order"])):
        return
    pool = db.player_impact_pool(season)
    draft.apply_pick(state, label)
    draft.run_cpu_until_user(state, pool, np.random.default_rng(),
                             usage_league_total=_meta()[2])
    _tb_bump()


def _board_html(state: dict, pool: pd.DataFrame, names: list[str]) -> str:
    """The draft board: one column per team, one row per round."""
    n = len(names)
    rounds = len(state["order"]) // n
    pick_at = {(k // n, t): k for k, t in enumerate(state["order"])}
    user = state["user_team"]
    cell = (f"border-radius:{T.RADIUS};padding:.35rem .5rem;min-height:3.05rem;"
            f"min-width:0;")
    parts = ['<div></div>']
    for t, name in enumerate(names):
        color = T.ACCENT if t == user else T.INK_2
        parts.append(
            f'<div style="padding:0 .2rem .3rem;border-bottom:2px solid '
            f'{T.ACCENT if t == user else T.BORDER}">'
            f'<div style="font-weight:800;font-size:.85rem;color:{color}">{name}</div>'
            f'<div style="font-size:.68rem;color:{T.MUTED}">picks {_ordinal(t + 1)}</div>'
            f'</div>')
    for r in range(rounds):
        parts.append(f'<div style="align-self:center;font-size:.7rem;font-weight:700;'
                     f'color:{T.MUTED}">R{r + 1}</div>')
        for t in range(n):
            k = pick_at[(r, t)]
            mine = "background:rgba(57,135,229,.08);" if t == user else ""
            if r < len(state["rosters"][t]):
                p = pool.loc[state["rosters"][t][r]]
                tc = T.team_color(_last_team(p.team))
                parts.append(
                    f'<div style="{cell}{mine}border:1px solid {T.BORDER};'
                    f'border-left:3px solid {tc}">'
                    f'<div style="font-weight:700;font-size:.8rem;color:{T.INK};'
                    f'white-space:nowrap;overflow:hidden;text-overflow:ellipsis">'
                    f'{html.escape(p.player)}</div>'
                    f'<div style="font-size:.7rem;color:{T.MUTED}">{p.season} &middot; '
                    f'{p.impact:+.2f}</div></div>')
            elif k == state["pick_no"]:
                parts.append(
                    f'<div style="{cell}border:1px dashed {T.ACCENT};display:flex;'
                    f'align-items:center;font-size:.75rem;font-weight:700;'
                    f'color:{T.ACCENT}">On the clock</div>')
            else:
                parts.append(
                    f'<div style="{cell}{mine}border:1px dashed {T.BORDER};display:flex;'
                    f'align-items:center;font-size:.7rem;color:{T.MUTED}">#{k + 1}</div>')
    grid = "".join(parts)
    return (f'<div style="overflow-x:auto"><div style="display:grid;'
            f'grid-template-columns:2rem repeat({n}, minmax(0, 1fr));gap:6px;'
            f'min-width:760px">{grid}</div></div>')


def _highlight_user(df: pd.DataFrame):
    return df.style.apply(
        lambda row: [("background-color: rgba(57,135,229,.16)"
                      if row["Team"] == "Your team" else "")] * len(row), axis=1)


def _tb_sim_draft(key, nets: list[float]) -> None:
    st.session_state["tb_draft_season"] = {
        "key": key, "result": sim.simulate_league_once(nets, np.random.default_rng()),
    }


def _draft_results(state: dict, pool: pd.DataFrame, names: list[str], choice: str,
                   meta) -> None:
    n = len(names)
    user = state["user_team"]
    rosters = [pool.loc[state["rosters"][t]] for t in range(n)]
    # Every drafted team is stacked, so absolute ratings would run far past
    # any real team. Rate each one against its own league instead: the
    # league averages 0, which is all the round robin needs.
    raw = np.array([_team_net(r, meta) for r in rosters])
    nets = [float(x) for x in raw - raw.mean()]
    keys = [f"{t}|{k}" for t, r in enumerate(rosters) for k in _row_keys(r)]
    cache_key = ("draft", choice, tuple(keys))

    def project() -> dict:
        res = sim.simulate_league(nets, np.random.default_rng(sim.roster_seed(keys)))
        wins = res["wins"]
        return {
            "median": [int(round(float(x))) for x in res["median_wins"]],
            "p10": [int(round(float(x))) for x in np.percentile(wins, 10, axis=0)],
            "p90": [int(round(float(x))) for x in np.percentile(wins, 90, axis=0)],
            "title": [float(x) for x in res["title_odds"]],
            "playoff": [float(x) for x in res["playoff_odds"]],
        }

    proj = _cached(cache_key, project)
    st.markdown("#### Projection")
    _results_row(nets[user], proj["median"][user], proj["p10"][user],
                 proj["p90"][user], "Title odds", proj["title"][user],
                 rating_sub="points per 100 vs this draft league")

    table = pd.DataFrame({
        "Team": names,
        "Rating": [_rating(x) for x in nets],
        "Projected record": [_record(w) for w in proj["median"]],
        "Wins": proj["median"],
        "Playoff odds": [round(p * 100) for p in proj["playoff"]],
        "Title odds": [round(p * 100) for p in proj["title"]],
    }).sort_values(["Wins", "Rating"], ascending=False)
    cc = st.column_config
    st.dataframe(
        _highlight_user(table), hide_index=True, width="stretch", row_height=38,
        column_config={
            "Rating": cc.NumberColumn(format="%+.1f", **glossary.described("Team rating")),
            "Projected record": cc.TextColumn(**glossary.described("Projected record")),
            "Wins": cc.NumberColumn(format="%d", help="Median wins."),
            "Playoff odds": cc.NumberColumn(format="%d%%", help="Share of 1,000 "
                                            "seasons finishing in the top four."),
            "Title odds": cc.NumberColumn(format="%d%%", **glossary.described("Title odds")),
        },
    )
    st.caption("A six-team league: an 82-game round robin, then the top four play "
               "best-of-seven series. Your team is highlighted.")

    st.button("Simulate a season", key="tb_draft_sim", type="primary",
              on_click=_tb_sim_draft, args=(cache_key, nets))
    played = st.session_state.get("tb_draft_season")
    if played and played["key"] == cache_key:
        _league_season(played["result"], names)


def _league_season(res: dict, names: list[str]) -> None:
    seeds = res["seeds"]
    seed_of = {t: i + 1 for i, t in enumerate(seeds)}
    rest = sorted((t for t in range(len(names)) if t not in seed_of),
                  key=lambda t: -res["wins"][t])
    order = list(seeds) + rest
    standings = pd.DataFrame({
        "Seed": [str(seed_of[t]) if t in seed_of else "-" for t in order],
        "Team": [names[t] for t in order],
        "W": [res["wins"][t] for t in order],
        "L": [res["games"][t] - res["wins"][t] for t in order],
    })
    rows = []
    for s in res["bracket"]:
        label = "Round 1" if s["round"] == "semifinal" else "Final"
        hi, lo = s["high"], s["low"]

        def nm(t):
            text = f"{names[t]} ({seed_of[t]})"
            return f"<b>{text}</b>" if t == s["winner"] else text

        rows.append(f'<div class="bip-row"><span class="bip-name" style="font-weight:500">'
                    f'{label}: {nm(hi)} {s["high_wins"]}-{s["low_wins"]} {nm(lo)}'
                    f'</span></div>')
    champ = names[res["champion"]]
    left, right = st.columns([2, 3])
    with left:
        st.markdown("#### One simulated season")
        st.dataframe(_highlight_user(standings), hide_index=True, width="stretch",
                     row_height=38)
        st.caption("All-star leagues are close by design, so a single season is "
                   "often decided by luck - the projection shows the long-run odds.")
    with right:
        st.markdown("#### Playoffs")
        st.markdown(T.card_html("Bracket", "".join(rows)) +
                    T.chip(f"Champion: {champ}"), unsafe_allow_html=True)


def _render_draft(pool: pd.DataFrame, season: str | None, choice: str, meta) -> None:
    state = st.session_state.get("tb_draft")
    if state is not None and state.get("pool") != choice:
        st.session_state.pop("tb_draft", None)
        state = None
    n_picks = DRAFT_TEAMS * sim.ROSTER_SIZE
    if state is None:
        st.caption("A snake draft: you and five CPU teams take turns for eight rounds, "
                   "and the order reverses every round. Your slot is drawn at random. "
                   "The CPU takes the best impact left, steers away from too many "
                   "ball-dominant players, and adds a little randomness so no two "
                   "drafts match.")
        if len(pool) < n_picks:
            st.info(f"This pool has {len(pool)} players, too few for a "
                    f"{n_picks}-pick draft - pick another pool.")
            return
        st.button("Start draft", key="tb_draft_start", type="primary",
                  on_click=_tb_start_draft, args=(season, choice))
        return

    names = _team_names(state)
    user = state["user_team"]
    done = state["pick_no"] >= len(state["order"])
    if not done:
        rnd = state["pick_no"] // DRAFT_TEAMS + 1
        st.markdown(
            f"{T.chip(f'Round {rnd} of {sim.ROSTER_SIZE}')} &nbsp;"
            f"You're on the clock with pick **{state['pick_no'] + 1}** of {n_picks}. "
            f"You pick {_ordinal(user + 1)} in odd rounds and "
            f"{_ordinal(DRAFT_TEAMS - user)} in even ones.",
            unsafe_allow_html=True)
        label, bar = _pool_table(pool, exclude=state["taken"])
        with bar:
            c1, c2 = st.columns([1, 4], vertical_alignment="center")
            if label is not None:
                r = pool.loc[label]
                note = f"Selected: **{r.player}**, {r.season} (impact {r.impact:+.2f})."
            else:
                note = "Select a row in the table, then draft him."
            c1.button("Draft player", key="tb_draft_pick", type="primary",
                      width="stretch", disabled=label is None,
                      on_click=_tb_draft_pick, args=(season, label))
            c2.caption(note)
    else:
        _draft_results(state, pool, names, choice, meta)
    st.markdown("#### Draft board")
    st.markdown(_board_html(state, pool, names), unsafe_allow_html=True)


def _explainer(meta_row: dict) -> None:
    r2 = meta_row.get("team_r2")
    fit = (f" On real team-seasons the conversion explains {float(r2):.0%} of the "
           f"spread in net rating." if r2 is not None and r2 == r2 else "")
    with st.expander("How the simulation works"):
        st.markdown(
            f"""
**Impact.** Every player-season since 1985-86 gets one number: points, rebounds,
assists, steals, blocks, turnovers, shots and fouls per 36 minutes, each weighed by
a model fit to how much players' teams outscored opponents while they were on the
court. 0 is a typical rotation player; the best seasons ever reach about +5 to +6.

**Era adjustment.** Every rate is compared with that season's league average
before it's weighed, so a 1988 rebounder and a 2024 shooter are rated on the same
scale. That's what makes an all-time team possible.

**Minutes.** The five best impacts start and play {sim.STARTER_MINUTES} minutes;
the three bench players play {sim.BENCH_MINUTES} (5 × {sim.STARTER_MINUTES} + 3 ×
{sim.BENCH_MINUTES} = 240, one game's worth of player-minutes). Impact weighted by
those minutes becomes the team rating.{fit}

**Usage overlap.** There's only one ball. When a lineup's combined usage (shots,
free throws and turnovers) runs past what a normal lineup carries, part of its
positive impact is lost. This rule is a rough heuristic, not fitted to data.

**Game randomness.** Each game's margin is the rating gap, plus {sim.HOME_EDGE}
points for the home team, plus random noise of ±{sim.GAME_SD} points (one standard
deviation, as measured on real NBA games). Good teams lose plenty of single games.

**A ceiling, and draft leagues.** Real teams top out around +13 (the 1995-96
Bulls). In Build mode a rating up to +{sim.ABS_NET_KNEE:.0f} is shown exactly as
computed; past that, a stacked roster's rating bends smoothly toward a
+{sim.ABS_NET_CAP:.0f} ceiling instead of running off the chart. In Draft mode every
team is stacked, so each is rated against its own six-team league (the league
averages 0). Projections can shift slightly when the weekly data refresh updates
the current season.

**Same team, same projection.** The projection plays 1,000 seasons from a seed tied
to your roster, so the same eight players always get the same numbers. "Simulate a
season" plays one fresh season, so each one comes out differently.

It's a game built on real numbers, not a scouting tool.
"""
        )


def render_build_team() -> None:
    if not db.player_impact_available():
        st.info("Team building needs a newer copy of the data - check back after "
                "the next refresh.")
        return
    all_pool = db.player_impact_pool(None)
    choices = [ALL_TIME] + sorted((str(s) for s in all_pool["season"].unique()),
                                  reverse=True)
    if st.session_state.get("tb_mode") not in MODES:
        st.session_state["tb_mode"] = MODES[0]
    if st.session_state.get("tb_pool") not in choices:
        st.session_state["tb_pool"] = ALL_TIME

    c1, c2, c3, _ = st.columns([1.1, 1.3, 0.8, 2.8], vertical_alignment="bottom")
    c1.segmented_control("Mode", MODES, key="tb_mode", required=True,
                         on_change=_tb_reset)
    c2.selectbox("Player pool", choices, key="tb_pool", on_change=_tb_reset)
    c3.button("Start over", key="tb_restart", width="stretch", on_click=_tb_reset)

    choice = st.session_state["tb_pool"]
    season = None if choice == ALL_TIME else choice
    pool = all_pool if season is None else db.player_impact_pool(season)
    meta = _meta()
    if st.session_state["tb_mode"] == "Build":
        _render_build(pool, season, choice, meta)
    else:
        _render_draft(pool, season, choice, meta)
    _explainer(db.player_impact_meta())


def render() -> None:
    n = len(db.seasons())
    st.markdown(
        f'## Arcade &nbsp;<span class="bip-chip">{n} seasons of data</span>',
        unsafe_allow_html=True,
    )
    tab_hl, tab_my, tab_tb = st.tabs(["Higher or Lower", "Mystery Player",
                                      "Build a team"])
    with tab_hl:
        render_higher_lower()
    with tab_my:
        render_mystery()
    with tab_tb:
        render_build_team()
