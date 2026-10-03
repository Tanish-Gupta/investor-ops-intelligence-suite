"""Weekly Product Pulse: code-first assembly, optional LLM copy, strict word / idea budget.

`run_pulse()` = load → scrub → classify → rank → quotes → copy (LLM or template) → render with
a ≤ 250-word budget → guard → persist (SQLite + `pulse_<id>.md/.json` + classified CSV + notes).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import IO, Annotated, Any

import pandas as pd
from pydantic import AfterValidator, BaseModel, Field

from config.settings import ROOT_DIR, get_settings
from core import guardrails, llm, notes, pii, state
from core.prompts import load_prompt

from .classifier import ThemeCache, classify_frame
from .market_context import build_market_context
from .quotes import Quote, select_quotes
from .ranking import ThemeStat, active_themes, rank_themes
from .reviews import ReviewInputError, load_reviews
from .taxonomy import load_taxonomy

_log = logging.getLogger(__name__)

DEFAULT_CSV = ROOT_DIR / "data" / "reviews" / "reviews.csv"
WRITER_PROMPT = "pulse_writer.v1.md"
GENERIC_IDEAS = (
    "Publish an in-app 'known issues' banner covering this week's top review themes.",
    "Route top-theme reviews to the owning squad with a 48-hour response target.",
    "Add a one-question survey after support chats to track resolution quality.",
)
_LIST_MARKER = re.compile(r"^\s*(?:#+|[-*>]|\d+\.)\s+")
_ALNUM = re.compile(r"[A-Za-z0-9]")


def word_count(md: str) -> int:
    """Words in rendered markdown: list / heading markers and pure-symbol tokens don't count."""
    total = 0
    for line in md.splitlines():
        line = _LIST_MARKER.sub("", line).replace("**", "").replace("_", " ")
        total += sum(1 for tok in line.split() if _ALNUM.search(tok))
    return total


def _max_words(n: int):
    def check(v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("empty text")
        if len(v.split()) > n:
            raise ValueError(f"must be at most {n} words")
        return v

    return AfterValidator(check)


class PulseCopy(BaseModel):
    summaries: list[Annotated[str, _max_words(20)]] = Field(default_factory=list, max_length=5)
    ideas: list[Annotated[str, _max_words(25)]] = Field(min_length=3, max_length=3)


@dataclass
class PulseResult:
    pulse_id: str
    week_start: date | None
    week_end: date | None
    review_count: int
    top_theme: str | None
    themes: list[dict[str, Any]]
    quotes: list[dict[str, Any]]
    summaries: dict[str, str]
    action_ideas: list[str]
    pulse_md: str
    market_context: str
    word_count: int
    action_idea_count: int
    copy_method: str = "template"
    classifier: dict[str, int] = field(default_factory=dict)
    prep: dict[str, int] = field(default_factory=dict)
    created_at: str = ""
    artifacts: dict[str, str] = field(default_factory=dict)

    @property
    def top3(self) -> list[dict[str, Any]]:
        return [t for t in self.themes if t.get("eligible")][:3]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["week_start"] = self.week_start.isoformat() if self.week_start else None
        d["week_end"] = self.week_end.isoformat() if self.week_end else None
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> PulseResult:
        d = dict(d)
        for k in ("week_start", "week_end"):
            if d.get(k):
                d[k] = date.fromisoformat(d[k])
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})

    @classmethod
    def from_row(cls, row: state.Pulse) -> PulseResult:
        ideas = json.loads(row.action_ideas or "[]")
        return cls(
            pulse_id=row.pulse_id,
            week_start=row.week_start,
            week_end=row.week_end,
            review_count=row.review_count,
            top_theme=row.top_theme,
            themes=json.loads(row.themes_json or "[]"),
            quotes=[],
            summaries={},
            action_ideas=ideas,
            pulse_md=row.pulse_md,
            market_context=row.market_context,
            word_count=word_count(row.pulse_md),
            action_idea_count=len(ideas),
            created_at=row.created_at.isoformat() if row.created_at else "",
        )


# --- copy (LLM or template) -------------------------------------------------------------------


def _template_summary(t: ThemeStat) -> str:
    trend = ", rising week on week" if t.growth >= 0.25 else ""
    return f"{t.count} reviews, average rating {t.mean_rating:.1f}{trend}"


def template_ideas(top: list[ThemeStat]) -> list[str]:
    tax = load_taxonomy()
    ideas = [tax.get(t.theme).action_idea for t in top if tax.get(t.theme)]  # type: ignore[union-attr]
    ideas = [i for i in ideas if i]
    for g in GENERIC_IDEAS:
        if len(ideas) >= 3:
            break
        ideas.append(g)
    return ideas[:3]


