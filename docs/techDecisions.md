# Tech & Design Decisions — Options, Trade-offs, Recommendations

> Review of every major element of the suite: what the options are, which is best, and what we use.
> Assessed **October 2026** against the project's real constraints:
> - a capstone built by **one developer** on a **free or low-cost budget**
> - a **single Streamlit entry point**
> - compliance, auditability and **reproducible evals** matter more than raw scale.
>
> "Best" here means **best for this product**, not best at enterprise scale. Where the enterprise answer differs, we say so.
> Library versions and model names change quickly. **Pin exact versions at install time** (`uv lock`) and re-check the model leaderboards if this doc is more than ~3 months old.

Status legend: ✅ keep · 🔄 change (upgrade) · ➕ new addition

---

## 1. Summary

| # | Element | Previous design | **Recommended** | Status |
|---|---------|-----------------|-----------------|--------|
| 1 | UI / single entry point | Streamlit | **Streamlit** (multipage `st.navigation`, native `st.audio_input`) | ✅ |
| 2 | LLM provider | Groq or Gemini via custom client | **Gemini Flash (primary) + Groq-hosted open model (fallback)** via **LiteLLM** | 🔄 |
| 3 | Structured outputs | JSON mode | **Pydantic models + provider-native JSON-schema outputs** (Instructor-style retry on validation error) | 🔄 |
| 4 | Orchestration framework | Plain Python | **Plain Python services** (no LangChain/LlamaIndex) | ✅ |
| 5 | PDF / document parsing | pdfplumber / trafilatura | **Docling** (tables + layout), trafilatura for HTML, PyMuPDF4LLM fallback | 🔄 |
| 6 | Fact storage | Chunks only | **Structured `scheme_facts` table + chunks** (facts are looked up, not just retrieved) | ➕ |
| 7 | Fee logic | Prose chunks only | **`fee_rules.yaml` + deterministic calculators** + prose chunks for explanations | ➕ |
| 8 | Chunking | Custom section-aware | **Docling HybridChunker** (structure + token aware) + one "field card" per scheme field | 🔄 |
| 9 | Embeddings | bge-small-en-v1.5 | **Qwen3-Embedding-0.6B** (local) — hosted Gemini embeddings when deployed to the cloud | 🔄 |
| 10 | Vector store + keyword search | ChromaDB + rank_bm25 | **LanceDB** (embedded; native full-text + vector hybrid with RRF; metadata filters) | 🔄 |
| 11 | Reranker | Optional bge-reranker-base | **bge-reranker-v2-m3 cross-encoder, on by default** | 🔄 |
| 12 | PII detection / masking | Custom regex + NER | **Microsoft Presidio** (built-in `IN_PAN`, `IN_AADHAAR`, phone, email, card) + custom folio recognizer + spaCy NER | 🔄 |
| 13 | Safety guardrails | Rules + LLM classifier | **3 layers: rules → domain intent classifier (structured LLM) → output validator**; Llama Guard 4 optional | ✅ (refined) |
| 14 | Theme classification | LLM, fixed taxonomy | **LLM zero-shot, fixed taxonomy** + embedding-cluster review of the `Other` bucket (BERTopic, offline) | ✅ (+ improvement) |
| 15 | Pulse generation | LLM + validators | **Code builds the skeleton; LLM writes only quotes context + action ideas** | 🔄 |
| 16 | Voice — interaction model | Push-to-talk turns | **Turn-based push-to-talk in Streamlit**; Pipecat real-time pipeline as a stretch goal | ✅ |
| 17 | Speech-to-text (STT) | faster-whisper / Groq Whisper | **Groq Whisper large-v3-turbo** (hosted), faster-whisper local fallback | ✅ (fixed choice) |
| 18 | Text-to-speech (TTS) | edge-tts / gTTS | **edge-tts with an Indian-English neural voice** (e.g. `en-IN-NeerjaNeural`) | ✅ (fixed choice) |
| 19 | Dialog management | State machine + LLM NLU | **Explicit finite-state machine + LLM slot extraction** (not a free-form agent) | ✅ |
| 20 | MCP server | Official Python SDK | **FastMCP (`fastmcp` 4.x)**, the same package and code as M3 (`build_server`, `ToolClient`, `ToolGate`, outbox); own least-privilege server | 🔄 (reuse M3) |
| 21 | HITL mechanism | DB-backed approval queue | **DB-backed approval queue** (not LangGraph `interrupt`) | ✅ |
| 22 | Calendar / Notes / Email | Google APIs or mocks | **Mocks by default; Google Calendar, Google Docs and Gmail `drafts.create` live** | ✅ |
| 23 | State store | SQLite | **SQLite (WAL) + SQLModel** | ✅ |
| 24 | Eval framework | Custom runner + pytest | **DeepEval (pytest-native) + our deterministic checks**; judge model ≠ generator model | 🔄 |
| 25 | Red-teaming | Hand-written prompts | Hand-written required set + **Promptfoo red-team** (optional extension) | ➕ |
| 26 | Observability / tracing | JSON logs | JSON logs + **Arize Phoenix (local, OpenTelemetry)** for LLM/retrieval traces | ➕ |
| 27 | Packaging & tooling | pip + requirements.txt | **uv** (lockfile) + **ruff** + **pytest** + pre-commit | 🔄 |
| 28 | Demo hosting | Local | Local, then **Hugging Face Spaces** or Streamlit Community Cloud | ➕ |

