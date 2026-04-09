# Prompt Routing System — Master Project Context Document

**Financial Document Intelligence Pipeline (FDIP)**

*Master Project Context Document — Coding Agent Prompt*

Builder: Srishan KN | Stack: Python 3.11, FastAPI, React.js, Groq, LlamaParse, Docling, PyMuPDF

---

## 1. Project Overview

The Financial Document Intelligence Pipeline is a production-aware, two-phase document processing system that accepts user prompts and documents as input, identifies intent from the prompt, and routes the request to the appropriate processing module. The system is designed to handle complex financial documents — including 40+ page annual reports and messy bank invoices — with intelligent parser selection, metadata-informed routing, and real-time streaming output.

*The core thesis: most document processing demos handle clean, simple inputs. This system handles the real world — multi-page financial statements, scanned invoices, complex tables, and ambiguous prompts — and makes defensible routing decisions grounded in document structure, not just prompt text.*

**North Star Definition of Done**

A working demo where a reviewer can upload a real bank invoice or annual report, type a natural language prompt, and watch the system correctly identify intent, select the right processing strategy, and stream a structured, accurate result — with full observability of the routing decision and confidence score.

**MVP vs Phase B Split**

The MVP must be fully working end-to-end: upload → parse → scrub → route → process → stream. Every component must function correctly before Phase B begins. Phase B adds intelligence on top of a working foundation — it does not fix a broken one. The MVP keeps the routing layer intentionally simple. Phase B adds confidence calibration, hard rules, map-reduce summarization, and the evaluation harness. Do not build Phase B features during the MVP. Do not leave MVP features incomplete and move on.

---

## 2. System Architecture — Two-Phase Workflow

### Phase A — Ingestion and Triage (Upload-Triggered)

**Purpose:** Front-load all parsing, metadata extraction, and PII scrubbing before the user types anything. Every decision in Phase B is faster and more accurate because Phase A has already done the heavy lifting.

---

**Step 1 — PyMuPDF Scout**

Runs on every uploaded document immediately on upload. Scans the **entire document** — not just the first pages. Benchmarked at under 60 seconds on a 45-page document, which is acceptable as a background upload task. Extracts the following from the full document:

- Total page count
- Total drawing count across all pages (table border and line density signal)
- Total image count across all pages (scanned PDF detection)
- Total character count across all pages
- Total block count and average characters per block across all pages
- First 1000 characters of page one as text preview
- Language detection via langdetect on the text preview

Computes three derived routing signals:

- `is_scanned` — true if image count is high and total character count is below threshold
- `has_complex_layout` — true if total drawing count exceeds threshold
- `likely_has_tables` — true if average chars per block is low and block count is high

All thresholds must be named constants in `config.py`. Calibrate against actual test documents before finalizing values. Print `drawing_count`, `block_count`, and `avg_chars_per_block` for Document4 and Document5 before hardcoding anything.

---

**Step 2 — Parser Routing Decision**

Deterministic logic. No LLM involved. Two paths:

- **Simple path:** `is_scanned` is false AND `has_complex_layout` is false AND `likely_has_tables` is false. PyMuPDF output is used directly as the parsed text.
- **Complex path:** Any one of the three signals is true. Original PDF sent to LlamaParse (markdown output mode). If LlamaParse fails for any reason (rate limit, timeout, API error), fall back to Docling running locally. If Docling also fails, use raw PyMuPDF text with `parsing_quality` flagged as degraded. Never surface a parsing failure as an unhandled exception.

Parser outputs must never be mixed. Once the parser factory selects a parser for a document, all downstream processing uses only that parser's output.

---

**Step 3 — PII Scrubbing (Document)**

Regex-based masking runs on the parsed text before any content is stored or sent to any external API. MVP applies **three patterns only**:

| Type | Pattern | Token Format |
|---|---|---|
| Aadhaar | `\b\d{4}\s?\d{4}\s?\d{4}\b` | `{{AADHAAR_1}}`, `{{AADHAAR_2}}`, … |
| PAN | `\b[A-Z]{5}\d{4}[A-Z]{1}\b` | `{{PAN_1}}`, `{{PAN_2}}`, … |
| Phone | `\b(?:\+91|91|0)?[6-9]\d{9}\b` | `{{PHONE_1}}`, `{{PHONE_2}}`, … |

Each detected value is replaced with a typed, incrementing token. The token-to-value mapping is stored in session state. This mapping is the source of truth for prompt synchronization and response re-hydration.

Named persons, bank account numbers, and all other PII types are intentionally out of scope for the MVP. See Section 11 (Path to Production) for the expanded detection strategy.

The scrubbed text replaces the raw parsed text in all downstream processing. The raw text is never stored, never sent externally, never passed to any LLM.

---

**Step 4 — Prompt PII Synchronization (Called at Start of Phase B)**

