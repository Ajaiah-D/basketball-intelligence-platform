"""Plain-English explanations for every stat a casual fan might not know.

One place, so "usage" means the same thing on the Overview, Advanced and
Players pages. Two ways onto the page:

  - theme.tip(TERMS[...]) - a hoverable/tappable ⓘ next to a card title,
    KPI label or HTML table header.
  - marked(label) / described(label) - st.column_config kwargs for the
    canvas-drawn data grids, which can't hold an HTML icon: `marked` puts
    "ⓘ" in the header text for real jargon (TS%, USG%...), `described`
    adds the hover text only, for abbreviations most fans can read (FGA).
"""

from __future__ import annotations

MARK = "ⓘ"

_TS = (
    "True shooting %: scoring efficiency that counts 3-pointers as worth more "
    "and includes free throws. Around 57% has been league average in recent "
    "seasons; 60%+ is excellent."
)
_USG = (
    "Usage rate: the share of his team's plays a player finishes - with a shot, "
    "free throws or a turnover - while he's on the court. About 20% is average; "
    "30%+ means the offense runs through him."
)
_REB = (
    "Rebound rate: the share of available rebounds he grabbed while on the "
    "court. Fairer than rebounds per game, which rewards players who simply "
    "play more minutes."
)
_GMSC = (
    "Game score: a one-number summary of a box score (John Hollinger's "
    "formula), scaled like points. About 10 is an average game; 20+ is "
    "excellent."
)
_PIE = (
    "Player Impact Estimate: the NBA's own measure of a player's share of "
    "everything that happened in his games. About 10 is average."
)
_PLUS_MINUS = (
    "Plus/minus: how many points his team outscored opponents by while "
    "he was on the court. Positive is good, but it depends heavily on "
    "teammates."
)

