"""
scout.py — PyMuPDF full-document metadata extractor.

Scans the entire document (not just the first page) and returns raw metrics
plus three derived routing signals: is_scanned, has_complex_layout, likely_has_tables.

All threshold comparisons use named constants from config.py.
Calibrate thresholds by running:

    python -m utils.scout <path_to_document.pdf>

and inspecting the printed raw values before changing config constants.
"""

import logging
from typing import Optional

import fitz  # PyMuPDF

try:
    from langdetect import detect as langdetect_detect, LangDetectException
    _LANGDETECT_AVAILABLE = True
except ImportError:
    _LANGDETECT_AVAILABLE = False

from config import (
    SCANNED_CHAR_THRESHOLD,
    SCANNED_IMAGE_THRESHOLD,
    COMPLEX_LAYOUT_DRAWING_THRESHOLD,
    TABLE_AVG_CHARS_THRESHOLD,
    TABLE_BLOCK_COUNT_THRESHOLD,
    TEXT_PREVIEW_LENGTH,
)

logger = logging.getLogger(__name__)


def run_scout(file_bytes: bytes, filename: str = "document") -> dict:
    """
    Scan the entire document and return metadata + routing signals.

    Args:
        file_bytes: Raw PDF bytes.
        filename:   Used only for logging.

    Returns:
        {
            # Raw metrics
            "page_count":          int,
            "total_drawing_count": int,
            "total_image_count":   int,
            "total_char_count":    int,
            "total_block_count":   int,
            "avg_chars_per_block": float,
            "text_preview":        str,
            "language":            str,

            # Derived routing signals
            "is_scanned":          bool,
            "has_complex_layout":  bool,
            "likely_has_tables":   bool,
        }
    """
    doc = fitz.open(stream=file_bytes, filetype="pdf")

    total_drawing_count = 0
    total_image_count = 0
    total_char_count = 0
    total_block_count = 0
    text_preview: str = ""

    for page_num, page in enumerate(doc):
        # Drawing elements (table borders, lines, boxes)
        drawings = page.get_drawings()
        total_drawing_count += len(drawings)

        # Images (key signal for scanned documents)
        images = page.get_images(full=False)
        total_image_count += len(images)

        # Text blocks
        blocks = page.get_text("blocks")  # list of (x0,y0,x1,y1,text,block_no,block_type)
        text_blocks = [b for b in blocks if b[6] == 0]  # type 0 = text block
        total_block_count += len(text_blocks)

        page_text = page.get_text("text")
        total_char_count += len(page_text)

        # Capture text preview from page 1 only
        if page_num == 0 and page_text.strip():
            text_preview = page_text[:TEXT_PREVIEW_LENGTH]

    doc.close()

    avg_chars_per_block = (
        total_char_count / total_block_count if total_block_count > 0 else 0.0
    )

    # Language detection (best-effort; falls back to "unknown")
    language = _detect_language(text_preview)

    # Derived routing signals
    is_scanned = (
        total_char_count < SCANNED_CHAR_THRESHOLD
        and total_image_count >= SCANNED_IMAGE_THRESHOLD
    )
    has_complex_layout = total_drawing_count >= COMPLEX_LAYOUT_DRAWING_THRESHOLD
    likely_has_tables = (
        avg_chars_per_block < TABLE_AVG_CHARS_THRESHOLD
        and total_block_count > TABLE_BLOCK_COUNT_THRESHOLD
    )

    page_count = fitz.open(stream=file_bytes, filetype="pdf").page_count

    result = {
        "page_count":          page_count,
        "total_drawing_count": total_drawing_count,
        "total_image_count":   total_image_count,
        "total_char_count":    total_char_count,
        "total_block_count":   total_block_count,
        "avg_chars_per_block": round(avg_chars_per_block, 2),
        "text_preview":        text_preview,
        "language":            language,
        "is_scanned":          is_scanned,
        "has_complex_layout":  has_complex_layout,
        "likely_has_tables":   likely_has_tables,
    }

    logger.info(
        "Scout [%s]: pages=%d drawings=%d images=%d chars=%d blocks=%d "
        "avg_chars/block=%.1f → scanned=%s complex=%s tables=%s",
        filename,
        result["page_count"],
        result["total_drawing_count"],
        result["total_image_count"],
        result["total_char_count"],
        result["total_block_count"],
        result["avg_chars_per_block"],
        result["is_scanned"],
        result["has_complex_layout"],
        result["likely_has_tables"],
    )

    return result


def _detect_language(text: str) -> str:
    if not text.strip() or not _LANGDETECT_AVAILABLE:
        return "unknown"
    try:
        return langdetect_detect(text)
    except Exception:
        return "unknown"


# ---------------------------------------------------------------------------
# CLI calibration helper: python -m utils.scout <path>
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m utils.scout <path_to_pdf>")
        sys.exit(1)

    path = sys.argv[1]
    with open(path, "rb") as f:
        data = f.read()

    result = run_scout(data, filename=path)
    print("\n=== Scout calibration output ===")
    for key, value in result.items():
        if key != "text_preview":
            print(f"  {key:25s}: {value}")
    print(f"\n  text_preview (first 200 chars):\n    {result['text_preview'][:200]!r}")
    print()
