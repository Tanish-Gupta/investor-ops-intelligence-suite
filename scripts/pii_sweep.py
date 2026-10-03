"""PII sweep (task 9.2): scan everything the suite stores at runtime for PII that escaped masking.

Scanned, under DATA_DIR (default `data/`):
- every text artifact (`.md`, `.json`, `.jsonl`, `.ics`, `.txt`) line by line, CSVs cell by cell;
- `.eml` drafts: Subject and body (the To header is the configured advisor address);
- every text column of every table in the SQLite DB.

Not scanned: `corpus/` and `lancedb/` (public source documents and their index; AMC contact
numbers there are published, not user data) and model caches.

    uv run python scripts/pii_sweep.py                 # exit code 1 if anything is found
    uv run python scripts/pii_sweep.py --data-dir /path/to/data --db /path/to/suite.db
"""

from __future__ import annotations

import argparse
import csv
import re
import sqlite3
import sys
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from email import policy
from email.parser import BytesParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import get_settings  # noqa: E402
from core import pii  # noqa: E402

TEXT_SUFFIXES = {".md", ".json", ".jsonl", ".csv", ".ics", ".txt"}
SKIP_DIRS = {"corpus", "lancedb"}


UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


@dataclass(frozen=True)
class Finding:
    location: str
    entity_types: tuple[str, ...]
    note: str = ""


def _files(data_dir: Path) -> Iterator[Path]:
    for path in sorted(data_dir.rglob("*")):
        rel = path.relative_to(data_dir).parts
        if path.is_file() and not (rel and rel[0] in SKIP_DIRS):
            yield path


def _eml_texts(path: Path) -> Iterator[tuple[str, str]]:
    msg = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
    yield "Subject", str(msg["Subject"] or "")
    body = msg.get_body(preferencelist=("plain", "html"))
    for i, line in enumerate((body.get_content() if body else "").splitlines(), 1):
        yield f"body:{i}", line


def iter_texts(data_dir: Path, db_path: Path | None) -> Iterator[tuple[str, str]]:
    """Yield (location, text) for every stored string worth scanning."""
    for path in _files(data_dir):
        rel = path.relative_to(data_dir)
        if path.suffix == ".eml":
            for where, text in _eml_texts(path):
                yield f"{rel}:{where}", text
        elif path.suffix == ".csv":
            with path.open(encoding="utf-8", errors="replace", newline="") as f:
                for i, row in enumerate(csv.DictReader(f), 2):
                    for col, value in row.items():
                        if value:
                            yield f"{rel}:{i}:{col}", value
        elif path.suffix in TEXT_SUFFIXES:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            for i, line in enumerate(lines, 1):
                yield f"{rel}:{i}", line
    if db_path and db_path.exists():
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            tables = [
                r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
            ]
            for table in tables:
                cur = con.execute(f'SELECT rowid, * FROM "{table}"')  # noqa: S608 - names from sqlite
                cols = [d[0] for d in cur.description]
                for row in cur:
                    for col, value in zip(cols[1:], row[1:], strict=True):
                        if isinstance(value, str) and value:
                            yield f"db:{table}:{row[0]}:{col}", value
        finally:
            con.close()


def sweep(data_dir: Path, db_path: Path | None) -> tuple[list[Finding], Counter]:
    findings, scanned = [], Counter()
    for location, text in iter_texts(data_dir, db_path):
        scanned[location.split(":", 1)[0] if not location.startswith("db:") else "db"] += 1
        entities = pii.detect(text)
        if entities:
            # Triage hint only: the finding is still reported and still fails the sweep.
            note = "value is a UUID record id" if UUID_RE.match(text.strip()) else ""
            types = tuple(sorted({e.entity_type for e in entities}))
            findings.append(Finding(location, types, note))
    return findings, scanned


def main(argv: list[str] | None = None) -> int:
    s = get_settings()
    ap = argparse.ArgumentParser(description="Scan stored artifacts and the DB for PII.")
    ap.add_argument("--data-dir", type=Path, default=s.data_dir)
    ap.add_argument("--db", type=Path, default=s.db_path)
    args = ap.parse_args(argv)
    findings, scanned = sweep(args.data_dir, args.db)
    print(
        f"Scanned {sum(scanned.values())} strings in {len(scanned)} sources under {args.data_dir}"
    )
    for source, n in sorted(scanned.items()):
        print(f"  {n:>6}  {source}")
    if not findings:
        print("PII found: 0 ✅")
        return 0
    print(f"PII found: {len(findings)} ❌ (raw values not printed)")
    notes = Counter(f.note or "needs review" for f in findings)
    print("  triage: " + "; ".join(f"{n} × {k}" for k, n in notes.most_common()))
    for f in findings[:50]:
        print(f"  {f.location}: {', '.join(f.entity_types)}{f'  ({f.note})' if f.note else ''}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