The next sections give the reasoning for each.

---

## 2. Application Layer

### 2.1 UI — single entry point ✅ Streamlit

| Option | Pros | Cons |
|--------|------|------|
| **Streamlit** | Fastest to build dashboards, tabs and tables; native `st.audio_input` (mic) and `st.audio`; huge community; free hosting | Re-run model means session state needs care; no real-time duplex audio |
| Gradio | Best audio/streaming components; ML-demo friendly | Weaker for multi-page dashboards and tables (the Approval Center) |
| Chainlit | Excellent chat UX, step visualisation | Chat-first; dashboards (Pulse, Approvals) are awkward |
| Next.js + FastAPI | Production-grade, real-time voice possible | 3–4× the effort; overkill for a capstone |

**Recommendation:** Streamlit. Use multipage `st.navigation` for the 7 sections, `st.audio_input` for the microphone (this removes the `streamlit-mic-recorder` dependency), and `st.cache_resource` for models and the index. Keep business logic out of the UI files so a FastAPI layer could be added later without changes.

### 2.2 LLM provider 🔄 Gemini Flash primary, Groq fallback, via LiteLLM

| Option | Strengths | Weaknesses |
|--------|-----------|------------|
| **Gemini Flash tier** | Generous free tier; native JSON-schema structured output; long context; strong instruction following | Free-tier rate limits; data-usage terms on the free tier |
| **Groq (hosted open models: Llama / Qwen / gpt-oss)** | Very low latency — good for voice turns; also hosts Whisper and Llama Guard | Model catalogue changes; JSON-schema strictness varies by model |
| GPT mini tier (OpenAI) | Very reliable structured outputs | Paid only |
| Claude Haiku tier | Excellent instruction following and refusals | Higher cost |
| Local (Ollama) | Free, private, offline | Weaker on CPU; slower; hurts eval scores |

**Recommendation:**
- **Answers, pulse and judging prep → Gemini Flash.** It is the most reliable for structured JSON on a free budget.
- **Voice-turn NLU → Groq**, because it is the fastest. Groq is also the automatic fallback if Gemini fails.
- Wrap both in **LiteLLM**, which gives one interface plus built-in retries, fallbacks and cost logging. This replaces our hand-written `core/llm.py` provider code.
- **Eval judge:** use a *different, stronger* model from the generator (e.g. Gemini Pro tier or GPT/Claude) so the system doesn't grade its own answers.

### 2.3 Structured outputs 🔄
Define every LLM output (router, composer, classifier, pulse, judge) as a **Pydantic model** and pass its JSON schema to the provider's native structured-output mode. On a validation error, retry once with the error message appended (the Instructor pattern; the `instructor` library can do this for you). Hard rules — counts, word limits, citations — are still checked in code ([rules.md L3](./rules.md)).

### 2.4 Orchestration framework ✅ Plain Python

