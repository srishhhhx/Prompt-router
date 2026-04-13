"""
eval/metrics/groundedness.py — Extraction Groundedness.

Uses Groq (llama-3.3-70b) as an LLM-as-a-Judge to evaluate whether each
extraction response only contains facts that are traceable to the source document.

Judge prompt asks the model to count:
  - supported_claims   : facts directly present in the source document
  - unsupported_claims : facts absent from or contradicted by the source document

Faithfulness score = supported / (supported + unsupported)

Source documents used: LlamaParse pre-parsed markdown files (highest quality).
These are used as the reference "what the document actually says" — the same
high-quality input the backend would use on the complex parser path.

Rate limiting: judgment calls are batched with a configurable cooldown.
"""

import asyncio
import json
import re
import sys
from pathlib import Path
from typing import List, Optional

# Groq SDK (already in backend venv)
from groq import AsyncGroq

BACKEND_ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(BACKEND_ROOT))
from config import GROQ_API_KEY, GROQ_70B_MODEL

LLAMAPARSE_DIR = Path(__file__).parents[3] / "parser_tests" / "Parsed" / "llamaparse"

_client: Optional[AsyncGroq] = None

def _get_client() -> AsyncGroq:
    global _client
    if _client is None:
        if not GROQ_API_KEY:
            raise RuntimeError("GROQ_API_KEY is not set — cannot run groundedness judge")
        _client = AsyncGroq(api_key=GROQ_API_KEY)
    return _client


def _load_source(doc_id: str) -> Optional[str]:
    path = LLAMAPARSE_DIR / f"{doc_id}.pdf_llamaparse.md"
    if path.exists():
        # Limit to first 3000 chars to avoid Groq context limits for judge call
        # (Aggressive truncation to fit within Groq TPM/rate-limit thresholds)
        return path.read_text(encoding="utf-8")[:3_000]
    return None


_JUDGE_SYSTEM = """\
You are a strict factual grounding evaluator for a financial document AI system.

Your job: Given a SOURCE DOCUMENT and an AI RESPONSE, count how many factual 
claims in the RESPONSE are supported vs unsupported by the SOURCE DOCUMENT.

DEFINITIONS:
- "Supported claim": A specific fact (number, name, date, code, entity) that 
  appears explicitly in the SOURCE DOCUMENT or can be directly inferred from it.
- "Unsupported claim": A specific fact that is absent from the SOURCE DOCUMENT, 
  contradicts it, or cannot be verified from it.

RULES:
- Do NOT penalise hedging language ("approximately", "around") if the underlying   
  value is present in the document.
- Do NOT penalise for facts not mentioned that the question didn't ask about.
- Count each distinct factual claim separately.
- If the response says "This information is not present in the document", treat 
  the response as 1 supported claim and 0 unsupported (correct refusal).

Respond ONLY with valid JSON in this exact format (no markdown, no prose):
{"supported": <int>, "unsupported": <int>, "explanation": "<one sentence>"}
"""


async def _judge_single(
    source_text: str,
    prompt: str,
    response: str,
) -> dict:
    """
    Call Groq to judge one (prompt, response, source) triple.
    Returns {"supported": int, "unsupported": int, "explanation": str}.
    """
    user_content = (
        f"PROMPT ASKED:\n{prompt}\n\n"
        f"AI RESPONSE:\n{response}\n\n"
        f"SOURCE DOCUMENT (excerpt):\n{source_text}"
    )

    client = _get_client()
    completion = await client.chat.completions.create(
        model=GROQ_70B_MODEL,
        messages=[
            {"role": "system", "content": _JUDGE_SYSTEM},
            {"role": "user",   "content": user_content},
        ],
        temperature=0.0,
        max_tokens=200,
    )

    raw = completion.choices[0].message.content.strip()
    # Strip markdown code fences if present
    raw = re.sub(r"^```[a-z]*\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw)

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Fallback: try to extract numbers with regex
        sup = re.search(r'"supported"\s*:\s*(\d+)', raw)
        uns = re.search(r'"unsupported"\s*:\s*(\d+)', raw)
        return {
            "supported":   int(sup.group(1)) if sup else 0,
            "unsupported": int(uns.group(1)) if uns else 1,
            "explanation": raw[:200],
        }


async def run(
    doc_id: str,
    extraction_cases: List[dict],
    responses: List[str],
    cooldown_s: float = 20.0,
) -> dict:
    """
    Judge groundedness for one document's extraction results.

    Args:
        doc_id:            e.g. "Document6"
        extraction_cases:  List of {prompt, expected, field_type} from ground truth.
        responses:         Parallel list of actual LLM responses from extraction.
        cooldown_s:        Seconds between Groq judge calls.

    Returns:
        {
          "doc_id": str,
          "faithfulness_score": float,
          "supported_total": int,
          "unsupported_total": int,
          "cases": [{"prompt", "response_snippet", "supported", "unsupported", "explanation"}]
        }
    """
    source_text = _load_source(doc_id)
    if source_text is None:
        return {
            "doc_id": doc_id,
            "faithfulness_score": None,
            "note": f"LlamaParse source not found for {doc_id}",
            "cases": [],
        }

    cases = []
    sup_total = 0
    uns_total = 0

    for i, (case, response) in enumerate(zip(extraction_cases, responses)):
        if i > 0:
            await asyncio.sleep(cooldown_s)

        prompt = case["prompt"]
        try:
            judgment = await _judge_single(source_text, prompt, response)
            sup  = judgment.get("supported", 0)
            uns  = judgment.get("unsupported", 0)
            expl = judgment.get("explanation", "")
        except Exception as exc:
            sup, uns, expl = 0, 1, f"Judge error: {exc}"

        sup_total += sup
        uns_total += uns

        cases.append({
            "prompt":           prompt,
            "response_snippet": response[:200],
            "supported":        sup,
            "unsupported":      uns,
            "explanation":      expl,
        })

    total_claims = sup_total + uns_total
    faithfulness = sup_total / total_claims if total_claims > 0 else 1.0

    return {
        "doc_id":             doc_id,
        "faithfulness_score": round(faithfulness, 4),
        "supported_total":    sup_total,
        "unsupported_total":  uns_total,
        "cases":              cases,
    }


def aggregate(all_results: List[dict]) -> dict:
    """
    Aggregate per-document groundedness into a global faithfulness score.
    Documents without source files are excluded from the average.
    """
    valid = [r for r in all_results if r.get("faithfulness_score") is not None]
    if not valid:
        return {"global_faithfulness_score": None, "per_doc": all_results}

    global_score = sum(r["faithfulness_score"] for r in valid) / len(valid)
    total_sup = sum(r["supported_total"] for r in valid)
    total_uns = sum(r["unsupported_total"] for r in valid)

    return {
        "global_faithfulness_score": round(global_score, 4),
        "micro_faithfulness_score":  round(total_sup / (total_sup + total_uns), 4) if (total_sup + total_uns) > 0 else 1.0,
        "total_supported":   total_sup,
        "total_unsupported": total_uns,
        "per_doc":           all_results,
    }
