"""Session-state keys shared across pages. A key that only one page or game
uses is named in that module instead."""

# The sidebar season picker's key; every season-scoped page reads the chosen
# season from it.
SEASON_KEY = "season"