| Option | Verdict |
|--------|---------|
| LangChain | Heavy abstraction; makes the custom validators, citations and guardrails harder to see and test |
| LlamaIndex | Strong for RAG, but we'd still customise routing, validation and citations |
| LangGraph | Excellent for durable agent graphs; our voice flow is a small finite-state machine and HITL is asynchronous (see §6.2) |
| **Plain Python + focused libraries** | Transparent, easy to test, easy to explain in a capstone review |

**Recommendation:** plain Python services with focused libraries (Docling, LanceDB, Presidio, LiteLLM, FastMCP, DeepEval). Reviewers value that every step is visible and testable.

---

## 3. Pillar A — Knowledge Base

### 3.1 Document parsing 🔄 Docling

| Option | Tables in factsheets | Hosting | Notes |
|--------|----------------------|---------|-------|
| **Docling** (IBM, open source) | Best open-source table/layout fidelity | Local | Exports Markdown/JSON plus a document hierarchy; includes HybridChunker |
| Marker | Good, weaker on complex tables | Local (GPU helps) | Fast with GPU |
| LlamaParse | Strong | Cloud API (paid beyond free credits) | Sends documents to a third party |
| PyMuPDF4LLM | Basic; struggles with merged cells | Local | Very fast fallback |
| pdfplumber (previous) | Manual table logic | Local | Most custom code |

**Recommendation:** use **Docling** for PDFs (factsheets, KIM/SID), **trafilatura** for HTML pages (AMFI/SEBI), and **PyMuPDF4LLM** as the fallback when Docling fails on a file. Factsheets are table-heavy multi-scheme PDFs, which is exactly where Docling is strongest.

### 3.2 ➕ Design improvement — structured `scheme_facts` table
Retrieval alone is not the most reliable way to answer "what is the exit load?". **Best practice for numeric facts is to extract them once into a structured table, with provenance, and look them up.**

```
scheme_facts(scheme, field, value, unit, conditions, source_doc_id, page, url, as_of)
fields: exit_load, lock_in, expense_ratio_direct, expense_ratio_regular, min_sip, min_lumpsum,
        benchmark, riskometer, fund_manager, category
```
- Extracted at ingest (Docling tables → LLM extraction into a Pydantic model → **human spot-check** of every row, since there are only ~5 schemes × 10 fields).
- The router's FACT sub-query first tries `scheme_facts` (exact, cited); vector retrieval supplies the surrounding context.
- **Why this is better:** numbers become deterministic, faithfulness goes up, and the "number grounding" validator becomes trivial.

### 3.3 ➕ Design improvement — `fee_rules.yaml` + calculators
The M2 fee explainer becomes **structured rules plus prose**:

```yaml
stamp_duty:  {rate: 0.00005, applies_on: purchase, source: <url>}
exit_load:   {per_scheme: true, basis: redemption_value, source: <url>}
graded_exit_load_liquid: {slabs: [...], source: <url>}
```
Bullet 4 of the 6-bullet answer (the worked example) is **computed in code** from these rules and `scheme_facts`; the LLM only phrases it. LLMs are unreliable at arithmetic, so this removes the riskiest part of a fee answer.

### 3.4 Chunking 🔄
Use **Docling's HybridChunker**, which respects headings and tables and is token-aware for the embedding model. Add **field cards** — one small chunk per `scheme_facts` row, carrying the same metadata — so vector search and fact lookup agree. Fee explainer: one chunk per fee type and scenario (unchanged).

### 3.5 Embeddings 🔄 Qwen3-Embedding-0.6B

| Option | Quality (MTEB) | CPU friendly | Notes |
|--------|----------------|--------------|-------|
| bge-small-en-v1.5 (previous) | Good (older) | Excellent | Clearly behind 2025–26 models |
| **Qwen3-Embedding-0.6B** | Top tier for its size | Good (~0.6B) | Instruction-aware queries; pairs with Qwen3-Reranker |
| BGE-M3 | Very good; dense + sparse + multi-vector | Good | Best if you want learned sparse retrieval |
| jina-embeddings (latest small/nano) | Very good | Excellent | Check the licence (some are non-commercial) |
| Hosted Gemini embeddings | Top tier | n/a (API) | No local RAM; rate limits; network needed |