This is the critical second half of the two-way tokenization system. It solves the mapping mismatch problem: the document has been scrubbed and contains `{{NAME_1}}`, but the user types a prompt containing the real name "IEKRAM HOSSAIN". Without synchronization, the LLM sees two different representations of the same entity and cannot match them.

**The Match-and-Swap workflow:**

1. User submits prompt: `"What are the transactions linked to PAN ABCDE1234F?"`
2. System calls `sync_prompt_with_tokens(user_prompt, session_id)`
3. The function iterates through the session token map. For each entry, if the real value appears in the prompt, it replaces it with the token.
4. Match found: prompt becomes `"What are the transactions linked to PAN {{PAN_1}}?"`
5. This synchronized prompt is passed to the Intent Router and all processing modules. The LLM now sees `{{PAN_1}}` in both the prompt and the document — a perfect match. It can extract the correct value without ever seeing the raw PAN.

**The unknown PII scenario:**

If the user types a PAN, Aadhaar, or phone number that does not appear in the document's token map (it was never in the document), the function finds no match. In this case, apply the same three regex patterns to the prompt directly to scrub any loose PII. The resulting token (e.g., `{{UNKNOWN_PAN_1}}`) will not appear in the document text, so the LLM will correctly respond that it cannot find the entity. The user receives an accurate "not found" response. No PII leaks to the cloud.

**Why this is non-negotiable:**

Without prompt scrubbing, two critical failures occur. First, raw PII (names, Aadhaar, account numbers) reaches Groq through the prompt, violating the core security requirement. Second, the LLM sees "IEKRAM HOSSAIN" in the prompt and `{{NAME_1}}` in the document — it will hallucinate or claim the person is not present even when they are. Both failures are unacceptable.

**Implementation:** `sync_prompt_with_tokens(user_prompt: str, session_id: str) -> str` lives in `utils/pii.py`. It is called as the very first operation in `POST /chat` before routing, before module execution, before anything else.

---

**Step 5 — MVP Metadata Packet Assembly**

Assembled from scout outputs and parsing results. Stored in server-side session state. The MVP packet contains only the fields that directly influence routing and processing decisions. All additional metadata is a Phase B addition.

**MVP metadata packet — 6 fields:**

- `page_count` — drives strategy selection in the router
- `likely_has_tables` — influences processing approach for extraction
- `is_scanned` — informs the user about document quality
- `language` — flags non-English documents
- `parser_used` — records which parser ran (simple / llamaparse / docling / pymupdf_fallback)
- `text_preview` — first 1000 chars for LLM domain awareness in the router

Stored alongside scrubbed full text and token map in the session dictionary under the session ID.

---

### Phase B — Intelligence and Streaming (Prompt-Triggered)

**Purpose:** Use the pre-computed metadata packet from Phase A, synchronize the prompt, route to the correct processing module, and stream results back to the user.

---

**Step 1 — Prompt Synchronization**

Call `sync_prompt_with_tokens(user_prompt, session_id)` immediately on receipt of the prompt. All downstream logic uses the synchronized prompt only. The raw user prompt is discarded after this step.

---

**Step 2 — MVP Intent Router**

Single LLM call using `llama-3.1-8b-instant` via Groq. Receives the synchronized prompt and the MVP metadata packet. Uses `instructor` to enforce a Pydantic `RoutingDecision` output.

MVP router output:
- `intent`: Literal["extraction", "summarization", "classification"]
- `confidence`: float 0–1
- `reasoning`: str (one sentence explaining the decision)

Router system prompt must include four few-shot examples: a clear extraction prompt, a clear summarization prompt, a clear classification prompt, and one ambiguous prompt. Examples must reference metadata fields explicitly so the model uses them.

No confidence calibration in the MVP. No hard rules check in the MVP. The router output is used directly. These are Phase B additions.

---

**Step 3 — Module Execution**

Three processing modules, each an independent async function with a consistent interface: receives scrubbed document text, MVP metadata packet, and synchronized prompt. Returns a result object.

- **Summarizer:** Single LLM call. Model: `llama-3.1-70b-versatile`. MVP uses direct single-pass only. Map-reduce is Phase B.
- **Extractor:** Uses `FinancialStatementSchema` Pydantic model enforced via instructor. Deterministic JSON output. Model: `llama-3.1-70b-versatile`.
- **Classifier:** Single LLM call. Returns document type, confidence, and key signals. Model: `llama-3.1-8b-instant`.

---

**Step 4 — Re-hydration and Streaming**

Before any content reaches the SSE stream, run re-hydration: iterate through the session token map and replace all tokens with their real values. The user sees real names and numbers in the response. The LLM never saw them.

Stream results via Server-Sent Events. The final SSE event must be type `done` and include a metadata payload: intent detected, confidence, parser used, and any quality flags.

