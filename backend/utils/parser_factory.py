"""
parser_factory.py — Cascading parser strategy: LlamaParse → Docling → PyMuPDF fallback.

Decision logic (deterministic, no LLM):
  - Simple path:  is_scanned=False AND has_complex_layout=False AND likely_has_tables=False
                  → use PyMuPDF text directly (fast, zero external dependency)
  - Complex path: any signal is True
                  → try LlamaParse via LlamaCloud REST API (markdown, table-preserving)
                  → on failure: try Docling (local)
                  → on failure: use raw PyMuPDF text with parsing_quality=degraded

LlamaParse uses the LlamaCloud REST API directly (httpx) to avoid SDK
version conflicts. Docling weights are loaded lazily only when needed.
"""

import asyncio
import logging
import os
import tempfile
from typing import Optional

import fitz   # PyMuPDF
import httpx

from config import (
    LLAMA_CLOUD_API_KEY,
    PARSING_QUALITY_NORMAL,
    PARSING_QUALITY_DEGRADED,
    PARSER_SIMPLE,
    PARSER_LLAMAPARSE,
    PARSER_DOCLING,
    PARSER_FALLBACK,
)

logger = logging.getLogger(__name__)

# LlamaCloud REST API
_LLAMA_BASE    = "https://api.cloud.llamaindex.ai/api/parsing"
_POLL_INTERVAL = 3.0    # seconds between job status polls
_MAX_WAIT      = 180.0  # seconds before giving up


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def parse_document(file_bytes: bytes, scout_result: dict, filename: str = "document") -> dict:
    """
    Select a parser based on scout signals and return parsed text.

    Returns:
        {
            "parsed_text":     str,
            "parser_used":     str,   # one of the PARSER_* constants
            "parsing_quality": str,   # "normal" | "degraded"
        }
    """
    needs_complex = (
        scout_result["is_scanned"]
        or scout_result["has_complex_layout"]
        or scout_result["likely_has_tables"]
    )

    if not needs_complex:
        logger.info("[%s] Simple path: using PyMuPDF direct extraction", filename)
        text = _extract_pymupdf(file_bytes)
        return {
            "parsed_text": text,
            "parser_used": PARSER_SIMPLE,
            "parsing_quality": PARSING_QUALITY_NORMAL,
        }

    # Complex path — try cascade
    logger.info("[%s] Complex path: attempting LlamaParse (REST API)", filename)
    text = await _try_llamaparse(file_bytes, filename)
    if text is not None:
        return {
            "parsed_text": text,
            "parser_used": PARSER_LLAMAPARSE,
            "parsing_quality": PARSING_QUALITY_NORMAL,
        }

    logger.warning("[%s] LlamaParse failed — falling back to Docling", filename)
    text = await _try_docling(file_bytes, filename)
    if text is not None:
        return {
            "parsed_text": text,
            "parser_used": PARSER_DOCLING,
            "parsing_quality": PARSING_QUALITY_NORMAL,
        }

    logger.warning("[%s] Docling failed — falling back to raw PyMuPDF", filename)
    text = _extract_pymupdf(file_bytes)
    return {
        "parsed_text": text,
        "parser_used": PARSER_FALLBACK,
        "parsing_quality": PARSING_QUALITY_DEGRADED,
    }



# ---------------------------------------------------------------------------
# PyMuPDF (always available, zero egress)
# ---------------------------------------------------------------------------

def _extract_pymupdf(file_bytes: bytes) -> str:
    """Extract plain text using PyMuPDF. Always succeeds."""
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    pages = [page.get_text("text") for page in doc]
    doc.close()
    return "\n\n".join(pages)


# ---------------------------------------------------------------------------
# LlamaParse via LlamaCloud REST API (no SDK — pure httpx)
# ---------------------------------------------------------------------------

async def _try_llamaparse(file_bytes: bytes, filename: str) -> Optional[str]:
    """
    Upload to LlamaCloud REST API, poll for completion, and return markdown.
    Returns None on any failure so the cascade can continue.
    """
    if not LLAMA_CLOUD_API_KEY:
        logger.warning("[%s] LlamaParse skipped — LLAMA_CLOUD_API_KEY not set", filename)
        return None

    headers = {"Authorization": f"Bearer {LLAMA_CLOUD_API_KEY}"}

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:

            # ── Step 1: Upload ──────────────────────────────────────────────
            upload_resp = await client.post(
                f"{_LLAMA_BASE}/upload",
                headers=headers,
                files={"file": (filename, file_bytes, "application/pdf")},
                data={"language": "en", "result_type": "markdown"},
            )
            upload_resp.raise_for_status()
            job_id = upload_resp.json()["id"]
            logger.info("[%s] LlamaParse job submitted: %s", filename, job_id)

            # ── Step 2: Poll until done ─────────────────────────────────────
            elapsed = 0.0
            status  = "PENDING"
            while elapsed < _MAX_WAIT:
                await asyncio.sleep(_POLL_INTERVAL)
                elapsed += _POLL_INTERVAL

                status_resp = await client.get(
                    f"{_LLAMA_BASE}/job/{job_id}",
                    headers=headers,
                    timeout=15.0,
                )
                status_resp.raise_for_status()
                status = status_resp.json().get("status", "PENDING")
                logger.debug(
                    "[%s] LlamaParse job %s — status=%s elapsed=%.0fs",
                    filename, job_id, status, elapsed,
                )

                if status == "SUCCESS":
                    break
                if status in ("ERROR", "CANCELLED"):
                    logger.warning(
                        "[%s] LlamaParse job %s failed with status=%s",
                        filename, job_id, status,
                    )
                    return None

            if status != "SUCCESS":
                logger.warning(
                    "[%s] LlamaParse job %s timed out after %.0fs",
                    filename, job_id, _MAX_WAIT,
                )
                return None

            # ── Step 3: Fetch markdown result ───────────────────────────────
            result_resp = await client.get(
                f"{_LLAMA_BASE}/job/{job_id}/result/markdown",
                headers=headers,
                timeout=30.0,
            )
            result_resp.raise_for_status()
            text = result_resp.json().get("markdown", "")

            if not text.strip():
                logger.warning("[%s] LlamaParse returned empty markdown", filename)
                return None

            logger.info(
                "[%s] LlamaParse succeeded via REST API (%d chars)",
                filename, len(text),
            )
            return text

    except Exception as exc:
        logger.warning("[%s] LlamaParse REST error: %s", filename, exc)
        return None


# ---------------------------------------------------------------------------
# Docling (local, zero data egress)
# ---------------------------------------------------------------------------

async def _try_docling(file_bytes: bytes, filename: str) -> Optional[str]:
    """
    Parse with Docling (local, zero data egress).
    Returns None on any failure so the cascade can continue.
    """
    try:
        # Late import: triggers model download/load only when this fallback runs.
        from docling.document_converter import DocumentConverter  # noqa: PLC0415

        loop = asyncio.get_event_loop()

        def _run_docling() -> str:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp.write(file_bytes)
                tmp_path = tmp.name
            try:
                converter = DocumentConverter()          # weights loaded here
                result = converter.convert(tmp_path)
                return result.document.export_to_markdown()
            finally:
                os.unlink(tmp_path)

        text = await loop.run_in_executor(None, _run_docling)
        if not text.strip():
            logger.warning("[%s] Docling returned empty text", filename)
            return None

        logger.info("[%s] Docling succeeded (%d chars)", filename, len(text))
        return text

    except Exception as exc:
        logger.warning("[%s] Docling error: %s", filename, exc)
        return None