**Recommendation:** **Qwen3-Embedding-0.6B** locally (no rate limits during evals, reproducible). For cloud hosting with limited RAM, switch to **hosted Gemini embeddings** with one config flag (`EMBED_PROVIDER`). Re-embed the corpus when switching; the corpus is small, so this takes about a minute. Validate the choice with recall@k on the golden set rather than trusting leaderboards alone.

### 3.6 Vector store + hybrid search 🔄 LanceDB

| Option | Embedded (no server) | Native hybrid (keyword + vector) | Metadata filtering | Verdict |
|--------|----------------------|----------------------------------|--------------------|---------|
| ChromaDB (previous) | ✅ | ❌ in local mode (needs separate BM25 + manual fusion) | ✅ | Simple, but hybrid search is DIY |
| **LanceDB** | ✅ | ✅ full-text + vector with RRF reranker | ✅ (pre-filter) | **Best fit**: one store, hybrid built in |
| Qdrant (local / Docker) | Partial (local mode) | ✅ dense + sparse | ✅ (pre-filter) | Best for production scale; more setup |
| sqlite-vec | ✅ | ❌ manual fusion with FTS5 | ✅ | Neat single-file option; more glue code |
| pgvector | ❌ (Postgres) | ✅ with tsvector | ✅ | Production choice if Postgres already exists |

**Recommendation:** **LanceDB**. It replaces Chroma + `rank_bm25` with a single embedded store that does hybrid search natively. Keyword matching matters here: fund names and exact terms like "exit load" and "STT" retrieve better with full-text search. For production at scale, migrate to Qdrant or pgvector.

### 3.7 Reranker 🔄 on by default
**bge-reranker-v2-m3** (cross-encoder, CPU-viable for ~16 candidate pairs per query). Qwen3-Reranker-0.6B is an equally strong alternative. With a small top-k and a 6-bullet output, reranking is the cheapest precision gain available.

---

## 4. Safety & Privacy

### 4.1 PII 🔄 Microsoft Presidio

| Option | Indian identifiers | Verdict |
|--------|--------------------|---------|
| Custom regex (previous) | Whatever we write | Easy to miss variants; no confidence scores or context words |
| **Presidio** (analyzer + anonymizer) | Built-in `IN_PAN`, `IN_AADHAAR` (with checksum), plus email, phone, credit card; easy custom recognizers | **Industry standard**, explainable, testable |
| Guardrails AI PII validator | Wraps Presidio-style detection | Extra layer we don't need |
| LLM-based PII detection | Flexible | Non-deterministic; slow; can't be the only line of defence |

**Recommendation:** **Presidio** with:
- built-in recognizers for `IN_PAN`, `IN_AADHAAR`, `EMAIL_ADDRESS`, `PHONE_NUMBER` (region IN) and `CREDIT_CARD`;
- custom recognizers for folio/account numbers (context words like "folio" or "account") and UPI IDs;
- spaCy `en_core_web_lg` (or a transformer model) for `PERSON`;
- the anonymizer's `replace` operator → `[REDACTED]`.

Run it at the same five boundaries as before: ingest, input, output, logs and MCP payloads.

### 4.2 Guardrails ✅ layered, refined

| Option | Fit |
|--------|-----|
| NeMo Guardrails (Colang) | Powerful dialog policies; heavy learning curve; overkill here |
| Llama Guard 4 | Fast safety classifier whose taxonomy includes *specialized (financial) advice* and *privacy*; good as a second opinion; hosted on Groq |
| Guardrails AI | Good for output validation; overlaps with our Pydantic validators |
| **Rules + domain intent classifier + output validator** | Precise for *our* categories (ADVICE / PII_REQUEST / PII_SHARED / OUT_OF_SCOPE); fully testable |

**Recommendation:** keep our **three-layer design**:
1. **Rules** (regex/keywords) — instant blocks.
2. **Domain intent classifier** — a structured LLM call at temperature 0 with few-shot adversarial examples.
3. **Output validator** — advice patterns and a Presidio scan on every response.

Add **Llama Guard 4** as an optional fourth check on outputs if the Safety Eval shows misses. Retrieved text and reviews are always wrapped as data (prompt-injection defence).

---

## 5. M2 — Themes & Pulse

### 5.1 Theme classification ✅ LLM zero-shot on a fixed taxonomy