---

**Phase B Additions — Not in MVP**

These are explicitly excluded from the MVP and built after Checkpoint 12 passes:

- Hard rules check (page_count override, language flag, quality penalty)
- Confidence calibration (metadata-adjusted confidence scores)
- Map-reduce summarization strategy
- Fallback intent on low confidence
- Extended metadata packet (estimated_tokens, doc_structure_type, avg_chars_per_block, block_count, parsing_quality)
- Evaluation harness (`eval/router_eval.py`)
- LangSmith tracing
- `/metrics` endpoint

---

## 3. Technical Stack

| Category | Technology |
|---|---|
| Language | Python 3.11 |
| Backend | FastAPI (async-first), Uvicorn |
| LLM Provider | Groq |
| Routing Model | llama-3.1-8b-instant |
| Processing Model | llama-3.1-70b-versatile |
| Structured Output | instructor + Pydantic v2 |
| Parsers | LlamaParse (cloud), PyMuPDF (scout + simple path), Docling (local fallback) |
| Language Detection | langdetect |
| Session State | In-memory dictionary, 30-minute TTL |
| Streaming | FastAPI StreamingResponse, Server-Sent Events (text/event-stream) |
| Observability (Phase B) | LangSmith, structlog, /metrics endpoint |
| Frontend | React 18, Tailwind CSS, react-pdf-viewer |

---

## 4. Key Design Decisions and Rationale

**Full-Document Scout**

PyMuPDF runs across the entire document. Benchmarked at under 60 seconds on a 45-page PDF — acceptable as a background upload task. Full-document scanning produces accurate metadata: drawing count, block density, and image detection are document-wide properties, not first-page properties. Checking only the first three pages risks missing complex tables that appear later in the document.

**Cascading Parser Architecture**

LlamaParse produces clean markdown that preserves table structure — empirically verified against the HUL Annual Report where PyMuPDF alone lost column alignment. LlamaParse is cloud-only, so Docling (local, markdown output, zero data egress) is the fallback for rate limit failures and for deployments where financial document data cannot leave the premises. PyMuPDF handles clean digital text at 0.39s with no external dependency.

**Parse-First, Route-Second**

Parsing is triggered on upload, not on prompt submission. The metadata packet is ready before the user types. Phase B routing consumes this pre-computed packet, making the routing call faster and better-informed.

**Two-Way PII Tokenization**

Document text is scrubbed on ingestion. Prompts are scrubbed and synchronized with the session token map before any LLM call. Responses are re-hydrated before streaming. The LLM operates entirely on tokens throughout. No raw PII ever reaches the cloud. Prompt synchronization also solves the context alignment problem — the LLM sees the same token in both the document and the prompt, enabling accurate entity-level extraction.

**8B for Routing, 70B for Processing**

Routing is a classification task — 8B is fast and sufficient. Processing financial documents requires deeper reasoning — 70B is justified for extraction and summarization. Matching model size to task complexity reduces latency on the most frequent operation while preserving accuracy on the most critical.

---

## 5. Backend API Specification

Three endpoints. All must be implemented and working before frontend development begins.

---

### `POST /upload`

Phase A entry point. Accepts a multipart form upload of a PDF file.

**Request:** `multipart/form-data` with field `file` containing the PDF.

**Processing sequence:**
1. Validate file type — return HTTP 415 immediately for unsupported formats
2. Generate a UUID session ID
3. Read file into memory (bytes) — do not write to disk
4. Create initial session entry in `SESSIONS[session_id]` with `status: "processing"` and `expires_at`
5. Enqueue the Phase A pipeline as a FastAPI `BackgroundTask` — non-blocking
6. Return `202 Accepted` with `session_id` immediately. **The client must poll `GET /status/{session_id}`.**

**Phase A pipeline (runs in background):**
1. Run PyMuPDF Scout on the full document
2. Run parser routing decision — select simple or complex path
3. Execute selected parser (LlamaParse / Docling / PyMuPDF)
4. Run PII scrubber on parsed text — build token map
5. Assemble MVP metadata packet
6. Update `SESSIONS[session_id]` with `status: "ready"` and all metadata fields

If any step fails, update session with `status: "failed"` and `error: "<reason>"`. The client discovers this via `/status`. Never raise an unhandled exception in the background task.

**Response (202 Accepted, JSON):**
```json
{
  "session_id": "uuid-string",
  "status": "processing"
}
```

**Error handling:** Unsupported file types return HTTP 415 synchronously before the background task is started. Empty or corrupt files return HTTP 422.

---

### `GET /status/{session_id}`

Polling endpoint. Called by the frontend every 1.5 seconds after upload until `status` is `ready` or `failed`.

