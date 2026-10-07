"""The sentences the Finances page puts next to its numbers."""

import pandas as pd

from dashboard.lib import payroll
from dashboard.lib import theme as T

CAP, TAX, A1, A2 = 140_588_000, 170_814_000, 178_132_000, 188_931_000


def _row(pay, season="2024-25", code="BOS", flagged=False, tax=TAX, a1=A1, a2=A2):
    return pd.Series({
        "season": season, "team_abbreviation": code, "team_payroll": pay,
        "salary_cap": CAP, "luxury_tax": tax, "first_apron": a1, "second_apron": a2,
        "payroll_likely_incomplete": flagged,
        "over_cap": pay > CAP,
        "over_tax": (pay > tax) if tax else pd.NA,
        "over_first_apron": (pay > a1) if a1 else pd.NA,
        "over_second_apron": (pay > a2) if a2 else pd.NA,
    })


def test_money_and_ordinal():
    assert payroll.money(193_348_445) == "$193.3M"
    assert payroll.money(850_000) == "$850K"
    assert [payroll.ordinal(n) for n in (1, 2, 3, 4, 11, 12, 13, 21, 22)] == \
        ["1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "22nd"]


def test_bracket_picks_the_highest_line_crossed():
    assert payroll.bracket(_row(130e6)) == ("Under cap", T.GOOD)
    assert payroll.bracket(_row(150e6))[0] == "Over cap"
    assert payroll.bracket(_row(175e6))[0] == "Over tax"
    assert payroll.bracket(_row(180e6))[0] == "Over 1st apron"
    assert payroll.bracket(_row(200e6)) == ("Over 2nd apron", T.CRITICAL)
    assert payroll.bracket(_row(200e6, flagged=True))[0] == "Data incomplete"


def test_bracket_handles_pre_apron_nulls():
    row = _row(150e6, season="2010-11", tax=None, a1=None, a2=None)
    assert payroll.bracket(row)[0] == "Over cap"


def test_position_phrase():
    assert payroll.position_phrase(_row(130_588_000)) == "$10.0M under the salary cap"
    assert payroll.position_phrase(_row(150_588_000)) == \
        "$10.0M over the salary cap and $20.2M under the luxury tax line"
    assert payroll.position_phrase(_row(175_814_000)) == \
        "$5.0M over the luxury tax line and $2.3M under the first apron"
    assert payroll.position_phrase(_row(198_931_000)) == "$10.0M over the second apron"
    pre_tax = _row(150_588_000, season="1999-00", tax=None, a1=None, a2=None)
    assert payroll.position_phrase(pre_tax) == "$10.0M over the salary cap"


def _league():
    return pd.DataFrame([_row(p, code=c) for c, p in
                         [("BOS", 193e6), ("PHX", 214e6), ("DET", 141.8e6), ("ORL", 150e6)]]
                        + [_row(2e6, code="XXX", flagged=True)])


def test_league_rank_ignores_unreliable_rows():
    assert payroll.league_rank(_league(), "PHX") == (1, 4)
    assert payroll.league_rank(_league(), "BOS") == (2, 4)
    assert payroll.league_rank(_league(), "XXX") is None


def test_league_summary():
    text = payroll.league_summary(_league(), "2024-25")
    assert text == ("In 2024-25, 4 of 4 teams were over the salary cap, 2 over the "
                    "luxury tax line, 2 over the first apron and 2 over the second "
                    "apron. 1 team has no reliable figure for this season.")


def test_team_summary_with_contracts():
    contracts = pd.DataFrame({
        "player": ["Player One", "Player Two", "Player Three", "Player Four"],
        "salary_usd": [50e6, 30e6, 20e6, 10e6],
        "salary_rank": [1, 2, 3, 4],
        "share_of_payroll": [0.25, 0.15, 0.10, 0.05],
    })
    text = payroll.team_summary(_row(175_814_000), "Boston Celtics", (3, 30), contracts)
    assert text == ("In 2024-25 the Boston Celtics spent $175.8M, the 3rd-highest payroll "
                    "of 30 teams. That's $5.0M over the luxury tax line and $2.3M under "
                    "the first apron. Their three biggest contracts (Player One, Player "
                    "Two and Player Three) made up 50% of the payroll.")


def test_team_summary_top_payroll_and_no_contracts():
    text = payroll.team_summary(_row(214e6), "Phoenix Suns", (1, 30), None)
    assert text.startswith("In 2024-25 the Phoenix Suns spent $214.0M, the highest "
                           "payroll of 30 teams.")
    assert "contracts" not in text


def test_team_summary_unreliable():
    text = payroll.team_summary(_row(2e6, flagged=True), "Denver Nuggets", None, None)
    assert text == "There's no reliable payroll figure for the Denver Nuggets in 2024-25."


def test_freshness_text():
    ts = pd.Timestamp("2026-09-23 20:58:40")
    assert payroll.freshness_text(ts, "2025-26", "2025-26") == \
        "Salary data updated Sep 23, 2026 · covers through 2025-26."
    assert payroll.freshness_text(ts, "2025-26", "2026-27") == \
        ("Salary data updated Sep 23, 2026 · covers through 2025-26. "
         "2026-27 payrolls aren't loaded yet.")
    assert payroll.freshness_text(None, "2025-26", "2025-26") == \
        "Salary data covers through 2025-26 (update date not recorded in this copy)."
