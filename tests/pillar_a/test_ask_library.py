"""Ask page: coverage questions ("which funds / sources do you have?") are answered from the source
registry, and the "What I can answer" library card lists the funds and every source."""

import pytest

from tests.ui_helpers import goto, md, open_app


@pytest.fixture
def ask(workspace, monkeypatch):
    import shutil

    from pillar_a_kb import ui
    from tests.ui_helpers import ROOT

    shutil.copy(ROOT / "data" / "sources.csv", workspace / "sources.csv")
    monkeypatch.setattr(ui, "_manifest", lambda: {"documents": {}})
    monkeypatch.setattr(ui, "_warm_models", lambda: True)

    def no_retrieval(*a, **k):
        raise AssertionError("coverage questions must not hit retrieval")

    monkeypatch.setattr("pillar_a_kb.service.answer", no_retrieval)
    return goto(open_app(), "ask")


def test_library_card_lists_funds_and_sources(ask):
    text = md(ask)
    assert not ask.exception
    assert "What I can answer" in text and 'class="io-lib"' in text
    for fund in (
        "ELSS",
        "Flexi Cap",
        "Large Cap",
        "Index",
        "Liquid",
        "Bajaj Finserv Small Cap Fund",
    ):
        assert fund in text
    assert "Edelweiss MF" in text and "Bajaj Finserv MF" in text
    assert "fund documents" in text and "fee explainers" in text


@pytest.mark.parametrize(
    "q", ["what all mutual funds sources do you have?", "Which funds do you cover?"]
)
def test_coverage_question_answered_from_registry(ask, q):
    ask.text_input[0].input(q)
    ask.button(key="FormSubmitter:kb_form-Ask").click()
    at = ask.run()
    assert not at.exception, at.exception
    text = md(at)
    assert "From the library" in text and q in text
    sheet = next(m.value for m in at.markdown if 'class="io-paras"' in m.value)
    assert sheet.count("<li>") == 6  # keeps the six-point structure
    assert any("sources" in e.label for e in at.expander)
