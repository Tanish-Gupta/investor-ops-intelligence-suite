# Corpus (Phase 2)

Input documents for Pillar A (Unified Search). Every document has one row in
[`../sources.csv`](../sources.csv); that registry is what ingest reads and what citations point to.

## Layout

| Path | What | How it was made |
|---|---|---|
| `schemes/F-*.md` | Scheme pages for 30 funds: 5 Edelweiss MF (M1) and 25 Bajaj Finserv MF, Direct plans | See capture methods below |
| `raw/R-*.html\|pdf` | Regulator / investor-education pages (SEBI, AMFI Mutual Funds Sahi Hai, AMC knowledge centres) | `scripts/fetch_corpus.py` (HTTP) |
| `raw/F-FLEXI-01.html` | Original M1 HTML for the Flexi Cap page | Copied from M1 run `089ad379` |
| `text/R-*.md` | Plain-text previews of the raw files, for review and grep only (ingest parses `raw/` with Docling) | `scripts/fetch_corpus.py` |
| `fee_explainer.md` | M2 Fee Explainer, one `##` section per fee type (`FE-*` rows) | Written by hand from the cited public pages |
| `manifest.json` | sha256, size, final URL and fetch time for each HTTP fetch | `scripts/fetch_corpus.py` |

Re-fetch the HTTP sources with:

```bash
uv run python scripts/fetch_corpus.py            # missing files only
uv run python scripts/fetch_corpus.py --force    # everything
uv run python scripts/fetch_corpus.py --only R-AMC-STT-01
```

The fetcher discards bot-wall pages (for example a "you are a bot" 200 response) instead of
saving them.

## Schemes

| Scheme | doc_id | Data as of |
|---|---|---|
| Edelweiss ELSS Tax Saver Fund | F-ELSS-01 | 2026-08-31 |
| Edelweiss Flexi Cap Fund | F-FLEXI-01 | 2026-09-30 |
| Edelweiss Large Cap Fund | F-LC-01, F-LC-02 | 2026-06-03 |
| Edelweiss Nifty 50 Index Fund | F-IDX-01 | 2026-08-21 |
| Edelweiss Liquid Fund | F-LIQ-01, F-LIQ-02 | 2026-06-17 / 2025-01-31 |

**Bajaj Finserv MF (25 schemes).** Each scheme has two documents: `F-<ID>-01` is the official
scheme page on bajajamc.com (exit load, lock-in, minimums, benchmark, riskometer; data as of
2026-08-31) and `F-<ID>-02` is the Direct Plan base expense ratio from the official
[August 2026 factsheet](https://media.bajajamc.com/wp-content/uploads/2026/08/Factsheet_August-2026.pdf)
(as on 2026-07-31). Ids:

| Category | Schemes (id) |
|---|---|
| Equity | Large Cap (BLC), Flexi Cap (BFLEXI), Large & Mid Cap (BLMC), Multi Cap (BMC), Small Cap (BSC), ELSS Tax Saver (BELSS) |
| Sectoral/Thematic | Healthcare (BHC), Consumption (BCONS), Banking & Financial Services (BBFS) |
| Index | Nifty 50 Index (BN50), Nifty Next 50 Index (BNN50) |
| Hybrid | Balanced Advantage (BBAF), Multi Asset Allocation (BMAAF), Equity Savings (BESF), Arbitrage (BARB) |
| Debt | Liquid (BLIQ), Money Market (BMM), Overnight (BON), Low Duration (BLD), Gilt (BGILT), Banking and PSU (BBPSU) |
| ETF | Nifty 50 ETF (BETF50), Nifty Bank ETF (BETFBANK), BSE Top 10 Banks ETF (BETFT10), Nifty 1D Rate Liquid ETF (BETFLIQ) |

## Capture methods (`fetch_method` in sources.csv)

- **`http`**: fetched directly by `scripts/fetch_corpus.py`.
- **`m1_local`**: reused from the M1 project's own fetch (Flexi Cap only; the other M1 schemes
  returned HTTP 403 in M1's last run).
- **`search_capture`**: INDmoney, ET Money and edelweissmf.com block automated requests
  (Cloudflare HTTP 403, also with a headless browser). Their page text was captured from a
  web-search index on 2026-10-03 and saved with YAML front-matter (`url`, `as_of`,
  `captured_on`, `capture`, `note`). Citations still use the original public URL.
- **`internal`**: the M2 Fee Explainer. Each section cites the public page it was based on.
- **`http_extract`**: the 25 Bajaj Finserv schemes. The official scheme pages and the August
  2026 factsheet PDF were fetched over HTTP on 2026-10-03; the cited sections are kept
  verbatim, after a one-line-per-fact "Key facts" block. `fetch_corpus.py` does not re-fetch
  them, so a refresh cannot overwrite the extract.

## Known issues (human spot-check before final evals)

1. **Large Cap minimum SIP conflict.** INDmoney (F-LC-01) shows ₹100/₹100 (lump sum/SIP);
   ET Money shows SIP ₹500 and lump sum ₹5,000 for the same direct plan. The ET Money excerpt
   (F-LC-02) leaves that line out. Golden question G5 uses ₹100. Confirm against the AMC KIM.
2. **Liquid fund exit load.** The INDmoney summary (F-LIQ-01) shows "Exit Load · 0.0%", but
   the AMC factsheet (F-LIQ-02) lists graded day-1-to-day-6 slabs, as SEBI requires for liquid
   funds. `config/fee_rules.yaml` and the fee explainer use the graded slabs. The factsheet
   capture is from Jan 2025; the slabs are AMFI-standard and unchanged since 2019.
3. **Index fund TER.** F-IDX-01 shows 0.14% (Aug 2026); an older capture showed 0.05%. Use
   the newest value and refresh before the final run.
4. **Stale tax text in M1.** M1's Flexi Cap taxation text quotes an LTCG exemption of ₹1
   lakh, which is outdated. Pillar A must not answer tax-rate questions from it; the fee
   explainer makes no tax-rate claims.
5. **Search-captured pages** reflect the index snapshot, not a live fetch. Check the `as_of`
   dates against the live pages when refreshing.

## Reviews and other Phase 2 data

- `../reviews/reviews.csv`: 3,678 Groww Play Store reviews (13 Feb – 8 May 2026) from the M2
  project, written by `scripts/port_reviews.py`. `user_name` is always `[REDACTED]`, and the
  text is scrubbed with `core.pii`. The name recogniser errs on the side of redaction (about
  13 reviews lose a word such as "I am [REDACTED]"); that is acceptable for this data.
- `../availability.json`: mock advisor calendar (10 working days, 30-minute IST slots,
  09:00–18:00), written by `scripts/make_availability.py`.
- `../../evals/fixtures/reviews_fixture_*.csv`: synthetic, PII-free review sets for the UX eval
  (`nominee` → top theme Nominee Updates, `login` → Login Issues, `empty` → no pulse).
