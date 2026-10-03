"""Evaluations page: run the evals and browse the latest report."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from dashboard.ui_kit import empty_state, esc, page_header, pill, section

from .run_evals import REPORTS, SUITES, run_all, to_markdown, write_report

LATEST_JSON = REPORTS / "eval_report_latest.json"
BASELINE_JSON = REPORTS / "eval_report_baseline.json"


def load_report(path: Path | None = None) -> dict | None:
    try:
        return json.loads((path or LATEST_JSON).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _mark(ok: bool) -> str:
    return "✅" if ok else "❌"


def summary_frame(report: dict) -> pd.DataFrame:
    rows = [
        {
            "Eval": s["title"],
            "Metric": m["name"],
            "Score": m["value"],
            "Threshold": m["threshold"],
            "Status": _mark(m["passed"]),
        }
        for s in report["suites"]
        for m in s["metrics"]
    ]
    rows += [
        {"Eval": s["title"], "Metric": "crashed", "Score": s["error"], "Threshold": "—",
         "Status": "❌"}
        for s in report["suites"] if s.get("error")
    ]  # fmt: skip
    return pd.DataFrame(rows)


def checks_frame(suite: dict) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"ID": c["id"], "Check": c["name"], "Result": _mark(c["passed"]), "Detail": c["detail"]}
            for c in suite["checks"]
        ]
    )


def _run(keys: list[str]) -> None:
    with st.spinner("Running evals in an isolated sandbox (models load on first run)…"):
        report = run_all(keys or None)
        write_report(report)
    st.session_state["eval_flash"] = (
        "success" if report["all_passed"] else "warning",
        f"{report['passed']}/{report['total']} suites passed.",
    )
    st.rerun()


def _render_suite(suite: dict) -> None:
    head = f"{_mark(suite['passed'])} {suite['title']} · {suite.get('seconds', 0):.1f} s"
    with st.expander(head, expanded=not suite["passed"]):
        if suite.get("error"):
            st.error(suite["error"])
        if suite["checks"]:
            st.dataframe(checks_frame(suite), hide_index=True, width="stretch")
        for note in suite.get("notes", []):
            st.caption(note)
        if suite["key"] == "rag":
            for c in suite["checks"]:
                data = c.get("data") or {}
                if not data.get("bullets"):
                    continue
                st.markdown(f"**{c['id']}** — {c['name']}")
                st.markdown("\n".join(f"{i}. {b}" for i, b in enumerate(data["bullets"], 1)))
                if data.get("sources"):
                    st.caption(" · ".join(data["sources"]))


def _scorecards(report: dict) -> None:
    suites = report["suites"]
    for col, suite in zip(st.columns(len(suites) or 1), suites, strict=False):
        with col, st.container(border=True):
            badge = pill("Pass", "ok") if suite["passed"] else pill("Fail", "bad")
            st.markdown(
                f"**{esc(suite['title'])}**<br>{badge}",
                unsafe_allow_html=True,
            )
            for m in suite["metrics"][:3]:
                st.caption(f"{m['name']}: {m['value']} (≥ {m['threshold']})")


def render() -> None:
    page_header(
        "Quality",
        "Evaluations",
        "Proof the suite works: retrieval accuracy on the golden set, refusal of advice and PII, "
        "pulse structure and the theme-aware greeting, plus an end-to-end run. Every run uses a "
        "throwaway sandbox, so live bookings and notes are never touched.",
    )
    flash = st.session_state.pop("eval_flash", None)
    if flash:
        getattr(st, flash[0])(flash[1])

    with st.container(border=True):
        c1, c2 = st.columns([3, 1], vertical_alignment="bottom")
        keys = c1.multiselect(
            "Suites to run", list(SUITES), default=list(SUITES), key="eval_suites"
        )
        if c2.button("Run evaluations", type="primary", width="stretch", key="eval_run",
                     icon=":material/play_arrow:"):  # fmt: skip
            _run(keys)

    report = load_report()
    if not report:
        empty_state(
            "No eval report yet",
            "Run the evaluations above, or from a terminal: uv run python -m evals.run_evals",
        )
        return

    cfg = report.get("config", {})
    m1, m2, m3 = st.columns(3)
    m1.metric("Suites passed", f"{report['passed']}/{report['total']}", border=True)
    m2.metric("Generated", report["generated_at"][:16].replace("T", " "), border=True)
    m3.metric("Judge", cfg.get("judge", "—"), border=True)
    _scorecards(report)
    section("All metrics")
    st.dataframe(summary_frame(report), hide_index=True, width="stretch")
    st.caption(" · ".join(f"{k}={v}" for k, v in cfg.items()))
    section("Details by suite")
    for suite in report["suites"]:
        _render_suite(suite)

    with st.container(horizontal=True):
        st.download_button(
            "Report (Markdown)", to_markdown(report), "eval_report_latest.md",
            key="eval_dl_md", icon=":material/download:",
        )  # fmt: skip
        st.download_button(
            "Report (JSON)", json.dumps(report, indent=2, ensure_ascii=False),
            "eval_report_latest.json", key="eval_dl_json", icon=":material/download:",
        )  # fmt: skip

    baseline = load_report(BASELINE_JSON)
    if baseline:
        with st.expander("Baseline run (first execution, before fixes)"):
            st.caption(f"{baseline['passed']}/{baseline['total']} suites passed")
            st.dataframe(summary_frame(baseline), hide_index=True, width="stretch")
