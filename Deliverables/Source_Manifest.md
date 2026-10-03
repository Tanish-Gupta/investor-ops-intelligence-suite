# Source Manifest: Investor Ops & Intelligence Suite

This is the combined list of every external source used across the bootcamp milestones (M1 RAG chatbot, M2 Review Analyst, M3 Voice Scheduler) and the integrated capstone suite.

| Summary | Count |
|---|---|
| **Official URLs** (AMC, SEBI, AMFI, app store) | **40** |
| Third-party aggregator pages (from M1; disclosed below) | 6 |
| **Total unique source URLs** | **46** |
| Corpus documents built from these URLs | 76 (`data/sources.csv`) |
| Mutual funds covered | 30 (5 Edelweiss, 25 Bajaj Finserv) |

Each URL maps to one or more `doc_id`s in [`data/sources.csv`](../data/sources.csv), the machine-readable registry. Every answer's citations resolve to one of these URLs. Scheme facts are as of the **August 2026** factsheet and scheme pages fetched on **2026-10-03**. Edelweiss scheme pages carry over from M1.

## A. Scheme facts, official AMC sources (M1 · Pillar A): 27 URLs

### A1. Bajaj Finserv Mutual Fund scheme pages (25)

Each page supplies the exit load, lock-in, minimum lump sum and SIP, benchmark, riskometer and plan details (`doc_id` suffix `-01`).

| # | Scheme | Category | Official URL | doc_id |
|---|--------|----------|--------------|--------|
| 1 | Bajaj Finserv Large Cap Fund | Large Cap | <https://www.bajajamc.com/mutual-funds/equity-funds/bajaj-finserv-large-cap-fund/> | `F-BLC-01` |
| 2 | Bajaj Finserv Flexi Cap Fund | Flexi Cap | <https://www.bajajamc.com/mutual-funds/equity-funds/bajaj-finserv-flexi-cap-fund/> | `F-BFLEXI-01` |
| 3 | Bajaj Finserv Large and Mid Cap Fund | Large & Mid Cap | <https://www.bajajamc.com/mutual-funds/equity-funds/bajaj-finserv-large-and-mid-cap-fund/> | `F-BLMC-01` |
| 4 | Bajaj Finserv Multi Cap Fund | Multi Cap | <https://www.bajajamc.com/mutual-funds/equity-funds/bajaj-finserv-multi-cap-fund/> | `F-BMC-01` |
| 5 | Bajaj Finserv Small Cap Fund | Small Cap | <https://www.bajajamc.com/mutual-funds/equity-funds/bajaj-finserv-small-cap-fund/> | `F-BSC-01` |
| 6 | Bajaj Finserv ELSS Tax Saver Fund | ELSS | <https://www.bajajamc.com/mutual-funds/equity-funds/bajaj-finserv-elss-tax-saver-fund/> | `F-BELSS-01` |
| 7 | Bajaj Finserv Healthcare Fund | Sectoral/Thematic | <https://www.bajajamc.com/mutual-funds/equity-funds/bajaj-finserv-healthcare-fund/> | `F-BHC-01` |
| 8 | Bajaj Finserv Consumption Fund | Sectoral/Thematic | <https://www.bajajamc.com/mutual-funds/equity-funds/bajaj-finserv-consumption-fund/> | `F-BCONS-01` |
| 9 | Bajaj Finserv Banking and Financial Services Fund | Sectoral/Thematic | <https://www.bajajamc.com/mutual-funds/equity-funds/bajaj-finserv-banking-and-financial-services-fund/> | `F-BBFS-01` |
| 10 | Bajaj Finserv Nifty 50 Index Fund | Index | <https://www.bajajamc.com/mutual-funds/index-funds/bajaj-finserv-nifty-50-index-fund/> | `F-BN50-01` |
| 11 | Bajaj Finserv Nifty Next 50 Index Fund | Index | <https://www.bajajamc.com/mutual-funds/index-funds/bajaj-finserv-nifty-next-50-index-fund/> | `F-BNN50-01` |
| 12 | Bajaj Finserv Balanced Advantage Fund | Balanced Advantage | <https://www.bajajamc.com/mutual-funds/hybrid-funds/bajaj-finserv-balanced-advantage-fund/> | `F-BBAF-01` |
| 13 | Bajaj Finserv Multi Asset Allocation Fund | Multi Asset Allocation | <https://www.bajajamc.com/mutual-funds/hybrid-funds/bajaj-finserv-multi-asset-allocation-fund/> | `F-BMAAF-01` |
| 14 | Bajaj Finserv Equity Savings Fund | Equity Savings | <https://www.bajajamc.com/mutual-funds/hybrid-funds/bajaj-finserv-equity-savings-fund/> | `F-BESF-01` |
| 15 | Bajaj Finserv Arbitrage Fund | Arbitrage | <https://www.bajajamc.com/mutual-funds/hybrid-funds/bajaj-finserv-arbitrage-fund/> | `F-BARB-01` |
| 16 | Bajaj Finserv Liquid Fund | Liquid | <https://www.bajajamc.com/mutual-funds/debt-funds/bajaj-finserv-liquid-fund/> | `F-BLIQ-01` |
| 17 | Bajaj Finserv Money Market Fund | Money Market | <https://www.bajajamc.com/mutual-funds/debt-funds/bajaj-finserv-money-market-fund/> | `F-BMM-01` |
| 18 | Bajaj Finserv Overnight Fund | Overnight | <https://www.bajajamc.com/mutual-funds/debt-funds/bajaj-finserv-overnight-fund/> | `F-BON-01` |
| 19 | Bajaj Finserv Low Duration Fund | Low Duration | <https://www.bajajamc.com/mutual-funds/debt-funds/bajaj-finserv-low-duration-fund/> | `F-BLD-01` |
| 20 | Bajaj Finserv Gilt Fund | Gilt | <https://www.bajajamc.com/mutual-funds/debt-funds/bajaj-finserv-gilt-fund/> | `F-BGILT-01` |
| 21 | Bajaj Finserv Banking and PSU Fund | Banking and PSU | <https://www.bajajamc.com/mutual-funds/debt-funds/bajaj-finserv-banking-and-psu-fund/> | `F-BBPSU-01` |
| 22 | Bajaj Finserv Nifty 50 ETF | Equity ETF | <https://www.bajajamc.com/mutual-funds/etf/bajaj-finserv-nifty-50-etf/> | `F-BETF50-01` |
| 23 | Bajaj Finserv Nifty Bank ETF | Equity ETF | <https://www.bajajamc.com/mutual-funds/etf/bajaj-finserv-nifty-bank-etf/> | `F-BETFBANK-01` |
| 24 | Bajaj Finserv BSE Top 10 Banks ETF | Equity ETF | <https://www.bajajamc.com/mutual-funds/etf/bajaj-finserv-bse-top-10-banks-etf/> | `F-BETFT10-01` |
| 25 | Bajaj Finserv Nifty 1D Rate Liquid ETF | Liquid ETF | <https://www.bajajamc.com/mutual-funds/etf/bajaj-finserv-nifty-1d-rate-liquid-etf/> | `F-BETFLIQ-01` |

