"""
modules/summarizer.py — Summarization module.

Streams summarization responses token-by-token using Cerebras (primary)
with Groq as fallback. Each chunk is rehydrated by the caller in main.py
before entering the SSE stream.
"""

import logging
from typing import AsyncGenerator
from langsmith import traceable

from groq import AsyncGroq, RateLimitError as GroqRateLimitError
from config import GROQ_API_KEY, CEREBRAS_API_KEY, GROQ_70B_MODEL, CEREBRAS_MODEL, TRUNCATION_SIGNAL, GROQ_CONTEXT_LIMIT
from utils.truncation import truncate_for_context
from openai import AsyncOpenAI, RateLimitError as OpenAIRateLimitError
from utils.errors import RateLimitExhausted

logger = logging.getLogger(__name__)

# Module-level singletons for connection pooling
_client_cerebras = None
if CEREBRAS_API_KEY:
    _client_cerebras = AsyncOpenAI(base_url="https://api.cerebras.ai/v1", api_key=CEREBRAS_API_KEY, max_retries=0)

_client_groq = None
if GROQ_API_KEY:
    _client_groq = AsyncGroq(api_key=GROQ_API_KEY)


_SYSTEM_PROMPT = """\
You are a financial document analyst. You produce clear, structured summaries of \
financial documents for business stakeholders.

When summarising, always include:
- Document type and period covered
- Key financial figures (revenue, profit, assets if present)
- 3–5 most important highlights or findings
- Any notable risks, anomalies, or areas of concern

Write in clear, professional prose. Use bullet points for highlights. \
Do not fabricate figures — only use what is in the document.\
"""



@traceable(name="Summarizer", tags=["summarizer"])
async def summarize_stream(
    scrubbed_text: str,
    metadata: dict,
    prompt: str,
) -> AsyncGenerator[str, None]:
    """
    Stream a summarization response token-by-token.

    Args:
        scrubbed_text: PII-scrubbed document text.
        metadata:      MVP metadata packet.
        prompt:        PII-synchronised user prompt.

    Yields:
        Text chunks (strings) as they arrive from the Groq streaming API.
    """
    if not _client_cerebras:
        raise RuntimeError("CEREBRAS_API_KEY is not set.")

    # Guard against None — text-only sessions have empty scrubbed_text
    scrubbed_text = scrubbed_text or ""

    estimated_tokens = metadata.get("estimated_tokens", 0)
    truncated, was_truncated = truncate_for_context(scrubbed_text, estimated_tokens)
    
    logger.info("Summarizer context limit logic [%s]: tokens=%d, was_truncated=%s, tier=%s", 
                "unknown", estimated_tokens, was_truncated, "2 (Split)" if was_truncated else "1 (Full)")

    user_content = ""
    if was_truncated:
        user_content += TRUNCATION_SIGNAL
        
    user_content += (
        f"Document Scale: {metadata.get('page_count', '?')} pages "
        f"(~{estimated_tokens} tokens), "
        f"language={metadata.get('language', 'en')}.\n"
        f"Adapt your summary depth proportionally to the document scale.\n\n"
        f"{truncated}\n\n"
        f"User request: {prompt}"
    )

    try:
        stream = await _client_cerebras.chat.completions.create(
            model=CEREBRAS_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": user_content,
                },
            ],
            stream=True,
            temperature=0.3,
        )
        async for chunk in stream:
            content = chunk.choices[0].delta.content
            if content:
                yield content
                
    except Exception as cerebras_exc:
        logger.warning(f"Cerebras summarization failed ({cerebras_exc}), falling back to Groq Llama 70B...")
        if not _client_groq:
            raise RuntimeError("GROQ_API_KEY is not set for fallback.") from cerebras_exc
            
        groq_truncated, groq_was_truncated = truncate_for_context(scrubbed_text, estimated_tokens, context_limit=GROQ_CONTEXT_LIMIT)
        
        user_content_groq = ""
        if groq_was_truncated:
            user_content_groq += TRUNCATION_SIGNAL
            
        user_content_groq += (
            f"Document Scale: {metadata.get('page_count', '?')} pages "
            f"(~{estimated_tokens} tokens), "
            f"language={metadata.get('language', 'en')}.\n"
            f"Adapt your summary depth proportionally to the document scale.\n\n"
            f"{groq_truncated}\n\n"
            f"User request: {prompt}"
        )
        
        try:
            stream_groq = await _client_groq.chat.completions.create(
                model=GROQ_70B_MODEL,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": user_content_groq,
                    },
                ],
                stream=True,
                temperature=0.3,
            )
            async for chunk in stream_groq:
                content = chunk.choices[0].delta.content
                if content:
                    yield content
        except GroqRateLimitError as e:
            logger.error(f"Groq fallback summarization ({GROQ_70B_MODEL}) failed due to Rate Limit Exceeded.")
            raise RateLimitExhausted(
                f"Both primary Cerebras ({CEREBRAS_MODEL}) and fallback Groq "
                f"({GROQ_70B_MODEL}) rate limits are exhausted."
            ) from e
