"""
modules/summarizer.py — Summarization module.

Uses llama-3.1-70b-versatile via Groq with stream=True.
Yields text chunks as they arrive — each chunk is re-hydrated by the caller
in main.py before entering the SSE stream.

MVP: single-pass summarization only.
Phase B: map-reduce for documents exceeding ~60k chars.
"""

import logging
from typing import AsyncGenerator

from groq import AsyncGroq

from config import GROQ_API_KEY, PROCESSING_MODEL

logger = logging.getLogger(__name__)

MAX_SUMMARIZER_CHARS = 60_000   # ~15k tokens — stays well within 128k context

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
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is not set.")

    truncated = scrubbed_text[:MAX_SUMMARIZER_CHARS]
    if len(scrubbed_text) > MAX_SUMMARIZER_CHARS:
        logger.warning(
            "Summarizer: document truncated from %d to %d chars (Phase B: map-reduce)",
            len(scrubbed_text), MAX_SUMMARIZER_CHARS
        )

    client = AsyncGroq(api_key=GROQ_API_KEY)

    stream = await client.chat.completions.create(
        model=PROCESSING_MODEL,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Document ({metadata.get('page_count', '?')} pages, "
                    f"language={metadata.get('language', 'en')}):\n\n"
                    f"{truncated}\n\n"
                    f"User request: {prompt}"
                ),
            },
        ],
        stream=True,
        temperature=0.3,
    )

    async for chunk in stream:
        content = chunk.choices[0].delta.content
        if content:
            yield content
