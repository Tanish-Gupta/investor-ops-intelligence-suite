"""Lite runtime (Streamlit Community Cloud): keyword-only index, no torch or local models."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from config.settings import get_settings

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = json.loads((ROOT / "evals" / "golden_dataset.json").read_text(encoding="utf-8"))


def _reset() -> None:
    from core import state
    from pillar_a_kb import retriever

    get_settings.cache_clear()
    state.get_engine.cache_clear()
    retriever._retriever = None


@pytest.fixture(scope="module")
def lite_kb(tmp_path_factory):
    """Build the keyword-only index once into a temp data dir with the real corpus."""
    from pillar_a_kb.ingest import ingest

    real = get_settings().data_dir
    root = tmp_path_factory.mktemp("lite")
    for name in ("corpus", "sources.csv"):
        (root / name).symlink_to((real / name).resolve())
    mp = pytest.MonkeyPatch()
    mp.setenv("KB_LITE", "true")
    mp.setenv("DATA_DIR", str(root))
    mp.setenv("DB_PATH", str(root / "artifacts" / "suite.db"))
    mp.setenv("PULSE_AUTOBUILD", "false")
    _reset()
    report = ingest(rebuild=True, use_docling=False)
    yield report
    mp.undo()
    _reset()


def test_lite_index_builds_without_models(lite_kb):
    assert lite_kb["total_chunks"] > 0
    assert lite_kb["chunker"] == "heading-fallback"
    assert lite_kb["embed_model"].startswith("none")
    assert get_settings().lancedb_dir.name == "lancedb_lite"


def test_models_are_disabled_in_lite(lite_kb):
    from pillar_a_kb import models

    models.embedder.cache_clear()
    models.reranker.cache_clear()
    with pytest.raises(models.ModelUnavailable):
        models.embed_query("exit load")
    with pytest.raises(models.ModelUnavailable):
        models.rerank("exit load", ["text"])


def test_keyword_search_finds_fee_logic(lite_kb):
    from pillar_a_kb.retriever import get_retriever

    r = get_retriever(refresh=True)
    hits = r.search("stamp duty on purchase")
    assert hits, "FTS search returned nothing"
    assert not r.degraded
    assert not r.reranks
    assert any("stamp" in h.text.lower() for h in hits)


@pytest.mark.parametrize("item", GOLDEN, ids=[g["id"] for g in GOLDEN])
def test_golden_questions_in_lite(lite_kb, item):
    from pillar_a_kb.retriever import get_retriever
    from pillar_a_kb.service import answer

    get_retriever(refresh=True)
    ans = answer(item["question"], use_llm=False)
    assert ans.status == "ANSWERED", ans.message
    assert len(ans.bullets) == 6
    assert not ans.validation_errors
    assert not any("unavailable" in n.lower() for n in ans.notices)
