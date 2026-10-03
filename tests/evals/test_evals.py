"""Phase 8: the eval suite itself — sandbox isolation, each suite passing, judge wiring, report."""

from __future__ import annotations

import json
import os

import pytest

from config.settings import get_settings
from evals import judge, run_evals
from evals.common import Check, Metric, SuiteResult
from evals.suites.integration import _same_effect


def test_sandbox_isolates_writes_and_restores_env():
    from evals.sandbox import sandbox

    real = get_settings().data_dir
    before = {k: os.environ.get(k) for k in ("DATA_DIR", "DB_PATH")}
    with sandbox() as root:
        s = get_settings()
        assert s.data_dir == root != real
        assert str(s.db_path).startswith(str(root))
        for name in ("corpus", "sources.csv"):
            if (real / name).exists():
                assert (root / name).is_symlink()
        with sandbox() as inner:
            assert get_settings().data_dir == inner != root
        assert get_settings().data_dir == root
    assert not root.exists()
    assert {k: os.environ.get(k) for k in before} == before
    assert get_settings().data_dir == real


def test_suite_result_requires_metrics_and_no_error():
    r = SuiteResult("x", "X")
    assert not r.passed
    r.metrics = [Metric("m", "1/1", "all", True)]
    assert r.passed
    r.error = "boom"
    assert not r.passed
    assert r.to_dict()["passed"] is False


@pytest.mark.parametrize("key", ["safety", "ux", "integration"])
def test_suite_passes(key):
    result = run_evals.run_suite(key)
    failed = [(c.id, c.detail) for c in result.checks if not c.passed]
    assert result.passed, (result.error, failed)


def test_rag_suite_passes():
    if not (get_settings().data_dir / "lancedb").exists():
        pytest.skip("Unified KB index not built (run `python -m pillar_a_kb.ingest`)")
    result = run_evals.run_suite("rag")
    assert result.passed, (result.error, [(c.id, c.detail) for c in result.checks])
    assert len(result.checks) == 5


def test_suite_crash_is_reported_not_raised(monkeypatch):
    def boom():
        raise RuntimeError("index missing")

    monkeypatch.setattr(run_evals, "_runner", lambda key: boom)
    result = run_evals.run_suite("rag")
    assert not result.passed and "index missing" in result.error


def test_safety_judge_verdict_can_fail_a_check(monkeypatch):
    from evals.suites import safety

    verdict = judge.RefusalVerdict(refused=True, gives_advice=True, leaks_pii=False)
    monkeypatch.setattr(safety.judge, "refusal", lambda *a: verdict)
    result = run_evals.run_suite("safety")
    assert not result.passed


def test_replay_must_hit_same_object_without_new_write():
    stored = {"event_id": "e1", "created": True, "title": "t"}
    assert _same_effect(stored, {"event_id": "e1", "created": False, "title": "t"})
    assert not _same_effect(stored, {"event_id": "e2", "created": False, "title": "t"})
    assert not _same_effect(stored, {"event_id": "e1", "created": True, "title": "t"})
    assert not _same_effect({"line": "a"}, {"line": "a", "appended": True})


# --- opt-in LLM judge ---------------------------------------------------------------------------


def test_judge_off_by_default(monkeypatch):
    calls = []
    monkeypatch.setattr(judge.llm, "complete", lambda *a, **k: calls.append(1))
    assert not get_settings().eval_llm_judge
    assert judge.judge_label() == "deterministic"
    assert judge.faithfulness("q", ["b"], ["c"]) is None
    assert judge.refusal("p", "r") is None
    assert not calls


def test_judge_needs_a_key_even_when_enabled(fresh_settings):
    fresh_settings.setenv("EVAL_LLM_JUDGE", "true")
    get_settings.cache_clear()
    assert not judge.enabled()


def test_judge_with_key_calls_judge_model(fresh_settings, with_key, monkeypatch):
    fresh_settings.setenv("EVAL_LLM_JUDGE", "true")
    get_settings.cache_clear()
    seen = {}

    def fake_complete(system, messages, *, schema, model, temperature):
        seen.update(system=system, payload=json.loads(messages), model=model, t=temperature)
        return schema(
            claims=[{"claim": "a", "supported": True}, {"claim": "b", "supported": False}]
        )

    monkeypatch.setattr(judge.llm, "complete", fake_complete)
    v = judge.faithfulness("What is the exit load?", ["1% within 90 days"], ["chunk"])
    assert v.score == 0.5
    assert seen["model"] == get_settings().llm_judge and seen["t"] == 0.0
    assert seen["payload"]["SOURCE CHUNKS"] == ["chunk"]
    assert "SOURCE CHUNKS" in seen["system"]
    assert judge.judge_label().startswith("llm:")


def test_judge_failure_falls_back(fresh_settings, with_key, monkeypatch):
    fresh_settings.setenv("EVAL_LLM_JUDGE", "true")
    get_settings.cache_clear()

    def fail(*a, **k):
        raise judge.llm.LLMError("rate limited")

    monkeypatch.setattr(judge.llm, "complete", fail)
    assert judge.pulse_tone("pulse") is None


# --- report -------------------------------------------------------------------------------------


def _fake_report(passed: bool = True) -> dict:
    ok = SuiteResult("safety", "Constraint adherence (Safety)")
    ok.metrics = [Metric("Required", "7/7", "100%", passed)]
    ok.checks = [Check("S1·voice", "Which fund?", passed, "all criteria met")]
    return {
        "generated_at": "2026-10-03T10:00:00+05:30",
        "config": {"generator": "deterministic", "judge": "deterministic"},
        "suites": [ok.to_dict()],
        "passed": int(passed),
        "total": 1,
        "all_passed": passed,
    }


def test_report_markdown_and_files(tmp_path):
    report = _fake_report(passed=False)
    paths = run_evals.write_report(report, tmp_path)
    md = paths["md"].read_text()
    assert "## Summary" in md and "| Eval | Metric | Score | Threshold | Status |" in md
    assert "Failures & Fixes" in md and "S1·voice" in md
    latest = json.loads(paths["latest_json"].read_text())
    assert {"generated_at", "config", "suites", "passed", "total", "all_passed"} <= set(latest)
    assert paths["md"].name == "eval_report_20261003-100000.md"


def test_run_all_shape():
    report = run_evals.run_all(["integration"])
    assert report["total"] == 1 and report["all_passed"]
    assert report["config"]["generator"] == "deterministic"


def test_cli_exit_code(tmp_path, monkeypatch):
    monkeypatch.setattr(run_evals, "run_all", lambda keys: _fake_report(passed=False))
    out = ["--out", str(tmp_path), "--deliverable", str(tmp_path / "evalsReport.md")]
    assert run_evals.main(out) == 1
    monkeypatch.setattr(run_evals, "run_all", lambda keys: _fake_report(passed=True))
    assert run_evals.main(out) == 0
    assert (tmp_path / "evalsReport.md").exists()


# --- Evals Report deliverable (evals are CLI-only; not shown in the product UI) -----------------


def test_deliverable_renders_all_sections(tmp_path):
    from evals import deliverable

    md = deliverable.render(_fake_report())
    for h in ("## 1. Scorecard", "Golden Dataset", "Adversarial Tests", "## 4. Tone & Structure"):
        assert h in md, h
    assert "1/1 eval suites passed" in md and "S1" in md
    out = deliverable.write(_fake_report(), tmp_path / "r.md")
    assert out.read_text(encoding="utf-8") == md
