"""Design tokens and global CSS. Dark-first theme; chart palette values are
the validated dark-mode steps from the dataviz reference palette. Team
colors are brand-adjacent hues tuned for legibility on the dark surface
(identity accents on UI chrome, not chart series colors)."""

# Categorical series slots (dark-surface steps, fixed order - never cycle)
SERIES = ["#3987e5", "#199e70", "#c98500", "#008300",
          "#9085e9", "#e66767", "#d55181", "#d95926"]

ACCENT = SERIES[0]          # blue - primary/emphasis hue
DIVERGE_POS = "#3987e5"     # diverging pair: blue <-> red
DIVERGE_NEG = "#e66767"
GOOD = "#0ca30c"            # status - reserved, never a series color
CRITICAL = "#d03b3b"

SURFACE = "#1a1a19"         # card / chart surface
PAGE = "#0d0d0d"            # page plane
INK = "#ffffff"             # primary text
INK_2 = "#c3c2b7"           # secondary text
MUTED = "#898781"           # axis / labels
GRID = "#2c2c2a"            # hairline gridlines
BASELINE = "#383835"        # axis baseline / de-emphasis marks
BORDER = "rgba(255,255,255,0.10)"

FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'

# One recognizable color per franchise, brightened where the true primary
# is too dark to read on the dark surface. Historical codes included.
TEAM_COLORS = {
    "ATL": "#E03A3E", "BOS": "#00B25A", "BKN": "#A7A9AC", "CHA": "#00A9C4",
    "CHI": "#E23A47", "CLE": "#FDBB30", "DAL": "#2E8FE0", "DEN": "#FEC524",
    "DET": "#E01E38", "GSW": "#FFC72C", "HOU": "#E5313E", "IND": "#FDBB30",
    "LAC": "#E5484D", "LAL": "#FDB927", "MEM": "#7B9FD4", "MIA": "#F9A01B",
    "MIL": "#00B25A", "MIN": "#78BE20", "NOP": "#C9A25C", "NYK": "#F58426",
    "OKC": "#3AA0E0", "ORL": "#2E9BE0", "PHI": "#3B8FE0", "PHX": "#E56020",
    "POR": "#E03A3E", "SAC": "#9B6BC9", "SAS": "#C4CED4", "TOR": "#E5484D",
    "UTA": "#F9A01B", "WAS": "#E31837",
    # historical / relocated franchises
    "SEA": "#2DA05A", "VAN": "#00B2A9", "NJN": "#A7A9AC", "WSB": "#E31837",
    "SDC": "#E5484D", "KCK": "#4B8FD4", "CHH": "#00A9C4", "NOH": "#C9A25C",
    "NOK": "#C9A25C", "GOS": "#FFC72C", "SAN": "#C4CED4", "UTH": "#F9A01B",
    "PHL": "#3B8FE0", "CAP": "#E31837",
}


def team_color(abbr: str) -> str:
    return TEAM_COLORS.get(abbr, ACCENT)


def team_dot(abbr: str, size: int = 9) -> str:
    return (f'<span style="display:inline-block;width:{size}px;height:{size}px;'
            f'border-radius:50%;background:{team_color(abbr)};'
            f'margin-right:6px;vertical-align:baseline"></span>')


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
.block-container {{ padding-top: 1.2rem; padding-bottom: 5rem; max-width: 1180px; }}
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
  border-radius: 20px;
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
.bip-hero-spot .val {{ font-size: 1.35rem; font-weight: 800; color: #f6c65b;
                       font-variant-numeric: tabular-nums; }}

/* ---- cards ---- */
.bip-card {{
  background: linear-gradient(180deg, #1e1e1d 0%, #171716 100%);
  border: 1px solid {BORDER};
  border-radius: 16px;
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
                  color: {MUTED}; font-weight: 600; }}
.bip-kpi-value {{ font-size: 1.85rem; font-weight: 800; color: {INK}; line-height: 1.2;
                  font-variant-numeric: tabular-nums; }}
.bip-kpi-sub   {{ font-size: .75rem; color: {INK_2}; }}

/* ---- leader rows ---- */
.bip-row {{ display: flex; align-items: baseline; gap: .55rem; padding: .42rem 0;
            border-bottom: 1px solid rgba(255,255,255,.06); }}
.bip-row:last-child {{ border-bottom: none; }}
.bip-rank {{ width: 1.35rem; height: 1.35rem; border-radius: 50%; flex: none;
             display: inline-flex; align-items: center; justify-content: center;
             color: {MUTED}; font-size: .72rem; font-weight: 700;
             font-variant-numeric: tabular-nums; align-self: center;
             background: rgba(255,255,255,.05); }}
.bip-rank.r1 {{ background: linear-gradient(135deg, #f6c65b, #b8860b); color: #141414; }}
.bip-rank.r2 {{ background: linear-gradient(135deg, #d9d9d9, #8f8f8f); color: #141414; }}
.bip-rank.r3 {{ background: linear-gradient(135deg, #e0a370, #8c5a2b); color: #141414; }}
.bip-name {{ flex: 1; font-weight: 600; font-size: .88rem; color: {INK};
             white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.bip-team {{ color: {MUTED}; font-size: .72rem; font-weight: 700; }}
.bip-val  {{ font-weight: 800; font-size: .95rem; color: {INK}; font-variant-numeric: tabular-nums; }}
.bip-row:first-of-type .bip-val {{ color: #f6c65b; }}

/* ---- chips / dots ---- */
.bip-chip {{ display: inline-block; padding: 3px 12px; border-radius: 999px;
             background: rgba(57,135,229,.16); color: #7db4f0;
             font-size: .75rem; font-weight: 700; letter-spacing: .02em;
             border: 1px solid rgba(57,135,229,.25); }}
.dot {{ display: inline-block; width: 9px; height: 9px; border-radius: 50%; margin-right: 3px; }}
.dot-w {{ background: {GOOD}; box-shadow: 0 0 6px rgba(12,163,12,.5); }}
.dot-l {{ background: {CRITICAL}; }}

/* ---- score cards ---- */
.bip-game {{ background: linear-gradient(180deg, #1e1e1d 0%, #171716 100%);
             border: 1px solid {BORDER}; border-radius: 14px;
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
</style>
"""


def inject(st) -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def card(st, title: str, body_html: str) -> None:
    st.markdown(
        f'<div class="bip-card"><h4>{title}</h4>{body_html}</div>',
        unsafe_allow_html=True,
    )


def kpi(label: str, value: str, sub: str = "", accent: str = ACCENT) -> str:
    sub_html = f'<div class="bip-kpi-sub">{sub}</div>' if sub else ""
    return (f'<div class="bip-card bip-kpi" style="border-left-color:{accent}">'
            f'<div class="bip-kpi-label">{label}</div>'
            f'<div class="bip-kpi-value">{value}</div>{sub_html}</div>')


def rank_badge(i: int) -> str:
    cls = f" r{i}" if i <= 3 else ""
    return f'<span class="bip-rank{cls}">{i}</span>'


def chip(text: str, color: str = ACCENT) -> str:
    return (f'<span class="bip-chip" style="background:{color}26;'
            f'border-color:{color}40;color:{color}">{text}</span>')
