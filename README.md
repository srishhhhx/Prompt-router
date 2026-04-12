# Financial Document Intelligence Pipeline

## Table of Contents
- [Financial Document Intelligence Pipeline](#financial-document-intelligence-pipeline)
  - [Table of Contents](#table-of-contents)
  - [1. Introduction](#1-introduction)
  - [2. Demo Video](#2-demo-video)
  - [3. Architecture](#3-architecture)
  - [4. Design Decisions](#4-design-decisions)
    - [Prompt Routing Strategy](#prompt-routing-strategy)
    - [System Design](#system-design)
  - [5. Evaluation \& Observability](#5-evaluation--observability)
    - [Evaluation Suite](#evaluation-suite)
    - [Observability](#observability)
  - [6. API Endpoints](#6-api-endpoints)
  - [7. Tech Stack](#7-tech-stack)
  - [8. Project Structure](#8-project-structure)
  - [9. Setup](#9-setup)
    - [Prerequisites](#prerequisites)
    - [Step 1: Clone \& Setup](#step-1-clone--setup)
    - [Step 2: Backend Setup](#step-2-backend-setup)
    - [Step 3: Frontend Setup](#step-3-frontend-setup)
    - [Step 4: Run the Application](#step-4-run-the-application)
  - [10. Path to Production](#10-path-to-production)


## 1. Introduction

A full-stack **prompt routing** system that accepts user prompts alongside financial documents, **identifies the intent** from the prompt, and **routes the request to the appropriate processing module** — extraction, summarization, or classification — streaming results in real time.

Built with **React** and **FastAPI**, the core of the system is an **intent-aware router** powered by a Groq-hosted Llama 3.1-8B model with structured Pydantic output. The router analyzes each prompt against document metadata (page count, layout complexity, document type) to produce a routing decision with confidence scoring, before delegating to the matched specialized module.

The pipeline further includes automatic PII tokenization and rehydration, adaptive document parsing, and LangSmith-based observability.


## 2. Demo Video

[Demo video](https://github.com/user-attachments/assets/45843d45-7b2d-4068-bdaf-8ad777be2961)


## 3. Architecture

![Architecture Diagram](./assets/Architecture.png)

**Pipeline Flow:**

1. **Upload & Scout** — Document is uploaded via `/upload`. PyMuPDF Scout performs a fast structural analysis (page count, drawing density, block statistics) to determine parsing complexity.

2. **Adaptive Parsing** — Based on Scout signals, the parser factory routes to either PyMuPDF (simple text PDFs) or LlamaParse REST API (complex layouts, tables, scanned documents).

3. **PII Scrubbing** — Regex-based scrubber detects PAN, IFSC, and GSTIN patterns, replaces them with reversible tokens (`{{PAN_1}}`, `{{IFSC_2}}`), and stores the token map in the session.

4. **Prompt Routing (Core)** — The heart of the system. Each user prompt is analyzed alongside document metadata (page count, `doc_type_hint`, `likely_has_tables`) by a Groq-hosted **Llama 3.1-8B** model. The router uses few-shot examples and strict intent definitions to classify into `extraction`, `summarization`, or `classification`, returning a structured `RoutingDecision` (intent, confidence score, reasoning) validated via **Instructor + Pydantic**. This ensures every downstream module receives only the queries it is optimized for.

5. **Module Execution** — The matched module (Extractor, Summarizer, or Classifier) streams its response via SSE, with Cerebras as primary provider and Groq as automatic fallback.

6. **PII Rehydration** — Before tokens reach the user, the response is rehydrated — `{{PAN_1}}` is replaced back with the real value.


## 4. Design Decisions

### Prompt Routing Strategy

* **Intent Router as the Central Gatekeeper:** Rather than sending every query through a single general-purpose prompt, a lightweight **8B model classifies intent first**. This keeps extraction prompts sharp (no summary preamble) and summarization prompts broad (no field-hunting), improving output quality for both tasks.

* **Metadata-Augmented Routing:** The router doesn't classify prompts in isolation — it receives document signals (`page_count`, `likely_has_tables`, `doc_type_hint`, `text_preview`) alongside the prompt. This context helps disambiguate edge cases like *"show me the transactions"* (extraction on a bank statement vs. summarization on a narrative report).

* **Structured Routing Output:** Every routing decision is enforced through an `instructor`-wrapped Pydantic schema (`RoutingDecision`), guaranteeing a valid `intent`, numeric `confidence`, and human-readable `reasoning` string — no fragile regex parsing of freeform LLM text.

### System Design

* **Multi-Provider LLM Fallback:** Cerebras is the primary generation provider for extraction and summarization. If it returns a 429, the system automatically falls back to Groq — ensuring the pipeline never hard-fails on a single provider outage.

* **PII Tokenization over Redaction:** Instead of permanently stripping sensitive data, we replace PII with reversible tokens (`{{PAN_1}}`). The LLM can reference the token in its response, and rehydration restores the real value before the user sees it — keeping sensitive data out of third-party LLM APIs without breaking answer correctness.

* **Head-Tail Truncation with Snap:** For documents exceeding the context window, a 60/40 head-tail split preserves the opening (company name, report title) and closing sections (signatures, totals). Sentence-boundary snapping prevents mid-word cuts, and a gap marker explicitly tells the LLM that content was omitted.

* **PyMuPDF Scout → Parser Routing:** A zero-cost structural pre-scan (drawing count, average chars per block, image count) determines whether a document needs the simple PyMuPDF path or the heavier LlamaParse API — avoiding unnecessary API calls for clean digital PDFs.


## 5. Evaluation & Observability

### Evaluation Suite

The project includes a custom evaluation framework (`backend/eval/`) that benchmarks four metrics across six diverse financial documents:

| Metric | What It Measures | Target |
|---|---|---|
| **Intent Routing Accuracy** | Correct classification of prompts into extraction / summarization / classification | ≥ 95% |
| **PII Safety Score** | Scrub recall (were all PII tokens caught?) + Rehydration success (were they restored correctly?) | 100% |
| **Extraction Fidelity** | Exact and fuzzy numeric match between extracted values and ground truth | ≥ 90% |
| **Pipeline Latency** | Time-to-first-token (TTFT) and end-to-end response time | TTFT < 800ms |

**Fast Evaluation Mode:** Pre-parsed LlamaParse markdown files are injected directly via `/internal/inject-session`, bypassing the upload and parsing phases entirely. This enables rapid iteration on prompt tuning and routing logic without incurring LlamaParse API costs or wait times.

### Observability

**LangSmith** is integrated across all four LLM modules (Router, Extractor, Summarizer, Classifier) using `@traceable` decorators. When enabled, every LLM call is logged to the LangSmith dashboard with:
- Full input prompts and raw outputs
- Token usage and latency waterfall
- Session-grouped traces for end-to-end request debugging


## 6. API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Health check. Returns `{"status": "ok"}`. |
| `POST` | `/upload` | Accepts a PDF or image file. Returns `session_id` with status `processing` (202). Phase A runs asynchronously. |
| `GET` | `/status/{session_id}` | Poll for document processing status. Returns `processing`, `ready`, or `failed` with metadata. |
| `POST` | `/session` | Creates a text-only session (no document). Returns an immediately-ready `session_id`. |
| `POST` | `/chat` | Main query endpoint. Accepts `{session_id, prompt}`. Returns an SSE stream of token events and a terminal `done` event with routing metadata. |
| `POST` | `/internal/inject-session` | Eval-only. Injects pre-parsed markdown directly, bypassing Scout and the parser cascade. |


## 7. Tech Stack

* **Frontend:** React 19, Vite, Vanilla CSS, React-Markdown, Remark-GFM
* **Backend:** Python 3.9+, FastAPI, Uvicorn
* **LLMs:**
    * Intent Routing: Groq (Llama 3.1-8B via `instructor`)
    * Extraction & Summarization: Cerebras (Qwen 3-235B) with Groq (Llama 3.3-70B) fallback
    * Classification: Groq (Llama 3.3-70B) with Cerebras fallback
* **Document Parsing:** PyMuPDF (structural scout + simple extraction), LlamaParse (complex layouts & tables) with Docling as fallback
* **PII:** Regex-based scrubber for PAN, IFSC, GSTIN with reversible tokenization
* **Structured Output:** Pydantic + Instructor
* **Observability:** LangSmith (`@traceable` decorators)
* **Evaluation:** Custom async evaluation runner with ground-truth fixture files


## 8. Project Structure
```
Prompt-routing/
├── frontend/                        # React Frontend (Vite)
│   ├── src/
│   │   ├── views/                   # LandingView, ResultsView
│   │   ├── components/              # UploadArea, MessageBubble, FilePreview
│   │   ├── hooks/                   # usePolling, useSSEStream
│   │   └── App.jsx
│   └── package.json
├── backend/                         # FastAPI Backend
│   ├── modules/                     # LLM Modules
│   │   ├── router.py                # Intent classification (Groq 8B)
│   │   ├── extractor.py             # Data extraction (Cerebras → Groq fallback)
│   │   ├── summarizer.py            # Document summarization (Cerebras → Groq)
│   │   └── classifier.py            # Document type classification (Groq → Cerebras)
│   ├── utils/                       # Core Utilities
│   │   ├── scout.py                 # PyMuPDF structural pre-scan
│   │   ├── parser_factory.py        # Adaptive parser routing
│   │   ├── pii.py                   # PII scrubbing & rehydration
│   │   ├── truncation.py            # Context window management
│   │   └── metadata.py              # Metadata assembly
│   ├── schemas/                     # Pydantic response schemas
│   ├── eval/                        # Evaluation Suite
│   │   ├── fixtures/                # Ground truth JSON
│   │   ├── metrics/                 # Routing, PII, fidelity, latency metrics
│   │   ├── run_eval_fast.py         # Fast eval runner (pre-parsed injection)
│   │   └── api_client.py            # SSE client for eval
│   ├── main.py                      # FastAPI app & route definitions
│   ├── session.py                   # In-memory session store
│   └── config.py                    # All thresholds, models, and env loading
├── parser_tests/                    # Parser comparison outputs
├── start_backend.sh                 # Backend launch script
└── .env                             # API keys (not committed)
```


## 9. Setup

### Prerequisites
* Python 3.9+
* Node.js 18+
* API keys: `GROQ_API_KEY`, `LLAMA_CLOUD_API_KEY`, `CEREBRAS_API_KEY`
* (Optional) `LANGCHAIN_API_KEY` for LangSmith observability

### Step 1: Clone & Setup
```bash
git clone <your-repo-link>
cd Prompt-routing
```

### Step 2: Backend Setup
```bash
cd backend
python3 -m venv venv
source venv/bin/activate

pip install -r requirements.txt
```

Create a `.env` file in `/backend`:
```env
GROQ_API_KEY=your_groq_key
LLAMA_CLOUD_API_KEY=your_llamaparse_key
CEREBRAS_API_KEY=your_cerebras_key

# Optional: LangSmith observability
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=your_langsmith_key
LANGCHAIN_PROJECT=fdip_pipeline
```

### Step 3: Frontend Setup
```bash
cd frontend
npm install
```

### Step 4: Run the Application
```bash
# Terminal 1: Start Backend (from project root)
./start_backend.sh

# Terminal 2: Start Frontend
cd frontend
npm run dev
```
Access the application at http://localhost:5173.


## 10. Path to Production

* **Parsing:** Replace LlamaParse with a **VLM-based agentic parser** (e.g., **Reducto** or **NVIDIA Nemotron-Parse**) that uses multi-pass layout segmentation and contextual correction — critical for messy, unstructured banking documents where standard OCR consistently fails on nested tables and multi-column layouts.

* **PII Scrubbing:** Migrate from regex patterns to a **dedicated NLP scrubber** (e.g., **Microsoft Presidio** or **spaCy NER pipelines**) to capture a broader range of PII entities — names, addresses, account numbers — with higher recall than hand-tuned regular expressions.

* **Summarization:** Upgrade from single-pass context stuffing to a **MapReduce summarization** strategy, where each document chunk is summarized independently (map) and then merged into a final summary (reduce) — eliminating context window limitations on large documents.

* **Extraction:** Move to a **RAG-based extraction** approach with chunked vector retrieval, so the extractor can locate and pull specific values from any section of a 100+ page document without relying on truncation heuristics.

* **Observability & Reliability:** Add **Prometheus + Grafana** dashboards for real-time latency, token usage, and error-rate monitoring. Replace the in-memory session store with **Redis** for horizontal scalability and crash recovery.
