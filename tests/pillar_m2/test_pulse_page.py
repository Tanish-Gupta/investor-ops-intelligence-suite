"""Admin portal, Review pulse page: reviews CSV in, Weekly Pulse out, and the pulse briefs the voice
agent (greeting) and the advisor email (Market Context)."""

from tests.pillar_m2.conftest import NOMINEE
from tests.ui_helpers import goto, md, open_app


def test_pulse_page_empty_then_processes_sample(workspace):
    at = goto(open_app(), "pulse")
    assert not at.exception and not at.error
    assert "No pulse yet" in md(at)
    at.button(key="pulse_run").click()
    at = at.run()
    assert not at.exception and not at.error
    text = md(at)
    assert "PULSE-" in text and at.session_state["pulse_id"] in text
    assert "Briefs the voice agent" in text and "Market Context" in text
    assert 'class="io-bars sage"' in text  # cleaning funnel from the processed file
    assert "Unique reviews analysed" in text


def test_processed_upload_rebriefs_the_book_page(workspace):
    at = goto(open_app(), "pulse")
    at.button(key="pulse_run").click()  # sample first, then the upload changes the theme
    at = at.run()
    from pillar_m2_pulse.pulse import run_pulse

    with NOMINEE.open("rb") as fh:
        p = run_pulse(fh)
    at = goto(at, "pulse")
    assert "Nominee Updates" in md(at) and p.pulse_id in md(at)
    at = goto(at, "book")
    assert "<b>Nominee Updates</b>" in md(at)
    first_agent_line = at.session_state["voice_turns"][0][1].text
    assert "Nominee" in first_agent_line
