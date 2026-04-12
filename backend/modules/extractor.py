"""
modules/extractor.py — Extraction module.

Freeform text extraction — no Pydantic schema, no instructor enforcement.
Returns a plain string streamed token-by-token, structurally identical to
the summarizer.

The LLM decides output format based on the prompt:
  - Single-field question  → one sentence
  - Multi-field question   → markdown bullet list
  - Tabular data request   → markdown table
  - Broad extraction       → mix of headers, bullets, tables
"""

import logging
from typing import AsyncGenerator
from langsmith import traceable

from groq import AsyncGroq, RateLimitError as GroqRateLimitError
from openai import AsyncOpenAI, RateLimitError as OpenAIRateLimitError

from config import (
    GROQ_API_KEY, CEREBRAS_API_KEY,
    GROQ_70B_MODEL, CEREBRAS_MODEL,
    TRUNCATION_SIGNAL, GROQ_CONTEXT_LIMIT,
)
from utils.truncation import truncate_for_context
from utils.errors import RateLimitExhausted

logger = logging.getLogger(__name__)

# Module-level singletons for connection pooling
_client_cerebras = None
if CEREBRAS_API_KEY:
    _client_cerebras = AsyncOpenAI(
        base_url="https://api.cerebras.ai/v1",
        api_key=CEREBRAS_API_KEY,
        max_retries=0,
    )

_client_groq = None
if GROQ_API_KEY:
    _client_groq = AsyncGroq(api_key=GROQ_API_KEY)


_SYSTEM_PROMPT = """\
You are a financial document data extraction specialist. Your job is to \
extract exactly what the user asks for from the provided document.

RESPONSE FORMAT RULES:
- If the user asks for a specific value or field, you may respond with the value directly OR provide a concise answer in one or two clear sentences.
- For numeric values, you may include currency symbols or commas to make the information more readable for the user.
- If the user asks for multiple values or a list of items, use a markdown \
  bullet list.
- If the user asks for tabular data (transactions, line items, comparative \
  figures), use a markdown table.
- If the user asks a broad extraction request across the whole document, \
  use a combination of markdown headers, bullet lists, and tables as \
  appropriate.

CONTENT RULES:
- Extract only values that are explicitly present in the document.
- If the requested information is not present in the document, respond with \
  exactly: "This information is not present in the provided document." Do \
  not invent values. Do not infer from context. Do not approximate.
- If a field in the document contains a value in the format {{TOKEN_TYPE_N}} \
  (for example {{PAN_1}}, {{AADHAAR_1}}, {{IFSC_1}}), treat it as a valid \
  present value and include it in your response. The real value will be \
  restored before the response reaches the user.
- Do not flag tokenized fields as missing, anomalous, or malformed.\
"""


def _build_user_content(truncated: str, was_truncated: bool, metadata: dict, prompt: str) -> str:
    """Build the user message content string for the extraction prompt."""
    content = ""
    if was_truncated:
        content += TRUNCATION_SIGNAL
    content += (
        f"Document context: {metadata.get('page_count', '?')} pages, "
        f"type: {metadata.get('doc_type_hint', 'unknown')}\n"
        f"Contains structured tables: {metadata.get('likely_has_tables', False)}\n"
        "(If True, prioritize data from markdown table structures over prose "
        "when values conflict.)\n\n"
        f"Document text:\n{truncated}\n\n"
        f"User request: {prompt}"
    )
    return content


async def _stream_cerebras(user_content: str) -> AsyncGenerator[str, None]:
    """Stream from Cerebras. Raises on error so the caller can fall back."""
    stream = await _client_cerebras.chat.completions.create(
        model=CEREBRAS_MODEL,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user",   "content": user_content},
        ],
        stream=True,
        temperature=0.1,
    )
    async for chunk in stream:
        content = chunk.choices[0].delta.content
        if content:
            yield content


async def _stream_groq(user_content: str) -> AsyncGenerator[str, None]:
    """Stream from Groq fallback."""
    stream = await _client_groq.chat.completions.create(
        model=GROQ_70B_MODEL,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user",   "content": user_content},
        ],
        stream=True,
        temperature=0.1,
    )
    async for chunk in stream:
        content = chunk.choices[0].delta.content
        if content:
            yield content



@traceable(name="Financial_Extractor", tags=["extractor"])
async def extract(
    scrubbed_text: str,
    metadata: dict,
    prompt: str,
) -> AsyncGenerator[str, None]:
    """
    Stream freeform extraction results token-by-token.

    Args:
        scrubbed_text: PII-scrubbed document text (may be None or empty).
        metadata:      MVP metadata packet.
        prompt:        PII-synchronised user prompt.

    Yields:
        Text chunks (strings) as they arrive from the LLM streaming API.
    """
    if not _client_cerebras:
        raise RuntimeError("CEREBRAS_API_KEY is not set.")

    # Guard against None — text-only or unprocessed sessions
    scrubbed_text = scrubbed_text or ""

    estimated_tokens = metadata.get("estimated_tokens", 0)
    truncated, was_truncated = truncate_for_context(scrubbed_text, estimated_tokens)

    logger.info(
        "Extractor context limit logic: tokens=%d, was_truncated=%s, tier=%s",
        estimated_tokens, was_truncated,
        "2 (Split)" if was_truncated else "1 (Full)",
    )

    user_content = _build_user_content(truncated, was_truncated, metadata, prompt)

    # --- Attempt Cerebras primary ---
    cerebras_ok = False
    try:
        async for chunk in _stream_cerebras(user_content):
            cerebras_ok = True
            yield chunk
    except Exception as cerebras_exc:
        logger.warning(
            "Cerebras extraction failed (%s), falling back to Groq Llama 70B...",
            cerebras_exc,
        )

    if cerebras_ok:
        logger.info(
            "Extractor (Cerebras): doc_type=%s was_truncated=%s",
            metadata.get("doc_type_hint", "unknown"), was_truncated,
        )
        return

    # --- Groq fallback ---
    if not _client_groq:
        raise RuntimeError("Both Cerebras and Groq API keys are missing — cannot extract.")

    groq_truncated, groq_was_truncated = truncate_for_context(
        scrubbed_text, estimated_tokens, context_limit=GROQ_CONTEXT_LIMIT
    )
    groq_content = _build_user_content(groq_truncated, groq_was_truncated, metadata, prompt)

    try:
        async for chunk in _stream_groq(groq_content):
            yield chunk
    except GroqRateLimitError as e:
        logger.error(f"Groq fallback extraction ({GROQ_70B_MODEL}) failed due to Rate Limit Exceeded.")
        raise RateLimitExhausted(
            f"Both primary Cerebras ({CEREBRAS_MODEL}) and fallback Groq "
            f"({GROQ_70B_MODEL}) rate limits are exhausted."
        ) from e

    logger.info(
        "Extractor (Groq fallback): doc_type=%s was_truncated=%s",
        metadata.get("doc_type_hint", "unknown"), groq_was_truncated,
    )
