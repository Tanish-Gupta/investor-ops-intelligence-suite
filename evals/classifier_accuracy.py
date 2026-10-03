"""Theme-classifier accuracy on the 50-review hand-labelled sample (themeClassification.md §5).

Run: `uv run python -m evals.classifier_accuracy [--llm]` → prints accuracy and writes
`evals/reports/classifier_accuracy.md`. The default checks the deterministic keyword fallback;
`--llm` uses the LLM classifier (needs PULSE_LLM_ENABLED-style opt-in and a configured key).

Sample: `evals/fixtures/classifier_sample50.csv`, stratified by rating (18×★1, 8×★2, 8×★3, 6×★4,
10×★5, seed 50) from `data/reviews/reviews.csv`, labelled by hand against `config/themes.yaml`.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from pillar_m2_pulse.classifier import classify_frame

ROOT = Path(__file__).resolve().parent
SAMPLE = ROOT / "fixtures" / "classifier_sample50.csv"
REPORTS = ROOT / "reports"
TARGET = 0.80


def evaluate(use_llm: bool = False) -> dict:
    s = pd.read_csv(SAMPLE, dtype={"review_id": str})
    frame = s.assign(title="", date=pd.Timestamp("2026-05-01"))
    out, stats = classify_frame(frame, use_llm=use_llm)
    out["correct"] = out["theme"] == out["gold_theme"]
    misses = out[~out["correct"]][["review_id", "gold_theme", "theme", "text"]]
    per_theme = {
        theme: f"{int(g['correct'].sum())}/{len(g)}" for theme, g in out.groupby("gold_theme")
    }
    return {
        "accuracy": round(float(out["correct"].mean()), 3),
        "n": len(out),
        "method": "llm" if stats.get("llm") else "keyword",
        "classifier_stats": stats,
        "per_theme": per_theme,
        "confusions": Counter(zip(misses["gold_theme"], misses["theme"], strict=True)),
        "misses": misses.to_dict("records"),
    }


def to_markdown(r: dict) -> str:
    verdict = "PASS" if r["accuracy"] >= TARGET else "BELOW TARGET"
    lines = [
        "# Theme classifier accuracy",
        "",
        f"_Generated {datetime.now(UTC):%Y-%m-%d %H:%M UTC} · method: {r['method']} · "
        f"n = {r['n']}_",
        "",
        f"**Accuracy: {r['accuracy']:.0%}** (target ≥ {TARGET:.0%}) — {verdict}",
        "",
        "| Gold theme | Correct |",
        "|---|---|",
        *[f"| {k} | {v} |" for k, v in sorted(r["per_theme"].items())],
        "",
        "## Misses",
        "",
        "| Gold | Predicted | Review (truncated) |",
        "|---|---|---|",
        *[
            f"| {m['gold_theme']} | {m['theme']} | {' '.join(str(m['text']).split()[:14])}… |"
            for m in r["misses"]
        ],
        "",
        "Note: the keyword list was extended after a first pass on this sample (76% → 86%), so the",
        "keyword figure is optimistic; the LLM classifier is the primary path when enabled.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", action="store_true", help="use the LLM classifier (needs a key)")
    args = ap.parse_args(argv)
    r = evaluate(use_llm=args.llm)
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "classifier_accuracy.md").write_text(to_markdown(r), encoding="utf-8")
    print(f"accuracy={r['accuracy']:.2f} method={r['method']} n={r['n']}")
    return 0 if r["accuracy"] >= TARGET else 1


if __name__ == "__main__":
    sys.exit(main())
