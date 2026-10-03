"""Load, validate, window, scrub and dedupe app reviews before classification."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import IO

import pandas as pd

from core import pii

REQUIRED = ("date", "rating", "text")
ALIASES = {
    "review_id": ("review_id", "reviewid", "id"),
    "date": ("date", "at", "review_date", "created_at", "timestamp"),
    "rating": ("rating", "score", "stars", "star_rating"),
    "title": ("title", "headline", "summary"),
    "text": ("text", "review", "content", "body", "review_text", "comment"),
    "platform": ("platform", "source", "store"),
}
MIN_WORDS = 5
WINDOW_WEEKS = 12


class ReviewInputError(ValueError):
    """The uploaded CSV cannot be used (missing columns, unreadable, ...)."""


@dataclass
class PreparedReviews:
    df: pd.DataFrame
    stats: dict[str, int] = field(default_factory=dict)

    @property
    def empty(self) -> bool:
        return self.df.empty


def _normalise_columns(df: pd.DataFrame) -> pd.DataFrame:
    lookup = {re.sub(r"[^a-z_]", "", str(c).strip().lower()): c for c in df.columns}
    rename = {}
    for canon, options in ALIASES.items():
        for opt in options:
            if opt in lookup:
                rename[lookup[opt]] = canon
                break
    df = df.rename(columns=rename)
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ReviewInputError(f"CSV is missing required column(s): {', '.join(missing)}")
    return df


def _norm_key(text: str) -> str:
    return hashlib.sha1(re.sub(r"\W+", " ", text.lower()).strip()[:300].encode()).hexdigest()


def load_reviews(
    source: str | Path | IO,
    window_weeks: int = WINDOW_WEEKS,
    end: date | None = None,
) -> PreparedReviews:
    """Read a reviews CSV and return cleaned, PII-scrubbed rows inside the analysis window.

    The window is the `window_weeks` weeks ending at `end` (inclusive) or at the newest review.
    """
    try:
        raw = pd.read_csv(source, dtype=str, keep_default_na=False)
    except pd.errors.EmptyDataError:
        raw = pd.DataFrame()
    except Exception as exc:  # pragma: no cover - parser specific
        raise ReviewInputError(f"Could not read CSV: {exc}") from exc
    if raw.empty and not len(raw.columns):
        raise ReviewInputError("CSV is empty")
    df = _normalise_columns(raw)
    stats = {"input": len(df)}

    df["date"] = pd.to_datetime(df["date"], errors="coerce", utc=False, format="mixed")
    df["rating"] = pd.to_numeric(df["rating"], errors="coerce")
    df = df[df["date"].notna() & df["rating"].between(1, 5)].copy()
    stats["valid"] = len(df)
    if "title" not in df.columns:
        df["title"] = ""
    if "platform" not in df.columns:
        df["platform"] = "unknown"
    if "review_id" not in df.columns or (df["review_id"].astype(str).str.strip() == "").any():
        ids = [f"R{i:05d}" for i in range(1, len(df) + 1)]
        df["review_id"] = (
            df["review_id"].where(df["review_id"].astype(str).str.strip() != "", ids)
            if "review_id" in df.columns
            else ids
        )
    df["date"] = df["date"].dt.tz_localize(None) if df["date"].dt.tz is not None else df["date"]
    df["text"] = df["text"].astype(str).str.strip()

    if end is not None:
        df = df[df["date"] < pd.Timestamp(end) + timedelta(days=1)]
    if not df.empty:
        stop = df["date"].max().normalize() + timedelta(days=1)
        df = df[df["date"] >= stop - timedelta(weeks=window_weeks)]
    stats["in_window"] = len(df)

    df = df[df["text"].str.split().str.len() >= MIN_WORDS]
    stats["min_words"] = len(df)

    # Scrub before anything leaves this function: text, title; user names are never kept.
    df["text"] = [pii.redact(t) for t in df["text"]]
    df["title"] = [pii.redact(str(t)) if t else "" for t in df["title"]]
    df["user_name"] = pii.REDACTED

    df["_key"] = [_norm_key(t) for t in df["text"]]
    df = df.drop_duplicates("_key").drop(columns="_key")
    stats["deduped"] = len(df)

    cols = ["review_id", "date", "rating", "title", "text", "platform", "user_name"]
    df = df[cols].sort_values("date").reset_index(drop=True)
    df["rating"] = df["rating"].astype(int)
    return PreparedReviews(df=df, stats=stats)