**Response (JSON):**
```json
{
  "session_id": "uuid-string",
  "status": "processing",
  "page_count": null,
  "parser_used": null,
  "language": null,
  "is_scanned": null,
  "likely_has_tables": null,
  "parsing_quality": null,
  "text_preview": null,
  "error": null
}
```

All metadata fields are `null` when `status` is `processing`. When `status` is `ready`, all fields are populated. When `status` is `failed`, `error` contains a human-readable failure reason and all other metadata fields are `null`.

**Error handling:** Return HTTP 404 if `session_id` is not found or has expired.

---

### `POST /chat`

Phase B entry point. Returns a streaming SSE response.

**Request (JSON):**
```json
{
  "session_id": "uuid-string",
  "prompt": "Summarize the key financial highlights"
}
```

**Processing sequence (all async):**
1. Retrieve session — return HTTP 404 with `{"error": "Session not found or expired"}` if missing
2. Call `sync_prompt_with_tokens(prompt, session_id)` — get synchronized prompt
3. Call Intent Router with synchronized prompt + metadata packet
4. Select and call the correct processing module
5. Re-hydrate the result — swap tokens back to real values
6. Stream result via SSE

**Response headers:**
```
Content-Type: text/event-stream
Cache-Control: no-cache
X-Accel-Buffering: no
```

**SSE event format:**

Token events (one per token or small chunk):
```
data: {"type": "token", "content": "The company reported..."}

```

Final event (always sent, even on error):
```
data: {"type": "done", "intent": "summarization", "confidence": 0.91, "parser_used": "llamaparse", "flags": []}

```

Error event:
```
data: {"type": "error", "message": "Session not found or expired"}

```

Note: Each SSE event must be followed by a blank line (`\n\n`) as per the SSE spec.

---

### `GET /health`

Returns HTTP 200 with `{"status": "ok"}`. No auth. Used to confirm the server is running.

---

### Session State Structure

```python
SESSIONS = {}  # Global in-memory dictionary

SESSIONS[session_id] = {
    "metadata": {
        "page_count": int,
        "likely_has_tables": bool,
        "is_scanned": bool,
        "language": str,
        "parser_used": str,       # "simple" | "llamaparse" | "docling" | "pymupdf_fallback"
        "text_preview": str,
        "parsing_quality": str    # "normal" | "degraded"
    },
    "scrubbed_text": str,
    "token_map": {
        "{{NAME_1}}": "IEKRAM HOSSAIN",
        "{{ACCOUNT_1}}": "9876543210",
        "{{PAN_1}}": "ABCDE1234F"
    },
    "expires_at": datetime
}
```

Check expiry on every `/chat` request. Run a background cleanup task every 5 minutes to evict expired sessions.

---

## 6. Frontend Specification

React 18 + Vite. Two distinct views managed by a single `view` state variable in `App.jsx` — no React Router. Dark theme throughout. Font: **Inter** (Google Fonts).

---

### Design System

**Colors:**
- Background: `#080808`
- Surface / card: `#111111`
- Border: `#1e1e1e`
- Border dashed (upload zone): `#2e2e2e`
- Text primary: `#FFFFFF`
- Text secondary: `#888888`
- Hover overlay: `rgba(255,255,255,0.05)`

**Typography:** Inter. Weights: 400 (body), 500 (labels), 700 (titles, button text).

**Radius:** `16px` for cards and panels. `10px` for inputs and buttons.

**Transitions:** `150ms ease` on all interactive states.

---

### View 1 — Landing Page

The first visible view on load. Full-viewport dark background. Content centered, max-width 600px.

**Layout:**

