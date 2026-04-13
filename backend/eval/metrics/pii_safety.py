"""
eval/metrics/pii_safety.py — PII Safety Score (Lifecycle Integrity).

Tests the full scrub-and-rehydrate loop:
  1. Scrub Check  : Re-runs the PII scrubber in-process on the raw parsed text
                    (read from the llamaparse pre-parsed .md files) and checks
                    that all expected PII fields are detected.
  2. Rehydration  : Sends a prompt asking for the PII field value via /chat and
                    checks that the real value appears in the response (not the
                    {{TOKEN}} placeholder).

The scrub check runs directly against utils/pii.py — no API call needed.
The rehydration check runs through the full live pipeline.

NOTE: The /status endpoint does not expose token_map for security reasons.
      We test scrubbing by running the scrubber directly on the llamaparse
      pre-parsed files, which are the highest-quality input texts available.
"""

import asyncio
import re
import sys
from pathlib import Path
from typing import List, Optional

import httpx

# ---------------------------------------------------------------------------
# Config: Constants & Paths
# ---------------------------------------------------------------------------
BACKEND_ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(BACKEND_ROOT))

from utils.pii import scrub_document
from eval.api_client import send_chat

LLAMAPARSE_DIR = Path(__file__).parents[3] / "parser_tests" / "Parsed" / "llamaparse"

DEFAULT_COOLDOWN = 10.0


async def run(
    doc_id: str,
    session_id: str,
    expected_pii: List[dict],
    client: httpx.AsyncClient,
    cooldown_s: float = DEFAULT_COOLDOWN,
) -> dict:
    """
    Standard entry point: Runs both scrub and rehydration checks for a document.
    """
    scrub_result = run_scrub_check(doc_id, expected_pii)
    reh_result = await run_rehydration_check(
        doc_id, session_id, expected_pii, client, cooldown_s
    )
    return {
        "doc_id": doc_id,
        "scrub": scrub_result,
        "rehydration": reh_result,
    }


def _load_llamaparse_text(doc_id: str) -> Optional[str]:
    """Load the pre-parsed llamaparse markdown for a document."""
    path = LLAMAPARSE_DIR / f"{doc_id}.pdf_llamaparse.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return None


def run_scrub_check(doc_id: str, expected_pii: List[dict]) -> dict:
    """
    Run the PII scrubber in-process on the llamaparse text.
    Checks that each expected PII field is captured in the token map.

    Returns:
        {
          "doc_id": str,
          "source": "llamaparse" | "not_found",
          "expected_count": int,
          "detected_count": int,
          "scrub_recall": float,
          "details": [{"type", "value", "detected", "token"}]
        }
    """
    text = _load_llamaparse_text(doc_id)
    if text is None:
        return {
            "doc_id": doc_id,
            "source": "not_found",
            "expected_count": len(expected_pii),
            "detected_count": 0,
            "scrub_recall": 0.0,
            "details": [],
            "note": f"LlamaParse file not found for {doc_id}",
        }

    result = scrub_document(text)
    token_map = result["token_map"]
    # token_map: { "{{PAN_1}}": "CZUPP7582B", ... }
    detected_values = set(token_map.values())

    details = []
    detected_count = 0
    for pii in expected_pii:
        real_value = pii["value"]
        detected = real_value in detected_values
        if detected:
            detected_count += 1
            # Find which token it was assigned
            assigned_token = next((t for t, v in token_map.items() if v == real_value), None)
        else:
            assigned_token = None

        details.append({
            "type":     pii["type"],
            "value":    real_value,
            "detected": detected,
            "token":    assigned_token,
        })

    recall = detected_count / len(expected_pii) if expected_pii else 1.0  # vacuously 100% if no PII expected

    return {
        "doc_id": doc_id,
        "source": "llamaparse",
        "expected_count": len(expected_pii),
        "detected_count": detected_count,
        "scrub_recall": round(recall, 4),
        "total_tokens_found": len(token_map),
        "details": details,
    }


