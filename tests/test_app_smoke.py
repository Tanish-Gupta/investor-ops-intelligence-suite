from tests.ui_helpers import PAGES, goto, md, open_app


def test_every_page_renders_without_errors(workspace):
    at = open_app()
    assert not at.exception and not at.error
    assert "Investor ops and intelligence, in one place." in md(at)  # Home is the landing page
    for page in PAGES:
        at = goto(at, page)
        assert not at.exception, page
        assert not at.error, (page, [e.value for e in at.error])
        assert 'class="io-title"' in md(at), page  # every page has the shared masthead


def test_footer_shows_disclaimer_and_redaction(workspace):
    at = open_app()
    foot = next(m.value for m in at.markdown if 'class="io-foot"' in m.value)
    assert "No investment advice" in foot and "[REDACTED]" in foot
    assert not at.sidebar.metric  # no ops widgets in the product


def test_no_eval_or_ops_pages_in_navigation(workspace):
    text = md(open_app())
    for word in ("Faithfulness", "Health", "eval suite"):
        assert word not in text
