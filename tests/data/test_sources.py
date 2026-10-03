"""Corpus registry (data/sources.csv) and fee explainer contract — docs/architecture/rag.md §2."""

from __future__ import annotations

import csv
import json
import re
from datetime import date

import pytest
import yaml

from tests.data.conftest import DATA, ROOT, SOURCES, doc_text, fee_sections, sources

COLUMNS = [
    "doc_id",
    "url",
    "title",
    "scheme",
    "category",
    "source_type",
    "fetched_on",
    "as_of",
    "local_path",
    "fetch_method",
]
SOURCE_TYPES = {"M1_FACTSHEET", "M1_REGULATOR", "M2_FEE_EXPLAINER"}
FETCH_METHODS = {"http", "http_extract", "m1_local", "search_capture", "internal"}
FEE_TYPES = {"exit_load", "stamp_duty", "stt", "expense_ratio", "capital_gains", "lock_in"}
REQUIRED_CATEGORIES = {"ELSS", "Large Cap", "Flexi Cap", "Index", "Liquid"}
REQUIRED_FEE_ANCHORS = {
    "exit-load",
    "graded-exit-load-liquid-funds",
    "stamp-duty",
    "securities-transaction-tax-stt",
    "expense-ratio-ter",
    "elss-lock-in",
    "capital-gains-statement",
}


def test_header_and_unique_ids():
    with SOURCES.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames == COLUMNS
        ids = [r["doc_id"] for r in reader]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("doc_id", sorted(sources()))
def test_row_is_valid(doc_id):
    row = sources()[doc_id]
    assert row["url"].startswith("https://"), "citations must be public https links"
    assert row["title"].strip()
    assert row["source_type"] in SOURCE_TYPES
    assert row["fetch_method"] in FETCH_METHODS
    date.fromisoformat(row["fetched_on"])
    if row["as_of"]:
        date.fromisoformat(row["as_of"])
    path, _, anchor = row["local_path"].partition("#")
    assert (ROOT / path).is_file(), f"missing {path}"
    if anchor:
        assert anchor in fee_sections(), f"no '## ' section for #{anchor}"
    assert len(doc_text(doc_id)) > 200, "document text looks empty or blocked"


def test_prefix_matches_source_type(registry):
    prefix = {"F": "M1_FACTSHEET", "R": "M1_REGULATOR", "FE": "M2_FEE_EXPLAINER"}
    for doc_id, row in registry.items():
        assert row["source_type"] == prefix[doc_id.split("-")[0]], doc_id


def test_all_five_scheme_categories_present(registry):
    cats = {r["category"] for r in registry.values() if r["source_type"] == "M1_FACTSHEET"}
    assert REQUIRED_CATEGORIES <= cats
    funds = {r["scheme"] for r in registry.values() if r["source_type"] == "M1_FACTSHEET"}
    assert len(funds) == 30  # 5 Edelweiss (M1) + 25 Bajaj Finserv


def test_http_rows_are_in_manifest(registry):
    manifest = json.loads((DATA / "corpus" / "manifest.json").read_text(encoding="utf-8"))
    for doc_id, row in registry.items():
        if row["fetch_method"] == "http":
            assert doc_id in manifest, doc_id
            assert (ROOT / row["local_path"]).stat().st_size == manifest[doc_id]["bytes"]


@pytest.mark.parametrize(
    "doc_id",
    [d for d, r in sources().items() if r["local_path"].startswith("data/corpus/schemes/")],
)
def test_scheme_front_matter_matches_registry(doc_id):
    row = sources()[doc_id]
    text = (ROOT / row["local_path"]).read_text(encoding="utf-8")
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    assert m, "scheme docs need YAML front-matter"
    meta = yaml.safe_load(m.group(1))
    assert meta["doc_id"] == doc_id
    assert meta["url"] == row["url"]
    assert str(meta["as_of"]) == row["as_of"]
    assert meta["capture"] == row["fetch_method"]


def test_fee_explainer_covers_every_fee_type():
    sections = fee_sections()
    assert REQUIRED_FEE_ANCHORS <= set(sections)
    fe_rows = {
        r["local_path"].partition("#")[2]: d for d, r in sources().items() if d.startswith("FE-")
    }
    assert set(fe_rows) == REQUIRED_FEE_ANCHORS


@pytest.mark.parametrize("anchor", sorted(REQUIRED_FEE_ANCHORS))
def test_fee_section_structure(anchor):
    body = fee_sections()[anchor]
    meta = re.search(r"doc_id: (FE-[A-Z]+-\d+) · fee_type: (\w+)", body)
    assert meta, "each section starts with its doc_id and fee_type"
    doc_id, fee_type = meta.groups()
    assert fee_type in FEE_TYPES
    assert sources()[doc_id]["local_path"].endswith(f"#{anchor}")
    for part in ("**What it is.**", "**Worked example.**", "**Why was I charged it?**"):
        assert part in body, f"{anchor} is missing {part}"
    cited = re.findall(r"https://\S+", body.split("Source:", 1)[1])
    assert cited, "each section cites at least one public URL"
    assert sources()[doc_id]["url"] in cited, "registry URL must be one of the section's sources"
