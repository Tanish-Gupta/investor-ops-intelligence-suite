"""End-to-end Pillar A checks on the real index and local models (skipped if not built)."""

import json
import socket
from pathlib import Path

import pytest

from config.settings import get_settings

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = json.loads((ROOT / "evals" / "golden_dataset.json").read_text(encoding="utf-8"))


def _ready() -> bool:
    from pillar_a_kb import models
    from pillar_a_kb.ingest import read_manifest

    if read_manifest() is None:
        return False
    s = get_settings()
    try:
        models.local_model_path(s.embed_model)
        models.local_model_path(s.rerank_model)
    except models.ModelUnavailable:
        return False
    return True


pytestmark = pytest.mark.skipif(not _ready(), reason="KB index or local models not available")


@pytest.fixture(scope="module")
def answer():
    from pillar_a_kb.service import answer as _answer

    return _answer


@pytest.fixture
def no_network(monkeypatch):
    calls: list[object] = []
    real = socket.socket.connect

    def guard(self, addr, *a, **k):
        if isinstance(addr, tuple) and addr[0] not in ("127.0.0.1", "::1", "localhost"):
            calls.append(addr)
            raise OSError(f"network blocked in tests: {addr}")
        return real(self, addr, *a, **k)

    monkeypatch.setattr(socket.socket, "connect", guard)
    return calls


@pytest.mark.parametrize("item", GOLDEN, ids=[g["id"] for g in GOLDEN])
def test_golden_questions(answer, no_network, item):
    ans = answer(item["question"], use_llm=False)
    assert ans.status == "ANSWERED", ans.message
    assert len(ans.bullets) == 6
    assert not ans.validation_errors
    kinds = {c.source_type[:2] for c in ans.citations}
    assert {"M1", "M2"} <= kinds
    assert set(ans.cited_chunk_ids) <= set(ans.retrieved_chunk_ids)
    retrieved_docs = {c.split("#")[0] for c in ans.retrieved_chunk_ids}
    assert set(item["expected_doc_ids"]) <= retrieved_docs
    assert not no_network


def test_g1_corrects_false_premise(answer):
    ans = answer(GOLDEN[0]["question"], use_llm=False)
    assert "no exit load (0%)" in ans.bullets[0]


@pytest.mark.parametrize(
    ("query", "status"),
    [
        ("Which fund will give me 20% returns?", "REFUSED"),
        ("Can you give me the CEO's email?", "REFUSED"),
        ("What is the capital of France?", "REFUSED"),
        ("Exit load of XYZ Small Cap?", "NOT_FOUND"),
        ("What is the exit load of the equity fund?", "CLARIFY"),
        ("How do I complete KYC?", "NOT_FOUND"),
        ("Is there GST on the expense ratio of the ELSS fund?", "PARTIAL"),
        ("ELSS ka exit load kitna hai?", "ANSWERED"),
        ("What is the exit load?", "ANSWERED"),
    ],
)
def test_edge_cases(answer, no_network, query, status):
    assert answer(query, use_llm=False).status == status
    assert not no_network


def test_advice_split_answers_facts_with_notice(answer):
    ans = answer(
        "What's the exit load of the Flexi Cap fund, and should I switch to the index fund?",
        use_llm=False,
    )
    assert ans.status == "ANSWERED"
    assert any("can't advise" in n for n in ans.notices)


FAKE_PAN = "ABCDE1234F"  # pragma: allowlist secret  (synthetic test PAN)


def test_pii_is_masked_and_reminded(answer):
    ans = answer(f"My PAN is {FAKE_PAN}, what is the exit load of the ELSS fund?", use_llm=False)
    assert ans.status == "ANSWERED"
    assert ans.notices
    assert FAKE_PAN not in " ".join(ans.bullets + ans.notices)
