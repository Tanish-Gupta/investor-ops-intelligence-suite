import pytest

from core import pii
from core.pii import REDACTED

# (input, raw values that must disappear)
MASKED = [
    ("My PAN is ABCPD1234E", ["ABCPD1234E"]),
    ("pan abcde1234f please", ["abcde1234f"]),  # pragma: allowlist secret
    ("my aadhaar is 2345 6789 0124", ["2345 6789 0124"]),
    ("aadhaar 1234 5678 9012 (invalid checksum)", ["1234 5678 9012"]),
    ("aadhaar 123456789012", ["123456789012"]),
    ("call me on +91 98765 43210", ["98765 43210"]),
    ("my number is 9876543210", ["9876543210"]),
    ("whatsapp 09876543210", ["9876543210"]),
    ("email jane.doe@example.com", ["jane.doe@example.com"]),
    ("pay to ramesh.k@okaxis", ["ramesh.k@okaxis"]),
    ("folio number 1234567/89", ["1234567/89"]),
    ("account no: 001234567890", ["001234567890"]),
    ("acct 12345678", ["12345678"]),
    ("card 4111 1111 1111 1111", ["4111 1111 1111 1111"]),
    ("ref 1234-5678-901", ["1234-5678-901"]),
    ("nine eight seven six five four three two one zero", ["nine eight seven"]),
    ("My name is Rahul Sharma and I need help", ["Rahul", "Sharma"]),
    ("mera naam priya verma hai", ["priya", "verma"]),
    ("I am Anil Kumar from Pune", ["Anil", "Kumar"]),
    ("I'm Neha, I need help with KYC", ["Neha"]),
    ("Mr. Suresh Iyer called yesterday", ["Suresh", "Iyer"]),
    ("name: Kavya Reddy", ["Kavya", "Reddy"]),
]

UNCHANGED = [
    "Booking NL-A742 on 2026-01-14 at 10:30 for PULSE-2026-W02",
    "Exit load is 1% if redeemed within 365 days; NAV 45.67, AUM Rs 12,345 crore",
    "ELSS lock-in is 3 years, expense ratio 0.62%",
    "Edelweiss Flexi Cap Fund direct growth",
    "I am facing login issues since the update",
    "this is Groww support",
    "The app crashed 3 times; rated 1 star on 12/01/2025",
    "SIP of 5000 per month since 2019",
    "UID:evt-nl-a742-v1@investor-ops.local",
    "What's the phone number of the advisor I'm booked with?",
    "How do I update my nominee in the app?",
    "Stamp duty of 0.005% applies on purchases",
]


@pytest.mark.parametrize(("text", "raw"), MASKED)
def test_pii_is_masked(text, raw):
    out = pii.redact(text)
    assert REDACTED in out
    for value in raw:
        assert value not in out
    assert pii.contains_pii(text)


@pytest.mark.parametrize("text", UNCHANGED)
def test_non_pii_is_untouched(text):
    assert pii.redact(text) == text
    assert not pii.contains_pii(text)


def test_adjacent_entities_merge_into_one_marker():
    out = pii.redact("contact: 9876543210 jane@example.com")
    assert out.count(REDACTED) == 1


def test_detect_returns_types_not_values():
    entities = pii.detect("PAN ABCPD1234E, phone 9876543210")
    types = {e.entity_type for e in entities}
    assert "IN_PAN" in types
    assert types & {"IN_MOBILE", "PHONE_NUMBER"}
    assert all(not hasattr(e, "text") for e in entities)


def test_scrub_recurses_into_structures():
    data = {"note": "email a@b.com", "items": ["PAN ABCPD1234E", 5], "code": "NL-A742"}
    out = pii.scrub(data)
    assert out["note"] == f"email {REDACTED}"
    assert out["items"] == [f"PAN {REDACTED}", 5]
    assert out["code"] == "NL-A742"


def test_configured_advisor_email_is_allowed():
    s = pii.PIIScrubber(allow_terms=("advisor@example.com",))
    text = "to advisor@example.com cc jane@example.com"
    out, _ = s.redact_with_entities(text)
    assert "advisor@example.com" in out
    assert "jane@example.com" not in out


def test_empty_and_whitespace():
    assert pii.redact("") == ""
    assert pii.redact("   ") == "   "
    assert pii.detect("") == []


def test_no_model_download_and_ner_optional():
    s = pii.PIIScrubber(nlp_model="definitely_not_installed_model")
    assert s.ner_enabled is False
    assert REDACTED in s.redact_with_entities("my name is Rahul")[0]
