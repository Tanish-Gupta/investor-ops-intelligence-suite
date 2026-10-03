"""Unified Search latency check (task 9.3): target p50 < 4 s.

Runs the golden questions (G1-G5) plus the adversarial prompts through `pillar_a_kb.service.answer`
inside an eval sandbox (no writes to the real DB), once cold (first call loads the embedding and
re-ranker models) and then N warm rounds. The LLM is off by default, so this measures the
retrieval + deterministic composer path; `--llm` measures the configured provider instead.

    uv run python scripts/latency_check.py              # exit code 1 if warm p50 >= target
    uv run python scripts/latency_check.py --rounds 5 --target-ms 4000
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from evals.sandbox import sandbox  # noqa: E402


def _questions() -> list[tuple[str, str]]:
    golden = json.loads((ROOT / "evals" / "golden_dataset.json").read_text())
    adversarial = json.loads((ROOT / "evals" / "adversarial.json").read_text())
    qs = [(g["id"], g["question"]) for g in golden]
    qs += [(a["id"], a["prompt"]) for a in adversarial if a.get("prompt")]
    return qs


def _pct(values: list[float], q: float) -> float:
    s = sorted(values)
    return s[min(len(s) - 1, round(q * (len(s) - 1)))]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--rounds", type=int, default=3, help="warm rounds over all questions")
    ap.add_argument("--target-ms", type=int, default=4000)
    ap.add_argument("--llm", action="store_true", help="use the configured LLM (external calls)")
    args = ap.parse_args(argv)

    qs = _questions()
    rows: list[tuple[str, str, int]] = []
    with sandbox():
        from pillar_a_kb.service import answer

        t0 = time.perf_counter()
        first = answer(qs[0][1], use_llm=args.llm)
        cold_ms = (time.perf_counter() - t0) * 1000
        warm: list[float] = []
        for _ in range(args.rounds):
            for qid, q in qs:
                t = time.perf_counter()
                ans = answer(q, use_llm=args.llm)
                ms = (time.perf_counter() - t) * 1000
                warm.append(ms)
                rows.append((qid, str(getattr(ans.status, "value", ans.status)), round(ms)))

    answered = [ms for _, status, ms in rows if status == "ANSWERED"] or [0]
    p50, p95 = statistics.median(answered), _pct(answered, 0.95)
    print(f"Unified Search latency ({'LLM' if args.llm else 'offline composer'})")
    status0 = getattr(first.status, "value", first.status)
    print(f"  cold first call ({qs[0][0]}, {status0}): {cold_ms:,.0f} ms (includes model load)")
    print(f"  warm, all prompts: n={len(warm)}  p50={statistics.median(warm):,.0f} ms")
    print(f"  warm, ANSWERED only (gated): n={len(answered)}  p50={p50:,.0f} ms  p95={p95:,.0f} ms")
    per_q: dict[str, list[int]] = {}
    for qid, _status, ms in rows:
        per_q.setdefault(qid, []).append(ms)
    for qid, ms_list in per_q.items():
        status = next(s for i, s, _ in rows if i == qid)
        print(f"    {qid:<4} {status:<9} median {statistics.median(ms_list):>6,.0f} ms")
    ok = p50 < args.target_ms
    verdict = "PASS ✅" if ok else "FAIL ❌"
    print(f"warm p50 {'<' if ok else '>='} {args.target_ms} ms target: {verdict}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
