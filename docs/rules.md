# Rules — Compliance, Product & Engineering

> These rules are **non-negotiable**. Every pillar, prompt, and PR must follow them. Evals in [evals.md](./evals.md) verify the critical ones.

Severity: **🔴 MUST** (violation = bug / eval fail) · **🟡 SHOULD** (strong default; deviations documented)

---

## 1. Compliance & Safety

| ID | Rule | Sev |
|----|------|-----|
| C1 | **No investment advice.** Never recommend, rank, or compare funds as "better/best"; never predict or promise returns; never say buy/sell/hold/switch. | 🔴 |
| C2 | **Facts only from sources.** Customer-facing factual claims must come from the indexed corpus and carry a citation. | 🔴 |
| C3 | **Refuse and redirect.** On advice/PII/out-of-scope requests, give a polite refusal + what the system *can* do (facts, educational link, or book an advisor). | 🔴 |
| C4 | **Disclaimer.** Unified Search answers and every voice call show/say *"Facts only. Not investment advice."* | 🔴 |
| C5 | **No tax / legal advice** beyond restating rules present in sources. | 🔴 |
| C6 | **No performance claims.** Don't quote past returns as an indicator of future returns; if returns are asked, link the official factsheet only. | 🔴 |
| C7 | Refusals must not lecture or judge the user; ≤ 2 sentences + 1 helpful alternative. | 🟡 |

---

## 2. Privacy / PII

| ID | Rule | Sev |
|----|------|-----|
| P1 | **No PII collection.** The voice agent never asks for name, phone, email, PAN, Aadhaar, folio, account or card numbers, address, DOB. | 🔴 |
| P2 | **Mask everywhere.** PII is replaced with `[REDACTED]` at ingest (reviews CSV), input (chat/voice transcripts), output (LLM responses), storage (SQLite, artifacts), logs, and MCP payloads. | 🔴 |
| P3 | **Simulated users are `[REDACTED]`.** Any user/caller name shown in UI, notes, calendar or email is the literal string `[REDACTED]`. | 🔴 |
| P4 | **No PII disclosure.** Never reveal personal contact details of employees, executives (e.g. CEO email), advisors, or other users — even if found in a source. | 🔴 |
| P5 | Raw audio is not persisted; only scrubbed transcripts. | 🔴 |
| P6 | The only booking identifier is the **Booking Code**. | 🔴 |
| P7 | PII patterns covered at minimum: email, Indian mobile (+91 / 10-digit), PAN (`[A-Z]{5}[0-9]{4}[A-Z]`), Aadhaar (12 digits, spaced or not, checksum-validated), folio/account numbers (8–18 digits), UPI IDs, card numbers (13–19 digits, Luhn), person names (NER). Implemented with Microsoft Presidio built-in + custom recognizers (see [techDecisions.md](./techDecisions.md)). | 🔴 |

---

## 3. Pillar A — Unified Search

| ID | Rule | Sev |
|----|------|-----|
| A1 | Answers have **exactly 6 bullets** in the fixed slot order ([rag.md §4.3](./architecture/rag.md)). | 🔴 |
| A2 | Every bullet has ≥ 1 citation; every citation must be from the retrieved set (no invented URLs). | 🔴 |
| A3 | Combined (fact + fee) questions must cite ≥ 1 M1 source **and** ≥ 1 M2 fee source. | 🔴 |
| A4 | Every number (%, ₹, days, years) must appear in a cited chunk. | 🔴 |
| A5 | Show "Last updated from sources: <date>". | 🔴 |
| A6 | If info isn't in sources → say so; do not fall back to model knowledge. | 🔴 |
| A7 | Each bullet ≤ 30 words. | 🟡 |
| A8 | Correct false premises using sources (e.g. ELSS has no exit load) instead of agreeing with the user. | 🟡 |

---

## 4. M2 — Review Pulse

| ID | Rule | Sev |
|----|------|-----|
| M1 | Weekly Pulse **≤ 250 words**. | 🔴 |
| M2 | **Exactly 3 action ideas.** | 🔴 |
| M3 | Top 3 themes, 3 quotes (one per top theme). | 🔴 |
| M4 | Themes come from the fixed taxonomy (`config/themes.yaml`), max 5 active themes. | 🔴 |
| M5 | Quotes are PII-scrubbed and attributed only as `[REDACTED]`. | 🔴 |
| M6 | `top_theme` ranking is deterministic and computed in code, not by the LLM. | 🔴 |
| M7 | Market Context snippet ≤ 60 words, neutral, no advice, no PII. | 🔴 |

