"""Design tokens and global CSS. Dark-first theme; chart palette values are
the validated dark-mode steps from the dataviz reference palette. Team
colors are brand-adjacent hues tuned for legibility on the dark surface
(identity accents on UI chrome, not chart series colors)."""

import html

from core import teams

# Categorical series slots (dark-surface steps, fixed order - never cycle).
# This is the reference palette's own slot order: blue, orange, aqua,
# yellow, magenta, green, violet, red. An earlier shuffle of these same
# eight colours put red next to magenta and green next to yellow, pairs too
# close to tell apart (the red/magenta pair measured a perceptual distance
# of 7.8 against a floor of 15, so even full-colour vision struggled). The
# order is what makes adjacent slots legible, so keep it.
SERIES = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"]

ACCENT = SERIES[0]  # blue - primary/emphasis hue
DIVERGE_POS = "#3987e5"  # diverging pair: blue <-> red
DIVERGE_NEG = "#e66767"
GOOD = "#0ca30c"  # status - reserved, never a series color
CRITICAL = "#d03b3b"

SURFACE = "#1a1a19"  # card / chart surface
PAGE = "#0d0d0d"  # page plane
INK = "#ffffff"  # primary text
INK_2 = "#c3c2b7"  # secondary text
MUTED = "#898781"  # axis / labels
GRID = "#2c2c2a"  # hairline gridlines
BASELINE = "#383835"  # axis baseline / de-emphasis marks
BORDER = "rgba(255,255,255,0.10)"
AVATAR_BG = "#242423"  # behind a headshot, where the photo's transparent edges show

# Two-digit hex alpha suffixes for a "#rrggbb" token (f"{color}{TINT_ALPHA}"):
# the tinted fill of a chip or an initials disc (0x26, about 15%) and a
# chip's border (0x40, 25%).
TINT_ALPHA = "26"
TINT_BORDER_ALPHA = "40"

RADIUS = "2px"  # sharp, not rounded - the site-wide corner radius for every
# custom card/chip/badge/hero shape (native widgets get the
# same value via [theme] baseRadius/buttonRadius in
# .streamlit/config.toml, so nothing looks half-rounded)

FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'


def team_color(abbr: str) -> str:
    """The team's identity colour from the team_codes seed: one recognizable
    colour per franchise, historical codes included, brightened where the
    true primary is too dark to read on the dark surface. ACCENT for a code
    the seed doesn't know."""
    try:
        return teams.color(abbr)
    except KeyError:
        return ACCENT


def rgba(hex_color: str, alpha: float) -> str:
    """A "#rrggbb" token as a CSS rgba() string at the given opacity, so a
    translucent tint is derived from its token instead of retyped as RGB."""
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha:g})"


def team_dot(abbr: str, size: int = 9) -> str:
    return (
        f'<span style="display:inline-block;width:{size}px;height:{size}px;'
        f"border-radius:50%;background:{team_color(abbr)};"
        f'margin-right:6px;vertical-align:baseline"></span>'
    )


