"""Run the evaluation suite and write the report (docs/evals.md §5).

    uv run python -m evals.run_evals                 # all suites
    uv run python -m evals.run_evals --suites safety ux

Every suite runs inside a sandboxed DATA_DIR (temp dir; real corpus / index are read-only
symlinks), so evals never touch the app's bookings, notes or pulses. Writes
`evals/reports/eval_report_<ts>.{md,json}` plus `eval_report_latest.{md,json}`, and (on a full
run) the submission Evals Report `docs/evalsReport.md`. Exit code 0 only when every selected suite
passes.
"""

from __future__ import annotations

import argparse
import json
import logging
import time
import traceback
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from config.settings import get_settings
from evals import deliverable, judge
from evals.common import SuiteResult
from evals.sandbox import sandbox

REPORTS = Path(__file__).resolve().parent / "reports"
SUITES: dict[str, str] = {
    "rag": "evals.suites.rag",
    "safety": "evals.suites.safety",
    "ux": "evals.suites.ux",
    "integration": "evals.suites.integration",
}
_log = logging.getLogger(__name__)


def _runner(key: str) -> Callable[[], SuiteResult]:
    import importlib

    return importlib.import_module(SUITES[key]).run


def _index_info() -> str:
    try:
        from pillar_a_kb.ingest import read_manifest

        m = read_manifest() or {}
        if not m:
            return "not built"
        return f"{m.get('total_chunks')} chunks/{m.get('documents')} docs ({m.get('built_at')})"
    except Exception:
        return "n/a"


def run_config() -> dict[str, str]:
    s = get_settings()
    from core.llm import llm_available

    gen = "llm" if (s.rag_llm_enabled and llm_available(s)) else "deterministic"
    return {
        "generator": f"{gen} ({s.llm_primary})" if gen == "llm" else gen,
        "judge": judge.judge_label(),
        "embed": s.embed_model,
        "rerank": s.rerank_model if s.rerank_enabled else "off",
        "index": _index_info(),
        "adapters": s.adapter_mode,
    }


def run_suite(key: str) -> SuiteResult:
    t0 = time.perf_counter()
    with sandbox():
        try:
            res = _runner(key)()
        except Exception as exc:  # a crashing suite is a failing suite, never a crashed run
            _log.exception("eval_suite_crashed", extra={"suite": key})
            res = SuiteResult(key, key, error=f"{type(exc).__name__}: {exc}")
            res.notes.append(traceback.format_exc(limit=3))
    res.seconds = round(time.perf_counter() - t0, 1)
    return res


def run_all(keys: list[str] | None = None) -> dict:
    keys = keys or list(SUITES)
    started = datetime.now(get_settings().tz)
    config = run_config()
    results = [run_suite(k) for k in keys]
    return {
        "generated_at": started.isoformat(timespec="seconds"),
        "config": config,
        "suites": [r.to_dict() for r in results],
        "passed": sum(r.passed for r in results),
        "total": len(results),
        "all_passed": all(r.passed for r in results),
    }


# --- report ---------------------------------------------------------------------------------


def _mark(ok: bool) -> str:
    return "✅" if ok else "❌"


def _cell(text: object) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def to_markdown(report: dict) -> str:
    when = datetime.fromisoformat(report["generated_at"]).strftime("%Y-%m-%d %H:%M %Z")
    cfg = " · ".join(f"{k}={v}" for k, v in report["config"].items())
    lines = [
        f"# Eval Report — {when}",
        "",
        f"Run config: {cfg}",
        "",
        f"**Overall:** {report['passed']}/{report['total']} suites passed "
        f"{_mark(report['all_passed'])}",
        "",
        "## Summary",
        "",
        "| Eval | Metric | Score | Threshold | Status |",
        "|------|--------|-------|-----------|--------|",
    ]
    for s in report["suites"]:
        if s["error"]:
            lines.append(f"| {s['title']} | — | error | — | ❌ |")
        for m in s["metrics"]:
            lines.append(
                f"| {s['title']} | {m['name']} | {m['value']} | {m['threshold']} | "
                f"{_mark(m['passed'])} |"
            )
    lines += ["", "## Details", ""]
    for s in report["suites"]:
        lines += [f"### {s['title']} — {_mark(s['passed'])} ({s['seconds']} s)", ""]
        if s["error"]:
            lines += [f"**Suite error:** `{s['error']}`", ""]
        lines += ["| ID | Check | Result | Detail |", "|----|-------|--------|--------|"]
        for c in s["checks"]:
            lines.append(
                f"| {c['id']} | {_cell(c['name'])} | {_mark(c['passed'])} | {_cell(c['detail'])} |"
            )
        lines += ["", *[f"- {n}" for n in s["notes"] if "Traceback" not in n], ""]
        if s["key"] == "rag":
            for c in s["checks"]:
                lines += [f"**{c['id']}** — {c['name']}", ""]
                lines += [f"{i}. {b}" for i, b in enumerate(c["data"].get("bullets", []), 1)]
                lines += ["", "Sources: " + "; ".join(c["data"].get("sources", [])), ""]
    failures = [
        (s["title"], c) for s in report["suites"] for c in s["checks"] if not c["passed"]
    ] + [
        (s["title"], {"id": "suite", "detail": s["error"]}) for s in report["suites"] if s["error"]
    ]
    lines += ["## Failures & Fixes", ""]
    if failures:
        lines += [f"- **{t} · {c['id']}** — {_cell(c['detail'])}" for t, c in failures]
    else:
        lines.append("None in this run. See docs/evals.md §8 for the baseline → final history.")
    return "\n".join(lines) + "\n"


def write_report(report: dict, out_dir: Path = REPORTS) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.fromisoformat(report["generated_at"]).strftime("%Y%m%d-%H%M%S")
    md, js = to_markdown(report), json.dumps(report, indent=2, ensure_ascii=False, default=str)
    paths = {
        "md": out_dir / f"eval_report_{stamp}.md",
        "json": out_dir / f"eval_report_{stamp}.json",
        "latest_md": out_dir / "eval_report_latest.md",
        "latest_json": out_dir / "eval_report_latest.json",
    }
    for key, path in paths.items():
        path.write_text(md if key.endswith("md") else js, encoding="utf-8")
    return paths


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--suites", nargs="*", choices=list(SUITES), default=None)
    ap.add_argument("--out", type=Path, default=REPORTS)
    ap.add_argument(
        "--deliverable",
        type=Path,
        default=deliverable.DELIVERABLE,
        help="Submission Evals Report (golden dataset, adversarial tests, scores).",
    )
    args = ap.parse_args(argv)
    report = run_all(args.suites)
    paths = write_report(report, args.out)
    if args.suites is None:  # the deliverable needs every suite
        print(f"Evals Report → {deliverable.write(report, args.deliverable)}")
    for s in report["suites"]:
        metrics = "; ".join(f"{m['name']}={m['value']}" for m in s["metrics"]) or s["error"]
        print(f"{'PASS' if s['passed'] else 'FAIL'}  {s['title']}: {metrics}")
    print(f"\n{report['passed']}/{report['total']} suites passed → {paths['md']}")
    return 0 if report["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
