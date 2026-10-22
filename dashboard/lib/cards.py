"""HTML cards shared by more than one page. A view must not import another
view, so a card that two pages draw lives here."""

from . import theme as T


def game_card(r) -> str:
    """One final score: date, then away and home lines, the winner in bold.
    `r` is a row from data.games.games_list (itertuples)."""
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
        f"</div>"
    )
