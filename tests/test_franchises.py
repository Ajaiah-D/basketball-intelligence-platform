"""Franchise lineage for the Finances page: payroll follows the contracts,
and the mapping is by (code, season), never by code alone. The mapping
itself is the team_codes seed - see test_core_teams.py."""

import pandas as pd

from core import teams
from dashboard.lib import franchises


def test_annotate_and_era_spans():
    df = pd.DataFrame(
        {
            "season": ["2006-07", "2007-08", "2008-09", "2009-10"],
            "team_abbreviation": ["SEA", "SEA", "OKC", "OKC"],
        }
    )
    out = franchises.annotate(df)
    assert out["franchise"].tolist() == ["OKC"] * 4
    assert franchises.era_spans(out) == [
        ("2006-07", "2007-08", "Seattle SuperSonics"),
        ("2008-09", "2009-10", "Oklahoma City Thunder"),
    ]
    assert "franchise" not in df.columns, "annotate must not mutate its input"


def test_every_code_in_the_real_mart_maps_to_a_named_franchise(con):
    rows = con.execute(
        "select distinct team_abbreviation, season from main_marts.mart_team_finances"
    ).fetchall()
    franchise = {(c, s): teams.franchise_of(c, s) for c, s in rows}
    # franchise_name falls back to the id itself when there is no name.
    unnamed = {pair for pair, f in franchise.items() if teams.franchise_name(f) == f}
    assert not unnamed, f"codes with no franchise name: {sorted(unnamed)[:10]}"