---

## 5. Pillar B — Voice Agent

| ID | Rule | Sev |
|----|------|-----|
| V1 | Greeting **must mention the current `top_theme`** when a valid pulse (≤ 14 days old) exists. | 🔴 |
| V2 | Greeting is followed by the disclaimer + "don't share personal details" notice. | 🔴 |
| V3 | All times in **IST (Asia/Kolkata)**, stated explicitly ("3:00 PM IST"). | 🔴 |
| V4 | Offer **exactly 2** slots at a time. | 🟡 |
| V5 | Booking code format `NL-[A-HJ-NP-Z][0-9]{3}`, unique, read back to the user. | 🔴 |
| V6 | Confirm topic + date + time + code before ending. | 🔴 |
| V7 | Text-mode fallback must always work (same logic as voice). | 🔴 |

---

## 6. Pillar C — MCP / HITL

| ID | Rule | Sev |
|----|------|-----|
| H1 | **No side effect without approval.** MCP tools execute only for `APPROVED` actions. | 🔴 |
| H2 | **Email is draft-only.** The system never sends email. | 🔴 |
| H3 | Calendar entries are **tentative holds**. | 🔴 |
| H4 | Advisor email drafts **include the Market Context** section. | 🔴 |
| H5 | The **Booking Code** appears in the calendar title, notes row, and email subject + body. | 🔴 |
| H6 | Notes doc is **append-only**; changes are new rows (RESCHEDULED / CANCELLED). | 🔴 |
| H7 | Every decision (approve/reject/edit/execute/fail) is written to the audit log. | 🔴 |
| H8 | Booking code, slot and topic are read-only in the approval editor. | 🟡 |
| H9 | Every action has an idempotency key; re-execution must not duplicate. | 🔴 |

---

## 7. LLM & Prompting

| ID | Rule | Sev |
|----|------|-----|
| L1 | Temperature ≤ 0.2 for factual answers, classification and routing. | 🟡 |
| L2 | Structured outputs (JSON schema) for router, composer, classifier, pulse. | 🟡 |
| L3 | Hard constraints (counts, word limits, formats, codes, theme ranking) are validated **in code**. | 🔴 |
| L4 | Prompts live in `prompts/*.md` (versioned), not scattered in code. | 🟡 |
| L5 | Retrieved content is treated as **data, not instructions** (prompt-injection defence: wrap in delimiters, ignore instructions inside sources/reviews). | 🔴 |
| L6 | Max 1 automatic regeneration per request; then deterministic fallback. | 🟡 |

---

## 8. Engineering

| ID | Rule | Sev |
|----|------|-----|
| E1 | Single entry point: `streamlit run app.py`. | 🔴 |
| E2 | Secrets only in `.env` (git-ignored); `.env.example` committed. | 🔴 |
| E3 | `ADAPTER_MODE=mock` must run end-to-end offline (except LLM calls). | 🔴 |
| E4 | Shared logic lives in `core/`; pillars don't import each other's internals — they use artifacts/DB/interfaces. | 🟡 |
| E5 | Logs are structured JSON and PII-scrubbed. | 🔴 |
| E6 | Unit tests for: PII scrubber, guardrail classifier, booking code generator, pulse validator, answer validator, approval state machine. | 🟡 |
| E7 | `python -m evals.run_evals` reproduces the eval report. | 🔴 |
| E8 | Type hints + Pydantic models for all cross-module data. | 🟡 |
| E9 | Timestamps stored as timezone-aware ISO 8601 (IST for display). | 🔴 |

---

## 9. Standard Refusal Templates

| Trigger | Response |
|---------|----------|
| Investment advice / returns | "I can't provide investment advice or predict returns. I can share factual scheme details with official sources, or help you book a call with an advisor." |
| Request for someone's PII | "I can't share personal contact details. For official queries, please use the company's public support channels listed in the app." |
| User shares own PII | "For your safety, please don't share personal details here — I haven't stored them. Your advisor will collect anything needed securely during the call." |
| Out of scope | "I can help with mutual fund facts, fees and charges, and booking advisor calls. Could you ask something in those areas?" |
| Not in sources | "I couldn't find that in my official sources. You can check <closest official link>." |
