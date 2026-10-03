from core.prompts import load_prompt, load_yaml, refusal


def test_refusal_templates_exist():
    data = load_yaml("refusals.yaml")
    for key in ("advice", "pii_request", "pii_shared", "out_of_scope", "safe_fallback"):
        assert refusal(key)
    assert all(u.startswith("https://") for u in data["education_links"])


def test_refusal_formatting():
    assert "https://x" in refusal("not_in_sources", link="https://x")


def test_classifier_prompt_lists_intents():
    p = load_prompt("guardrail_classifier.v1.md")
    for intent in ("ALLOWED", "ADVICE", "PII_REQUEST", "OUT_OF_SCOPE"):
        assert intent in p
