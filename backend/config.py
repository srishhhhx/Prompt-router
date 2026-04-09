"""
config.py — Named constants, thresholds, and environment variable loading.

All routing thresholds must live here. No magic numbers in logic files.
Each threshold has a comment citing the calibration source (printed by scout.py
against the actual test documents before values were hardcoded).
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# API Keys
# ---------------------------------------------------------------------------
# Keys are validated at runtime when first used, not at import time.
# This allows config to be imported during calibration and tests without keys set.
GROQ_API_KEY: str = os.environ.get("GROQ_API_KEY", "")
LLAMA_CLOUD_API_KEY: str = os.environ.get("LLAMA_CLOUD_API_KEY", "")

# ---------------------------------------------------------------------------
# Model identifiers
# ---------------------------------------------------------------------------
ROUTING_MODEL = "llama-3.1-8b-instant"
PROCESSING_MODEL = "llama-3.3-70b-versatile"  # llama-3.1-70b-versatile was decommissioned 2025-01

# ---------------------------------------------------------------------------
# Session settings
# ---------------------------------------------------------------------------
SESSION_TTL_SECONDS = 1800          # 30 minutes
SESSION_CLEANUP_INTERVAL_SECONDS = 300  # Run eviction every 5 minutes

# ---------------------------------------------------------------------------
# PyMuPDF Scout — routing signal thresholds
#
# Calibration run (2026-04-09) against actual test documents:
#   Document4.pdf (HUL Annual Report, 47pp)
#     drawing_count=1980, block_count=1245, avg_chars_per_block=117.76, image_count=47
#   Document5.pdf (IL&FS Cash Flow, 2pp)
#     drawing_count=396,  block_count=60,   avg_chars_per_block=54.08,  image_count=0
# ---------------------------------------------------------------------------

# is_scanned: true when the PDF is primarily images with very little embedded text.
# Both test docs have chars >> 500, so this threshold correctly leaves them as non-scanned.
SCANNED_CHAR_THRESHOLD = 500        # Calibrated: Doc4=146606, Doc5=3245 — well above
SCANNED_IMAGE_THRESHOLD = 1         # Calibrated: scanned PDFs typically have ≥1 full-page image

# has_complex_layout: true when many drawing elements (table borders, boxes) are present.
# Doc4=1980 drawings, Doc5=396 drawings — both well above 50, correctly triggering complex path.
COMPLEX_LAYOUT_DRAWING_THRESHOLD = 50   # Calibrated: both test docs are >= 396; clean digital text ~0-10

# likely_has_tables: true when blocks are short and numerous (table cell pattern).
# Doc5 avg_chars_per_block=54.08 (table-heavy cash flow statement) — catches this correctly.
# Doc4 avg=117.76 — misses the table flag but has_complex_layout=True handles routing anyway.
TABLE_AVG_CHARS_THRESHOLD = 80      # Calibrated: Doc5=54.08 (tables), Doc4=117.76 (narrative+tables)
TABLE_BLOCK_COUNT_THRESHOLD = 30    # Calibrated: Doc5=60 blocks over 2 pages — lowered from 100

# Text preview length (chars from page 1) sent to the router as domain context
TEXT_PREVIEW_LENGTH = 1000

# ---------------------------------------------------------------------------
# PII Scrubber — regex patterns (MVP: Aadhaar, PAN, Phone only)
# ---------------------------------------------------------------------------
PII_PATTERNS = {
    "AADHAAR": r"\b\d{4}\s?\d{4}\s?\d{4}\b",
    "PAN":     r"\b[A-Z]{5}\d{4}[A-Z]{1}\b",
    "PHONE":   r"\b(?:\+91|91|0)?[6-9]\d{9}\b",
}

# ---------------------------------------------------------------------------
# Parsing quality flags
# ---------------------------------------------------------------------------
PARSING_QUALITY_NORMAL = "normal"
PARSING_QUALITY_DEGRADED = "degraded"

PARSER_SIMPLE = "pymupdf_simple"
PARSER_LLAMAPARSE = "llamaparse"
PARSER_DOCLING = "docling"
PARSER_FALLBACK = "pymupdf_fallback"

# ---------------------------------------------------------------------------
# File upload limits
# ---------------------------------------------------------------------------
SUPPORTED_MIME_TYPES = {
    "application/pdf",
    "image/png",
    "image/jpeg",
    "image/jpg",
}
MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB
