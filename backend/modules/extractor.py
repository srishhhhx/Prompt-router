"""
modules/extractor.py — Extraction module.

Uses llama-3.1-70b-versatile via Groq + instructor.
Returns a validated FinancialStatementSchema — no manual JSON parsing.

Phase B: schema selection based on ClassificationResult.document_type
(e.g. InvoiceSchema vs BalanceSheetSchema).
"""

import logging
import instructor
from groq import AsyncGroq

from config import GROQ_API_KEY, PROCESSING_MODEL
from schemas.extraction import FinancialStatementSchema

logger = logging.getLogger(__name__)

MAX_EXTRACTOR_CHARS = 60_000

_SYSTEM_PROMPT = """\
You are a financial data extraction specialist. Given a financial document, \
extract structured data and return it in the required JSON schema.

Rules:
- Only extract values that are explicitly present in the document.
- Use exact values as they appear (preserve currency symbols and units).
- If a field is not present in the document, set it to null.
- For key_line_items, include any important figures not covered by standard fields.
- For flagged_anomalies, note any values that seem unusual, inconsistent, or missing.
- Set extraction_confidence based on how clearly the values appeared in the document \
  (1.0 = values were explicit and unambiguous, 0.5 = values required inference).\
"""


async def extract(
    scrubbed_text: str,
    metadata: dict,
    prompt: str,
) -> FinancialStatementSchema:
    """
    Extract structured financial data from the document.

    Args:
        scrubbed_text: PII-scrubbed document text.
        metadata:      MVP metadata packet.
        prompt:        PII-synchronised user prompt.

    Returns:
        Validated FinancialStatementSchema instance.
    """
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is not set.")

    truncated = scrubbed_text[:MAX_EXTRACTOR_CHARS]
    if len(scrubbed_text) > MAX_EXTRACTOR_CHARS:
        logger.warning(
            "Extractor: document truncated from %d to %d chars",
            len(scrubbed_text), MAX_EXTRACTOR_CHARS
        )

    client = instructor.from_groq(
        AsyncGroq(api_key=GROQ_API_KEY),
        mode=instructor.Mode.JSON,
    )

    result: FinancialStatementSchema = await client.chat.completions.create(
        model=PROCESSING_MODEL,
        response_model=FinancialStatementSchema,
        max_retries=2,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Document ({metadata.get('page_count', '?')} pages):\n\n"
                    f"{truncated}\n\n"
                    f"User extraction request: {prompt}"
                ),
            },
        ],
        temperature=0.1,    # low temperature for deterministic extraction
    )

    logger.info(
        "Extractor: doc_type=%s confidence=%.2f anomalies=%d",
        result.document_type, result.extraction_confidence, len(result.flagged_anomalies)
    )
    return result
