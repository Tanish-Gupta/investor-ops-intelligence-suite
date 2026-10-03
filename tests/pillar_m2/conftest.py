from __future__ import annotations

from pathlib import Path

from config.settings import ROOT_DIR

FIXTURES = ROOT_DIR / "evals" / "fixtures"
NOMINEE = FIXTURES / "reviews_fixture_nominee.csv"
LOGIN = FIXTURES / "reviews_fixture_login.csv"
EMPTY = FIXTURES / "reviews_fixture_empty.csv"
FULL = ROOT_DIR / "data" / "reviews" / "reviews.csv"


def write_csv(path: Path, rows: list[tuple[str, int, str]]) -> Path:
    import csv

    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["review_id", "date", "rating", "title", "text", "platform", "user_name"])
        for i, (day, rating, text) in enumerate(rows, 1):
            w.writerow([f"t{i}", day, rating, "", text, "android", "Some Person"])
    return path