| Option | Pros | Cons |
|--------|------|------|
| **LLM zero-shot, fixed taxonomy** | No training data; high accuracy; stable labels week to week; easy to explain | API cost (small; cached) |
| BERTopic / embedding clustering | Discovers new themes | Unstable labels, so the Voice Agent logic can't be tested against it |
| SetFit / fine-tuned classifier | Cheap and fast at inference | Needs ~8–16 labelled examples per class plus training upkeep |
| Keyword rules | Deterministic | Low recall |

**Recommendation:** keep the fixed-taxonomy LLM classifier, which gives stable labels that the Voice Agent and evals depend on. **Improvement:** each week, cluster the reviews that landed in `Other` (BERTopic on Qwen3 embeddings) to *suggest* new taxonomy entries for a human to add. Discovery stays separate from production labels.

### 5.2 Pulse generation 🔄 code-first
The LLM no longer writes the whole pulse. **Code** renders the header, the top-3 themes with percentages, and the quote slots from aggregates. The **LLM writes only** a one-line theme summary per theme and the **3 action ideas** (a Pydantic list with `min_length=max_length=3`). This guarantees the structure, keeps the pulse well under 250 words, and makes the UX eval nearly deterministic.

---

## 6. Pillar B & C — Voice, MCP, HITL

### 6.1 Voice architecture ✅ turn-based now, real-time as a stretch

| Option | Latency | Control over greeting/guardrails | Fit with Streamlit |
|--------|---------|----------------------------------|--------------------|
| **Turn-based (push-to-talk): `st.audio_input` → STT → FSM/LLM → TTS** | ~1.5–3 s per turn | Full | ✅ native |
| Pipecat (open-source cascaded pipeline, VAD, barge-in) | ~0.6–1 s | Full (same agent core) | Separate process + WebRTC/phone transport |
| LiveKit Agents (WebRTC rooms) | ~0.6–1 s | Full | Needs a LiveKit server |
| Speech-to-speech (OpenAI Realtime / Gemini Live) | ~0.3 s | Weaker — harder to guarantee exact greeting text, refusals and PII masking before the model hears the audio | Separate client |
| Managed (Vapi / Retell) | Low | Medium | Vendor lock-in; PII leaves our boundary |

**Recommendation:** use **turn-based voice in Streamlit** for the graded product. It is fully controllable, and the deterministic theme greeting and PII masking happen before any LLM call. As a **stretch goal**, wrap the same `VoiceSession` core in a **Pipecat** pipeline for a real-time demo. Avoid speech-to-speech models for the compliance-critical flow.

### 6.2 STT / TTS ✅ fixed choices
- **STT:** **Groq Whisper large-v3-turbo**, which is fast and cheap and handles Indian-accented English well. Fallback: **faster-whisper** `small` locally. Deepgram is the best choice if streaming STT is ever needed (the Pipecat stretch).
- **TTS:** **edge-tts** with an **Indian-English neural voice** (e.g. `en-IN-NeerjaNeural`), which is free and natural-sounding. Drop gTTS, which sounds robotic. ElevenLabs or Cartesia are premium upgrades for the demo video.

### 6.3 Dialog management ✅ FSM + LLM slot extraction
A free-form tool-calling agent is more flexible but less predictable. For a **regulated booking flow**, an explicit state machine with the LLM limited to **extracting slots** (intent, topic, date/time, code, yes/no) is the safer, more testable design. Use `dateparser` plus explicit `ZoneInfo("Asia/Kolkata")`.

### 6.4 MCP server 🔄 FastMCP (`fastmcp` 4.x), reused from M3

| Option | Fit |
|--------|-----|
| **Standalone `fastmcp` 4.x (as installed in M3)** | Same API, client, `ToolError` and in-process `Client(mcp)` testing that M3 already uses in working, tested code. HTTP transport and server composition are available if needed. |
| `FastMCP` class inside the official `mcp` SDK | Similar decorator API, but a different package. Porting M3 would mean changing imports, the client and the tests for no functional gain. |
| Community Google Workspace MCP servers | Expose send, edit and delete, so they are not least-privilege. |

