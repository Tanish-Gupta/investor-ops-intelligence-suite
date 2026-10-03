"""The Weekly Pulse briefs the voice agent: the Book page shows the briefing, and uploading new
reviews rebuilds the pulse so the next greeting names the new top theme."""

import pytest

from tests.pillar_m2.conftest import NOMINEE
from tests.ui_helpers import goto, md, open_app


def test_rebrief_from_upload_changes_greeting(workspace):
    from pillar_b_voice.greeting import build_greeting
    from pillar_b_voice.ui import rebrief

    with NOMINEE.open("rb") as fh:
        p = rebrief(fh)
    assert p.top_theme == "Nominee Updates"
    g = build_greeting(p)
    assert g.kind == "bookable" and "Nominee Updates" in g.text
    at = goto(open_app(60), "book")
    assert not at.exception
    assert "<b>Nominee Updates</b>" in md(at) and p.pulse_id in md(at)


def test_rebrief_rejects_bad_csv(workspace, tmp_path):
    from pillar_b_voice.ui import rebrief
    from pillar_m2_pulse.reviews import ReviewInputError

    bad = tmp_path / "bad.csv"
    bad.write_text("foo,bar\n1,2\n")
    with pytest.raises(ReviewInputError), bad.open("rb") as fh:
        rebrief(fh)
