from pillar_a_kb.composer import Composed
from pillar_a_kb.retriever import Retrieved
from pillar_a_kb.validator import validate


def _chunk(cid: str, source_type: str, text: str) -> Retrieved:
    return Retrieved(
        chunk_id=cid,
        doc_id=cid.split("#")[0],
        source_type=source_type,
        scheme="",
        field="",
        fee_type="",
        url="https://example.org",
        title=cid,
        fetched_on="2026-10-03",
        text=text,
    )


CHUNKS = [
    _chunk("F-ELSS-01#exit_load", "M1_FACTSHEET", "Exit Load · 0%\nLock In · 3 Years"),
    _chunk("FE-EXIT-01", "M2_FEE_EXPLAINER", "An exit load is charged on early redemption."),
]
GOOD = Composed(
    bullets=[
        "The ELSS fund has a 0% exit load and a 3-year lock-in.",
        "Scheme page: Exit Load · 0%.",
        "An exit load is charged only on early redemption.",
        "ELSS units cannot be redeemed during the lock-in.",
        "Check your account statement for the deduction.",
        "Sources: Edelweiss ELSS; Fee Explainer – Exit load. Last updated 2026-10-03.",
    ],
    bullet_cites=[
        ["F-ELSS-01#exit_load"],
        ["F-ELSS-01#exit_load"],
        ["FE-EXIT-01"],
        ["FE-EXIT-01"],
        ["FE-EXIT-01"],
        ["F-ELSS-01#exit_load", "FE-EXIT-01"],
    ],
    mode="template",
)


def _with(bullets=None, cites=None) -> Composed:
    return Composed(
        bullets or list(GOOD.bullets), cites or [list(c) for c in GOOD.bullet_cites], "llm"
    )


def test_valid_answer_passes():
    assert validate(GOOD, CHUNKS, intent="COMBINED").ok


def test_wrong_bullet_count():
    ans = _with(GOOD.bullets[:5], GOOD.bullet_cites[:5])
    assert "bullet_count:5" in validate(ans, CHUNKS, intent="FEE").errors


def test_too_long_and_uncited():
    bullets = list(GOOD.bullets)
    bullets[2] = " ".join(["word"] * 31)
    cites = [list(c) for c in GOOD.bullet_cites]
    cites[3] = []
    errors = validate(_with(bullets, cites), CHUNKS, intent="FEE").errors
    assert "bullet_3_too_long:31" in errors and "bullet_4_uncited" in errors


def test_citation_must_be_retrieved():
    cites = [list(c) for c in GOOD.bullet_cites]
    cites[2] = ["FE-STT-01"]
    errors = validate(_with(cites=cites), CHUNKS, intent="FEE").errors
    assert "bullet_3_cites_unretrieved:FE-STT-01" in errors


def test_combined_needs_m1_and_m2():
    cites = [["FE-EXIT-01"]] * 6
    errors = validate(_with(cites=cites), CHUNKS, intent="COMBINED").errors
    assert "combined_missing_m1_source" in errors


def test_number_grounding():
    bullets = list(GOOD.bullets)
    bullets[0] = "The ELSS fund has a 2% exit load."
    errors = validate(_with(bullets), CHUNKS, intent="FEE").errors
    assert "bullet_1_ungrounded_numbers:2" in errors
    # numbers from the user's own question are allowed
    assert validate(_with(bullets), CHUNKS, intent="FEE", question="is it 2%?").ok


def test_output_guardrail_catches_advice():
    bullets = list(GOOD.bullets)
    bullets[3] = "You should buy this fund now."
    errors = validate(_with(bullets), CHUNKS, intent="FEE").errors
    assert any(e.startswith("bullet_4_") for e in errors)
