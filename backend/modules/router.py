"""
modules/router.py — Intent Router.

Uses llama-3.1-8b-instant via Groq + instructor to classify the user's intent
into one of three processing modules: extraction, summarization, classification.

System prompt includes five few-shot examples:
  1. A clear broad extraction prompt
  2. A clear summarization prompt
  3. A clear classification prompt
  4. Single-field extraction (formerly handled by lookup)
  5. An ambiguous prompt (extraction wins over summarization for number-heavy queries)

Extraction now explicitly covers the full spectrum from single-field questions
("What is the PAN number?") to broad structured requests ("Extract all figures").
"""

import logging
import instructor
from groq import AsyncGroq, RateLimitError as GroqRateLimitError

from config import GROQ_API_KEY, ROUTING_MODEL
from schemas.routing import RoutingDecision
from utils.errors import RateLimitExhausted
from langsmith import traceable

logger = logging.getLogger(__name__)

# Module-level singleton to reuse connection pool across concurrent requests
_client = None
if GROQ_API_KEY:
    _client = instructor.from_groq(
        AsyncGroq(api_key=GROQ_API_KEY),
        mode=instructor.Mode.JSON,
    )

# ---------------------------------------------------------------------------
# System prompt — includes few-shot examples and metadata placeholder
# ---------------------------------------------------------------------------
_SYSTEM_PROMPT = """\
You are a financial document intent router. Your task is to read a user's prompt \
and classify it into exactly one of three processing intents.

DOCUMENT METADATA (use this to inform your decision):
{metadata_block}

INTENT DEFINITIONS:
- extraction    : User wants to pull specific numeric data, facts, or tables out \
of the document. This includes single-field asks ("what is the PAN number?"), \
multi-field asks ("list all IFSC codes"), and table pulls ("show me all transactions"). \
Keywords: extract, find, what is, show me, get, list, how much, what are, \
transactions, numbers, data.
- summarization : User wants a narrative paragraph conveying what the document \
is about, a high-level overview, bullet points of findings, or explanations of \
terms. Even for tabular documents, if the user asks for a general "summary" or "overview" \
without specifying tabular data, map this to summarization. Keywords: summarize, \
overview, key themes, bullet points, explain, describe, findings, clauses, terms.
- classification: User wants to know the category or type of the document. \
Keywords: what type, what kind, classify, identify, categorise, what is this.

FEW-SHOT EXAMPLES:

Prompt: "Give me a summary of all transactions in this bank statement"
→ intent=extraction, confidence=0.92, reasoning="Although the user says \
'summary', they are asking for a list of transactions (data points). Pushing \
this to extraction will pull the tabular data."

Prompt: "Summarise this bank statement for me"
→ intent=summarization, confidence=0.94, reasoning="The user is asking for \
a general, high-level narrative overview of the statement, not specific transactions."

Prompt: "Provide a high-level overview of the company's cash movement"
→ intent=summarization, confidence=0.93, reasoning="User wants a conceptual \
narrative overview, not a line-by-line data extraction."

Prompt: "Summarize the shipping and trade terms mentioned here"
→ intent=summarization, confidence=0.96, reasoning="User explicitly wants a \
narrative text summary of clauses/terms, not tabular data."

Prompt: "What is the debit amount for the ANMOL PALACE transaction?"
→ intent=extraction, confidence=0.99, reasoning="Direct query for a specific \
data point."

Now classify the following prompt. Use the document metadata (especially page_count, \
likely_has_tables, and doc_type_hint) to resolve any ambiguity.\
"""


def _format_metadata(metadata: dict) -> str:
    return (
        f"page_count={metadata.get('page_count', 'unknown')}, "
        f"likely_has_tables={metadata.get('likely_has_tables', False)}, "
        f"doc_type_hint={metadata.get('doc_type_hint', 'unknown')}, "
        f"text_preview_sample={repr(metadata.get('text_preview', '')[:100])}"
    )


@traceable(name="Intent_Router", tags=["router"])
async def route(prompt: str, metadata: dict) -> RoutingDecision:
    """
    Route the synchronised prompt to the correct processing module.

    Args:
        prompt:   The PII-synchronised user prompt.
        metadata: MVP metadata packet from the session.

    Returns:
        RoutingDecision with intent, confidence, and reasoning.
    """
    if not _client:
        raise RuntimeError("GROQ_API_KEY is not set.")

    system_prompt = _SYSTEM_PROMPT.format(
        metadata_block=_format_metadata(metadata)
    )

    try:
        decision: RoutingDecision = await _client.chat.completions.create(
            model=ROUTING_MODEL,
            response_model=RoutingDecision,
            max_retries=2,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
        )
    except GroqRateLimitError as e:
        logger.error(f"Groq routing failed due to Rate Limit Exceeded on model {ROUTING_MODEL}.")
        raise RateLimitExhausted(f"Groq rate limits are exhausted for model {ROUTING_MODEL}.") from e

    logger.info(
        "Router: intent=%s confidence=%.2f | %s",
        decision.intent, decision.confidence, decision.reasoning
    )
    return decision