**Recommendation:** use **`fastmcp>=4.0,<5`, the version M3 actually runs (4.0.10)**, and port M3's MCP layer instead of rewriting it:
- `build_server(calendar, docs, gmail)`: a factory with injected backends.
- Typed `@mcp.tool()` functions using `Annotated`/`Field(pattern=…)` and `Literal` inputs.
- A `_check_no_pii` call in each tool.
- `ToolError("retryable:…" | "permanent:…")` for failures.
- `ToolClient` over `fastmcp.Client`, whose allow-list discovery rejects any "send" tool.
- The deterministic `ToolGate`, the `GatedToolRunner` and the transactional outbox with backoff and compensation.

The tool set is the same as M3: `calendar_list_busy`, `calendar_create_hold`, `calendar_delete_hold`, `docs_append_prebooking` and `gmail_create_draft`. It is extended with `pulse_id`, `market_context` and the capstone's 6 topics.

- **Transport:** `inprocess` (`Client(mcp)`) inside Streamlit and tests; stdio or Streamable HTTP when the server runs as its own process, the same as M3's `MCP_SERVER_TARGET`.
- **Backends:** M3's Google wrappers for the live demo, and local `.ics`/`notes.md`/`.eml` backends with the same interface for offline evals. This is a deliberate difference from M3, which has no mocks.
- **Not reused:** M3's Gemini tool agent. Capstone actions are fixed by the booking plan, so having an LLM propose the calls adds nothing.

### 6.5 HITL ✅ DB-backed approval queue (not LangGraph `interrupt`)

| Option | Fit |
|--------|-----|
| LangGraph `interrupt` + checkpointer | Great for pausing *one running agent* waiting for the *same user* |
| **DB-backed approval queue** | Approval happens **after** the call, by a **different person** (reviewer), across many bookings, with edits and an audit trail |

**Recommendation:** keep the **DB-backed queue**, which matches the real workflow (asynchronous, multi-actor, auditable). Implement it as **M3's transactional outbox with an approval gate**: jobs are inserted as `PENDING` and only become runnable after approval. Add **automatic pre-checks** on each pending action (PII ✅, Market Context ✅, booking code ✅, slot still free via `calendar_list_busy` ✅) so the human reviews a checked payload.

### 6.6 Notes / Doc ✅
Mock `notes.md` by default and a **Google Doc** live, appending a line per event. Google Sheets `values.append` is technically simpler for tabular logs, but the requirement says **"Notes/Doc"**, so we keep the Doc for literal compliance.

### 6.7 State store ✅ SQLite (WAL) + SQLModel
Right-sized, zero-ops and transactional. Production alternative: Postgres, which could also host pgvector.

---

## 7. Evals & Observability

### 7.1 Eval framework 🔄 DeepEval + deterministic checks

| Option | Strengths | Fit |
|--------|-----------|-----|
| **DeepEval** | pytest-native; Faithfulness, Answer Relevancy, Contextual Precision/Recall; **G-Eval** custom rubrics (for the pulse tone rubric); conversational metrics for the voice agent; any LLM as judge | **Best fit** — maps 1:1 to our three required evals and runs in CI |
| RAGAS | Well-known RAG metrics; quick in notebooks | RAG only; less suited to the safety and UX evals |
| Promptfoo | YAML configs; **strong automated red-teaming** | Great complement for the Safety eval |
| TruLens / Arize Phoenix evals | Tracing-linked evals | Better as observability than as the primary harness |
| Custom (previous) | Full control | Re-implements standard metrics; less credible |

**Recommendation:** **DeepEval** for Faithfulness, Answer Relevancy, contextual precision/recall and G-Eval (pulse tone and action-idea quality), wrapped in pytest. **Keep our deterministic checks** — citations ⊆ retrieved, number grounding, 6 bullets, ≤ 250 words, exactly 3 ideas, theme mention, Presidio scan — because they are objective and can't be fooled by a lenient judge. Optionally add **Promptfoo red-team** to generate extra adversarial prompts beyond the required 3. The judge model must be different from the generator.

### 7.2 Observability ➕ Arize Phoenix (local)
Traces of every LLM call, retrieval (chunks and scores) and tool call make debugging eval failures much faster. **Phoenix** runs locally (OpenTelemetry, no account needed); **Langfuse** is the alternative if you want hosted prompt management. Traces must go through the PII scrubber.

