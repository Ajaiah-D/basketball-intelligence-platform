from dashboard.lib import glossary
from dashboard.lib import theme as T


def test_every_term_has_a_real_explanation():
    for term, text in glossary.TERMS.items():
        assert len(text) > 10 and text.endswith("."), term


def test_marked_and_described_column_kwargs():
    assert glossary.marked("TS%") == {"label": "TS% ⓘ", "help": glossary.TERMS["TS%"]}
    assert glossary.described("FGA") == {"label": "FGA", "help": glossary.TERMS["FGA"]}


def test_tip_escapes_its_text_and_is_reachable_without_a_mouse():
    html = T.tip('Say "hi" <b>')
    assert 'data-tip="Say &quot;hi&quot; &lt;b&gt;"' in html
    assert 'tabindex="0"' in html  # tap/keyboard focus shows it on phones


def test_kpi_and_card_accept_help():
    assert 'class="bip-tip"' in T.kpi("Pace", "99.1", help=glossary.TERMS["Pace"])
    assert 'class="bip-tip"' not in T.kpi("Games", "1,230")
    assert 'class="bip-tip"' in T.card_html("Usage", "", help=glossary.TERMS["Usage"])