CSS = f"""
<style>
/* ---- global chrome ---- */
#MainMenu, footer {{ visibility: hidden; }}
[data-testid="stHeader"] {{ background: transparent; }}
.stApp {{
  background:
    radial-gradient(1100px 520px at 15% -12%, rgba(57,135,229,.22), transparent 60%),
    radial-gradient(900px 440px at 95% -8%, rgba(229,96,32,.13), transparent 55%),
    radial-gradient(1000px 500px at 50% 115%, rgba(144,133,233,.07), transparent 60%),
    {PAGE};
}}
/* Scales with the viewport instead of a fixed cap: a flat 1180px used under
   half the width of a 2560px monitor and left huge dead gutters. The vw term
   does the scaling, the px term stops lines and wide tables from stretching
   to an unreadable width on ultrawide displays. */
.block-container {{ padding-top: 1.2rem; padding-bottom: 5rem;
                    max-width: min(94vw, 1780px); }}
html, body, [class*="css"] {{ font-family: {FONT}; }}
h1, h2, h3 {{ font-weight: 800; letter-spacing: -0.02em; }}
h4 {{ font-weight: 700; letter-spacing: -0.01em; }}
/* accent bar before section headers (the h4 "#### ..." markdown blocks) */
[data-testid="stMarkdownContainer"] h4::before {{
  content: ""; display: inline-block; width: 4px; height: .95em;
  background: linear-gradient(180deg, {ACCENT}, #7db4f0);
  border-radius: 2px; margin-right: .55rem; vertical-align: -0.12em;
}}
[data-testid="stSidebar"] {{ background: #101010; border-right: 1px solid {BORDER}; }}
[data-testid="stSidebarNav"] a span {{ font-weight: 600; }}

/* ---- hero banner ---- */
.bip-hero {{
  position: relative; overflow: hidden;
  background:
    radial-gradient(600px 260px at 88% 20%, rgba(229,96,32,.16), transparent 60%),
    linear-gradient(120deg, rgba(57,135,229,.22) 0%, rgba(57,135,229,.06) 45%,
                    rgba(23,23,22,.9) 100%),
    linear-gradient(180deg, #1e1e1d 0%, #161615 100%);
  border: 1px solid rgba(57,135,229,.28);
  border-radius: {RADIUS};
  padding: 1.4rem 1.6rem;
  margin-bottom: 1rem;
  display: flex; align-items: center; justify-content: space-between; gap: 1rem;
}}
.bip-hero-title {{ font-size: 1.9rem; font-weight: 800; letter-spacing: -0.03em;
                   color: {INK}; line-height: 1.15; }}
.bip-hero-sub {{ font-size: .85rem; color: {INK_2}; margin-top: .3rem; }}
.bip-hero-spot {{ display: flex; align-items: center; gap: .8rem; text-align: right; }}
.bip-hero-spot .lbl {{ font-size: .68rem; text-transform: uppercase; letter-spacing: .08em;
                       color: {MUTED}; font-weight: 700; }}
.bip-hero-spot .name {{ font-size: 1.05rem; font-weight: 800; color: {INK}; }}
.bip-hero-spot .val {{ font-size: 1.35rem; font-weight: 800; color: {ACCENT};
                       font-variant-numeric: tabular-nums; }}

/* ---- cards ---- */
.bip-card {{
  background: linear-gradient(180deg, #1e1e1d 0%, #171716 100%);
  border: 1px solid {BORDER};
  border-radius: {RADIUS};
  padding: 1rem 1.25rem;
  margin-bottom: 0.75rem;
  transition: transform .15s ease, border-color .15s ease, box-shadow .15s ease;
}}
.bip-card:hover {{
  transform: translateY(-2px);
  border-color: rgba(57,135,229,.35);
  box-shadow: 0 6px 24px rgba(0,0,0,.35);
}}
.bip-card h4 {{
  margin: 0 0 .5rem 0; font-size: .78rem; font-weight: 700;
  text-transform: uppercase; letter-spacing: .08em; color: {MUTED};
}}
.bip-card h4::before {{ content: none; }}

/* ---- KPI tiles ---- */
.bip-kpi {{ border-left: 3px solid {ACCENT}; }}
.bip-kpi-label {{ font-size: .72rem; text-transform: uppercase; letter-spacing: .08em;
                  color: {MUTED}; font-weight: 600;
                  display: flex; justify-content: space-between; gap: .5rem; }}
.bip-kpi-note  {{ text-transform: none; letter-spacing: 0; font-weight: 500;
                  color: {MUTED}; white-space: nowrap; }}
.bip-kpi-value {{ font-size: 1.85rem; font-weight: 800; color: {INK}; line-height: 1.2;
                  font-variant-numeric: tabular-nums; }}
.bip-kpi-sub   {{ font-size: .75rem; color: {INK_2}; }}
/* Equal-height KPI rows. Streamlit already stretches each column to the
   row's height, but the card inside stays as tall as its own content, so a
   tile with a sub-line stood taller than its neighbours. Every wrapper
   between the column and the card is made a growing flex box so the card
   fills the column. */
[data-testid="stColumn"] [data-testid="stElementContainer"]:has(.bip-kpi) {{
  flex: 1 1 auto; display: flex; }}
[data-testid="stColumn"] [data-testid="stElementContainer"]:has(.bip-kpi) [data-testid="stMarkdown"],
[data-testid="stColumn"] [data-testid="stElementContainer"]:has(.bip-kpi) [data-testid="stMarkdown"] > div,
[data-testid="stColumn"] [data-testid="stElementContainer"]:has(.bip-kpi) [data-testid="stMarkdownContainer"] {{
  flex: 1 1 auto; display: flex; flex-direction: column; width: 100%; }}
[data-testid="stColumn"] .bip-kpi {{ flex: 1 1 auto; }}

/* ---- explanation icon (glossary.py terms) ----
   The bubble inherits nothing from an uppercase, letter-spaced card title:
   it resets case, spacing and size itself. Shown on :focus too, so a tap
   opens it on a phone. */
.bip-tip {{ position: relative; display: inline-flex; align-items: center;
            justify-content: center; width: 13px; height: 13px; margin-left: 6px;
            border: 1px solid {MUTED}; border-radius: 50%; color: {MUTED};
            font-size: 9px; font-weight: 700; font-style: normal; line-height: 1;
            text-transform: none; letter-spacing: 0; vertical-align: 1px;
            cursor: help; outline: none; }}
.bip-tip:hover, .bip-tip:focus {{ color: {INK}; border-color: {INK}; }}
.bip-tip::after {{ content: attr(data-tip); position: absolute; z-index: 1000;
                   left: -8px; top: calc(100% + 8px); width: max-content;
                   max-width: 260px; padding: .5rem .65rem;
                   background: {SURFACE}; color: {INK}; border: 1px solid {BORDER};
                   border-radius: {RADIUS}; box-shadow: 0 6px 24px rgba(0,0,0,.45);
                   font-size: .78rem; font-weight: 400; line-height: 1.4;
                   text-align: left; white-space: normal;
                   display: none; pointer-events: none; }}
/* display, not opacity: a hidden bubble must take no space, or it widens a
   scrolling table (lib/tables.py) with blank room past its last column */
.bip-tip:hover::after, .bip-tip:focus::after {{ display: block; }}

/* ---- Arcade player card: everything stacked down the middle ---- */
.bip-pc {{ text-align: center; padding: 1.2rem 1rem 1.1rem; }}
.bip-pc-name {{ font-size: 1.45rem; font-weight: 800; color: {INK}; margin-top: .55rem;
                line-height: 1.2; white-space: nowrap; overflow: hidden;
                text-overflow: ellipsis; }}
.bip-pc-meta {{ display: flex; justify-content: center; flex-wrap: wrap; gap: .3rem .5rem;
                margin-top: .45rem; font-size: .9rem; color: {INK_2}; }}
.bip-pc-meta b {{ color: {INK}; }}
.bip-pc-val {{ margin-top: .85rem; padding-top: .75rem; border-top: 1px solid {BORDER};
               font-size: 2.2rem; font-weight: 800; line-height: 1.1;
               font-variant-numeric: tabular-nums; }}
.bip-pc-val .lbl {{ display: block; margin-top: .25rem; font-size: .7rem; font-weight: 700;
                    color: {MUTED}; text-transform: uppercase; letter-spacing: .08em; }}

/* ---- leader rows ---- */
.bip-row {{ display: flex; align-items: baseline; gap: .55rem; padding: .42rem 0;
            border-bottom: 1px solid rgba(255,255,255,.06); }}
.bip-row:last-child {{ border-bottom: none; }}
.bip-rank {{ width: 1.35rem; height: 1.35rem; border-radius: 50%; flex: none;
             display: inline-flex; align-items: center; justify-content: center;
             color: {MUTED}; font-size: .72rem; font-weight: 700;
             font-variant-numeric: tabular-nums; align-self: center;
             background: rgba(255,255,255,.05); }}
.bip-name {{ flex: 1; min-width: 0; font-weight: 600; font-size: .88rem; color: {INK};
             white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.bip-team {{ flex: none; color: {MUTED}; font-size: .72rem; font-weight: 700; }}
.bip-val  {{ font-weight: 800; font-size: .95rem; color: {INK}; font-variant-numeric: tabular-nums; }}

/* ---- chips / dots ---- */
.bip-chip {{ display: inline-block; padding: 3px 12px; border-radius: {RADIUS};
             background: rgba(57,135,229,.16); color: #7db4f0;
             font-size: .75rem; font-weight: 700; letter-spacing: .02em;
             border: 1px solid rgba(57,135,229,.25); }}
.dot {{ display: inline-block; width: 9px; height: 9px; border-radius: 50%; margin-right: 3px; }}
.dot-w {{ background: {GOOD}; box-shadow: 0 0 6px rgba(12,163,12,.5); }}
.dot-l {{ background: {CRITICAL}; }}

/* ---- score cards ---- */
.bip-game {{ background: linear-gradient(180deg, #1e1e1d 0%, #171716 100%);
             border: 1px solid {BORDER}; border-radius: {RADIUS};
             padding: .7rem .9rem; margin-bottom: .6rem;
             transition: transform .15s ease, border-color .15s ease; }}
.bip-game:hover {{ transform: translateY(-2px); border-color: rgba(57,135,229,.35); }}
.bip-game-date {{ font-size: .68rem; color: {MUTED}; text-transform: uppercase;
                  letter-spacing: .06em; margin-bottom: .35rem; font-weight: 700; }}
.bip-game-line {{ display: flex; justify-content: space-between; align-items: center;
                  padding: .12rem 0; font-size: .95rem; }}
.bip-game-line .tm {{ font-weight: 600; color: {INK_2}; }}
.bip-game-line .tm.winner {{ color: {INK}; font-weight: 800; }}
.bip-game-line .sc {{ font-weight: 700; font-variant-numeric: tabular-nums; color: {INK_2}; }}
.bip-game-line .sc.winner {{ color: {INK}; font-weight: 800; }}

/* ---- standings table ---- */
table.bip-table {{ width: 100%; border-collapse: collapse; font-size: .85rem; }}
table.bip-table th {{ text-align: right; color: {MUTED}; font-size: .68rem;
                      text-transform: uppercase; letter-spacing: .06em;
                      padding: .3rem .45rem; border-bottom: 1px solid {BORDER};
                      font-weight: 700; }}
table.bip-table th.lft, table.bip-table td.lft {{ text-align: left; }}
table.bip-table td {{ text-align: right; padding: .42rem .45rem; color: {INK_2};
                      border-bottom: 1px solid rgba(255,255,255,.05);
                      font-variant-numeric: tabular-nums; }}
table.bip-table tr:last-child td {{ border-bottom: none; }}
table.bip-table tr:hover td {{ background: rgba(255,255,255,.025); }}
table.bip-table td.tm {{ font-weight: 700; color: {INK}; }}
table.bip-table td.pos {{ color: {GOOD}; font-weight: 700; }}
table.bip-table td.neg {{ color: {CRITICAL}; font-weight: 700; }}
/* lib/tables.py: scroll sideways on a phone instead of squeezing columns */
table.bip-table th, table.bip-table td {{ border-left: none; border-right: none;
                                         border-top: none; }}
table.bip-table, table.bip-table tr {{ border: none; }}
.bip-table-wrap {{ overflow-x: auto; }}
.bip-table-wrap table.bip-table th, .bip-table-wrap table.bip-table td {{ white-space: nowrap; }}
table.bip-table td.name {{ color: {INK}; font-weight: 600; white-space: nowrap; }}
/* the name column stays put while a phone scrolls the stats sideways */
.bip-table-wrap table.bip-table tr > :first-child {{ position: sticky; left: 0;
                                                    background: #1b1b1a; }}
table.bip-table td.hi {{ color: {INK}; font-weight: 800; }}
table.bip-table tr.bip-foot td {{ border-top: 1px solid {BORDER}; color: {INK};
                                  font-weight: 700; }}
table.bip-table tr.bip-foot .pct {{ font-size: .68rem; color: {MUTED}; font-weight: 600; }}
/* box score: one team per card, logo and score in the header */
.bip-box-head {{ display: flex; align-items: center; gap: .7rem; margin-bottom: .6rem; }}
.bip-box-head .tm {{ font-size: 1.05rem; font-weight: 800; color: {INK}; }}
.bip-box-head .side {{ font-size: .7rem; color: {MUTED}; text-transform: uppercase;
                       letter-spacing: .08em; font-weight: 700; }}
.bip-box-head .sc {{ margin-left: auto; font-size: 1.6rem; font-weight: 800;
                     color: {INK_2}; font-variant-numeric: tabular-nums; }}
.bip-box-head .sc.winner {{ color: {INK}; }}
.bip-box-dnp {{ font-size: .75rem; color: {MUTED}; margin-top: .55rem; }}

/* ---- mobile (<= 640px, Streamlit's own column-stacking breakpoint) ----
   Desktop is untouched: these rules only exist on phone-width viewports.
   Streamlit stacks every column full-width there; tile-shaped content
   (KPI tiles, game score cards) reads better two-across. */
@media (max-width: 640px) {{
  .block-container {{ padding-left: .9rem; padding-right: .9rem; padding-top: .8rem; }}
  div[data-testid="stColumn"]:has(.bip-kpi),
  div[data-testid="stColumn"]:has(.bip-game) {{
    min-width: calc(50% - .5rem) !important;
    flex: 1 1 calc(50% - .5rem) !important;
  }}
  .bip-kpi-value {{ font-size: 1.4rem; }}
  .bip-card {{ padding: .8rem .95rem; }}
  .bip-hero {{ flex-wrap: wrap; padding: 1rem 1.1rem; }}
  .bip-hero-title {{ font-size: 1.45rem; }}
  .bip-hero-spot {{ text-align: left; }}
  [data-testid="stMarkdownContainer"] h2 {{ font-size: 1.45rem; }}
}}
</style>
"""


