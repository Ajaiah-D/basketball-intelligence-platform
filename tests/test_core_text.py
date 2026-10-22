"""core.text.fold: the one folding every search box matches in."""

import pytest

from core.text import fold


@pytest.mark.parametrize(
    ("text", "folded"),
    [
        ("Nikola Jokić", "nikola jokic"),
        ("Jonas Valančiūnas", "jonas valanciunas"),
        ("Kristaps Porziņģis", "kristaps porzingis"),
        ("ŁUKASZ", "lukasz"),
        ("Bjørn Ødegaard", "bjorn odegaard"),
        ("Đorđe", "dorde"),
        ("Þórsson", "thorsson"),
        ("Straße", "strasse"),
        ("Æsir", "aesir"),
        ("İlyasova", "ilyasova"),
        # Not letters: dropped, as before (the Arcade's search text holds the
        # team path "CHI → BOS").
        ("CHI → BOS", "chi  bos"),
    ],
)
def test_fold(text, folded):
    assert fold(text) == folded


def test_fold_takes_anything_printable():
    assert fold(2024) == "2024"


def test_fold_is_idempotent():
    for text in ("Łukasz Kowalski", "Bjørn", "Jokić", "plain"):
        assert fold(fold(text)) == fold(text)
