# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

- **Retail mutual-fund investors** of an Indian fintech (Groww / INDmoney class). They come with a specific question about a scheme or a charge they saw ("What is the ELSS exit load and why was I charged it?"), or they want to talk to an advisor. They want a factual, cited answer or a booked slot. They do not want advice, sales or a dashboard.
- **The advisor / compliance desk.** After a call ends, they review the Calendar Hold and the Email Draft the system prepared. They approve, edit or reject them before anything is sent. The email carries a Market Context snippet, so they know current customer sentiment before the meeting.

## Product Purpose

Investor Ops & Intelligence Suite turns internal review data into better customer-facing help, with a human approving every side effect. Only three features are exposed:

1. **Unified Search.** One question returns a 6-bullet answer that combines M1 factsheet facts (e.g. the Exit Load %) with M2 fee logic (why it was charged). Every bullet carries a source citation.
2. **Theme-aware voice agent.** The M2 Weekly Pulse briefs the M3 agent. When the top review theme is bookable (e.g. "Nominee Updates", "Login Issues"), the greeting mentions it proactively and offers to book a call for it.
3. **Post-call follow-ups with HITL.** When a call ends, the agent prepares a Calendar Hold and an Advisor Email Draft. The draft includes a Market Context snippet from the Weekly Pulse. Nothing executes until a human approves it, and the Booking Code then appears in the pre-booking Notes doc.

Success means an investor gets a cited answer or a booking in under a minute, and an advisor can approve a fully prepared follow-up in one glance.

## Positioning

Most help desks and FAQ bots never learn from their own reviews. Here the reviews (M2) decide what the voice agent leads with and what the advisor reads before the meeting. Every answer is grounded in official scheme documents and cited, and every outbound action waits for a human.

## Operating Context

- A single Streamlit app (`app.py`) is the only entry point.
- The Weekly Pulse is built automatically from the bundled reviews CSV (`data/reviews/reviews.csv`) at startup. A small "Upload new reviews" control inside the voice agent's briefing rebuilds it from a new CSV.
- The MCP tools (FastMCP) run with mock adapters by default (`.ics`, `.eml`, notes doc on disk). Google Calendar, Gmail and Docs adapters are optional.
- Eval suites, health checks and pulse analytics exist for the team, but they run from the CLI and docs (`evals/`, `docs/evals.md`). They are not part of the user-facing UI.

## Capabilities and Constraints

- Facts only, with no investment advice. Refusals link to official investor education.
- No PII. Caller names are always shown as `[REDACTED]`. Unified Search never collects or stores personal identifiers.
- Answers follow a 6-bullet structure, and every bullet carries a citation.
- The Booking Code (format `NL-XXXX`) links the call, the calendar hold, the email subject and the notes line.
- Every path works offline with a deterministic fallback. The LLM is opt-in.
- Out of scope in the UI: eval dashboards, KPI/insight panels, system health, theme charts.

## Brand Commitments

- Product name: "Investor Ops & Intelligence Suite". The wordmark and icon live in `assets/`.
- Voice: calm, factual and brief. Short sentences, with no hype and no emojis in copy.
- Compliance line, always visible: "Facts only. No investment advice."

## Evidence on Hand

- Corpus: AMC factsheets, KIM/SID and SEBI/AMFI pages, plus the M2 fee explainer, under `data/corpus/`.
- Reviews: `data/reviews/reviews.csv`. Its current top theme is "App Performance & UX", which is non-bookable. `tests/pillar_m2/conftest.py` holds a NOMINEE fixture.
- No customer testimonials, metrics or logos exist. Never fabricate them.

## Product Principles

1. Three jobs, done completely. Anything that doesn't serve asking, booking or approving stays off the screen.
2. Show the source. Every fact links to the document it came from.
3. A human signs off. No calendar, email or doc write happens without visible approval.
4. The reviews speak through the product. The pulse appears as the agent's greeting and the advisor's context, not as a chart.

## Accessibility & Inclusion

Target WCAG 2.2 AA: keyboard reachable, visible focus, 4.5:1 text contrast, and no information carried by color alone. The typed path must always be available as an alternative to voice.
