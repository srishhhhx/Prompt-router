"""
modules/classifier.py — Classification module.

Uses Groq 70B + instructor for structured classification.
Cerebras Qwen as fallback if Groq fails.

Returns a validated ClassificationResult with the document type,
confidence score, and key signals that led to the classification.

Document taxonomy (10 types) is calibrated against the 6 sample
document categories provided:
  Doc 1 → financial_statements  (proprietor full set)
  Doc 2 → commercial_invoice    (export trade invoice)
  Doc 3 → audit_report          (independent auditor's report)
  Doc 4 → annual_report         (corporate HUL annual report)
  Doc 5 → cash_flow_statement   (standalone cash flow)
  Doc 6 → bank_statement        (Canara Bank transaction history)
"""

import logging
import instructor
from groq import AsyncGroq, RateLimitError as GroqRateLimitError
from openai import AsyncOpenAI, RateLimitError as OpenAIRateLimitError

from config import GROQ_API_KEY, CEREBRAS_API_KEY, GROQ_70B_MODEL, CEREBRAS_MODEL
from schemas.classification import ClassificationResult
from utils.errors import RateLimitExhausted
from langsmith import traceable

logger = logging.getLogger(__name__)

# Module-level singletons for connection pooling
_client_groq = None
if GROQ_API_KEY:
    _client_groq = instructor.from_groq(
        AsyncGroq(api_key=GROQ_API_KEY),
        mode=instructor.Mode.JSON,
    )

_client_cerebras = None
if CEREBRAS_API_KEY:
    _client_cerebras = instructor.patch(
        AsyncOpenAI(
            base_url="https://api.cerebras.ai/v1",
            api_key=CEREBRAS_API_KEY,
            max_retries=0,
        ),
        mode=instructor.Mode.JSON,
    )

# Classifier only needs a representative sample — not the full doc
MAX_CLASSIFIER_CHARS = 30_000

_SYSTEM_PROMPT = """\
You are a financial document classifier. Given the content of a document, \
identify its type from the taxonomy below and explain what signals led you \
to that conclusion.

DOCUMENT TYPE TAXONOMY:

- financial_statements : A combined set of financial statements for an individual or \
  proprietorship business — typically includes Balance Sheet, Profit & Loss Account, \
  and Capital Account together in a single document. Key signals: proprietor name, \
  "Capital Account", combined P&L and balance sheet in one file, entity type \
  "Individual / Proprietorship".

- balance_sheet : A standalone Statement of Financial Position for a company or entity. \
  Lists assets, liabilities, and equity as of a specific date. Key signals: \
  "Assets", "Liabilities", "Equity / Capital", balance date, total assets = total liabilities + equity.

- profit_loss : A standalone Profit & Loss Account or Income Statement. Shows revenue, \
  expenses, and net profit/loss over a period. Does NOT include balance sheet data. \
  Key signals: "Revenue from Operations", "Gross Profit", "Net Profit", expense line items.

- cash_flow_statement : A standalone Cash Flow Statement. Shows cash movements across \
  operating, investing, and financing activities. Key signals: "Operating Activities", \
  "Investing Activities", "Financing Activities", "Net Change in Cash", opening/closing balances.

- annual_report : A full corporate annual report for a public or private company. \
  Contains multiple financial statements (balance sheet, P&L, cash flow), notes to accounts, \
  management discussion, and board disclosures. Key signals: company name, "Board of Directors", \
  "Notes to Financial Statements", auditor's report section, multiple financial statements combined.

- audit_report : A standalone independent auditor's report or audit findings document. \
  Issued by a Chartered Accountant or audit firm, expressing an opinion on financial statements. \
  Key signals: "Independent Auditor's Report", "Basis of Opinion", "Chartered Accountant", \
  "UDIN", audit firm name, "true and fair view".

- commercial_invoice : A commercial or export invoice issued for goods or services. \
  Contains itemised product list, quantities, unit prices, total value, and trade/customs details. \
  Key signals: "Invoice No.", "HSN Code", shipper/consignee details, "FOB", "CIF", \
  "Country of Origin", itemised product lines, invoice date.

- bank_statement : A bank account transaction statement showing transaction history. \
  Contains individual rows for each transaction: date, description, debit, credit, and balance. \
  Key signals: bank name, "NEFT", "RTGS", transaction date column, running balance, \
  account number, branch/IFSC code.

- legal_agreement : A contract, MOU, loan agreement, or legal document containing \
  financial terms. Key signals: "Agreement", "Party", "Whereas", "Terms and Conditions", \
  signatures, legal clauses, penalty clauses.

- other : Any document that does not match any of the above categories.

DECISION RULES:
1. If the document contains BOTH Balance Sheet AND P&L AND the entity is an \
   Individual/Proprietor → classify as financial_statements (not annual_report).
2. If the document contains ONLY transaction rows (date, debit, credit, balance) → bank_statement.
3. If the document is issued by an audit firm and expresses an opinion on other financial \
   statements → audit_report (even if it quotes balance sheet figures).
4. If the document has itemised product lines, shipping details, and invoice number → commercial_invoice.
5. annual_report is reserved for corporate entities (registered companies, public entities), \
   not for proprietorships.

For key_signals, return 3–5 short phrases (e.g. "NEFT transaction rows", \
"Auditor signature block", "Invoice No. field", "Operating Activities section").\
"""


