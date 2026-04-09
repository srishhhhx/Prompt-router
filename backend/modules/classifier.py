"""
modules/classifier.py — Classification module.

Uses llama-3.1-8b-instant via Groq + instructor.
8B is sufficient for document type classification — fast and cost-effective.
Returns a validated ClassificationResult.
"""

import logging
import instructor
from groq import AsyncGroq

from config import GROQ_API_KEY, ROUTING_MODEL
from schemas.classification import ClassificationResult

logger = logging.getLogger(__name__)

MAX_CLASSIFIER_CHARS = 30_000   # classifier only needs a sample of the document

_SYSTEM_PROMPT = """\
You are a financial document classifier. Given the content of a financial document, \
identify its type and explain what signals led you to that conclusion.

Document types:
- annual_report    : Full company annual report with financial statements and narrative
- audit_report     : Auditor's opinion or audit findings document
- balance_sheet    : Statement of financial position (assets, liabilities, equity)
- invoice          : Commercial invoice with line items and payment details
- bank_statement   : Bank account transaction history
- legal_agreement  : Contract, MOU, or legal document with financial terms
- other            : Any financial document not matching the above categories

For key_signals, list 3–5 short phrases or headings that indicate the document type \
(e.g. "Cash Flow Statement header", "Auditor signature block", "Invoice number field").\
"""


async def classify(
    scrubbed_text: str,
    metadata: dict,
    prompt: str,
) -> ClassificationResult:
    """
    Classify the document type.

    Args:
        scrubbed_text: PII-scrubbed document text.
        metadata:      MVP metadata packet (text_preview used for efficiency).
        prompt:        PII-synchronised user prompt.

    Returns:
        Validated ClassificationResult instance.
    """
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is not set.")

    # Use text_preview + beginning of document for speed — classifier doesn't
    # need the full text, just enough to identify the document type.
    sample = scrubbed_text[:MAX_CLASSIFIER_CHARS]

    client = instructor.from_groq(
        AsyncGroq(api_key=GROQ_API_KEY),
        mode=instructor.Mode.JSON,
    )

    result: ClassificationResult = await client.chat.completions.create(
        model=ROUTING_MODEL,    # 8B is sufficient for classification
        response_model=ClassificationResult,
        max_retries=2,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Document sample ({metadata.get('page_count', '?')} pages total):\n\n"
                    f"{sample}\n\n"
                    f"User request: {prompt}"
                ),
            },
        ],
        temperature=0.1,
    )

    logger.info(
        "Classifier: doc_type=%s confidence=%.2f signals=%s",
        result.document_type, result.confidence, result.key_signals
    )
    return result
