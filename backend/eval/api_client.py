"""
eval/api_client.py — Async HTTP client wrapping the live FDIP backend API.

All metric modules import this instead of hand-rolling their own httpx calls.
Handles SSE parsing, upload polling, and per-request latency capture.
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import httpx

BASE_URL = "http://localhost:8000"
POLL_INTERVAL = 2.0    # seconds between /status polls
POLL_TIMEOUT  = 300.0  # max seconds to wait for parse completion (LlamaParse can be slow)

logger = logging.getLogger(__name__)


class RateLimitError(RuntimeError):
    """Raised when the backend returns a 429 from an upstream LLM API."""
    pass


@dataclass
class ChatResult:
    intent: str
    confidence: float
    full_text: str          # complete rehydrated response
    is_card: bool
    parser_used: Optional[str]
    flags: list
    # Latency breakdown (seconds)
    ttft_s: float           # time to first token
    total_stream_s: float   # first token → DONE
    e2e_s: float            # POST sent → DONE received
    routing_detected: bool  # did we see a DONE event with intent?


@dataclass
class UploadResult:
    session_id: str
    parser_used: Optional[str]
    parsing_quality: Optional[str]
    page_count: Optional[int]
    is_scanned: Optional[bool]
    likely_has_tables: Optional[bool]
    parse_wall_s: float     # wall-clock seconds from upload POST to status=ready


async def upload_and_wait(pdf_path: Path, client: httpx.AsyncClient) -> UploadResult:
    """
    Upload a PDF and poll until status=ready. Returns an UploadResult with
    the session_id and timing info.

    Raises RuntimeError on failure or timeout.
    """
    t0 = time.perf_counter()
    with open(pdf_path, "rb") as f:
        resp = await client.post(
            f"{BASE_URL}/upload",
            files={"file": (pdf_path.name, f, "application/pdf")},
        )
    resp.raise_for_status()
    session_id = resp.json()["session_id"]

    # Poll until done
    elapsed = 0.0
    while elapsed < POLL_TIMEOUT:
        await asyncio.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL
        status_resp = await client.get(f"{BASE_URL}/status/{session_id}")
        status_resp.raise_for_status()
        data = status_resp.json()
        if data["status"] == "ready":
            wall_s = time.perf_counter() - t0
            return UploadResult(
                session_id=session_id,
                parser_used=data.get("parser_used"),
                parsing_quality=data.get("parsing_quality"),
                page_count=data.get("page_count"),
                is_scanned=data.get("is_scanned"),
                likely_has_tables=data.get("likely_has_tables"),
                parse_wall_s=wall_s,
            )
        if data["status"] == "failed":
            raise RuntimeError(f"Phase A failed for {pdf_path.name}: {data.get('error')}")

    raise RuntimeError(f"Timeout waiting for {pdf_path.name} to parse (>{POLL_TIMEOUT}s)")


async def send_chat(
    session_id: str,
    prompt: str,
    client: httpx.AsyncClient,
    timeout: float = 120.0,
) -> ChatResult:
    """
    Send a chat request and consume the SSE stream, capturing timing at each boundary.

    SSE event types from backend:
      {"type": "token",  "content": "...", "is_card": bool?}  — text chunk
      {"type": "done",   "intent": "...", "confidence": float, ...} — terminal
      {"type": "error",  "message": "..."} — pipeline error
    """
    t_sent = time.perf_counter()
    ttft_s = None
    t_first_token = None
    full_text = ""
    intent = "unknown"
    confidence = 0.0
    is_card = False
    parser_used = None
    flags = []
    routing_detected = False
    done_received = False

    async with client.stream(
        "POST",
        f"{BASE_URL}/chat",
        json={"session_id": session_id, "prompt": prompt},
        timeout=timeout,
    ) as response:
        response.raise_for_status()
        async for line in response.aiter_lines():
            if not line.startswith("data:"):
                continue
            raw = line[len("data:"):].strip()
            if not raw:
                continue
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                continue

            etype = event.get("type")

            if etype == "token":
                content = event.get("content", "")
                if content and ttft_s is None:
                    ttft_s = time.perf_counter() - t_sent
                    t_first_token = time.perf_counter()
                full_text += content
                if event.get("is_card"):
                    is_card = True

            elif etype == "done":
                done_received = True
                intent = event.get("intent", "unknown")
                confidence = event.get("confidence", 0.0)
                parser_used = event.get("parser_used")
                flags = event.get("flags", [])
                routing_detected = intent != "unknown"
                # Early 429 detection: backend sets flags=["error"] when both
                # Cerebras and Groq fallback are exhausted (rate limited).
                if "error" in flags and "429" in full_text:
                    logger.warning(
                        "\u26a0\ufe0f  RATE LIMIT (429): upstream LLM quota exhausted. "
                        "prompt=%r | response=%s", prompt[:80], full_text[:200]
                    )
                    raise RateLimitError(
                        f"Backend rate-limited (429) for prompt: {prompt[:80]!r}. "
                        f"Response: {full_text[:200]}"
                    )
                break

            elif etype == "error":
                raise RuntimeError(f"Backend error: {event.get('message', 'unknown')}")

    t_done = time.perf_counter()
    if not done_received:
        raise RuntimeError(
            "Chat SSE stream closed before a terminal done event was received "
            f"for prompt: {prompt[:80]!r}"
        )

    ttft_s = ttft_s or (t_done - t_sent)  # fallback if no tokens received
    total_stream_s = (t_done - t_first_token) if t_first_token else 0.0

    return ChatResult(
        intent=intent,
        confidence=confidence,
        full_text=full_text,
        is_card=is_card,
        parser_used=parser_used,
        flags=flags,
        ttft_s=ttft_s,
        total_stream_s=total_stream_s,
        e2e_s=t_done - t_sent,
        routing_detected=routing_detected,
    )


async def health_check() -> bool:
    """Returns True if the backend is up and responsive."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            r = await c.get(f"{BASE_URL}/health")
            return r.status_code == 200
    except Exception:
        return False
