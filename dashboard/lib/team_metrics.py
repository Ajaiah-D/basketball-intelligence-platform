"""Team-level numbers for the Teams page: league ranks, the Four Factors,
and record splits. Pure functions over db frames, tested in
tests/test_team_metrics.py."""

from __future__ import annotations

import pandas as pd

from .payroll import ordinal

CLOSE_GAME_MARGIN = 5

# (row label, offense column, defense column, offense higher-is-better,
#  defense higher-is-better). Dean Oliver's Four Factors: shooting,
# turnovers, rebounding and free throws decide most games, on both ends.
# Rebounding pairs offensive rebound % (offense) with defensive rebound %
# (defense) - the same contest seen from each side.
FOUR_FACTORS = [
    ("Shooting", "effective_fg_pct", "opp_effective_fg_pct", True, False),
    ("Turnovers", "turnover_pct", "opp_turnover_pct", False, True),
    ("Rebounding", "offensive_rebound_pct", "defensive_rebound_pct", True, True),
    ("Free throws", "free_throw_rate", "opp_free_throw_rate", True, False),
]


def league_rank(
    adv: pd.DataFrame, team: str, col: str, higher_is_better: bool
) -> tuple[int, int] | None:
    """(rank, out of) among teams with a value, 1 = best; None if this team
    has no value (a column added after an older warehouse was published, or
    an incomplete season)."""
    if col not in adv:
        return None
    ok = adv[adv[col].notna()]
    ranks = ok[col].rank(ascending=not higher_is_better, method="min")
    hit = ok.index[ok["team_abbreviation"] == team]
    return (int(ranks.loc[hit[0]]), len(ok)) if len(hit) else None


def four_factors(adv: pd.DataFrame, team: str) -> pd.DataFrame:
    """One row per factor: the team's offense and defense values, the league
    average for each, and each one's rank as an ordinal ('3rd')."""
    rows = []
    for label, off_col, def_col, off_high, def_high in FOUR_FACTORS:
        row = adv[adv["team_abbreviation"] == team]
        out: dict[str, object] = {"factor": label}
        for side, col, high in (("offense", off_col, off_high), ("defense", def_col, def_high)):
            value = row[col].iloc[0] if col in adv and len(row) else None
            rank = league_rank(adv, team, col, high)
            out[side] = value
            out[f"league_{side}"] = round(float(adv[col].mean()), 1) if col in adv else None
            out[f"{side}_rank"] = ordinal(rank[0]) if rank else "-"
        rows.append(out)
    return pd.DataFrame(rows)


def _record(games: pd.DataFrame) -> str:
    wins = int(games["is_win"].sum())
    return f"{wins}-{len(games) - wins}"


def splits(games: pd.DataFrame, standings: pd.DataFrame) -> dict[str, str]:
    """Home, away, last 10, current streak, close games and record against
    teams that finished above .500. `games` is oldest first."""
    ordered = games.sort_values("game_date")
    margin = (ordered["points"] - ordered["opp_points"]).abs()
    winning = set(standings.loc[standings["pct"] > 0.5, "team"])

    streak = ""
    if len(ordered):
        results = ordered["is_win"].tolist()
        last = results[-1]
        run = 0
        for result in reversed(results):
            if result != last:
                break
            run += 1
        streak = f"{'W' if last else 'L'}{run}"

    return {
        "home": _record(ordered[~ordered["is_away_game"]]),
        "away": _record(ordered[ordered["is_away_game"]]),
        "last10": _record(ordered.tail(10)),
        "streak": streak,
        "close": _record(ordered[margin <= CLOSE_GAME_MARGIN]),
        "vs_winning": _record(ordered[ordered["opponent"].isin(winning)]),
    }


def move_note(team_path: str | None, team: str) -> str:
    """'from CHI', 'to BOS', or both, for a player who changed teams mid-season;
    '' for everyone else. team_path is db.player_team_paths()'s 'A → B'."""
    if not team_path or " → " not in team_path:
        return ""
    teams = team_path.split(" → ")
    i = teams.index(team) if team in teams else -1
    parts = []
    if i > 0:
        parts.append(f"from {teams[i - 1]}")
    if 0 <= i < len(teams) - 1:
        parts.append(f"to {teams[i + 1]}")
    return ", ".join(parts)