def _copy_is_safe(texts: list[str]) -> bool:
    return all("[REDACTED]" not in t and not guardrails.output_violations(t) for t in texts)


def _llm_copy(df: pd.DataFrame, top: list[ThemeStat]) -> PulseCopy:
    blocks = []
    for t in top:
        sample = df[df["theme"] == t.theme].sort_values("rating")["text"].head(5)
        examples = [" ".join(str(x).split()[:40]) for x in sample]
        blocks.append(
            {
                "theme": t.theme,
                "share_pct": round(t.share * 100),
                "avg_rating": t.mean_rating,
                "sentiment": t.sentiment_label,
                "sample_reviews": examples,
            }
        )
    msg = "Themes (ranked):\n" + json.dumps(blocks, ensure_ascii=False)
    return llm.complete(load_prompt(WRITER_PROMPT), msg, schema=PulseCopy, temperature=0.2)


def write_copy(
    df: pd.DataFrame, top: list[ThemeStat], use_llm: bool
) -> tuple[dict[str, str], list[str], str]:
    """Return (summaries by theme, exactly 3 ideas, method)."""
    summaries = {t.theme: _template_summary(t) for t in top}
    ideas = template_ideas(top)
    if not (use_llm and top and llm.llm_available()):
        return summaries, ideas, "template"
    try:
        copy = _llm_copy(df, top)
    except llm.LLMError as exc:
        _log.warning("pulse_llm_failed", extra={"error": str(exc)[:120]})
        return summaries, ideas, "template"
    texts = [*copy.summaries, *copy.ideas]
    if not _copy_is_safe(texts):
        _log.warning("pulse_llm_copy_rejected_by_guard")
        return summaries, ideas, "template"
    for t, s in zip(top, copy.summaries, strict=False):
        summaries[t.theme] = s.rstrip(".")
    return summaries, list(copy.ideas), "llm"


# --- rendering + budget -----------------------------------------------------------------------


def _fmt_range(start: date | None, end: date | None) -> str:
    if not start or not end:
        return "this week"
    if start.year == end.year:
        return f"{start.day} {start:%b}–{end.day} {end:%b} {end.year}"
    return f"{start.day} {start:%b %Y}–{end.day} {end:%b %Y}"


def _shorten(text: str, n: int) -> str:
    words = text.split()
    return text if len(words) <= n else " ".join(words[:n]).rstrip(",;:.") + "…"


def render_pulse(
    *,
    pulse_id: str,
    week_start: date | None,
    week_end: date | None,
    review_count: int,
    top: list[ThemeStat],
    summaries: dict[str, str],
    quotes: list[Quote],
    ideas: list[str],
    with_summaries: bool = True,
    quote_words: int = 40,
    idea_words: int = 25,
) -> str:
    lines = [
        f"# Weekly Product Pulse — {_fmt_range(week_start, week_end)}",
        f"_Reviews analysed: {review_count} · {pulse_id}_",
        "",
        "## Top Themes",
    ]
    if not top:
        lines.append("No theme had enough evidence this period.")
    for i, t in enumerate(top, 1):
        line = f"{i}. **{t.theme}** — {round(t.share * 100)}% of reviews, {t.sentiment_label}"
        if with_summaries and summaries.get(t.theme):
            line += f": {summaries[t.theme]}"
        lines.append(line + ".")
    lines += ["", "## What Users Are Saying"]
    if not quotes:
        lines.append("No representative quotes this period.")
    lines += [f"- {q.render(quote_words)}" for q in quotes]
    lines += ["", "## Action Ideas"]
    lines += [f"{i}. {_shorten(idea, idea_words)}" for i, idea in enumerate(ideas, 1)]
    return "\n".join(lines) + "\n"


def _fit_budget(max_words: int, **kw: Any) -> str:
    attempts = [(True, 40, 25), (False, 40, 25), (False, 30, 25), (False, 22, 25)]
    attempts += [(False, 15, 20), (False, 10, 15)]
    md = ""
    for with_summaries, qw, iw in attempts:
        md = render_pulse(with_summaries=with_summaries, quote_words=qw, idea_words=iw, **kw)
        if word_count(md) <= max_words:
            return md
    raise RuntimeError(f"pulse exceeds {max_words} words even after trimming")


# --- pipeline ---------------------------------------------------------------------------------


def pulse_id_for(day: date) -> str:
    iso = day.isocalendar()
    return f"PULSE-{iso.year}-W{iso.week:02d}"


