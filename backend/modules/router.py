"""
modules/router.py — Intent Router.

Uses llama-3.1-8b-instant via Groq + instructor to classify the user's intent
into one of three processing modules: extraction, summarization, classification.

System prompt includes four few-shot examples so the model understands:
  1. A clear extraction prompt
  2. A clear summarization prompt
  3. A clear classification prompt
  4. An ambiguous prompt (lower confidence expected)

The metadata packet is formatted inline so the model can use page_count,
likely_has_tables, and language to make more informed decisions.
"""

import logging
import instructor
from groq import AsyncGroq

from config import GROQ_API_KEY, ROUTING_MODEL
from schemas.routing import RoutingDecision

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompt — includes few-shot examples and metadata placeholder
# ---------------------------------------------------------------------------
_SYSTEM_PROMPT = """\
You are a financial document intent router. Your task is to read a user's prompt \
and classify it into exactly one of three processing intents.

DOCUMENT METADATA (use this to inform your decision):
{metadata_block}

INTENT DEFINITIONS:
- extraction    : User wants specific data points, figures, tables, or named fields \
pulled from the document. Keywords: extract, find, what is, show me, get, list, \
how much, what are the figures.
- summarization : User wants a narrative overview or high-level understanding. \
Keywords: summarize, overview, key points, highlights, explain, describe, \
what happened, tell me about, brief.
- classification: User wants to know what type of document this is or its category. \
Keywords: what type, what kind, classify, identify, categorise, what is this.

FEW-SHOT EXAMPLES:

Prompt: "Extract all revenue figures and net profit margins from this document"
→ intent=extraction, confidence=0.97, reasoning="User explicitly requests extraction \
of specific financial figures from the document."

Prompt: "Summarize the key financial highlights of this annual report"
→ intent=summarization, confidence=0.96, reasoning="User wants a high-level \
narrative summary of the document's financial highlights."

Prompt: "What type of financial document is this?"
→ intent=classification, confidence=0.98, reasoning="User is asking to identify \
the document's category — a direct classification task."

Prompt: "Tell me about the numbers in this document"
→ intent=extraction, confidence=0.58, reasoning="'Numbers' loosely implies \
extraction, but the vague phrasing reduces confidence; routed to extraction \
as the most likely interpretation."

Now classify the following prompt. Use the document metadata (especially page_count, \
likely_has_tables, language) to resolve any ambiguity.\
"""


def _format_metadata(metadata: dict) -> str:
    return (
        f"page_count={metadata.get('page_count', 'unknown')}, "
        f"likely_has_tables={metadata.get('likely_has_tables', False)}, "
        f"is_scanned={metadata.get('is_scanned', False)}, "
        f"language={metadata.get('language', 'unknown')}, "
        f"parser_used={metadata.get('parser_used', 'unknown')}, "
        f"parsing_quality={metadata.get('parsing_quality', 'normal')}"
    )


async def route(prompt: str, metadata: dict) -> RoutingDecision:
    """
    Route the synchronised prompt to the correct processing module.

    Args:
        prompt:   The PII-synchronised user prompt.
        metadata: MVP metadata packet from the session.

    Returns:
        RoutingDecision with intent, confidence, and reasoning.
    """
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is not set.")

    client = instructor.from_groq(
        AsyncGroq(api_key=GROQ_API_KEY),
        mode=instructor.Mode.JSON,
    )

    system_prompt = _SYSTEM_PROMPT.format(
        metadata_block=_format_metadata(metadata)
    )

    decision: RoutingDecision = await client.chat.completions.create(
        model=ROUTING_MODEL,
        response_model=RoutingDecision,
        max_retries=2,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
    )

    logger.info(
        "Router: intent=%s confidence=%.2f | %s",
        decision.intent, decision.confidence, decision.reasoning
    )
    return decision
