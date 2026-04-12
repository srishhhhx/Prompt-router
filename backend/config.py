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
CEREBRAS_API_KEY: str = os.environ.get("CEREBRAS_API_KEY", "")

# ---------------------------------------------------------------------------
# Model identifiers
CEREBRAS_MODEL = "qwen-3-235b-a22b-instruct-2507"
GROQ_70B_MODEL = "llama-3.3-70b-versatile"

# Active usage mappings
ROUTING_MODEL = "llama-3.1-8b-instant"

# ---------------------------------------------------------------------------
# Session settings
# ---------------------------------------------------------------------------
SESSION_TTL_SECONDS = 86400          # 24 hours (86,400 seconds)
SESSION_CLEANUP_INTERVAL_SECONDS = 300  # Run eviction every 5 minutes

# ---------------------------------------------------------------------------
# PyMuPDF Scout — routing signal thresholds
# ---------------------------------------------------------------------------

# is_scanned: true when the PDF is primarily images with very little embedded text.
SCANNED_CHAR_THRESHOLD = 500
SCANNED_IMAGE_THRESHOLD = 1

# has_complex_layout: true when many drawing elements (table borders, boxes) are present.
COMPLEX_LAYOUT_DRAWING_THRESHOLD = 50

# likely_has_tables: true when blocks are short and numerous (table cell pattern).
TABLE_AVG_CHARS_THRESHOLD = 80
TABLE_BLOCK_COUNT_THRESHOLD = 30

# Text preview length (chars from page 1) sent to the router as domain context
TEXT_PREVIEW_LENGTH = 1000

# ---------------------------------------------------------------------------
# PII Scrubber — regex patterns (GSTIN, PAN, IFSC)
# ---------------------------------------------------------------------------
PII_PATTERNS = {
    # GSTIN: 2-digit state code + PAN prefix + entity no + 'Z' + checksum
    "GSTIN": r"\b[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b",
    # PAN: 5 letters + 4 digits + 1 letter
    "PAN":   r"\b[A-Z]{5}\d{4}[A-Z]{1}\b",
    # IFSC: 4 letters + '0' + 6 alphanumeric
    "IFSC":  r"\b[A-Z]{4}0[A-Z0-9]{6}\b",
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

# ---------------------------------------------------------------------------
# Truncation limits
# ---------------------------------------------------------------------------
CONTEXT_WINDOW_LIMIT = 12_000
GROQ_CONTEXT_LIMIT = 4_500

CHARS_PER_TOKEN = 3

HEAD_RATIO = 0.60
TAIL_RATIO = 0.40
SNAP_TOLERANCE = 500

GAP_MARKER = "\n\n[... DOCUMENT SECTION OMITTED — DO NOT ASSUME CONTINUITY ...]\n\n"

TRUNCATION_SIGNAL = (
    "The following text contains two non-contiguous excerpts from a financial "
    "document. They do not flow linearly. Extract key facts from each section "
    "independently. Do not infer or assume content in the omitted section.\n\n"
)
