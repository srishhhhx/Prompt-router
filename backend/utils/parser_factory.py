"""
parser_factory.py — Cascading parser strategy: LlamaParse → Docling → PyMuPDF fallback.

Decision logic (deterministic, no LLM):
  - Simple path:  is_scanned=False AND has_complex_layout=False AND likely_has_tables=False
                  → use PyMuPDF text directly (fast, zero external dependency)
  - Complex path: any signal is True
                  → try LlamaParse (markdown, table-preserving)
                  → on any failure: try Docling (local, markdown, zero egress)
                  → on any failure: use raw PyMuPDF text with parsing_quality=degraded

Parser outputs are never mixed. Once a parser is selected, all downstream
processing uses only that parser's output.
"""

import asyncio
import logging
from typing import Optional

import fitz  # PyMuPDF

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
    logger.info("[%s] Complex path: attempting LlamaParse", filename)
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
# Parser implementations
# ---------------------------------------------------------------------------

def _extract_pymupdf(file_bytes: bytes) -> str:
    """Extract plain text using PyMuPDF. Always succeeds."""
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    pages = []
    for page in doc:
        pages.append(page.get_text("text"))
    doc.close()
    return "\n\n".join(pages)


async def _try_llamaparse(file_bytes: bytes, filename: str) -> Optional[str]:
    """
    Parse with LlamaParse (cloud, markdown output mode).
    Returns None on any failure so the cascade can continue.
    """
    try:
        from llama_parse import LlamaParse

        loop = asyncio.get_event_loop()

        def _run_llamaparse() -> str:
            parser = LlamaParse(
                api_key=LLAMA_CLOUD_API_KEY,
                result_type="markdown",
                verbose=False,
            )
            # LlamaParse expects a file path or bytes; use from_bytes where available
            # Save bytes to a temp-like bytes buffer and parse
            import tempfile, os
            suffix = ".pdf"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(file_bytes)
                tmp_path = tmp.name
            try:
                documents = parser.load_data(tmp_path)
                return "\n\n".join(doc.text for doc in documents)
            finally:
                os.unlink(tmp_path)

        text = await loop.run_in_executor(None, _run_llamaparse)
        if not text.strip():
            logger.warning("[%s] LlamaParse returned empty text", filename)
            return None
        logger.info("[%s] LlamaParse succeeded (%d chars)", filename, len(text))
        return text

    except Exception as exc:
        logger.warning("[%s] LlamaParse error: %s", filename, exc)
        return None


async def _try_docling(file_bytes: bytes, filename: str) -> Optional[str]:
    """
    Parse with Docling (local, markdown output, zero data egress).
    Returns None on any failure so the cascade can continue.
    """
    try:
        from docling.document_converter import DocumentConverter
        import tempfile, os

        loop = asyncio.get_event_loop()

        def _run_docling() -> str:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp.write(file_bytes)
                tmp_path = tmp.name
            try:
                converter = DocumentConverter()
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
