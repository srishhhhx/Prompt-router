"""
pii.py — PII scrubber and prompt synchronizer.

Detects and tokenizes three PII patterns:
    GSTIN : \\b[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]\\b
    PAN   : \\b[A-Z]{5}\\d{4}[A-Z]{1}\\b
    IFSC  : \\b[A-Z]{4}0[A-Z0-9]{6}\\b

Public functions:
    scrub_document(text)                  → {scrubbed_text, token_map}
    sync_prompt_with_tokens(prompt, sid)  → sanitised prompt string
    rehydrate(text, sid)                  → restored text with real values
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
    Scan `text` for Aadhaar, PAN, and IFSC numbers.
    Replace each match with a typed, numbered token.

    Returns:
        {
            "scrubbed_text": str,           # text with all PII replaced by tokens
            "token_map":     dict[str, str] # {"{{PAN_1}}": "ABCDE1234F", ...}
        }
    """
    token_map: dict[str, str] = {}          # token  → real_value
    reverse_map: dict[str, str] = {}         # real_value → token  (O(1) dedup)
    counters: dict[str, int] = {ptype: 0 for ptype in _COMPILED_PATTERNS}

    def _replace(match: re.Match, ptype: str) -> str:
        real_value = match.group(0)
        # Re-use existing token if this value was already seen — O(1) lookup
        if real_value in reverse_map:
            return reverse_map[real_value]
        counters[ptype] += 1
        token = f"{{{{{ptype}_{counters[ptype]}}}}}"
        token_map[token] = real_value
        reverse_map[real_value] = token
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

    If the prompt contains a PAN / Aadhaar / IFSC that is NOT in the token map
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
        return _scrub_prompt_raw(prompt, prefix="UNKNOWN_")

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


class StreamRehydrator:
    """
    Handles PII token rehydration over a stream of text chunks.
    Since `{{PAN_1}}` might be broken across multiple chunks (e.g., `["{{P", "AN_", "1}}"]`),
    this class buffers characters safely and resolves the token as soon as it completes.
    """
    def __init__(self, session_id: str):
        session = SESSIONS.get(session_id)
        self.token_map = session.get("token_map", {}) if session else {}
        self.buffer = ""

    def process(self, chunk: str) -> str:
        if not self.token_map:
            return chunk

        self.buffer += chunk
        output = ""
        while self.buffer:
            idx = self.buffer.find('{')
            if idx == -1:
                output += self.buffer
                self.buffer = ""
                break

            output += self.buffer[:idx]
            self.buffer = self.buffer[idx:]

            if len(self.buffer) < 2:
                break
                
            if self.buffer[1] != '{':
                output += self.buffer[0]
                self.buffer = self.buffer[1:]
                continue

            end_idx = self.buffer.find('}}')
            if end_idx == -1:
                # Safety: if buffer gets too large, flush the first char and continue
                if len(self.buffer) > 50:
                    output += self.buffer[0]
                    self.buffer = self.buffer[1:]
                    continue
                break

            token = self.buffer[:end_idx+2]
            output += self.token_map.get(token, token)
            self.buffer = self.buffer[len(token):]

        return output

    def flush(self) -> str:
        output = self.buffer
        self.buffer = ""
        return output


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


def rehydrate_dict(data: dict, session_id: str) -> dict:
    """
    Recursively walk `data` and replace all token strings with their real values.
    Used to rehydrate structured extraction results before sending to the frontend.
    """
    session = SESSIONS.get(session_id)
    if not session or not session.get("token_map"):
        return data
    token_map = session["token_map"]
    return _walk(data, token_map)


def _walk(obj, token_map: dict):
    if isinstance(obj, str):
        for token, real in token_map.items():
            obj = obj.replace(token, real)
        return obj
    if isinstance(obj, dict):
        return {k: _walk(v, token_map) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_walk(item, token_map) for item in obj]
    return obj
