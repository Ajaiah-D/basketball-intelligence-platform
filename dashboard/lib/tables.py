"""Site-styled HTML tables for short, read-only data (the bip-table CSS in
theme.py).

The native st.dataframe grid draws into a canvas: it sorts, scrolls and
selects rows, but no CSS reaches its cells. Tables a reader only scans (box
scores, rosters, short lists) render as HTML instead, so they share the
cards' fonts, colors and team accents. Tables people sort or click stay
native.
"""

from __future__ import annotations

import html
from collections.abc import Callable
from dataclasses import dataclass

import pandas as pd

from . import theme as T


def _text(v) -> str:
    if v is None or (isinstance(v, float) and v != v):
        return "-"
    return html.escape(str(v))


@dataclass(frozen=True)
class Col:
    """One column. `fmt` turns a cell value into the cell's HTML (escape any
    text you return); `css` gives a cell its class, e.g. "pos"/"neg"."""

    key: str
    label: str
    fmt: Callable[[object], str] = _text
    left: bool = False
    help: str = ""
    css: Callable[[object], str] | None = None


def signed(v) -> str:
    """+5, -3, 0; '-' when missing."""
    if v is None or v != v:
        return "-"
    return f"{int(v):+d}" if v else "0"


def pos_neg(v) -> str:
    if v is None or v != v or v == 0:
        return ""
    return "pos" if v > 0 else "neg"


def html_table(
    rows: pd.DataFrame,
    cols: list[Col],
    foot: dict | None = None,
    row_css: Callable[[object], str] | None = None,
) -> str:
    """The table's HTML. `foot` maps column keys to ready-made HTML for a
    totals row (missing keys stay blank); `row_css` gives a row its class."""

    def cls(*names: str) -> str:
        joined = " ".join(n for n in names if n)
        return f' class="{joined}"' if joined else ""

    head = "".join(
        f"<th{cls('lft' if c.left else '')}>{html.escape(c.label)}"
        f"{T.tip(c.help) if c.help else ''}</th>"
        for c in cols
    )
    body = []
    for r in rows.itertuples(index=False):
        cells = "".join(
            f"<td{cls('lft' if c.left else '', c.css(getattr(r, c.key)) if c.css else '')}>"
            f"{c.fmt(getattr(r, c.key))}</td>"
            for c in cols
        )
        body.append(f"<tr{cls(row_css(r) if row_css else '')}>{cells}</tr>")
    if foot is not None:
        cells = "".join(
            f"<td{cls('lft' if c.left else '')}>{foot.get(c.key, '')}</td>" for c in cols
        )
        body.append(f'<tr class="bip-foot">{cells}</tr>')
    return (
        f'<div class="bip-table-wrap"><table class="bip-table">'
        f"<tr>{head}</tr>{''.join(body)}</table></div>"
    )
