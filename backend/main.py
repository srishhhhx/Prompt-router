"""
main.py — FastAPI application: route definitions only.

Phase 1 endpoints:
    GET  /health
    POST /upload          → 202 immediately; Phase A runs as BackgroundTask
    GET  /status/{sid}    → polling endpoint

Phase 2 adds:
    POST /chat            → SSE streaming response
"""

import asyncio
import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, UploadFile, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config import SUPPORTED_MIME_TYPES, MAX_UPLOAD_BYTES
from session import (
    create_session,
    get_session,
    update_session_ready,
    update_session_failed,
    cleanup_expired_sessions,
)
from utils.scout import run_scout
from utils.parser_factory import parse_document
from utils.pii import scrub_document
from utils.metadata import assemble_metadata

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
        # Images go straight to PyMuPDF scout via a workaround: skip parsing
        # for pure images — wrap as single-page PDF if needed (Phase B).
        # For MVP, treat image uploads as unsupported in the pipeline gracefully.
        if content_type in ("image/png", "image/jpeg", "image/jpg"):
            # Image: no text to parse in Phase 1 — store placeholder
            update_session_ready(
                session_id,
                metadata={
                    "page_count": 1,
                    "likely_has_tables": False,
                    "is_scanned": True,
                    "language": "unknown",
                    "parser_used": "image_passthrough",
                    "text_preview": "[Image document — no text extracted in MVP]",
                    "parsing_quality": "degraded",
                },
                scrubbed_text="[Image document — no text extracted in MVP]",
                token_map={},
            )
            return

        # Step 1: Scout
        logger.info("[%s] Phase A step 1: PyMuPDF Scout", session_id)
        scout_result = run_scout(file_bytes, filename=filename)

        # Step 2+3: Parser routing + execution
        logger.info("[%s] Phase A step 2-3: Parser factory", session_id)
        parser_result = await parse_document(file_bytes, scout_result, filename=filename)

        # Step 4: PII scrubbing
        logger.info("[%s] Phase A step 4: PII scrubber", session_id)
        scrub_result = scrub_document(parser_result["parsed_text"])

        # Step 5: Metadata assembly
        metadata = assemble_metadata(scout_result, parser_result)

        # Step 6: Mark session ready
        update_session_ready(
            session_id,
            metadata=metadata,
            scrubbed_text=scrub_result["scrubbed_text"],
            token_map=scrub_result["token_map"],
        )
        logger.info("[%s] Phase A complete — session ready", session_id)

    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        logger.exception("[%s] Phase A failed: %s", session_id, error_msg)
        update_session_failed(session_id, error=error_msg)