### A2. AMC factsheets (2)

| # | Source | Used for | Official URL | doc_id(s) |
|---|--------|----------|--------------|-----------|
| 26 | Bajaj Finserv MF monthly factsheet, August 2026 | Base expense ratio (TER) for all 25 Bajaj schemes | <https://media.bajajamc.com/wp-content/uploads/2026/08/Factsheet_August-2026.pdf> | `F-B*-02` (25 docs) |
| 27 | Edelweiss Liquid Fund factsheet | Graded exit-load slabs (day 1–7) | <https://www.edelweissmf.com/Files/downloads/Product%20Collateral/Factsheet/2025/Feb/published/Edelweiss_Liquid_Fund_18022025_091849_PM.pdf> | `F-LIQ-02` |

## B. Fee Explainer and regulator education (M2 Fee Explainer · Pillar A): 12 URLs

These sources supply the "why was I charged" logic: exit load, graded exit load, lock-in, stamp duty, STT, TER and statements.

| # | Publisher | Topic | Official URL | doc_id(s) |
|---|-----------|-------|--------------|-----------|
| 28 | SEBI (regulator) | Circular SEBI/HO/IMD/DF2/CIR/P/2019/101: graded exit load for liquid funds | <https://www.sebi.gov.in/sebi_data/attachdocs/sep-2019/1568988295926.pdf> | `R-SEBI-LIQ-01`, `FE-GRADED-01` |
| 29 | SEBI investor education | Exit load | <https://investor.sebi.gov.in/exit_load.html> | `R-SEBI-EXIT-01` |
| 30 | AMFI, Mutual Funds Sahi Hai | What are loads (exit load) | <https://www.mutualfundssahihai.com/en/what-are-loads> | `R-MFSH-LOADS-01`, `FE-EXIT-01` |
| 31 | AMFI, Mutual Funds Sahi Hai | Costs incurred while redeeming units | <https://www.mutualfundssahihai.com/en/what-costs-does-one-incur-while-redeeming-mutual-fund-units> | `R-MFSH-REDEEM-01` |
| 32 | AMFI, Mutual Funds Sahi Hai | Expenses of a mutual fund scheme | <https://www.mutualfundssahihai.com/en/what-are-expenses-incurred-mutual-fund-scheme> | `R-MFSH-EXP-01` |
| 33 | AMFI, Mutual Funds Sahi Hai | What is a lock-in period | <https://www.mutualfundssahihai.com/en/what-is-lock-in-period> | `R-MFSH-LOCKIN-01`, `FE-LOCKIN-01` |
| 34 | AMFI, Mutual Funds Sahi Hai | ELSS tax-saving mutual fund | <https://www.mutualfundssahihai.com/en/elss-fund-tax-saving-mutual-fund> | `R-MFSH-ELSS-01` |
| 35 | AMFI, Mutual Funds Sahi Hai | ELSS through SIP or lump sum (per-instalment lock-in) | <https://www.mutualfundssahihai.com/en/should-i-invest-elss-through-sip-or-lumpsum> | `R-MFSH-ELSSSIP-01` |
| 36 | AMFI, Mutual Funds Sahi Hai | Documents provided as proof of investment (statements) | <https://www.mutualfundssahihai.com/en/what-documents-are-provided-proof-my-investment-mutual-funds> | `R-MFSH-DOCS-01`, `FE-CG-01` |
| 37 | Bajaj Finserv AMC knowledge centre | Stamp duty on mutual funds (0.005%) | <https://www.bajajamc.com/knowledge-centre/stamp-duty-on-mutual-funds> | `R-AMC-STAMP-01`, `FE-STAMP-01` |
| 38 | Bajaj Finserv AMC knowledge centre | Securities Transaction Tax (0.001%) | <https://www.bajajamc.com/knowledge-centre/securities-transaction-tax> | `R-AMC-STT-01`, `FE-STT-01` |
| 39 | Tata Mutual Fund (AMC) | Expense ratio: TER deducted daily inside the NAV | <https://www.tatamutualfund.com/blogs/what-expense-ratio-mutual-funds-learn-how-much-you-are-actually-paying-your-fund> | `R-AMC-TER-01`, `FE-TER-01` |

