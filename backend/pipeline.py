"""
pipeline.py — background document processing pipeline.

This module owns Phase A: scout, parse, PII scrub, metadata assembly, and
session state update after a file upload.
"""

import logging
import time

from config import CHARS_PER_TOKEN, TEXT_PREVIEW_LENGTH
from session import update_session_ready, update_session_failed
from utils.metadata import assemble_metadata
from utils.parser_factory import parse_document
from utils.pii import scrub_document
from utils.scout import run_scout

logger = logging.getLogger(__name__)


async def run_phase_a(
    session_id: str,
    file_bytes: bytes,
    filename: str,
    content_type: str,
) -> None:
    """
    Process an uploaded file in the background and mark the session ready/failed.
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
            parsed_len = len(parser_result["parsed_text"])
            scout_result["text_preview"] = parser_result["parsed_text"][:TEXT_PREVIEW_LENGTH]
            scout_result["total_char_count"] = parsed_len
            scout_result["estimated_tokens"] = parsed_len // CHARS_PER_TOKEN

        # Step 4: PII scrubbing
        t_pii = time.perf_counter()
        logger.info("[%s] Phase A step 4: PII scrubber (GSTIN, PAN, IFSC)", session_id)
        scrub_result = scrub_document(parser_result["parsed_text"])
        token_map = scrub_result["token_map"]
        logger.info(
            "[%s] PII scrub: %.0f ms | %d token(s) found",
            session_id,
            (time.perf_counter() - t_pii) * 1000,
            len(token_map),
        )
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
        logger.info(
            "[%s] Phase A complete — %.0f ms total | parser=%s",
            session_id,
            total_ms,
            parser_result["parser_used"],
        )

    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        logger.exception("[%s] Phase A failed: %s", session_id, error_msg)
        update_session_failed(session_id, error=error_msg)