async def run_rehydration_check(
    doc_id: str,
    session_id: str,
    expected_pii: List[dict],
    client: httpx.AsyncClient,
    cooldown_s: float = 10.0,
) -> dict:
    """
    For each expected PII field, sends a prompt asking for that value and
    checks the response contains the real value (not the {{TOKEN}} placeholder).

    Example: sends "What is the PAN number?" and checks response contains
    "CZUPP7582B" and does NOT contain "{{PAN_".

    Returns:
        {
          "doc_id": str,
          "expected_count": int,
          "rehydrated_count": int,
          "rehydration_success_rate": float,
          "details": [{"type", "value", "prompt", "response_snippet",
                        "contains_real": bool, "contains_token": bool}]
        }
    """
    if not expected_pii:
        return {
            "doc_id": doc_id,
            "expected_count": 0,
            "rehydrated_count": 0,
            "rehydration_success_rate": 1.0,
            "details": [],
            "note": "No expected PII — vacuously passing",
        }

    PII_PROMPTS = {
        "PAN":    "What is the PAN number in this document?",
        "AADHAAR": "What is the Aadhaar number in this document?",
        "IFSC":   "What is the IFSC code of the bank in this document?",
    }

    details = []
    rehydrated_count = 0
    for i, pii in enumerate(expected_pii):
        if i > 0:
            await asyncio.sleep(cooldown_s)

        pii_type = pii["type"]
        real_value = pii["value"]
        prompt = PII_PROMPTS.get(pii_type, f"What is the {pii_type} in this document?")

        try:
            result = await send_chat(session_id, prompt, client)
            response_text = result.full_text
            contains_real  = real_value.lower() in response_text.lower()
            contains_token = bool(re.search(r'\{\{[A-Z_0-9]+\}\}', response_text))
            success = contains_real and not contains_token
            if success:
                rehydrated_count += 1
        except Exception as exc:
            response_text = f"ERROR: {exc}"
            contains_real = False
            contains_token = False
            success = False

        details.append({
            "type": pii_type,
            "value": real_value,
            "prompt": prompt,
            "response_snippet": response_text[:200],
            "contains_real": contains_real,
            "contains_token": contains_token,
            "success": success,
        })

    rate = rehydrated_count / len(expected_pii)
    return {
        "doc_id": doc_id,
        "expected_count": len(expected_pii),
        "rehydrated_count": rehydrated_count,
        "rehydration_success_rate": round(rate, 4),
        "details": details,
    }


def aggregate(scrub_results: List[dict], rehydration_results: List[dict]) -> dict:
    """
    Combine scrub and rehydration results into a single PII Safety Score.

    Score = 0.5 * avg(scrub_recall) + 0.5 * avg(rehydration_success_rate)
    Documents with no PII are excluded from the average (vacuously passing).
    """
    # Only score docs that have expected PII
    scrub_scored    = [r for r in scrub_results      if r.get("expected_count", 0) > 0]
    rehydrate_scored = [r for r in rehydration_results if r.get("expected_count", 0) > 0]

    avg_scrub    = (sum(r["scrub_recall"] for r in scrub_scored) / len(scrub_scored)) if scrub_scored else 1.0
    avg_rehydrate = (sum(r["rehydration_success_rate"] for r in rehydrate_scored) / len(rehydrate_scored)) if rehydrate_scored else 1.0
    pii_safety_score = round(0.5 * avg_scrub + 0.5 * avg_rehydrate, 4)

    return {
        "pii_safety_score":          pii_safety_score,
        "avg_scrub_recall":          round(avg_scrub, 4),
        "avg_rehydration_success":   round(avg_rehydrate, 4),
        "docs_with_pii":             len(scrub_scored),
        "scrub_results":             scrub_results,
        "rehydration_results":       rehydration_results,
    }