## C. Review data (M2 Review Analyst · Pillar B Weekly Pulse): 1 URL

| # | Source | Used for | Official URL |
|---|--------|----------|--------------|
| 40 | Google Play Store: Groww app (`com.nextbillion.groww`) | Public app reviews that feed the Weekly Pulse themes. Reviewer names are stored as `[REDACTED]` and the review text is scrubbed for PII ([`data/reviews/reviews.csv`](../data/reviews/reviews.csv)). | <https://play.google.com/store/apps/details?id=com.nextbillion.groww> |

## D. Third-party aggregator pages (carried over from M1, disclosed): 6 URLs

M1 originally sourced Edelweiss scheme facts from aggregator pages. They are kept so that M1's golden questions still resolve, and every answer that uses them shows the full aggregator URL in its citations. All 25 funds added for the capstone use **official AMC sources only** (section A).

| # | Aggregator | Scheme | URL | doc_id |
|---|------------|--------|-----|--------|
| 41 | INDmoney | Edelweiss ELSS Tax Saver Fund | <https://www.indmoney.com/mutual-funds/edelweiss-elss-tax-saver-direct-plan-growth-option-2669> | `F-ELSS-01` |
| 42 | INDmoney | Edelweiss Flexi Cap Fund | <https://www.indmoney.com/mutual-funds/edelweiss-flexi-cap-fund-direct-growth-3174> | `F-FLEXI-01` |
| 43 | INDmoney | Edelweiss Large Cap Fund | <https://www.indmoney.com/mutual-funds/edelweiss-large-cap-fund-direct-plan-growth-option-2965> | `F-LC-01` |
| 44 | ET Money | Edelweiss Large Cap Fund (exit-load window) | <https://www.etmoney.com/mutual-funds/edelweiss-large-cap-fund-direct-growth/16911> | `F-LC-02` |
| 45 | INDmoney | Edelweiss Nifty 50 Index Fund | <https://www.indmoney.com/mutual-funds/edelweiss-nifty-50-index-fund-direct-growth> | `F-IDX-01` |
| 46 | INDmoney | Edelweiss Liquid Fund | <https://www.indmoney.com/mutual-funds/edelweiss-liquid-fund-direct-growth-1009> | `F-LIQ-01` |

## E. Milestone codebases (provenance, not cited data)

M3, the Voice Scheduler, uses no external data source. Calendar, Docs and Gmail actions run through its FastMCP server against mock backends, and every write is gated by the HITL Approval Center.

| Milestone | Repository |
|-----------|------------|
| M1: Mutual Fund RAG chatbot | <https://github.com/Tanish-Gupta/mutual-fund-rag-chatbot> |
| M2: App Review Analyser | <https://github.com/Tanish-Gupta/app-review-analyser> |
| M3: Advisor Appointment Voice Agent | <https://github.com/Tanish-Gupta/advisor-appointment-voice-agent> |
