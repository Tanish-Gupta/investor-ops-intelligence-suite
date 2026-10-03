"""Advisor-facing Market Context snippet (≤ 60 words, neutral, no PII, no advice) from a pulse."""

from __future__ import annotations

from typing import Any

from .taxonomy import load_taxonomy

MAX_WORDS = 60
MATCH_LINE = "This caller's topic matches a current top theme."


def _fmt_range(start, end) -> str:
    if not start or not end:
        return ""
    if start.year == end.year:
        return f"{start.day} {start:%b}–{end.day} {end:%b} {end.year}"
    return f"{start.day} {start:%b %Y}–{end.day} {end:%b %Y}"


def _theme_rows(pulse: Any) -> list[dict]:
    rows = getattr(pulse, "themes", None) or []
    return [r for r in rows if r.get("eligible", True)]


def topic_matches(pulse: Any, booking_topic: str | None) -> bool:
    if not pulse or not booking_topic:
        return False
    tax = load_taxonomy()
    for row in _theme_rows(pulse)[:3]:
        theme = tax.get(row["theme"])
        if theme and (theme.voice_topic == booking_topic or theme.label == booking_topic):
            return True
    return False


def build_market_context(pulse: Any, booking_topic: str | None = None) -> str:
    """Template-first snippet. `pulse` is a `PulseResult` (or anything with the same fields)."""
    if pulse is None:
        return "Market Context: no Weekly Pulse is available yet."
    rows = _theme_rows(pulse)
    rng = _fmt_range(getattr(pulse, "week_start", None), getattr(pulse, "week_end", None))
    head = f"Market Context (Pulse {pulse.pulse_id}{', ' + rng if rng else ''}): "
    if not pulse.top_theme or not rows:
        body = (
            f"No single dominant customer theme across {pulse.review_count} recent reviews. "
            "Expect general account and app questions."
        )
    else:
        top = next((r for r in rows if r["theme"] == pulse.top_theme), rows[0])
        body = (
            f'Top customer theme is "{top["theme"]}" ({round(top["share"] * 100)}% of '
            f"{pulse.review_count} reviews, {top['sentiment_label']})."
        )
        others = [r for r in rows if r["theme"] != top["theme"]][:2]
        if others:
            also = " and ".join(f"{r['theme']} ({round(r['share'] * 100)}%)" for r in others)
            body += f" Also notable: {also}."
        body += " Expect questions on these topics."
    text = head + body
    match = topic_matches(pulse, booking_topic)
    budget = MAX_WORDS - (len(MATCH_LINE.split()) if match else 0)
    words = text.split()
    if len(words) > budget:  # defensive: long theme names
        text = " ".join(words[:budget]).rstrip(",.;") + "."
    return f"{text} {MATCH_LINE}" if match else text