---

## 8. Engineering & Delivery

| Element | Recommendation | Why |
|---------|----------------|-----|
| Package / env manager | **uv** + `pyproject.toml` + `uv.lock` | Much faster than pip, reproducible lockfile |
| Lint / format | **ruff** | One fast tool for lint + format |
| Tests | **pytest** (+ DeepEval plugin) | Single runner for unit tests and evals |
| Pre-commit | ruff, secret scanning (`detect-secrets`) | Prevents committing keys |
| Config | `pydantic-settings` | Typed config, `.env` support |
| Hosting (demo) | **Hugging Face Spaces** (more RAM for local models) or Streamlit Community Cloud (use hosted embeddings) | Free public demo link |

---

## 9. Design Improvements (beyond tool swaps)

| # | Improvement | Impact |
|---|-------------|--------|
| D1 | **Structured `scheme_facts` lookup** before vector retrieval (§3.2) | Deterministic, cited numbers → higher faithfulness |
| D2 | **Fee calculators from `fee_rules.yaml`** for the worked-example bullet (§3.3) | Removes LLM arithmetic errors |
| D3 | **Code-first pulse rendering**; LLM only for summaries + 3 ideas (§5.2) | Guaranteed structure and word limit |
| D4 | **Deterministic theme greeting templates** (already in design) | Voice logic check becomes 100% reliable |
| D5 | **Automatic pre-checks in the Approval Center** (§6.5) | Human reviews validated payloads, so approvals are faster and safer |
| D6 | **Least-privilege FastMCP server reused from M3**: draft-only, append-only, idempotent, ToolGate-checked (§6.4) | Compliance by construction; proven, tested code |
| D7 | **Judge ≠ generator** + 10% human verification (§7.1) | Credible eval numbers |
| D8 | **Tracing with Phoenix** (§7.2) | Faster root-cause analysis of eval failures |
| D9 | **`Other`-bucket theme discovery** offline (§5.1) | Taxonomy evolves without destabilising production |
| D10 | **Provider fallback via LiteLLM** (§2.2) | The demo survives rate limits or outages |

---

## 10. Final Recommended Stack

```text
UI            Streamlit (st.navigation, st.audio_input)
LLM           LiteLLM → Gemini Flash (primary) | Groq open model (fallback, voice NLU)
Structured    Pydantic schemas + native structured output (+ instructor-style retry)
Parsing       Docling (PDF) · trafilatura (HTML) · PyMuPDF4LLM (fallback)
Facts         scheme_facts (SQLite) + fee_rules.yaml + calculators
Retrieval     LanceDB hybrid (FTS + vector, RRF) · Qwen3-Embedding-0.6B · bge-reranker-v2-m3
PII           Microsoft Presidio (+ custom folio/UPI recognizers, spaCy NER)
Guardrails    Rules → domain intent classifier → output validator (+ optional Llama Guard 4)
Themes        LLM zero-shot fixed taxonomy (+ BERTopic discovery on "Other", offline)
Voice         st.audio_input → Groq Whisper v3-turbo → FSM + LLM slot extraction → edge-tts (en-IN)
MCP           FastMCP (fastmcp 4.x) from M3: build_server + ToolClient + ToolGate + outbox; in-process/stdio/HTTP
HITL          SQLite-backed approval queue (outbox jobs gated on approval) + automatic pre-checks + audit log
Integrations  Local backends (default) · M3 Google wrappers: Calendar · Docs · Gmail drafts.create
State         SQLite (WAL) + SQLModel
Evals         DeepEval (pytest) + deterministic checks (+ Promptfoo red-team optional)
Observability Arize Phoenix (local OTel), PII-scrubbed JSON logs
Tooling       uv · ruff · pytest · pre-commit · pydantic-settings
```

## 11. When to Revisit

- **Scale beyond a demo** → Qdrant or pgvector, Postgres, FastAPI backend + Next.js UI, LiveKit/Pipecat real-time voice.
- **Leaderboards move** → re-check embedding and reranker choices with recall@k on the golden set (5 minutes with the eval suite).
- **Provider terms or pricing change** → LiteLLM makes switching a config change.
