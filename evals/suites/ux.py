"""Eval 3 — Tone & structure (UX) (docs/evals.md §3).

Pulse rubric (per pulse: production reviews + the two fixtures): ≤ 250 words, exactly 3 action
ideas (both the list in the markdown and `action_ideas`), listed themes all from the taxonomy,
≤ 3 PII-free quotes, no PII anywhere; tone / idea quality scored by the opt-in judge (≥ 4/5).

Voice theme logic (U1–U3): each scenario runs in its own sandbox so the agent reads the *latest
persisted* pulse exactly as in the app. The top theme is recomputed independently from the CSV
with a keyword count (not the pipeline's classifier) and must match the pulse and the greeting.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import timedelta
from pathlib import Path

import pandas as pd

from config.settings import get_settings
from core import pii
from evals import judge
from evals.common import Check, Metric, SuiteResult, ratio
from evals.sandbox import sandbox
from pillar_m2_pulse.taxonomy import load_taxonomy

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
MAX_WORDS, N_IDEAS, MIN_JUDGE = 250, 3, 4


def _section(md: str, title: str) -> list[str]:
    m = re.search(rf"^## {re.escape(title)}\s*$(.*?)(?=^## |\Z)", md, re.M | re.S)
    if not m:
        return []
    return [ln.strip() for ln in m.group(1).splitlines() if re.match(r"\s*(?:\d+\.|-)\s+", ln)]


def keyword_top_theme(csv_path: Path) -> str | None:
    """Independent recount: taxonomy keywords per review, ties broken by taxonomy order."""
    df = pd.read_csv(csv_path)
    if df.empty:
        return None
    tax = load_taxonomy()
    counts: Counter[str] = Counter()
    for text in df["text"].astype(str):
        low = text.lower()
        best, best_hits = tax.fallback_label, 0
        for t in tax.themes:
            hits = sum(bool(re.search(rf"\b{re.escape(k)}\b", low)) for k in t.keywords)
            if hits > best_hits:
                best, best_hits = t.label, hits
        counts[best] += 1
    counts.pop(tax.fallback_label, None)
    return counts.most_common(1)[0][0] if counts else None


def pulse_rubric(name: str, p) -> Check:
    tax = load_taxonomy()
    ideas_md = _section(p.pulse_md, "Action Ideas")
    themes_md = _section(p.pulse_md, "Top Themes")
    listed = [re.search(r"\*\*(.+?)\*\*", t) for t in themes_md]
    labels = [m.group(1) for m in listed if m]
    quotes = _section(p.pulse_md, "What Users Are Saying")
    crit = {
        "words ≤ 250": p.word_count <= MAX_WORDS,
        "exactly 3 ideas": len(ideas_md) == N_IDEAS and len(p.action_ideas) == N_IDEAS,
        "themes from taxonomy": bool(labels)
        and len(labels) <= 3
        and all(lb in tax.labels for lb in labels),
        "≤ 3 PII-free quotes": len(quotes) <= 3 and not any(pii.contains_pii(q) for q in quotes),
        "no PII": not pii.contains_pii(p.pulse_md),
    }
    verdict = judge.pulse_tone(p.pulse_md)
    if verdict is not None:
        crit["tone/ideas ≥ 4 (judge)"] = (
            verdict.tone >= MIN_JUDGE and verdict.ideas_quality >= MIN_JUDGE
        )
    failed = [k for k, ok in crit.items() if not ok]
    return Check(
        id=f"PULSE·{name}",
        name=f"Weekly Pulse rubric — {name}",
        passed=not failed,
        detail=f"{p.word_count} words · {len(ideas_md)} ideas · themes {labels}"
        + (f" · failed: {', '.join(failed)}" if failed else ""),
        score=float(p.word_count),
        data={
            "pulse_id": p.pulse_id,
            "word_count": p.word_count,
            "ideas": p.action_ideas,
            "themes": labels,
            "top_theme": p.top_theme,
            "copy_method": p.copy_method,
            "criteria": crit,
            "judge": verdict.model_dump() if verdict else None,
            "pulse_md": p.pulse_md,
        },
    )


def _greet() -> tuple:
    from pillar_b_voice.agent import VoiceSession

    s = VoiceSession(on_end=None)  # pulse="latest" → reads the persisted pulse like the app
    turn = s.start()
    return s.greeting, turn


def voice_case(cid: str, csv: Path | None, expect: str | None, *, stale: bool = False) -> Check:
    from core import state
    from pillar_m2_pulse.pulse import run_pulse
    from pillar_m2_pulse.reviews import ReviewInputError

    with sandbox():
        pulse = None
        if csv is not None:
            try:
                pulse = run_pulse(csv, use_llm=False)
            except ReviewInputError:
                pulse = None
        if stale and pulse is not None:
            from sqlmodel import select

            with state.session_scope() as db:
                row = db.exec(select(state.Pulse)).first()
                row.created_at = state.now() - timedelta(days=30)
                db.add(row)
            artifact = get_settings().artifacts_dir / f"pulse_{pulse.pulse_id}.json"
            artifact.unlink(missing_ok=True)  # force the DB row (with its old timestamp) to be read
        greeting, turn = _greet()
    independent = keyword_top_theme(csv) if csv is not None and not stale else None
    text = turn.text.lower()
    if expect is None:
        crit = {
            "generic greeting": greeting.kind == "generic",
            "greeting_theme null": turn.greeting_theme is None,
        }
    else:
        crit = {
            "pulse top theme": pulse is not None and pulse.top_theme == expect,
            "independent recount agrees": independent == expect,
            "greeting_theme": turn.greeting_theme == expect,
            "theme mentioned": expect.lower() in text,
            "offers help/booking": "book" in text or "help" in text,
        }
    failed = [k for k, ok in crit.items() if not ok]
    return Check(
        id=cid,
        name=f"Voice greeting — {csv.name if csv else 'no pulse'}{' (stale)' if stale else ''}",
        passed=not failed,
        detail=f"kind={greeting.kind} theme={turn.greeting_theme}"
        + (f" · failed: {', '.join(failed)}" if failed else ""),
        data={
            "expected": expect,
            "pulse_top_theme": pulse.top_theme if pulse else None,
            "independent_top_theme": independent,
            "greeting_kind": greeting.kind,
            "greeting": turn.text,
            "criteria": crit,
        },
    )


def run() -> SuiteResult:
    from pillar_m2_pulse.pulse import DEFAULT_CSV, run_pulse

    res = SuiteResult("ux", "Tone & structure (UX)")
    pulses = [("production reviews.csv", DEFAULT_CSV)]
    pulses += [(n, FIXTURES / f"reviews_fixture_{n}.csv") for n in ("nominee", "login")]
    for name, path in pulses:
        if Path(path).exists():
            res.checks.append(pulse_rubric(name, run_pulse(path, persist=False)))

    voice = [
        voice_case("U1", FIXTURES / "reviews_fixture_nominee.csv", "Nominee Updates"),
        voice_case("U2", FIXTURES / "reviews_fixture_login.csv", "Login Issues"),
        voice_case("U3", FIXTURES / "reviews_fixture_empty.csv", None),
        voice_case("U3b", FIXTURES / "reviews_fixture_nominee.csv", None, stale=True),
    ]
    if DEFAULT_CSV.exists():
        with sandbox():
            real = run_pulse(DEFAULT_CSV)
            greeting, turn = _greet()
        ok = turn.greeting_theme == real.top_theme and real.top_theme.lower() in turn.text.lower()
        voice.append(
            Check(
                id="U4",
                name="Voice greeting — production reviews.csv (the top theme in the Review CSV)",
                passed=ok,
                detail=f"pulse top theme {real.top_theme!r} · greeting_theme "
                f"{turn.greeting_theme!r}",
                data={"greeting": turn.text, "pulse_id": real.pulse_id},
            )
        )
    res.checks += voice

    rubric = [c for c in res.checks if c.id.startswith("PULSE")]
    logic = [c for c in voice if c.id in ("U1", "U2", "U3")]
    words = max((int(c.data["word_count"]) for c in rubric), default=0)
    p_r, p_l = sum(c.passed for c in rubric), sum(c.passed for c in logic)
    p_x = sum(c.passed for c in voice)
    res.metrics = [
        Metric(
            "Pulse rubric (≤250 words, =3 ideas, taxonomy, PII)",
            ratio(p_r, len(rubric)),
            "all",
            bool(rubric) and p_r == len(rubric),
        ),
        Metric("Max pulse words", str(words), f"≤ {MAX_WORDS}", 0 < words <= MAX_WORDS),
        Metric("Voice theme logic U1–U3", ratio(p_l, len(logic)), "3/3", p_l == 3),
        Metric(
            "Voice extended (stale pulse, production CSV)",
            ratio(p_x, len(voice)),
            "all",
            p_x == len(voice),
        ),
    ]
    res.notes.append(f"Judge: {judge.judge_label()} (tone / idea quality only run with the judge).")
    return res
