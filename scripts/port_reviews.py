"""Port the M2 Review Analyst's cleaned reviews into `data/reviews/reviews.csv`.

Reads the newest `clean_reviews_*.parquet` from the M2 project (or `--src`), maps it to the
schema in docs/architecture/themeClassification.md §2, scrubs PII from title and text with
`core.pii`, and always writes `user_name` as `[REDACTED]`.

    uv run python scripts/port_reviews.py
    uv run python scripts/port_reviews.py --src path/to/clean_reviews.parquet
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.pii import REDACTED, redact  # noqa: E402

DEFAULT_SRC_DIR = Path.home() / "app review analyser" / "data" / "interim"
DEST = ROOT / "data" / "reviews" / "reviews.csv"
COLUMNS = ["review_id", "date", "rating", "title", "text", "platform", "user_name"]
ALIASES = {"content": "text", "score": "rating", "at": "date", "reviewId": "review_id"}


def newest_parquet(src_dir: Path) -> Path:
    files = sorted(src_dir.glob("clean_reviews_*.parquet"))
    if not files:
        raise SystemExit(f"no clean_reviews_*.parquet in {src_dir}")
    return files[-1]


def normalise(df: pd.DataFrame, platform: str) -> pd.DataFrame:
    df = df.rename(columns={k: v for k, v in ALIASES.items() if k in df.columns})
    missing = {"review_id", "date", "rating", "text"} - set(df.columns)
    if missing:
        raise SystemExit(f"source is missing required columns: {sorted(missing)}")

    out = pd.DataFrame()
    out["review_id"] = df["review_id"].astype(str)
    out["date"] = (
        pd.to_datetime(df["date"], utc=True).dt.tz_convert("Asia/Kolkata").dt.date.astype(str)
    )
    out["rating"] = pd.to_numeric(df["rating"], errors="coerce").astype("Int64")
    text = df["text"].fillna("").astype(str).str.strip()
    title = df["title"].fillna("").astype(str).str.strip() if "title" in df else ""
    # Play Store reviews have no title; M2 filled it with the start of the text. Drop those.
    if isinstance(title, pd.Series):
        derived = [t == "" or x.startswith(t) for t, x in zip(title, text, strict=True)]
        out["title"] = title.mask(derived, "")
    else:
        out["title"] = ""
    out["text"] = text
    out["platform"] = df["platform"].astype(str) if "platform" in df else platform
    out["user_name"] = REDACTED

    out = out[out["text"].str.len() > 0]
    out = out[out["rating"].between(1, 5)]
    out = out.drop_duplicates("review_id")

    out["text"] = out["text"].map(redact)
    out["title"] = out["title"].map(lambda t: redact(t) if t else t)
    return out[COLUMNS].sort_values(["date", "review_id"], ascending=[False, True])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--src", type=Path, help="parquet file (default: newest M2 clean_reviews)")
    ap.add_argument("--platform", default="android", help="platform value when the source has none")
    ap.add_argument("--dest", type=Path, default=DEST)
    args = ap.parse_args()

    src = args.src or newest_parquet(DEFAULT_SRC_DIR)
    df = normalise(pd.read_parquet(src), args.platform)
    args.dest.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.dest, index=False)
    redacted = int(df["text"].str.contains(REDACTED, regex=False).sum())
    print(f"wrote {len(df)} reviews -> {args.dest.relative_to(ROOT)} (source: {src.name})")
    print(
        f"date range {df['date'].min()} .. {df['date'].max()}; {redacted} reviews had PII redacted"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