```
┌──────────────────────────────────────────────────────────┐
│                                                          │
│         FDIP                           [bold, white]     │
│         Financial Document Intelligence Pipeline         │
│                                                          │
│  ┌───────────────────────────────────────────────────┐   │
│  │                                                   │   │
│  │  ┌ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┐  │   │
│  │  │  ↑  Drop PDF or image here                │  │   │
│  │  │     or click to browse                    │  │   │
│  │  │     PDF · PNG · JPG · JPEG                │  │   │
│  │  └ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┘  │   │
│  │  [filename.pdf  ✕]  ← shown after selection      │   │
│  │                                                   │   │
│  │  ┌─────────────────────────────────────────────┐  │   │
│  │  │  Ask something about this document...       │  │   │
│  │  │                                             │  │   │
│  │  └─────────────────────────────────────────────┘  │   │
│  │                                                   │   │
│  │  [status text: "Parsing document..."]             │   │
│  │                         [ Analyse ▷ ]             │   │
│  └───────────────────────────────────────────────────┘   │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

**File is optional.** Users may submit a text-only prompt with no file. The Analyse button is active as long as a prompt is entered, regardless of whether a file is attached.

**Submit behaviour:**
1. Disable Analyse button. Show inline spinner inside button text.
2. If file is present:
   - Call `POST /upload` → receive `{session_id, status: "processing"}` immediately
   - Start `usePolling` hook: poll `GET /status/{session_id}` every 1.5 seconds
   - Show cycling status text below the card (time-based, not wired to actual backend state):
     - 0–3s: "Uploading document..."
     - 3–8s: "Parsing document..."
     - 8–15s: "Running PII scrubber..."
     - 15s+: "Almost ready..."
   - On `status: "ready"` → clear polling, transition to ResultsView
   - On `status: "failed"` → show error reason inside the card, restore Analyse button
3. If text-only (no file): skip upload and polling entirely, go directly to ResultsView

---

### View 2 — Results Page

Replaces the landing page entirely (same-page state swap, no URL change). A `← New query` back button top-left resets all state and returns to the landing view.

**Conditional layout:**

**With file (PDF or image):**
```
┌──────────────────────────┬────────────────────────────────┐
│                          │                                │
│   FILE PREVIEW (50%)     │   QUERY & RESPONSE (50%)       │
│                          │                                │
│  PDF → react-pdf-viewer  │  [User prompt, styled block]   │
│  Image → <img>           │                                │
│  scrollable              │  [Streaming response bubble]   │
│                          │  [Metadata footer]             │
│                          │                                │
│                          │  [Next prompt input + Send]    │
│                          │                                │
└──────────────────────────┴────────────────────────────────┘
```

**Text-only (no file):**
```
┌────────────────────────────────────────────────────────────┐
│                                                            │
│   QUERY & RESPONSE  (full width, max-width 800px, centred) │
│                                                            │
│   [User prompt]                                            │
│   [Streaming response bubble]                              │
│   [Metadata footer]                                        │
│   [Next prompt input + Send]                               │
│                                                            │
└────────────────────────────────────────────────────────────┘
```

**Streaming behaviour:** On prompt submission, add user message to list, add empty assistant bubble with blinking cursor, call `POST /chat`, open SSE stream. Token events append to the bubble in real time. `done` event renders the metadata footer and re-enables the input.

**Metadata footer** (small secondary-colour text below each response):
```
Intent: summarization · Confidence: 91% · Parser: llamaparse
```

With flags:
```
Intent: extraction · Confidence: 74% · Parser: docling · ⚠ Low confidence
```

**Extraction results** render as an `ExtractionCard` — surface-colour background, two-column layout, field names left, values right. Fields with null or empty values are omitted. Card header shows detected document type.

**Multi-turn:** The right panel supports additional prompts after the first response. The input bar is always visible at the bottom of the right panel. Each prompt → response pair appends to the message list.

---

### Error States

- Upload fails → error message inside the landing card, allow retry without page reload
- Parsing fails (`status: "failed"`) → backend reason shown inside card, allow retry
- Session expired (404 from `/chat`) → transition back to landing with "Session expired — please upload again"
- SSE error event → error message appears inside the response bubble
- Network failure during streaming → "Connection lost — try again" with retry button

---

### State Management

`useState` and `useRef` only. No Redux, no Zustand, no React Query.

Key state in `App.jsx`:
- `view` — `"landing"` | `"results"`
- `sessionId` — string or null
- `uploadedFile` — File object or null (drives split-screen vs full-screen and file preview)
- `initialPrompt` — string (the prompt submitted from the landing page)
- `messages` — array of `{role, content, metadata, isCard}` objects
- `isUploading` — boolean
- `uploadStatus` — `"idle"` | `"uploading"` | `"processing"` | `"ready"` | `"failed"`
- `isStreaming` — boolean

The polling interval ref must be cleared on every view transition and on unmount. The fetch stream reader ref must be cancelled before each new submission and on unmount.

---

### SSE Client Implementation

Use `fetch` with `ReadableStream`. Do not use the native `EventSource` API — it only supports GET requests.

Implementation pattern:
```javascript
const response = await fetch('/chat', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ session_id, prompt })
})
const reader = response.body.getReader()
const decoder = new TextDecoder()

