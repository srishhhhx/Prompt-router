"""
pii.py — PII scrubber and prompt synchronizer.

MVP patterns (three only):
    Aadhaar : \\b\\d{4}\\s?\\d{4}\\s?\\d{4}\\b
    PAN     : \\b[A-Z]{5}\\d{4}[A-Z]{1}\\b
    Phone   : \\b(?:\\+91|91|0)?[6-9]\\d{9}\\b

Named persons, bank account numbers, and other PII are out of scope for the MVP.
See Section 11 of Master-doc.md for the Phase B / production expansion plan.

Two public functions:
    scrub_document(text)                  → {scrubbed_text, token_map}
    sync_prompt_with_tokens(prompt, sid)  → sanitised_prompt_str
"""

import re
import logging
from typing import Optional

from config import PII_PATTERNS
from session import SESSIONS

logger = logging.getLogger(__name__)

# Pre-compile patterns once at import time
_COMPILED_PATTERNS = {
    ptype: re.compile(pattern)
    for ptype, pattern in PII_PATTERNS.items()
}


def scrub_document(text: str) -> dict:
    """
    Scan `text` for Aadhaar, PAN, and Phone numbers.
    Replace each match with a typed, numbered token.

    Returns:
        {
            "scrubbed_text": str,           # text with all PII replaced by tokens
            "token_map":     dict[str, str] # {"{{PAN_1}}": "ABCDE1234F", ...}
        }
    """
    token_map: dict[str, str] = {}
    counters: dict[str, int] = {ptype: 0 for ptype in _COMPILED_PATTERNS}

    def _replace(match: re.Match, ptype: str) -> str:
        counters[ptype] += 1
        token = f"{{{{{ptype}_{counters[ptype]}}}}}"
        real_value = match.group(0)
        # Only add to map if this exact value hasn't been tokenised already
        if real_value not in token_map.values():
            token_map[token] = real_value
        else:
            # Re-use the existing token for this value
            for existing_token, val in token_map.items():
                if val == real_value:
                    counters[ptype] -= 1  # undo counter increment
                    return existing_token
        return token

    scrubbed = text
    for ptype, pattern in _COMPILED_PATTERNS.items():
        scrubbed = pattern.sub(lambda m, pt=ptype: _replace(m, pt), scrubbed)

    logger.info("PII scrub: found %d tokens across %d pattern types",
                len(token_map), len([c for c in counters.values() if c > 0]))
    return {"scrubbed_text": scrubbed, "token_map": token_map}


def sync_prompt_with_tokens(prompt: str, session_id: str) -> str:
    """
    Synchronise the user prompt with the session's token map.

    For each entry in the token map, if the real value appears in the prompt,
    replace it with the corresponding token so the LLM sees {{PAN_1}} in both
    the document and the prompt.

    If the prompt contains a PAN / Aadhaar / Phone that is NOT in the token map
    (i.e. it wasn't in the document), the three regex patterns are applied
    directly to scrub the loose PII before it reaches the LLM.

    Args:
        prompt:     Raw user prompt as typed.
        session_id: Active session ID (used to retrieve the token map).

    Returns:
        The synchronised prompt — safe to pass to the intent router.
    """
    session = SESSIONS.get(session_id)
    if not session or not session.get("token_map"):
        # No session or empty map — apply raw regex scrubbing as a safety net
        return _scrub_prompt_raw(prompt)

    token_map: dict[str, str] = session["token_map"]
    synced = prompt

    # Replace known real values with their tokens (reverse map: real → token)
    for token, real_value in token_map.items():
        if real_value in synced:
            synced = synced.replace(real_value, token)
            logger.debug("Prompt sync: replaced %r with %s", real_value, token)

    # Scrub any remaining PII that wasn't in the document
    synced = _scrub_prompt_raw(synced, prefix="UNKNOWN_")

    return synced


def rehydrate(text: str, session_id: str) -> str:
    """
    Reverse tokenisation: replace all {{TOKEN_N}} with their real values
    before streaming the response to the user.

    The LLM never saw real PII; the user always sees real values.
    """
    session = SESSIONS.get(session_id)
    if not session or not session.get("token_map"):
        return text

    token_map: dict[str, str] = session["token_map"]
    result = text
    for token, real_value in token_map.items():
        result = result.replace(token, real_value)
    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _scrub_prompt_raw(text: str, prefix: str = "") -> str:
    """
    Apply the MVP regex patterns directly to `text`.
    Used as a safety net for PII that wasn't in the document token map.
    Tokens are prefixed with `prefix` (e.g. "UNKNOWN_") to distinguish them.
    """
    counters: dict[str, int] = {ptype: 0 for ptype in _COMPILED_PATTERNS}

    def _replace(match: re.Match, ptype: str) -> str:
        counters[ptype] += 1
        return f"{{{{{prefix}{ptype}_{counters[ptype]}}}}}"

    result = text
    for ptype, pattern in _COMPILED_PATTERNS.items():
        result = pattern.sub(lambda m, pt=ptype: _replace(m, pt), result)
    return result