def _build_user_message(sample: str, metadata: dict, prompt: str) -> str:
    return (
        f"Document sample ({metadata.get('page_count', '?')} pages total):\n"
        f"Heuristic Doc Type Hint: {metadata.get('doc_type_hint', 'unknown')} "
        f"(verify against the text — this is only a fast keyword estimate)\n\n"
        f"{sample}\n\n"
        f"User request: {prompt}"
    )


@traceable(name="Document_Classifier", tags=["classifier"])
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
    if not _client_groq:
        raise RuntimeError("GROQ_API_KEY is not set.")

    scrubbed_text = scrubbed_text or ""
    sample = scrubbed_text[:MAX_CLASSIFIER_CHARS]
    user_msg = _build_user_message(sample, metadata, prompt)

    try:
        result: ClassificationResult = await _client_groq.chat.completions.create(
            model=GROQ_70B_MODEL,
            response_model=ClassificationResult,
            max_retries=1,
            temperature=0.1,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user",   "content": user_msg},
            ],
        )
    except GroqRateLimitError as groq_rl_exc:
        logger.warning("Groq classification failed (Rate Limit), falling back to Cerebras Qwen...")
        if not _client_cerebras:
            raise RuntimeError("CEREBRAS_API_KEY is not set for fallback.") from groq_rl_exc

        try:
            result: ClassificationResult = await _client_cerebras.chat.completions.create(
                model=CEREBRAS_MODEL,
                response_model=ClassificationResult,
                max_retries=1,
                temperature=0.1,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user",   "content": user_msg},
                ],
            )
        except OpenAIRateLimitError as cerebras_rl_exc:
            logger.error(f"Cerebras fallback classification ({CEREBRAS_MODEL}) failed due to Rate Limit Exceeded.")
            raise RateLimitExhausted(f"Both primary Groq ({GROQ_70B_MODEL}) and fallback Cerebras ({CEREBRAS_MODEL}) rate limits are exhausted.") from cerebras_rl_exc

    except Exception as groq_exc:
        logger.warning("Groq classification failed (%s), falling back to Cerebras Qwen...", groq_exc)
        if not _client_cerebras:
            raise RuntimeError("CEREBRAS_API_KEY is not set for fallback.") from groq_exc

        result: ClassificationResult = await _client_cerebras.chat.completions.create(
            model=CEREBRAS_MODEL,
            response_model=ClassificationResult,
            max_retries=1,
            temperature=0.1,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user",   "content": user_msg},
            ],
        )

    logger.info(
        "Classifier: doc_type=%s confidence=%.2f signals=%s",
        result.document_type, result.confidence, result.key_signals,
    )
    return result
