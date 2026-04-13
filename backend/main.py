"""
main.py — FastAPI application entry point.

Endpoints:
    GET  /health              → liveness check
    POST /upload              → file upload, returns session_id (202)
    GET  /status/{sid}        → poll processing status
    POST /session             → create text-only session
    POST /chat                → SSE streaming response
"""

import asyncio
import json
import logging
import sys
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, UploadFile, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from config import SUPPORTED_MIME_TYPES, MAX_UPLOAD_BYTES
from utils.errors import RateLimitExhausted
from session import (
    create_session,
    get_session,
    update_session_ready,
    update_session_failed,
    cleanup_expired_sessions,
)
from utils.scout import run_scout
from utils.parser_factory import parse_document
from utils.pii import scrub_document, sync_prompt_with_tokens, rehydrate, rehydrate_dict
from utils.metadata import assemble_metadata
from modules.router import route
from modules.summarizer import summarize_stream
from modules.extractor import extract
from modules.classifier import classify


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifespan: start background session cleanup on startup
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(cleanup_expired_sessions())
    logger.info("Session cleanup task started")
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    logger.info("Session cleanup task stopped")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Financial Document Intelligence Pipeline",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# POST /upload  →  202 Accepted immediately
# ---------------------------------------------------------------------------
@app.post("/upload", status_code=202)
async def upload(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
):
    """
    Accepts a PDF or image file. Returns a session_id with status 'processing'
    immediately (< 500ms). Phase A pipeline runs as a background task.
    Poll GET /status/{session_id} to receive the result.
    """
    # ---- Validate file type synchronously before starting anything ----
    content_type = file.content_type or ""
    # Normalise common mismatches
    if file.filename and file.filename.lower().endswith(".pdf"):
        content_type = "application/pdf"

    if content_type not in SUPPORTED_MIME_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type '{content_type}'. "
                   f"Supported: PDF, PNG, JPG, JPEG.",
        )

    file_bytes = await file.read()

    if len(file_bytes) == 0:
        raise HTTPException(status_code=422, detail="Uploaded file is empty.")

    if len(file_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds maximum size of {MAX_UPLOAD_BYTES // (1024*1024)} MB.",
        )

    # ---- Create session immediately ----
    session_id = create_session()
    filename = file.filename or "document"

    # ---- Enqueue Phase A as a background task ----
    background_tasks.add_task(
        _run_phase_a, session_id, file_bytes, filename, content_type
    )

    logger.info("Upload accepted: %s → session %s", filename, session_id)
    return {"session_id": session_id, "status": "processing"}


# ---------------------------------------------------------------------------
# GET /status/{session_id}  →  polling endpoint
# ---------------------------------------------------------------------------
@app.get("/status/{session_id}")
async def status(session_id: str):
    """
    Poll this endpoint every 1.5 seconds after upload.
    Returns status: 'processing' | 'ready' | 'failed'.

    When 'ready', all metadata fields are populated.
    When 'failed', the 'error' field contains the reason.
    """
    session = get_session(session_id)
    if session is None:
        raise HTTPException(
            status_code=404,
            detail="Session not found or expired.",
        )

    meta = session.get("metadata") or {}
    return {
        "session_id":      session_id,
        "status":          session["status"],
        "page_count":      meta.get("page_count"),
        "parser_used":     meta.get("parser_used"),
        "language":        meta.get("language"),
        "is_scanned":      meta.get("is_scanned"),
        "likely_has_tables": meta.get("likely_has_tables"),
        "parsing_quality": meta.get("parsing_quality"),
        "text_preview":    meta.get("text_preview"),
        "error":           session.get("error"),
    }


# ---------------------------------------------------------------------------
# POST /session  →  text-only session (no document uploaded)
# ---------------------------------------------------------------------------
class SessionRequest(BaseModel):
    prompt: str = ""


@app.post("/session", status_code=201)
async def create_text_session(request: SessionRequest = SessionRequest()):
    """
    Creates an immediately-ready session. If a prompt is provided (landing page
    text-only submission), it is scrubbed and stored as the session context.
    """
    session_id = create_session()
    
    # Defaults for empty session
    scrubbed_text = ""
    token_map = {}
    meta = {
        "page_count": 0,
        "likely_has_tables": False,
        "text_preview": "",
        "doc_type_hint": "unknown",
        "estimated_tokens": 0,
        "is_scanned": False,
        "has_complex_layout": False,
        "language": "en",
        "parsing_quality": "normal",
        "parser_used": "none",
        "total_char_count": 0,
        "avg_chars_per_block": 0.0,
        "total_block_count": 0,
        "total_drawing_count": 0,
        "total_image_count": 0,
        "per_page_char_count": [],
    }

    if request.prompt.strip():
        # Treat the initial prompt as the "document" context for text-only sessions
        from config import CHARS_PER_TOKEN, TEXT_PREVIEW_LENGTH
        scrub_res = scrub_document(request.prompt)
        scrubbed_text = scrub_res["scrubbed_text"]
        token_map = scrub_res["token_map"]
        
        meta["total_char_count"] = len(request.prompt)
        meta["estimated_tokens"] = len(request.prompt) // CHARS_PER_TOKEN
        meta["text_preview"] = request.prompt[:TEXT_PREVIEW_LENGTH]
        meta["parser_used"] = "text_input"

    update_session_ready(
        session_id,
        metadata=meta,
        scrubbed_text=scrubbed_text,
        token_map=token_map,
    )
    logger.info("Text-only session created: %s (context_len=%d)", 
                session_id, len(scrubbed_text))
    return {"session_id": session_id, "status": "ready"}


# ---------------------------------------------------------------------------
# POST /chat  →  SSE streaming response (Phase 2)
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    session_id: str
    prompt: str


@app.post("/chat")
async def chat(request: ChatRequest):
    """
    Phase B entry point. Synchronises prompt, routes intent, executes the
    matching module, re-hydrates the response, and streams via SSE.

    Summarization → true streaming (one token event per chunk).
    Extraction    → single JSON token event + done event (is_card=True).
    Classification → single JSON token event + done event (is_card=True).
    """
    session = get_session(request.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found or expired.")
    if session["status"] == "processing":
        raise HTTPException(status_code=409, detail="Document is still being processed. Poll /status first.")
    if session["status"] == "failed":
        raise HTTPException(status_code=422, detail=f"Session failed: {session.get('error')}")

    async def event_generator():
        routing_decision = None
        sid = request.session_id
        try:
            # Step 1: Sync prompt with PII token map
            synced_prompt = sync_prompt_with_tokens(request.prompt, sid)

            # Step 2: Route  (timed)
            t_route = time.perf_counter()
            
            # Enforce Architectural Constraint: Starve the Router
            # Router only receives the 4 specified fields, eliminating noise.
            routing_metadata = {
                "page_count": session["metadata"].get("page_count", 0),
                "likely_has_tables": session["metadata"].get("likely_has_tables", False),
                "text_preview": session["metadata"].get("text_preview", ""),
                "doc_type_hint": session["metadata"].get("doc_type_hint", "unknown"),
            }
            routing_decision = await route(synced_prompt, routing_metadata)
            route_ms = (time.perf_counter() - t_route) * 1000
            logger.info(
                "[%s] Router: %.0f ms | intent=%s confidence=%.2f",
                sid, route_ms, routing_decision.intent, routing_decision.confidence,
            )

            # Step 3: Resolve document text (empty for text-only sessions)
            raw_text = session.get("scrubbed_text") or ""
            doc_text = raw_text if raw_text.strip() else (
                "[No document was uploaded. Answer based on the user's prompt "
                "and general financial knowledge.]"
            )

            intent = routing_decision.intent
            meta   = session["metadata"]

            # Step 4: Execute module (timed per intent)
            t_module = time.perf_counter()

            if intent == "extraction":
                from utils.pii import StreamRehydrator
                stream_rehydrator = StreamRehydrator(sid)
                first_chunk = True
                async for chunk in extract(doc_text, meta, synced_prompt):
                    if first_chunk:
                        ttft_ms = (time.perf_counter() - t_module) * 1000
                        logger.info("[%s] Extractor TTFT: %.0f ms", sid, ttft_ms)
                        first_chunk = False
                    rehydrated_chunk = stream_rehydrator.process(chunk)
                    if rehydrated_chunk:
                        yield f'data: {json.dumps({"type": "token", "content": rehydrated_chunk})}\n\n'

                final_chunk = stream_rehydrator.flush()
                if final_chunk:
                    yield f'data: {json.dumps({"type": "token", "content": final_chunk})}\n\n'

                total_ms = (time.perf_counter() - t_module) * 1000
                logger.info("[%s] Extractor total stream: %.0f ms", sid, total_ms)

            elif intent == "summarization":
                from utils.pii import StreamRehydrator
                stream_rehydrator = StreamRehydrator(sid)
                first_chunk = True
                async for chunk in summarize_stream(doc_text, meta, synced_prompt):
                    if first_chunk:
                        ttft_ms = (time.perf_counter() - t_module) * 1000
                        logger.info("[%s] Summarizer TTFT: %.0f ms", sid, ttft_ms)
                        first_chunk = False
                    rehydrated_chunk = stream_rehydrator.process(chunk)
                    if rehydrated_chunk:
                        yield f'data: {json.dumps({"type": "token", "content": rehydrated_chunk})}\n\n'

                final_chunk = stream_rehydrator.flush()
                if final_chunk:
                    yield f'data: {json.dumps({"type": "token", "content": final_chunk})}\n\n'

                total_ms = (time.perf_counter() - t_module) * 1000
                logger.info("[%s] Summarizer total stream: %.0f ms", sid, total_ms)

            elif intent == "classification":
                result = await classify(doc_text, meta, synced_prompt)
                exec_ms = (time.perf_counter() - t_module) * 1000
                logger.info("[%s] Classifier: %.0f ms | doc_type=%s confidence=%.2f",
                            sid, exec_ms, result.document_type, result.confidence)
                rehydrated = rehydrate_dict(result.model_dump(), sid)
                yield f'data: {json.dumps({"type": "token", "content": json.dumps(rehydrated), "is_card": True})}\n\n'

            # Done event
            flags = []
            if meta.get("parsing_quality") == "degraded":
                flags.append("degraded_parsing")
            if meta.get("is_scanned"):
                flags.append("scanned_document")
            if meta.get("language") not in ("en", "unknown", None):
                flags.append(f"non_english_{meta['language']}")

            yield f'data: {json.dumps({"type": "done", "intent": routing_decision.intent, "confidence": routing_decision.confidence, "reasoning": routing_decision.reasoning, "parser_used": meta.get("parser_used"), "flags": flags})}\n\n'

        except RateLimitExhausted as exc:
            logger.warning("[%s] Pipeline aborted due to rate limit exhaustion: %s", sid, exc)
            yield f'data: {json.dumps({"type": "error", "message": str(exc)})}\n\n'
        except Exception as exc:
            logger.exception("[%s] Chat pipeline error: %s", sid, exc)
            
            # Map ugly pipeline exceptions to user-friendly messages for the frontend UI
            error_message = str(exc)
            error_str_lower = error_message.lower()
            if "status_code: 429" in error_str_lower or "429 rate limit" in error_str_lower:
                error_message = "Our language models are temporarily experiencing high traffic volume. Please wait a moment and try again."
            elif "status_code: 413" in error_str_lower or "request too large" in error_str_lower or "context_length_exceeded" in error_str_lower:
                error_message = "The document payload is too large for the current model processing window. Please try a smaller document."
            elif "status_code: 503" in error_str_lower or "service unavailable" in error_str_lower:
                error_message = "The AI processing server is temporarily unavailable. Please try again later."
            elif "api_key" in error_str_lower:
                error_message = "Authentication error: Missing or invalid API key configuration."

            yield f'data: {json.dumps({"type": "error", "message": error_message})}\n\n'
            if routing_decision:
                yield f'data: {json.dumps({"type": "done", "intent": routing_decision.intent, "confidence": 0.0, "parser_used": session["metadata"].get("parser_used"), "flags": ["error"]})}\n\n'
            else:
                yield f'data: {json.dumps({"type": "done", "intent": "unknown", "confidence": 0.0, "parser_used": None, "flags": ["error"]})}\n\n'

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Phase A pipeline (runs in background)
# ---------------------------------------------------------------------------
async def _run_phase_a(
    session_id: str,
    file_bytes: bytes,
    filename: str,
    content_type: str,
) -> None:
    """
    Full Phase A sequence:
        1. PyMuPDF Scout (full document scan)
        2. Parser routing decision  →  select simple or complex path
        3. Execute selected parser (LlamaParse / Docling / PyMuPDF)
        4. PII scrubber  →  build token map
        5. Metadata packet assembly
        6. Update session to 'ready'

    On any unhandled exception: update session to 'failed' with a reason string.
    """
    try:
        t0 = time.perf_counter()

        # Step 1: Scout
        if content_type in ("image/png", "image/jpeg", "image/jpg"):
            logger.info("[%s] Phase A step 1: Image upload detected — skipping PyMuPDF Scout.", session_id)
            scout_result = {
                "page_count": 1,
                "is_scanned": True,
                "has_complex_layout": True,
                "likely_has_tables": True,
                "doc_type_hint": "unknown",
                "text_preview": "",  # Populated after parsing
                "language": "en",
                "total_char_count": 0,
                "avg_chars_per_block": 0.0,
                "total_block_count": 0,
                "total_drawing_count": 0,
                "total_image_count": 1,
                "per_page_char_count": [0],
                "estimated_tokens": 0,
            }
        else:
            t_scout = time.perf_counter()
            logger.info("[%s] Phase A step 1: PyMuPDF Scout", session_id)
            scout_result = run_scout(file_bytes, filename=filename)
            logger.info("[%s] Scout: %.0f ms", session_id, (time.perf_counter() - t_scout) * 1000)

        # Step 2+3: Parser routing + execution
        t_parse = time.perf_counter()
        logger.info("[%s] Phase A step 2-3: Parser factory", session_id)
        parser_result = await parse_document(file_bytes, scout_result, filename=filename)
        logger.info(
            "[%s] Parsing: %.0f ms | parser=%s quality=%s",
            session_id,
            (time.perf_counter() - t_parse) * 1000,
            parser_result["parser_used"],
            parser_result["parsing_quality"],
        )

        # Backfill scout metadata for images using the parsed text
        if content_type in ("image/png", "image/jpeg", "image/jpg"):
            from config import TEXT_PREVIEW_LENGTH, CHARS_PER_TOKEN
            parsed_len = len(parser_result["parsed_text"])
            scout_result["text_preview"] = parser_result["parsed_text"][:TEXT_PREVIEW_LENGTH]
            scout_result["total_char_count"] = parsed_len
            scout_result["estimated_tokens"] = parsed_len // CHARS_PER_TOKEN
            
        # Step 4: PII scrubbing
        t_pii = time.perf_counter()
        logger.info("[%s] Phase A step 4: PII scrubber (GSTIN, PAN, IFSC)", session_id)
        scrub_result = scrub_document(parser_result["parsed_text"])
        token_map = scrub_result["token_map"]
        logger.info("[%s] PII scrub: %.0f ms | %d token(s) found",
                    session_id, (time.perf_counter() - t_pii) * 1000, len(token_map))
        if token_map:
            pii_display = " | ".join(
                f"{token} → {value}" for token, value in token_map.items()
            )
            logger.info("[%s] [PII] PII map: %s", session_id, pii_display)
        else:
            logger.info("[%s] [PII] PII map: (none detected)", session_id)

        # Step 5: Metadata assembly
        metadata = assemble_metadata(scout_result, parser_result)

        # Step 6: Mark session ready
        update_session_ready(
            session_id,
            metadata=metadata,
            scrubbed_text=scrub_result["scrubbed_text"],
            token_map=token_map,
        )
        total_ms = (time.perf_counter() - t0) * 1000
        logger.info("[%s] Phase A complete — %.0f ms total | parser=%s",
                    session_id, total_ms, parser_result["parser_used"])

    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        logger.exception("[%s] Phase A failed: %s", session_id, error_msg)
        update_session_failed(session_id, error=error_msg)
