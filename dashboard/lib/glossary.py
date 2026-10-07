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

_TS = ("True shooting %: scoring efficiency that counts 3-pointers as worth more "
       "and includes free throws. Around 57% has been league average in recent "
       "seasons; 60%+ is excellent.")
_USG = ("Usage rate: the share of his team's plays a player finishes - with a shot, "
        "free throws or a turnover - while he's on the court. About 20% is average; "
        "30%+ means the offense runs through him.")
_REB = ("Rebound rate: the share of available rebounds he grabbed while on the "
        "court. Fairer than rebounds per game, which rewards players who simply "
        "play more minutes.")
_GMSC = ("Game score: a one-number summary of a box score (John Hollinger's "
         "formula), scaled like points. About 10 is an average game; 20+ is "
         "excellent.")
_PIE = ("Player Impact Estimate: the NBA's own measure of a player's share of "
        "everything that happened in his games. About 10 is average.")
_PLUS_MINUS = ("Plus/minus: how many points his team outscored opponents by while "
               "he was on the court. Positive is good, but it depends heavily on "
               "teammates.")

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
    "eFG%": ("Effective field goal %: field goal percentage with each 3-pointer "
             "counted as 1.5 makes, since it's worth 50% more."),
    "USG%": _USG,
    "AST%": "Assist rate: the share of teammates' baskets he assisted while on the court.",
    "REB%": _REB,
    "TOV%": "Turnover rate: turnovers per 100 plays he finished. Lower is better.",
    "STL%": ("Steal rate: the share of opponent possessions that ended in his steal "
             "while he was on the court."),
    "BLK%": ("Block rate: the share of opponents' 2-point shots he blocked while on "
             "the court."),
    "GmSc": _GMSC,
    "P/36": "Points per 36 minutes: his scoring rate if he played a starter's minutes.",
    "P/100": "Points per 100 possessions: his scoring rate with team pace taken out.",
    "NET": ("Net rating: points his team scored minus points it allowed per 100 "
            "possessions while he was on the court."),
    "PIE": _PIE,
    # Leader-card titles - same meaning, readable names
    "True shooting": _TS,
    "Usage": _USG,
    "Game score": _GMSC,
    "Rebound rate": _REB,
    "Impact (PIE)": _PIE,
    "AST/TO": ("Assist-to-turnover ratio: assists per turnover. Higher means a "
               "player sets up teammates without giving the ball away; about 3 is "
               "excellent for a lead guard."),
    # Team metrics
    "PCT": "Winning percentage: wins divided by games played.",
    "OPP": "Points allowed per game.",
    "Team +/-": "Average point margin: points scored minus points allowed, per game.",
    "Form": "The last five games, oldest to newest. Green is a win, red a loss.",
    "Net / game": "Average point margin: points scored minus points allowed, per game.",
    "Offensive rating": ("Points scored per 100 possessions. Taking pace out lets a "
                         "fast team and a slow one compare fairly."),
    "Defensive rating": "Points allowed per 100 possessions. Lower is better.",
    "Net rating": ("Offensive rating minus defensive rating: how many points per 100 "
                   "possessions a team outscores opponents by."),
    "Pace": "Possessions per 48 minutes - how fast a team plays.",
    "Close games": ("The share of games decided by 5 points or fewer - how "
                    "competitive the season has been."),
    # Predictions
    "Accuracy": "The share of games where the predicted winner actually won.",
    "Brier score": ("How well-calibrated the win probabilities were: 0 is perfect, "
                    "0.25 is what always guessing 50/50 would score. Lower is better."),
    "Margin error": ("How many points the predicted margin missed the real final "
                     "margin by, on average."),
}


def marked(label: str) -> dict:
    """Column-config kwargs for a jargon column: 'TS% ⓘ' plus hover text."""
    return {"label": f"{label} {MARK}", "help": TERMS[label]}


def described(label: str) -> dict:
    """Column-config kwargs for a familiar abbreviation: hover text, no mark."""
    return {"label": label, "help": TERMS[label]}
