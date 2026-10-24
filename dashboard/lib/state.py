"""Session-state keys shared across pages. A key that only one page or game
uses is named in that module instead."""

# The sidebar season picker's key; every season-scoped page reads the chosen
# season from it.
SEASON_KEY = "season"

# A player for the Players page to open: another page sets his name here,
# with SEASON_KEY, before switching there. The Players page reads it once.
PLAYERS_PICK_KEY = "players_preset_pick"
