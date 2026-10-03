"""Fetch the public regulator/AMC pages listed in data/sources.csv.

Only rows with ``fetch_method == "http"`` are downloaded. Other rows are:
- ``search_capture``: the site blocks automated fetches (Cloudflare 403), so the page text was
  captured from a web-search index and stored under ``data/corpus/schemes/`` by hand.
- ``m1_local``: copied from the M1 project's own ingest output.
- ``internal``: authored in this repo (the M2 Fee Explainer).
- ``http_extract``: official Bajaj Finserv AMC scheme pages and factsheet, fetched over HTTP
  once; the cited sections are kept verbatim as Markdown under ``data/corpus/schemes/``.
  They are not re-downloaded here, so a refresh cannot overwrite the curated extract.

Usage:
    uv run python scripts/fetch_corpus.py            # fetch missing files
    uv run python scripts/fetch_corpus.py --force    # re-fetch everything
    uv run python scripts/fetch_corpus.py --only R-SEBI-EXIT-01
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "data" / "sources.csv"
MANIFEST = ROOT / "data" / "corpus" / "manifest.json"
TEXT_DIR = ROOT / "data" / "corpus" / "text"
IST = ZoneInfo("Asia/Kolkata")
# 200 responses that are really bot-wall / challenge pages.
BLOCK_MARKERS = ("you are a bot", "cf-chl", "just a moment...", "attention required")
MIN_TEXT_CHARS = 300

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def read_sources() -> tuple[list[str], list[dict[str, str]]]:
    with SOURCES.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader.fieldnames or []), list(reader)


def write_sources(fields: list[str], rows: list[dict[str, str]]) -> None:
    with SOURCES.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def extract_text(path: Path, url: str) -> str:
    """Plain-text preview used for human verification; Phase 3 ingest does the real parsing."""
    if path.suffix == ".pdf":
        import pymupdf4llm

        return pymupdf4llm.to_markdown(str(path))
    import trafilatura

    text = trafilatura.extract(
        path.read_text(encoding="utf-8", errors="replace"),
        url=url,
        output_format="markdown",
        include_tables=True,
        include_links=False,
    )
    return text or ""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--only", nargs="*", default=None)
    args = ap.parse_args(argv)

    fields, rows = read_sources()
    manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
    TEXT_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now(IST).date().isoformat()
    failures = 0

    with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=30.0) as client:
        for row in rows:
            if row["fetch_method"] != "http":
                continue
            if args.only and row["doc_id"] not in args.only:
                continue
            dest = ROOT / row["local_path"]
            if dest.exists() and not args.force:
                continue
            try:
                resp = client.get(row["url"])
            except httpx.HTTPError as exc:
                print(f"ERR  {row['doc_id']}: {exc}")
                failures += 1
                continue
            if resp.status_code != 200:
                print(f"ERR  {row['doc_id']}: HTTP {resp.status_code}")
                failures += 1
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(resp.content)
            text = extract_text(dest, row["url"])
            lowered = text.lower()
            if len(text) < MIN_TEXT_CHARS or any(m in lowered for m in BLOCK_MARKERS):
                dest.unlink()
                print(f"ERR  {row['doc_id']}: blocked or empty page ({len(text)} text chars)")
                failures += 1
                continue
            (TEXT_DIR / f"{row['doc_id']}.md").write_text(text, encoding="utf-8")
            row["fetched_on"] = today
            manifest[row["doc_id"]] = {
                "url": row["url"],
                "final_url": str(resp.url),
                "status": resp.status_code,
                "bytes": len(resp.content),
                "sha256": hashlib.sha256(resp.content).hexdigest(),
                "text_chars": len(text),
                "fetched_at": datetime.now(IST).isoformat(timespec="seconds"),
            }
            print(f"OK   {row['doc_id']}: {len(resp.content)} bytes, {len(text)} text chars")

    write_sources(fields, rows)
    MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
