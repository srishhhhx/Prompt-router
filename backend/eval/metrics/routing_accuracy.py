import asyncio
import json
import logging
import time
from datetime import datetime
from collections import defaultdict
from pathlib import Path
from typing import List
import sys

# Add backend to sys.path
BACKEND_ROOT = Path(__file__).parents[2]
REPO_ROOT = BACKEND_ROOT.parent
sys.path.append(str(BACKEND_ROOT))

from modules.router import route
from schemas.routing import RoutingDecision

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] — %(message)s",
)
logger = logging.getLogger("routing_eval")

EVAL_DIR = Path(__file__).parents[1]
PARSED_DIR = REPO_ROOT / "parser_tests" / "Parsed" / "llamaparse"
GOLDEN_FILE = EVAL_DIR / "fixtures" / "golden_dataset.json"
RESULTS_DIR = EVAL_DIR / "results"

COOLDOWN_SECONDS = 5.0


def aggregate(results: List[dict]) -> dict:
    """Calculate routing accuracy, precision, recall, and F1 from case results."""
    correct = sum(1 for r in results if r["correct"])
    accuracy = correct / len(results) if results else 0

    intents = ["extraction", "summarization", "classification"]
    tp = defaultdict(int)
    fp = defaultdict(int)
    fn = defaultdict(int)

    for r in results:
        exp = r["expected"]
        pred = r["predicted"]
        if r["correct"]:
            tp[exp] += 1
        else:
            fp[pred] += 1
            fn[exp] += 1

    intent_report = {}
    f1_scores = []
    for it in intents:
        prec = tp[it] / (tp[it] + fp[it]) if (tp[it] + fp[it]) else 0
        rec = tp[it] / (tp[it] + fn[it]) if (tp[it] + fn[it]) else 0
        f1 = (2 * prec * rec / (prec + rec)) if (prec + rec) else 0
        intent_report[it] = {
            "precision": round(prec, 4),
            "recall": round(rec, 4),
            "f1": round(f1, 4),
            "count": tp[it] + fn[it],
        }
        f1_scores.append(f1)

    macro_f1 = sum(f1_scores) / len(f1_scores) if f1_scores else 0
    return {
        "total_queries": len(results),
        "overall_accuracy": round(accuracy, 4),
        "macro_f1": round(macro_f1, 4),
        "per_intent": intent_report,
        "results": results,
    }


async def run() -> dict | None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    if not GOLDEN_FILE.exists():
        logger.error(f"Golden dataset not found: {GOLDEN_FILE}")
        return

    with open(GOLDEN_FILE) as f:
        dataset = json.load(f)

    # Cache for metadata/markdown to avoid redundant loads
    doc_cache = {}

    results = []
    total = len(dataset)
    
    logger.info(f"Starting evaluation of {total} queries with {COOLDOWN_SECONDS}s cooldown...")

    for i, case in enumerate(dataset):
        doc_id = case["doc_id"]
        prompt = case["prompt"]
        expected = case["expected_intent"]
        
        # Load doc data if not in cache
        if doc_id not in doc_cache:
            metadata_path = PARSED_DIR / f"{doc_id}_metadata.json"
            if not metadata_path.exists():
                logger.error(f"Metadata missing for {doc_id}. Run llamaparse_eval.py first.")
                continue
            with open(metadata_path) as f:
                raw_metadata = json.load(f)
            doc_cache[doc_id] = raw_metadata

        metadata = doc_cache[doc_id]
        
        # Enforce "Starve the Router" metadata pruning (as in main.py)
        routing_metadata = {
            "page_count": metadata.get("page_count", 0),
            "likely_has_tables": metadata.get("likely_has_tables", False),
            "text_preview": metadata.get("text_preview", ""),
            "doc_type_hint": metadata.get("doc_type_hint", "unknown"),
        }

        # 5-second cooldown (skip on first request)
        if i > 0:
            logger.info(f"Cooldown for {COOLDOWN_SECONDS}s...")
            await asyncio.sleep(COOLDOWN_SECONDS)

        logger.info(f"[{i+1}/{total}] Prompt: '{prompt}' (Doc: {doc_id})")
        
        t0 = time.perf_counter()
        try:
            decision: RoutingDecision = await route(prompt, routing_metadata)
            predicted = decision.intent
            confidence = decision.confidence
            reasoning = decision.reasoning
        except Exception as e:
            logger.error(f"Router error: {e}")
            predicted = "error"
            confidence = 0.0
            reasoning = str(e)
        
        latency = (time.perf_counter() - t0) * 1000
        
        results.append({
            "doc_id": doc_id,
            "prompt": prompt,
            "expected": expected,
            "predicted": predicted,
            "correct": (predicted == expected),
            "confidence": confidence,
            "reasoning": reasoning,
            "latency_ms": latency
        })

    final_report = {
        "timestamp": datetime.now().isoformat(),
        **aggregate(results),
    }

    # Save Report
    report_path = RESULTS_DIR / f"routing_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(report_path, "w") as f:
        json.dump(final_report, f, indent=2)

    # Print Summary Table
    print("\n" + "="*60)
    print(f"ROUTING ACCURACY REPORT - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)
    print(f"Overall Accuracy: {final_report['overall_accuracy']:.4f}")
    print(f"Macro F1-Score:   {final_report['macro_f1']:.4f}")
    print("-" * 60)
    print(f"{'Intent':<15} | {'Prec':<8} | {'Rec':<8} | {'F1':<8} | {'Count':<5}")
    print("-" * 60)
    for it, metrics in final_report["per_intent"].items():
        print(f"{it:<15} | {metrics['precision']:<8.4f} | {metrics['recall']:<8.4f} | {metrics['f1']:<8.4f} | {metrics['count']:<5}")
    print("="*60)
    print(f"Full report saved to: {report_path}\n")
    return final_report

if __name__ == "__main__":
    asyncio.run(run())