def _notes_summary(p: PulseResult) -> str:
    if not p.top3:
        return f"{p.review_count} reviews; no dominant theme."
    themes = ", ".join(f"{t['theme']} {round(t['share'] * 100)}%" for t in p.top3)
    return f"{_fmt_range(p.week_start, p.week_end)} · {p.review_count} reviews · top: {themes}."


def _persist(p: PulseResult, classified: pd.DataFrame) -> PulseResult:
    out = get_settings().artifacts_dir
    out.mkdir(parents=True, exist_ok=True)
    md_path = out / f"pulse_{p.pulse_id}.md"
    json_path = out / f"pulse_{p.pulse_id}.json"
    csv_path = out / f"classified_{p.pulse_id}.csv"
    p.artifacts = {"md": str(md_path), "json": str(json_path), "classified": str(csv_path)}
    md_path.write_text(p.pulse_md, encoding="utf-8")
    json_path.write_text(json.dumps(p.to_dict(), indent=2, default=str), encoding="utf-8")
    cols = ["review_id", "date", "rating", "platform", "theme", "secondary_theme"]
    cols += ["sentiment", "confidence", "method", "text"]
    classified[cols].to_csv(csv_path, index=False)
    state.save_pulse(
        pulse_id=p.pulse_id,
        top_theme=p.top_theme,  # type: ignore[arg-type]
        themes=p.themes,
        pulse_md=p.pulse_md,
        action_ideas=p.action_ideas,
        market_context=p.market_context,
        review_count=p.review_count,
        week_start=p.week_start,
        week_end=p.week_end,
    )
    notes.append_pulse_summary(p.pulse_id, _notes_summary(p))
    return p


def run_pulse(
    csv_path: str | Path | IO | None = None,
    week: date | None = None,
    *,
    use_llm: bool | None = None,
    persist: bool = True,
) -> PulseResult:
    """Build (and by default persist) the Weekly Pulse for the window ending at `week`."""
    settings = get_settings()
    use_llm = settings.pulse_llm_enabled if use_llm is None else use_llm
    prepared = load_reviews(csv_path or DEFAULT_CSV, end=week)
    if prepared.empty:
        raise ReviewInputError("No usable reviews in the selected window (after cleaning).")
    df = prepared.df
    cache = ThemeCache(settings.artifacts_dir / "cache" / "theme_cache.json") if use_llm else None
    classified, cls_stats = classify_frame(df, use_llm=use_llm, cache=cache)
    stats, top_theme = rank_themes(classified)
    top = active_themes(stats)[:3]
    quotes = select_quotes(classified, [t.theme for t in top])
    summaries, ideas, method = write_copy(classified, top, use_llm)

    week_end = classified["date"].max().date()
    week_start = classified["date"].min().date()
    pid = pulse_id_for(week_end)
    md = _fit_budget(
        settings.pulse_max_words,
        pulse_id=pid,
        week_start=week_start,
        week_end=week_end,
        review_count=len(classified),
        top=top,
        summaries=summaries,
        quotes=quotes,
        ideas=ideas,
    )
    md = pii.redact(md)
    if guardrails.output_violations(md):  # summaries are optional → drop them and re-check
        md = pii.redact(
            _fit_budget(
                settings.pulse_max_words,
                pulse_id=pid,
                week_start=week_start,
                week_end=week_end,
                review_count=len(classified),
                top=top,
                summaries={},
                quotes=quotes,
                ideas=template_ideas(top),
            )
        )
        ideas, method = template_ideas(top), "template"

    result = PulseResult(
        pulse_id=pid,
        week_start=week_start,
        week_end=week_end,
        review_count=len(classified),
        top_theme=top_theme,
        themes=[s.to_dict() for s in stats],
        quotes=[asdict(q) for q in quotes],
        summaries=summaries,
        action_ideas=ideas,
        pulse_md=md,
        market_context="",
        word_count=word_count(md),
        action_idea_count=len(ideas),
        copy_method=method,
        classifier=cls_stats,
        prep=prepared.stats,
        created_at=state.now().isoformat(timespec="seconds"),
    )
    result.market_context = build_market_context(result)
    return _persist(result, classified) if persist else result


def get_latest_pulse() -> PulseResult | None:
    row = state.latest_pulse()
    if row is None:
        return None
    path = get_settings().artifacts_dir / f"pulse_{row.pulse_id}.json"
    if path.exists():
        try:
            return PulseResult.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError):
            pass
    return PulseResult.from_row(row)