while (true) {
  const { done, value } = await reader.read()
  if (done) break
  const chunk = decoder.decode(value)
  // Split on \n\n, extract data: fields, JSON.parse each
}
```

Parse each chunk by splitting on `\n\n`, extracting the `data:` field from each segment, and JSON-parsing the result. Handle `type: token`, `type: done`, and `type: error` explicitly. Ignore unknown event types. Buffer incomplete events across chunk boundaries — do not assume a network packet aligns with an SSE event boundary.

Implement in `hooks/useSSEStream.js` as a reusable hook that accepts a callback per event type.

Add `hooks/usePolling.js` — accepts `(sessionId, intervalMs, onUpdate, onComplete)`, polls `GET /status/{session_id}` at the given interval, calls `onComplete` (with the final status payload) when status is `ready` or `failed`, then clears the interval.

---

## 7. Folder Structure

Create this exact structure before writing any code. Do not deviate.

```
fdip/
├── backend/
│   ├── main.py                    # FastAPI app, route definitions only
│   ├── config.py                  # Named constants, thresholds, env var loading
│   ├── session.py                 # SESSIONS dict, get/set/expire/cleanup logic
│   ├── utils/
│   │   ├── __init__.py
│   │   ├── scout.py               # PyMuPDF full-document scout
│   │   ├── parser_factory.py      # Parser routing + LlamaParse/Docling/PyMuPDF cascade
│   │   ├── pii.py                 # PII scrubber + sync_prompt_with_tokens
│   │   └── metadata.py            # MVP metadata packet assembly
│   ├── modules/
│   │   ├── __init__.py
│   │   ├── router.py              # Intent router (instructor + Groq 8B)
│   │   ├── summarizer.py          # Summarization module (Groq 70B)
│   │   ├── extractor.py           # Extraction module (Groq 70B + Pydantic schema)
│   │   └── classifier.py          # Classification module (Groq 8B)
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── routing.py             # RoutingDecision Pydantic model
│   │   ├── extraction.py          # FinancialStatementSchema Pydantic model
│   │   └── classification.py      # ClassificationResult Pydantic model
│   ├── requirements.txt           # Pinned versions
│   └── .env.example               # All required env var keys, no values
├── frontend/
│   ├── src/
│   │   ├── App.jsx                # Root — manages view state (landing / results)
│   │   ├── views/
│   │   │   ├── LandingView.jsx    # Upload + prompt input + submit + polling status
│   │   │   └── ResultsView.jsx    # Conditional split-screen or full-screen results
│   │   ├── components/
│   │   │   ├── UploadArea.jsx     # Drag-and-drop file input (PDF + image)
│   │   │   ├── PromptInput.jsx    # Textarea for prompt entry
│   │   │   ├── FilePreview.jsx    # react-pdf-viewer (PDF) or <img> (image)
│   │   │   ├── MessageBubble.jsx  # Text response bubble with metadata footer
│   │   │   └── ExtractionCard.jsx # Structured card for extraction results
│   │   ├── hooks/
│   │   │   ├── useSSEStream.js    # fetch + ReadableStream SSE hook
│   │   │   └── usePolling.js      # Polls /status/{session_id} until ready or failed
│   │   └── api/
│   │       └── client.js          # upload(), getStatus(), chat() API functions
│   ├── package.json
│   └── index.html
├── eval/                          # Phase B only — do not create during MVP
├── .gitignore                     # Excludes .env, __pycache__, node_modules, uploads/
└── README.md
```

---

## 8. Implementation Checkpoints

Each checkpoint must be fully complete and manually verified against its gate condition before starting the next. Never work on two checkpoints simultaneously.

---

**Checkpoint 1 — Project Skeleton**

Create the complete folder structure. Create all `__init__.py` files. Create `config.py` with placeholder constants. Create `.env.example`. Create `requirements.txt`. Create `main.py` with a FastAPI app that serves only `GET /health`. Start the server and verify it responds.

*Gate: `curl http://localhost:8000/health` returns `{"status": "ok"}` with HTTP 200.*

---

**Checkpoint 2 — PyMuPDF Scout**

Implement `scout.py`. The `run_scout(filepath: str) -> dict` function scans the full document and returns all metadata fields. Run it against Document4.pdf and Document5.pdf. Print the raw values for `drawing_count`, `block_count`, and `avg_chars_per_block` for both. Use these numbers to set thresholds in `config.py`. Add a comment next to each threshold explaining which document produced the calibration value.

*Gate: `run_scout("Document4.pdf")` returns a complete dict. `likely_has_tables` is True for Document4. Thresholds in config.py have calibration comments.*

---

**Checkpoint 3 — Parser Factory**

Implement `parser_factory.py`. The `parse_document(filepath: str, scout_result: dict) -> dict` function returns `{parsed_text, parser_used, parsing_quality}`. Test all three paths: simple PDF (text only), complex PDF (HUL annual report via LlamaParse), and simulated LlamaParse failure (trigger Docling). Verify LlamaParse output is markdown with table structure preserved. Verify Docling produces markdown when LlamaParse is forced to fail.

*Gate: HUL report produces LlamaParse markdown with tables intact. A text-only PDF uses PyMuPDF. Forcing LlamaParse to fail triggers Docling without raising an exception.*

---

**Checkpoint 4 — PII Scrubber and Prompt Synchronizer**

Implement `pii.py` with two functions:

`scrub_document(text: str) -> dict` returns `{scrubbed_text, token_map}`.

`sync_prompt_with_tokens(prompt: str, session_id: str) -> str` iterates the session token map and replaces matching real values with their tokens.