def inject(st) -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def tip(text: str) -> str:
    """A small ⓘ that shows `text` on hover - or on tap/keyboard focus, via
    tabindex, since phones have no hover. Pure CSS (.bip-tip), no script."""
    safe = html.escape(text, quote=True)
    return (
        f'<span class="bip-tip" tabindex="0" role="note" aria-label="{safe}" '
        f'data-tip="{safe}">i</span>'
    )


def card_html(title: str, body_html: str, help: str = "", style: str = "") -> str:
    # `style` is extra inline CSS for the card box (e.g. a highlighted border).
    style_attr = f' style="{style}"' if style else ""
    return (
        f'<div class="bip-card"{style_attr}><h4>{title}{tip(help) if help else ""}'
        f"</h4>{body_html}</div>"
    )


def card(st, title: str, body_html: str, help: str = "") -> None:
    st.markdown(card_html(title, body_html, help), unsafe_allow_html=True)


def kpi(
    label: str, value: str, sub: str = "", accent: str = ACCENT, note: str = "", help: str = ""
) -> str:
    # `note` is a short qualifier on the label's own line (keeps the card the
    # same height as its neighbours); `sub` adds a line under the value;
    # `help` adds a hoverable explanation icon after the label.
    note_html = f'<span class="bip-kpi-note">{note}</span>' if note else ""
    sub_html = f'<div class="bip-kpi-sub">{sub}</div>' if sub else ""
    tip_html = tip(help) if help else ""
    return (
        f'<div class="bip-card bip-kpi" style="border-left-color:{accent}">'
        f'<div class="bip-kpi-label"><span>{label}{tip_html}</span>{note_html}</div>'
        f'<div class="bip-kpi-value">{value}</div>{sub_html}</div>'
    )


def rank_badge(i: int) -> str:
    # Every rank gets the same neutral treatment now - no gold/silver/bronze
    # for the top 3, which read as a game-app medal ladder rather than a
    # plain leaderboard position.
    return f'<span class="bip-rank">{i}</span>'


def chip(text: str, color: str = ACCENT) -> str:
    return (
        f'<span class="bip-chip" style="background:{color}{TINT_ALPHA};'
        f'border-color:{color}{TINT_BORDER_ALPHA};color:{color}">{text}</span>'
    )
