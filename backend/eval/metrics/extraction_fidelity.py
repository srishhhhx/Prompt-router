"""
eval/metrics/extraction_fidelity.py — Extraction Fidelity (Value Accuracy).

Sends extraction prompts from the ground truth and compares the returned
values against expected answers.

Two comparison modes:
  - "exact"    : Normalised string comparison (strip, lowercase).
  - "numeric"  : Parses both strings as numbers using Indian number formatting
                 (e.g. "2,14,550" → 214550.0) and checks equality.
  - "contains" : Checks that the expected string appears anywhere in the response.
"""

import asyncio
import re
from typing import List

import httpx

from eval.api_client import send_chat


# ---------------------------------------------------------------------------
# Number parsing for Indian financial formatting
# ---------------------------------------------------------------------------

def _parse_number(s: str) -> float:
    """
    Parse a numeric string that may use Indian comma formatting or parentheses
    for negatives, e.g.:
      "46,12,930"  → 4612930.0
      "2,362.19"   → 2362.19
      "(784.75)"   → -784.75
      "-784.75"    → -784.75
    Raises ValueError if parsing fails.
    """
    s = s.strip()
    # Parentheses notation for negatives: (784.75) → -784.75
    negative = s.startswith("(") and s.endswith(")")
    s = re.sub(r"[()₹$£€\s]", "", s)
    # Remove commas (Indian or standard formatting)
    s = s.replace(",", "")
    value = float(s)
    return -value if negative else value


def _normalise_exact(s: str) -> str:
    """Normalise for exact matching: strip, lowercase, collapse internal whitespace."""
    return re.sub(r"\s+", " ", s.strip().lower())


def _compare(predicted: str, expected: str, field_type: str) -> tuple[bool, str]:
    """
    Compare predicted response against expected value.
    Returns (match: bool, reason: str).
    """
    if field_type == "exact":
        pred_norm = _normalise_exact(predicted)
        exp_norm  = _normalise_exact(expected)
        match = exp_norm in pred_norm
        return match, f"expected '{exp_norm}' in normalised response"

    elif field_type == "numeric":
        try:
            exp_val  = _parse_number(expected)
        except ValueError:
            return False, f"could not parse expected '{expected}' as number"

        # Extract all numbers from the predicted text and check if any matches
        # This handles cases where the LLM adds text around the value
        numbers_in_response = re.findall(
            r"[\-\(]?[\d,]+\.?\d*\)?",
            predicted.replace(" ", "")
        )
        for num_str in numbers_in_response:
            try:
                pred_val = _parse_number(num_str)
                if abs(pred_val - exp_val) < 0.005:  # tolerance for float rounding
                    return True, f"found {pred_val} ≈ {exp_val}"
            except ValueError:
                continue
        return False, f"expected {exp_val} not found in response numbers"

    elif field_type == "contains":
        match = _normalise_exact(expected) in _normalise_exact(predicted)
        return match, f"expected '{expected}' to appear in response"

    return False, f"unknown field_type '{field_type}'"


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

async def run(
    session_id: str,
    extraction_cases: List[dict],
    client: httpx.AsyncClient,
    cooldown_s: float = 15.0,
) -> dict:
    """
    Run extraction fidelity evaluation for one document.

    Args:
        session_id:       Active session with parsed document.
        extraction_cases: List of {prompt, expected, field_type} from ground truth.
        client:           Shared httpx.AsyncClient.
        cooldown_s:       Seconds between chat requests.

    Returns:
        {
          "cases": [...],
          "fidelity_score": float,
          "match_count": int,
          "total": int,
        }
    """
    cases = []
    for i, case in enumerate(extraction_cases):
        if i > 0:
            await asyncio.sleep(cooldown_s)

        prompt     = case["prompt"]
        expected   = str(case["expected"])
        field_type = case.get("field_type", "exact")

        try:
            result = await send_chat(session_id, prompt, client)
            predicted_text = result.full_text.strip()
            match, reason = _compare(predicted_text, expected, field_type)
            ttft_s = result.ttft_s
            total_stream_s = result.total_stream_s
            e2e_s = result.e2e_s
        except Exception as exc:
            predicted_text = f"ERROR: {exc}"
            match = False
            reason = str(exc)
            ttft_s = total_stream_s = e2e_s = None

        cases.append({
            "prompt":          prompt,
            "expected":        expected,
            "field_type":      field_type,
            "predicted":       predicted_text[:300],
            "match":           match,
            "reason":          reason,
            "ttft_s":          ttft_s,
            "total_stream_s":  total_stream_s,
            "e2e_s":           e2e_s,
        })

    total = len(cases)
    match_count = sum(1 for c in cases if c["match"])
    fidelity_score = match_count / total if total else 0.0

    return {
        "cases":           cases,
        "fidelity_score":  round(fidelity_score, 4),
        "match_count":     match_count,
        "total":           total,
    }


def aggregate(all_results: List[dict]) -> dict:
    """
    Aggregate per-document fidelity results.
    """
    all_cases = []
    for r in all_results:
        all_cases.extend(r.get("cases", []))

    total = len(all_cases)
    matched = sum(1 for c in all_cases if c["match"])
    score = matched / total if total else 0.0

    by_type: dict = {}
    for c in all_cases:
        ft = c["field_type"]
        by_type.setdefault(ft, {"total": 0, "matched": 0})
        by_type[ft]["total"] += 1
        if c["match"]:
            by_type[ft]["matched"] += 1
    for ft, d in by_type.items():
        d["score"] = round(d["matched"] / d["total"], 4) if d["total"] else 0.0

    return {
        "overall_fidelity_score": round(score, 4),
        "total_cases":  total,
        "matched":      matched,
        "by_field_type": by_type,
        "all_cases":    all_cases,
    }