Test with a synthetic document containing a PAN number, an Aadhaar number, and a person's name. Verify scrubbing produces correct tokens and the map is populated. Test `sync_prompt_with_tokens` with a prompt containing a known real value from the map — verify substitution. Test with an unknown name — verify generic token is applied and the session map is unchanged.

*Gate: Document with "PAN: ABCDE1234F" becomes "PAN: {{PAN_1}}" with `{"{{PAN_1}}": "ABCDE1234F"}` in the map. Prompt with known real value is correctly synchronized. Prompt with unknown name gets `{{UNKNOWN_NAME_1}}`.*

---

**Checkpoint 5 — Session State and POST /upload**

Implement `session.py` with `create_session`, `get_session`, `is_expired`, and `cleanup_expired` functions. Wire up `POST /upload` in `main.py` calling the full Phase A sequence: scout → parser factory → PII scrubber → metadata assembly → session store → return response. Test by uploading Document4.pdf. Verify the session ID is in memory. Verify scrubbed text and token map are stored. Verify the JSON response contains all 7 expected fields.

*Gate: `POST /upload` with Document4.pdf returns `{session_id, status: "processing"}` in under 500ms. Polling `GET /status/{session_id}` transitions from `processing` → `ready` with `page_count` matching actual Document4 page count, `parser_used: llamaparse`, `likely_has_tables: true`. Session exists in memory with scrubbed text and token map populated.*

---

**Checkpoint 6 — Pydantic Schemas**

Implement all three schemas in `schemas/`: `RoutingDecision`, `FinancialStatementSchema`, `ClassificationResult`. Test each standalone by instantiating with valid data and invalid data. Verify valid data instantiates cleanly and invalid data raises `ValidationError`. Do not implement modules yet.

*Gate: All three schemas instantiate with valid test data. All three raise `ValidationError` on invalid input.*

---

**Checkpoint 7 — Intent Router**

Implement `router.py`. The `route(prompt: str, metadata: dict) -> RoutingDecision` async function calls Groq 8B via instructor and returns a validated `RoutingDecision`. System prompt includes four few-shot examples. Test manually with five prompts covering all three intents and one ambiguous case. Verify instructor retries on malformed LLM output.

*Gate: Five test prompts all return valid `RoutingDecision` objects. The ambiguous prompt returns lower confidence than the clear ones. `reasoning` field is a meaningful one-sentence explanation.*

---

**Checkpoint 8 — Processing Modules**

Implement `summarizer.py`, `extractor.py`, `classifier.py` as independent async functions. Test each module in isolation using a sample scrubbed text and a prompt. Verify the extractor returns a populated `FinancialStatementSchema`. Verify the summarizer returns coherent narrative text. Verify the classifier returns a valid `ClassificationResult` with a recognized document type.

*Gate: Each module tested independently returns a valid result against the HUL annual report scrubbed text.*

---

**Checkpoint 9 — POST /chat with SSE Streaming**

Wire up `POST /chat` in `main.py`. Full sequence: retrieve session → sync prompt → route → execute module → re-hydrate → stream. Use `StreamingResponse` with `text/event-stream`. Test via curl:

```bash
curl -N -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"session_id": "YOUR_ID", "prompt": "summarize this document"}'
```

Verify tokens stream one by one. Verify the `done` event arrives last with correct metadata. Verify re-hydration: if the document contained a real name that was tokenized, the streamed response should show the real name.

*Gate: Full end-to-end pipeline from curl. Tokens stream visibly. `done` event contains correct intent and confidence. Re-hydrated response contains real values not tokens.*

---

**Checkpoint 10 — Frontend Skeleton and PDF Viewer**

Scaffold the React app with Vite. Create the split-screen layout in `App.jsx`. Implement `PDFViewer.jsx` using react-pdf-viewer. Implement `UploadArea.jsx` with drag-and-drop. Implement `api/client.js` with `upload(file)` and `chat(sessionId, prompt)` functions. Verify the layout renders in browser. Verify a test PDF displays in the left panel.

*Gate: App loads in browser. Left panel shows the PDF viewer. Right panel shows the upload area. Dragging a PDF onto the upload area renders it in the left panel.*

---

**Checkpoint 11 — SSE Stream Hook and Full Chat UI**

Implement `useSSEStream.js` using fetch + ReadableStream. Implement `ChatPanel.jsx` with message list and input bar. Implement `MessageBubble.jsx` with metadata footer. Implement `ExtractionCard.jsx` for structured extraction results. Wire all components: submitting a prompt adds the user message, opens the SSE stream, tokens append to the assistant bubble in real time, `done` event renders the metadata footer.

*Gate: Full demo working in browser. Upload a PDF, type "summarize this", watch tokens appear word by word. Metadata footer shows intent and confidence. Typing "extract financial figures" produces a structured card, not a text bubble.*

