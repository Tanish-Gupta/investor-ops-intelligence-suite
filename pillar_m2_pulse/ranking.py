"""Aggregate classified reviews per theme and rank them deterministically → `top_theme`."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import timedelta

import pandas as pd

from .taxonomy import load_taxonomy

W_SHARE, W_NEG, W_GROWTH = 0.6, 0.25, 0.15
MIN_TOP_COUNT = 5
MIN_TOP_SHARE = 0.05
MIN_GROWTH_BASE = 3


@dataclass
class ThemeStat:
    theme: str
    count: int
    share: float  # of all analysed reviews (displayed)
    theme_share: float  # of reviews with a real theme (used in the score; `Other` excluded)
    mean_rating: float
    negativity: float
    growth: float
    score: float
    sentiment_label: str
    eligible: bool

    def to_dict(self) -> dict:
        return asdict(self)


def sentiment_label(mean_rating: float) -> str:
    if mean_rating <= 2.5:
        return "mostly negative"
    if mean_rating >= 3.5:
        return "mostly positive"
    return "mixed"


def _growth(sub: pd.DataFrame, end: pd.Timestamp) -> float:
    last = (sub["date"] > end - timedelta(days=7)).sum()
    prior = (
        (sub["date"] <= end - timedelta(days=7)) & (sub["date"] > end - timedelta(days=14))
    ).sum()
    if prior == 0:
        return 1.0 if last >= MIN_GROWTH_BASE else 0.0
    return float(min(1.0, max(0.0, (last - prior) / prior)))


def rank_themes(df: pd.DataFrame) -> tuple[list[ThemeStat], str | None]:
    """Return themes sorted by score (desc) and the eligible top theme (or None)."""
    tax = load_taxonomy()
    if df.empty:
        return [], None
    total = len(df)
    themed = int((df["theme"] != tax.fallback_label).sum()) or 1
    end = df["date"].max()
    stats: list[ThemeStat] = []
    for theme, sub in df.groupby("theme"):
        count = len(sub)
        share = count / total
        theme_share = 0.0 if theme == tax.fallback_label else count / themed
        mean_rating = float(sub["rating"].mean())
        negativity = max(0.0, min(1.0, 1 - mean_rating / 5))
        growth = _growth(sub, end)
        score = W_SHARE * theme_share + W_NEG * negativity + W_GROWTH * growth
        # minimum evidence: ≥ 5 reviews and ≥ 5% of themed reviews (a 10-review theme must not
        # outrank a 700-review one on a large window just because it is angrier)
        eligible = (
            theme != tax.fallback_label and count >= MIN_TOP_COUNT and theme_share >= MIN_TOP_SHARE
        )
        stats.append(
            ThemeStat(
                theme=str(theme),
                count=count,
                share=round(share, 4),
                theme_share=round(theme_share, 4),
                mean_rating=round(mean_rating, 2),
                negativity=round(negativity, 3),
                growth=round(growth, 3),
                score=round(score, 4),
                sentiment_label=sentiment_label(mean_rating),
                eligible=eligible,
            )
        )
    # deterministic: score desc → count desc → label asc
    stats.sort(key=lambda s: (-s.score, -s.count, s.theme))
    top = next((s.theme for s in stats if s.eligible), None)
    return stats, top


def active_themes(stats: list[ThemeStat], limit: int | None = None) -> list[ThemeStat]:
    """Eligible (non-Other) themes, capped at `max_active_themes`."""
    limit = limit or load_taxonomy().max_active_themes
    return [s for s in stats if s.eligible][:limit]
