"""core.fmt: the money and rank formats the Finances and Teams pages share."""

from core.fmt import money, ordinal


def test_money():
    assert money(193_348_445) == "$193.3M"
    assert money(1_000_000) == "$1.0M"
    assert money(850_000) == "$850K"


def test_ordinal():
    assert [ordinal(n) for n in (1, 2, 3, 4, 11, 12, 13, 21, 22, 101, 111, 112)] == [
        "1st",
        "2nd",
        "3rd",
        "4th",
        "11th",
        "12th",
        "13th",
        "21st",
        "22nd",
        "101st",
        "111th",
        "112th",
    ]
