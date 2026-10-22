"""Team payroll against the league's cap, tax and apron lines, and each
team-season's contracts.

mart_team_finances is read whole (`select *`): the Finances page checks for
columns an older published warehouse lacks (payroll_incomplete_reason,
payroll_fetched_at_utc) and words its captions accordingly, which a
written-out column list would turn into a binder error.
"""

from __future__ import annotations

import pandas as pd

from core import teams

from .. import franchises
from .core import objects_exist, q


def team_finances_available() -> bool:
    """Whether the payroll mart and the cap history are in the warehouse.
    The Finances page reads both as soon as this passes, so it checks both:
    a warehouse missing just the seed would otherwise crash past it."""
    return objects_exist("main_marts.mart_team_finances", "main.salary_cap_history")


def team_payroll_history(franchise: str | None = None) -> pd.DataFrame:
    """Payroll vs. cap/tax/apron thresholds, one row per team-season, oldest
    first.

    With a franchise key (see dashboard/lib/franchises.py), returns every
    season of that franchise under any code it has played under - OKC
    includes the 1984-2008 SEA rows, NOP the 1988-2002 CHH rows - annotated
    with franchise and era_name.

    SQL narrows the rows to the codes the franchise has ever used; pandas
    then keeps the seasons each code really belonged to it. That last step
    stays in Python because the mapping is core.teams', season-aware and
    with fallbacks for codes the seed doesn't cover (a future Seattle team
    on "SEA" is its own franchise, not Oklahoma City's), and core.teams reads
    the seed file rather than the warehouse on purpose.
    """
    if franchise is None:
        return q(
            """
            select *
            from main_marts.mart_team_finances
            order by season, team_abbreviation
            """
        )
    codes = sorted({e.team_code for e in teams.eras() if e.franchise_id == franchise} | {franchise})
    df = q(
        """
        select *
        from main_marts.mart_team_finances
        where list_contains(?, team_abbreviation)
        order by season, team_abbreviation
        """,
        (codes,),
    )
    df = franchises.annotate(df)
    return df[df["franchise"] == franchise].reset_index(drop=True)


def salary_cap_history() -> pd.DataFrame:
    """League-wide cap/tax/apron thresholds by season, independent of any team."""
    return q(
        """
        select season, salary_cap, luxury_tax, first_apron, second_apron
        from main.salary_cap_history
        order by season
        """
    )


def team_contracts_available() -> bool:
    """Whether mart_team_contracts exists - a warehouse published before
    per-player salaries were scraped has the finances mart but not this."""
    return objects_exist("main_marts.mart_team_contracts")


def team_contracts(season: str, team_abbreviation: str) -> pd.DataFrame:
    """One team-season's salaries, biggest first."""
    return q(
        """
        select player, salary_usd, salary_rank, share_of_payroll
        from main_marts.mart_team_contracts
        where season = ? and team_abbreviation = ?
        order by salary_rank, player
        """,
        (season, team_abbreviation),
    )
