"""Build a team's session-state keys, as named constants, and the helpers
that clear them. The string values are the "tb_" keys the page has always
used, so a test or a saved session can still set them directly.

  MODE          "Build" | "Draft" (the segmented control)
  POOL          "All-time" | a season like "2024-25" (the selectbox)
  SEARCH        the pool table's search text
  NONCE         int, part of the pool table's widget key; bumped after a
                pick so the table's row selection starts empty again
  BUILD_SLOTS   Build roster: 8 spots, starters 1-5 then bench 1-3, each
                a (player_id, season) pair or None. Placement counts: the
                starter spots play starter minutes
  SLOT          the spot the user chose for the next pick (index), or
                absent; an empty chosen spot wins over the leftmost empty
  BUILD_SEASON  {"key": roster key, "result": sim.simulate_season_once,
                "names": opponent labels} - the last "Simulate a season"
  PICK          Draft state from draft.new_pick_draft: "budget" (hidden),
                "picks" (player_id, season) pairs filling the spots in
                order, "offer" the three pairs on offer now, plus "spent"
                credits and "pool", the pool choice it was started with
  PROJ          {roster key: projection dict} - projections are seeded
                from the roster, so they are cached per roster

Changing the mode or the pool, or "Start over", clears every one of the game
keys (GAME_KEYS) and the search.
"""

import streamlit as st

from dashboard.lib import sim

MODE = "tb_mode"
POOL = "tb_pool"
SEARCH = "tb_search"
NONCE = "tb_nonce"
BUILD_SLOTS = "tb_build_slots"
SLOT = "tb_slot"
BUILD_SEASON = "tb_build_season"
PICK = "tb_pick"
PROJ = "tb_proj"

ALL_TIME = "All-time"
MODES = ["Build", "Draft"]
GAME_KEYS = (BUILD_SLOTS, SLOT, BUILD_SEASON, PICK, PROJ)


def bump() -> None:
    """New key for the pool grid, so its row selection starts empty."""
    st.session_state[NONCE] = st.session_state.get(NONCE, 0) + 1


def reset() -> None:
    """Clear the game (mode and pool stay as chosen). No confirm step."""
    for key in GAME_KEYS:
        st.session_state.pop(key, None)
    st.session_state[BUILD_SLOTS] = [None] * sim.ROSTER_SIZE
    st.session_state[SEARCH] = ""
    bump()