TERMS = {
    # Box score abbreviations
    "GP": "Games played.",
    "MIN": "Minutes played per game.",
    "FG%": "Field goal percentage: the share of shots made, free throws not included.",
    "FGA": "Field goal attempts per game - shots taken, 2s and 3s together.",
    "3PM": "Three-pointers made per game.",
    "3PA": "Three-point attempts per game.",
    "3P%": "Three-point percentage: the share of three-point shots made.",
    "FT%": "Free throw percentage: the share of free throws made.",
    "FTA": "Free throw attempts per game.",
    "+/-": _PLUS_MINUS,
    # Advanced player metrics
    "TS%": _TS,
    "eFG%": (
        "Effective field goal %: field goal percentage with each 3-pointer "
        "counted as 1.5 makes, since it's worth 50% more."
    ),
    "USG%": _USG,
    "AST%": "Assist rate: the share of teammates' baskets he assisted while on the court.",
    "REB%": _REB,
    "TOV%": "Turnover rate: turnovers per 100 plays he finished. Lower is better.",
    "STL%": (
        "Steal rate: the share of opponent possessions that ended in his steal "
        "while he was on the court."
    ),
    "BLK%": ("Block rate: the share of opponents' 2-point shots he blocked while on the court."),
    "GmSc": _GMSC,
    "P/36": "Points per 36 minutes: his scoring rate if he played a starter's minutes.",
    "P/100": "Points per 100 possessions: his scoring rate with team pace taken out.",
    "NET": (
        "Net rating: points his team scored minus points it allowed per 100 "
        "possessions while he was on the court."
    ),
    "PIE": _PIE,
    # Leader-card titles - same meaning, readable names
    "True shooting": _TS,
    "Usage": _USG,
    "Game score": _GMSC,
    "Rebound rate": _REB,
    "Impact (PIE)": _PIE,
    "AST/TO": (
        "Assist-to-turnover ratio: assists per turnover. Higher means a "
        "player sets up teammates without giving the ball away; about 3 is "
        "excellent for a lead guard."
    ),
    # Team metrics
    "PCT": "Winning percentage: wins divided by games played.",
    "OPP": "Points allowed per game.",
    "Team +/-": "Average point margin: points scored minus points allowed, per game.",
    "Form": "The last five games, oldest to newest. Green is a win, red a loss.",
    "Net / game": "Average point margin: points scored minus points allowed, per game.",
    "Offensive rating": (
        "Points scored per 100 possessions. Taking pace out lets a "
        "fast team and a slow one compare fairly."
    ),
    "Defensive rating": "Points allowed per 100 possessions. Lower is better.",
    "Net rating": (
        "Offensive rating minus defensive rating: how many points per 100 "
        "possessions a team outscores opponents by."
    ),
    "Pace": "Possessions per 48 minutes - how fast a team plays.",
    "Close games": (
        "The share of games decided by 5 points or fewer - how competitive the season has been."
    ),
    "Four Factors": (
        "Dean Oliver's four things that decide most games: shooting, "
        "turnovers, rebounding and free throws. Each is measured on "
        "offense and again on defense (what opponents managed)."
    ),
    "Shooting": (
        "Effective FG% - field goal percentage with 3-pointers counted as "
        "1.5 makes. Offense: higher is better. Defense: what opponents shot; "
        "lower is better."
    ),
    "Turnovers": (
        "Turnovers per 100 plays. Offense: lower is better. Defense: how "
        "many the team forced from opponents; higher is better."
    ),
    "Rebounding": (
        "Offense: the share of its own misses a team rebounds. Defense: "
        "the share of opponents' misses it rebounds. Higher is better on "
        "both."
    ),
    "Free throws": (
        "Free throws made per field goal attempt - how often a team gets "
        "to the line and scores. Offense: higher is better. Defense: lower "
        "is better, it means fouling less."
    ),
    "Seed": "Where the team sits in its conference standings.",
    "Close-game record": "Wins and losses in games decided by 5 points or fewer.",
    "Vs winning teams": "Record against teams that finished the season above .500.",
    # Predictions
    "Accuracy": "The share of games where the predicted winner actually won.",
    "Brier score": (
        "How well-calibrated the win probabilities were: 0 is perfect, "
        "0.25 is what always guessing 50/50 would score. Lower is better."
    ),
    "Margin error": (
        "How many points the predicted margin missed the real final margin by, on average."
    ),
    "Win probability": (
        "The model's chance that the home team wins, from 0% to 100%. "
        "60% means that in 10 games like this one, the home team "
        "would be expected to win about 6."
    ),
    "Predicted margin": (
        "How many points the model expects the favorite to win by. "
        "It is a best guess, and real margins swing widely around it."
    ),
    "Calibration": (
        "Whether the percentages can be trusted. Games are grouped by the "
        "chance the model gave the home team; if it is well calibrated, "
        "teams given 70% win about 70% of those games, and the dots sit "
        "on the dashed line."
    ),
    # Arcade team builder
    "Impact": (
        "The team builder's rating of one player-season: about how many points "
        "of margin he adds per 36 minutes, read from his box-score rates "
        "compared with that season's league, so eras compare fairly. 0 is a "
        "typical rotation player, +2 is star level and the best seasons ever "
        "reach about +5 to +6."
    ),
    "Team rating": (
        "Your eight-man team's net rating, in points per 100 "
        "possessions against an average NBA team: 0 is a .500 team, +10 "
        "is one of the best ever, and stacked rosters past that level off "
        "at about +16."
    ),
    "Projected record": (
        "The median record over 1,000 simulated 82-game seasons: half "
        "the simulations went better, half worse. The same team always "
        "gets the same projection."
    ),
    "Win range": (
        "The middle 80% of the 1,000 simulated seasons: one in ten went "
        "worse than the low end and one in ten better than the high end."
    ),
    "Best-record odds": (
        "The share of 1,000 simulated seasons in which your team "
        "finished with the league's best record (a tie counts)."
    ),
}


def marked(label: str) -> dict:
    """Column-config kwargs for a jargon column: 'TS% ⓘ' plus hover text."""
    return {"label": f"{label} {MARK}", "help": TERMS[label]}


def described(label: str) -> dict:
    """Column-config kwargs for a familiar abbreviation: hover text, no mark."""
    return {"label": label, "help": TERMS[label]}
