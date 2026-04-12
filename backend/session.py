"""
session.py — In-memory session store with TTL expiry and background cleanup.

Structure:
    SESSIONS[session_id] = {
        "status":       "processing" | "ready" | "failed",
        "metadata":     {...} | None,
        "scrubbed_text": str | None,
        "token_map":    {token: real_value} | None,
        "error":        str | None,
        "expires_at":   datetime,
    }
"""

import uuid
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

from config import SESSION_TTL_SECONDS, SESSION_CLEANUP_INTERVAL_SECONDS

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Global store — single-process in-memory dict.
# ---------------------------------------------------------------------------
SESSIONS: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# CRUD helpers
# ---------------------------------------------------------------------------

def create_session() -> str:
    """Create a new session with status 'processing'. Returns the session_id."""
    session_id = str(uuid.uuid4())
    SESSIONS[session_id] = {
        "status": "processing",
        "metadata": None,
        "scrubbed_text": None,
        "token_map": None,
        "error": None,
        "expires_at": datetime.utcnow() + timedelta(seconds=SESSION_TTL_SECONDS),
    }
    logger.info("Session created: %s", session_id)
    return session_id


def get_session(session_id: str) -> Optional[dict]:
    """Return the session dict, or None if not found or expired."""
    session = SESSIONS.get(session_id)
    if session is None:
        return None
    if is_expired(session):
        del SESSIONS[session_id]
        logger.info("Session expired and evicted on access: %s", session_id)
        return None
    return session


def update_session_ready(session_id: str, metadata: dict, scrubbed_text: str, token_map: dict) -> None:
    """Mark the session as ready after successful Phase A processing."""
    if session_id not in SESSIONS:
        logger.warning("update_session_ready called for unknown session: %s", session_id)
        return
    SESSIONS[session_id].update({
        "status": "ready",
        "metadata": metadata,
        "scrubbed_text": scrubbed_text,
        "token_map": token_map,
        "error": None,
    })
    logger.info("Session ready: %s, parser=%s", session_id, metadata.get("parser_used"))


def update_session_failed(session_id: str, error: str) -> None:
    """Mark the session as failed with a human-readable error reason."""
    if session_id not in SESSIONS:
        logger.warning("update_session_failed called for unknown session: %s", session_id)
        return
    SESSIONS[session_id].update({
        "status": "failed",
        "error": error,
    })
    logger.error("Session failed: %s — %s", session_id, error)


def is_expired(session: dict) -> bool:
    return datetime.utcnow() > session["expires_at"]


# ---------------------------------------------------------------------------
# Background cleanup task
# ---------------------------------------------------------------------------

async def cleanup_expired_sessions() -> None:
    """Periodic task: evict all expired sessions every SESSION_CLEANUP_INTERVAL_SECONDS."""
    while True:
        await asyncio.sleep(SESSION_CLEANUP_INTERVAL_SECONDS)
        expired = [sid for sid, s in list(SESSIONS.items()) if is_expired(s)]
        for sid in expired:
            del SESSIONS[sid]
        if expired:
            logger.info("Evicted %d expired session(s): %s", len(expired), expired)