---

**Checkpoint 12 — MVP Complete**

Full end-to-end verification of all three intents against Document4.pdf. Verify PII synchronization: include a real name from the document in a prompt and verify the response is accurate and re-hydrated. Verify error handling: expired session returns correct error, unsupported file type returns 415, empty prompt is handled gracefully. Verify the frontend handles all error states without crashing.

*Gate: All three intents work correctly. PII synchronization end-to-end works. All error states handled gracefully. No unhandled exceptions in backend logs. Demo-ready.*

---

## 9. Processing Module Output Schemas

**RoutingDecision (MVP Router Output)**

- `intent`: Literal["extraction", "summarization", "classification"]
- `confidence`: float 0–1
- `reasoning`: str (one sentence)

**FinancialStatementSchema (Extractor Output)**

- `document_type`: str
- `date_range`: str
- `revenue`: Optional[str]
- `net_profit`: Optional[str]
- `total_assets`: Optional[str]
- `total_liabilities`: Optional[str]
- `key_line_items`: List[dict]
- `flagged_anomalies`: List[str]
- `extraction_confidence`: float

**ClassificationResult (Classifier Output)**

- `document_type`: Literal["annual_report", "audit_report", "balance_sheet", "invoice", "bank_statement", "legal_agreement", "other"]
- `confidence`: float
- `key_signals`: List[str]

---

## 10. Rules for the Coding Agent

1. **Follow checkpoints in order.** Gate conditions must pass before proceeding. No parallel checkpoint development.

2. **Never send unscrubbed text or prompts to a cloud API.** The PII scrubber targets three patterns: Aadhaar (`\b\d{4}\s?\d{4}\s?\d{4}\b`), PAN (`\b[A-Z]{5}\d{4}[A-Z]{1}\b`), and Phone (`\b(?:\+91|91|0)?[6-9]\d{9}\b`). `scrub_document` runs on parsed text at ingestion. `sync_prompt_with_tokens` runs on every prompt before routing. Both are non-negotiable.

3. **Use instructor for all LLM output.** No manual JSON parsing. No `json.loads` on LLM responses anywhere in the codebase.

4. **Async-first throughout.** All network calls must be `await`ed. CPU-bound operations that block for more than 100ms must use `loop.run_in_executor` with a `ThreadPoolExecutor`.

5. **No LangChain. No LangGraph.** asyncio handles concurrency. instructor handles structured output. FastAPI handles streaming.

6. **Parser outputs must not be mixed.** Once the parser factory selects a parser for a document, all downstream processing uses that output exclusively.

7. **All thresholds are named constants in config.py.** No magic numbers in logic. Every constant has a comment citing the empirical measurement that justifies it.

8. **MVP scope is locked.** Hard rules, confidence calibration, map-reduce, evaluation harness, and LangSmith are Phase B. Do not build them during the MVP.

9. **Session state is in-memory only.** Global dictionary with 30-minute expiry. Redis is a Phase B production upgrade noted in the README.

10. **Test each checkpoint manually against its gate condition before moving on.** A checkpoint is not done until its gate passes.

---

## 11. Path to Production (Phase B and Beyond)

**Phase B — Intelligence Upgrades**

- Hard rules check before routing (page_count override, language flag, quality penalty)
- Confidence calibration using extended metadata fields
- Map-reduce summarization for documents exceeding 80k tokens
- Fallback intent routing on low confidence
- Extended metadata packet (estimated_tokens, doc_structure_type, avg_chars_per_block, block_count)
- Evaluation harness (`eval/router_eval.py`) with 15 test cases including adversarial prompts, results in README
- LangSmith tracing on all LLM calls
- `/metrics` endpoint for aggregate routing stats
- structlog with trace IDs on every log entry

**Production Infrastructure**

- **Sovereign Compute:** Replace LlamaParse with Docling on internal GPUs. Replace Groq with self-hosted vLLM. Zero data egress — required for BFSI clients with data residency mandates.
- **Task Queue:** Move LlamaParse calls to Celery/Redis workers. Prevents upload timeouts on large documents and enables horizontal scaling.
- **Expanded PII Detection:** Add NER-based named person detection (spaCy `en_core_web_trf` or fine-tuned IndoBERT for Indian names). Extend regex coverage to bank account numbers (9–18 digit sequences), IFSC codes (`[A-Z]{4}0[A-Z0-9]{6}`), and email addresses. Replace in-memory token maps with an encrypted vault service for auditability and cross-session persistence.
- **Audit Trail:** Persist all routing decisions and reasoning fields to a database. Required for AI decision auditability in regulated financial environments.
- **Continuous Evaluation:** Router accuracy measured on every deployment. CI pipeline fails if accuracy drops below threshold.

---
