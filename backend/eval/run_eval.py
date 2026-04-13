"""
eval/run_eval.py — FDIP Evaluation Suite Orchestrator.

Runs the live document/session metrics against the 6 sample documents via the
API on localhost:8000. Routing accuracy is evaluated separately by
backend/eval/metrics/routing_accuracy.py against fixtures/golden_dataset.json.

Usage:
    source backend/venv/bin/activate
    export PYTHONPATH=./backend
    python backend/eval/run_eval.py [OPTIONS]

Options:
    --suite   simple | varied | both   (default: simple)
    --metrics all | pii | groundedness | fidelity | latency  (default: all)
    --cooldown-docs   N   Seconds between document uploads (default: 90)
    --cooldown-chats  N   Seconds between chat requests within a document (default: 12)
    --dry-run             Validate fixtures only, no API calls
    --output  PATH        Directory for results JSON (default: backend/eval/results/)

Rate limit guidance:
    - Groq Free Tier  : ~30 req/min, 6000 tokens/min. With 12s cooldown between
                         chats and 90s between docs, we stay well within limits.
    - Cerebras        : Similar limits. The pipeline handles its own retry logic.
    - LlamaParse      : Async polling with 3s intervals; 90s doc cooldown prevents
                         concurrent jobs from hitting queue limits.
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

import httpx

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
EVAL_DIR     = Path(__file__).parent
BACKEND_ROOT = EVAL_DIR.parent
REPO_ROOT    = BACKEND_ROOT.parent
SAMPLE_DOCS  = REPO_ROOT / "parser_tests" / "sample_docs" / "sample-docs"
FIXTURES_DIR = EVAL_DIR / "fixtures"
RESULTS_DIR  = EVAL_DIR / "results"

sys.path.insert(0, str(BACKEND_ROOT))

from eval.api_client import upload_and_wait, health_check
from eval.metrics import pii_safety, extraction_fidelity, groundedness, latency

LIVE_METRICS = {"pii", "groundedness", "fidelity", "latency"}


# ---------------------------------------------------------------------------
# Ground truth loader
# ---------------------------------------------------------------------------

def load_ground_truth() -> list:
    gt_path = FIXTURES_DIR / "ground_truth.json"
    with open(gt_path) as f:
        data = json.load(f)
    return data["documents"]


# ---------------------------------------------------------------------------
# Pretty printer
# ---------------------------------------------------------------------------

def _hr(char="─", width=70):
    print(char * width)


def _fmt_pct(value, precision=2) -> str:
    return f"{value:.{precision}%}" if isinstance(value, (int, float)) else "N/A"


def _select_extraction_cases(doc: dict, suite: str) -> list:
    if suite == "varied":
        return doc.get("varied_extraction", doc.get("simple_extraction", []))
    if suite == "both":
        return doc.get("simple_extraction", []) + doc.get("varied_extraction", [])
    return doc.get("simple_extraction", [])


def _parse_metrics_filter(metrics_filter: str) -> set[str]:
    if metrics_filter == "all":
        return set(LIVE_METRICS)

    requested = {m.strip().lower() for m in metrics_filter.split(",") if m.strip()}
    if "routing" in requested:
        raise ValueError(
            "routing is a standalone metric; run "
            "python backend/eval/metrics/routing_accuracy.py"
        )

    unknown = requested - LIVE_METRICS
    if unknown:
        raise ValueError(f"unknown metric(s): {', '.join(sorted(unknown))}")

    if "groundedness" in requested and "fidelity" not in requested:
        print("  [metrics] Groundedness requires extraction responses; enabling fidelity.")
        requested.add("fidelity")

    return requested


def _print_summary(report: dict):
    _hr("═")
    print("  FDIP EVALUATION SUITE — RESULTS SUMMARY")
    print(f"  Run at: {report['timestamp']}")
    print(f"  Suite: {report['suite']} | Documents: {report['doc_count']}")
    _hr("═")

    m = report["metrics"]

    print("\n  1. PII SAFETY SCORE (Lifecycle Integrity)")
    _hr()
    ps = m.get("pii_safety", {})
    print(f"     Safety Score       : {_fmt_pct(ps.get('pii_safety_score'))}   TARGET = 100%")
    print(f"     Scrub Recall       : {_fmt_pct(ps.get('avg_scrub_recall'))}")
    print(f"     Rehydration Success: {_fmt_pct(ps.get('avg_rehydration_success'))}")

    print("\n  2. EXTRACTION GROUNDEDNESS (Faithfulness, 3k source excerpt)")
    _hr()
    gn = m.get("groundedness", {})
    gs = gn.get("global_faithfulness_score")
    print(f"     Global Faithfulness: {gs:.2%}   TARGET ≥ 0.85" if gs is not None else "     Groundedness: N/A")

    print("\n  3. EXTRACTION FIDELITY (Value Accuracy)")
    _hr()
    ef = m.get("extraction_fidelity", {})
    print(f"     Fidelity Score : {_fmt_pct(ef.get('overall_fidelity_score'))}   TARGET ≥ 0.90")
    print(f"     Matched        : {ef.get('matched', 'N/A')} / {ef.get('total_cases', 'N/A')}")
    if "by_field_type" in ef:
        for ft, s in ef["by_field_type"].items():
            print(f"       {ft:10s}: {s['matched']}/{s['total']} ({s['score']:.0%})")

    print("\n  4. PIPELINE LATENCY")
    _hr()
    lt = m.get("latency", {})
    print(f"     TTFT P50 : {lt.get('ttft_p50_ms', 'N/A')} ms   TARGET < 800ms")
    print(f"     TTFT P95 : {lt.get('ttft_p95_ms', 'N/A')} ms")
    print(f"     TTFT Avg : {lt.get('ttft_avg_ms', 'N/A')} ms")
    if "parse" in lt:
        print(f"     Parse Avg: {lt['parse'].get('avg_ms', 'N/A')} ms")
        parsers = lt["parse"].get("by_parser_avg_s", {})
        for p, s in parsers.items():
            print(f"       {p:25s}: {s*1000:.0f} ms avg")
    print()
    _hr("═")


# ---------------------------------------------------------------------------
# Core orchestration
# ---------------------------------------------------------------------------

async def run_eval(
    suite: str = "simple",
    metrics_filter: str = "all",
    cooldown_docs: float = 90.0,
    cooldown_chats: float = 12.0,
    dry_run: bool = False,
    output_dir: Path = RESULTS_DIR,
):
    print(f"\n{'='*70}")
    print(f"  FDIP Evaluation Suite   suite={suite}  metrics={metrics_filter}")
    print(f"  cooldown_docs={cooldown_docs}s  cooldown_chats={cooldown_chats}s")
    print(f"{'='*70}\n")

    documents = load_ground_truth()
    run_metrics = _parse_metrics_filter(metrics_filter.lower())

    if dry_run:
        print("[DRY RUN] Fixtures loaded successfully:")
        for doc in documents:
            cases = _select_extraction_cases(doc, suite)
            print(f"  {doc['id']:12s}  type={doc['document_type']:25s}  "
                  f"extraction_cases={len(cases)}  "
                  f"intent_cases={len(doc.get('intent_cases', []))}  "
                  f"pii_expected={len(doc.get('expected_pii', []))}")
        print("\n[DRY RUN] No API calls made. Exiting.")
        return

    # Health check
    if not await health_check():
        print("ERROR: Backend is not running on http://localhost:8000")
        print("       Start it with: ./start_backend.sh")
        sys.exit(1)
    print("✓ Backend is reachable\n")

    # ── Session results store ──────────────────────────────────────────────
    session_map: dict[str, str] = {}      # doc_id → session_id
    upload_results: dict[str, object] = {}
    extraction_responses: dict[str, list] = {}  # doc_id → [response_text, ...]

    pii_scrub_per_doc   = []
    pii_rehydrate_per_doc = []
    fidelity_per_doc    = []
    groundedness_per_doc = []
    parse_latencies     = []
    chat_latencies      = []

    async with httpx.AsyncClient(timeout=300.0) as client:

        # ── Phase 1: Upload all documents ──────────────────────────────────
        print("PHASE 1: Uploading documents")
        _hr()
        for i, doc in enumerate(documents):
            if i > 0:
                print(f"  [cooldown] Waiting {cooldown_docs}s between document uploads...")
                await asyncio.sleep(cooldown_docs)

            pdf_path = SAMPLE_DOCS / doc["filename"]
            if not pdf_path.exists():
                print(f"  ✗ {doc['id']}: PDF not found at {pdf_path}")
                continue

            print(f"  Uploading {doc['id']} ({doc['filename']})...", end=" ", flush=True)
            try:
                upload_res = await upload_and_wait(pdf_path, client)
                session_map[doc["id"]] = upload_res.session_id
                upload_results[doc["id"]] = upload_res

                lat_rec = latency.record_parse_latency(upload_res)
                lat_rec["doc_id"] = doc["id"]
                parse_latencies.append(lat_rec)

                print(f"✓  parser={upload_res.parser_used}  "
                      f"pages={upload_res.page_count}  "
                      f"parse={upload_res.parse_wall_s:.1f}s")
            except Exception as exc:
                print(f"✗ FAILED: {exc}")
                continue

        _hr()
        print(f"  Sessions ready: {len(session_map)}/{len(documents)}\n")

        # ── Phase 2: Run chat-based metrics per document ───────────────────
        print("PHASE 2: Running live evaluation metrics")
        _hr()

        for i, doc in enumerate(documents):
            doc_id = doc["id"]
            session_id = session_map.get(doc_id)
            if not session_id:
                print(f"  Skipping {doc_id} — no session")
                continue

            extraction_cases = _select_extraction_cases(doc, suite)
            expected_pii  = doc.get("expected_pii", [])

            print(f"\n  [{doc_id}] session={session_id[:12]}...")

            # PII scrub check (in-process, no API call)
            if "pii" in run_metrics:
                scrub_result = pii_safety.run_scrub_check(doc_id, expected_pii)
                pii_scrub_per_doc.append(scrub_result)
                print(f"    PII scrub: {scrub_result['detected_count']}/{scrub_result['expected_count']} detected  "
                      f"recall={scrub_result['scrub_recall']:.0%}")

            # Extraction fidelity
            if "fidelity" in run_metrics:
                print(f"    Running {len(extraction_cases)} extraction cases...")
                fid_result = await extraction_fidelity.run(
                    session_id, extraction_cases, client, cooldown_s=cooldown_chats
                )
                fidelity_per_doc.append({"doc_id": doc_id, **fid_result})
                # Save responses for groundedness
                extraction_responses[doc_id] = [c.get("predicted", "") for c in fid_result["cases"]]
                print(f"    Fidelity: {fid_result['match_count']}/{fid_result['total']} "
                      f"({fid_result['fidelity_score']:.0%})")
                # Collect latency from extraction cases
                for case in fid_result["cases"]:
                    if case.get("ttft_s") is not None:
                        chat_latencies.append({
                            "ttft_s":         case["ttft_s"],
                            "ttft_ms":        round(case["ttft_s"] * 1000, 1),
                            "total_stream_s": case.get("total_stream_s", 0),
                            "total_stream_ms": round(case.get("total_stream_s", 0) * 1000, 1),
                            "e2e_s":          case.get("e2e_s", 0),
                            "e2e_ms":         round(case.get("e2e_s", 0) * 1000, 1),
                            "intent":         "extraction",
                            "parser_used":    upload_results.get(doc_id, {}).parser_used if doc_id in upload_results else None,
                        })

            # PII rehydration check
            if "pii" in run_metrics and expected_pii:
                print(f"    Running PII rehydration check...")
                await asyncio.sleep(cooldown_chats)
                reh_result = await pii_safety.run_rehydration_check(
                    doc_id, session_id, expected_pii, client, cooldown_s=cooldown_chats
                )
                pii_rehydrate_per_doc.append(reh_result)
                print(f"    Rehydration: {reh_result['rehydrated_count']}/{reh_result['expected_count']}")

        # ── Phase 3: Groundedness (requires extraction responses) ──────────
        if "groundedness" in run_metrics:
            print("\nPHASE 3: Groundedness evaluation (LLM-as-Judge via Groq)")
            _hr()
            for i, doc in enumerate(documents):
                doc_id = doc["id"]
                if doc_id not in extraction_responses:
                    continue

                extraction_cases = _select_extraction_cases(doc, suite)
                responses = extraction_responses[doc_id]
                if not responses:
                    continue

                if i > 0:
                    print(f"  [cooldown] Waiting {cooldown_docs}s before next document groundedness...")
                    await asyncio.sleep(cooldown_docs)

                print(f"  Judging {doc_id} ({len(responses)} responses)...", end=" ", flush=True)
                gnd_result = await groundedness.run(
                    doc_id, extraction_cases, responses, cooldown_s=cooldown_chats * 2
                )
                groundedness_per_doc.append(gnd_result)
                score = gnd_result.get("faithfulness_score")
                print(f"faithfulness={score:.0%}" if score is not None else "source not found")

    # ── Aggregate results ──────────────────────────────────────────────────
    print("\nAGGREGATING RESULTS")
    _hr()
    report = {
        "timestamp":   datetime.now().isoformat(),
        "suite":       suite,
        "metrics_filter": sorted(run_metrics),
        "doc_count":   len(session_map),
        "metrics": {
            "pii_safety":         pii_safety.aggregate(pii_scrub_per_doc, pii_rehydrate_per_doc) if "pii" in run_metrics else {},
            "groundedness":       groundedness.aggregate(groundedness_per_doc)     if groundedness_per_doc else {},
            "extraction_fidelity": extraction_fidelity.aggregate(fidelity_per_doc) if fidelity_per_doc   else {},
            "latency":            latency.aggregate(parse_latencies, chat_latencies) if "latency" in run_metrics else {},
        },
        "raw": {
            "sessions":          {k: str(v) for k, v in session_map.items()},
            "parse_latencies":   parse_latencies,
        }
    }

    # ── Save results ───────────────────────────────────────────────────────
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = output_dir / f"eval_report_{suite}_{ts}.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"  Report saved → {report_path}")

    # ── Print summary ──────────────────────────────────────────────────────
    _print_summary(report)

    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args():
    p = argparse.ArgumentParser(description="FDIP Evaluation Suite")
    p.add_argument("--suite",          default="simple", choices=["simple", "varied", "both"])
    p.add_argument("--metrics",        default="all",
                   help="Comma-separated: pii,groundedness,fidelity,latency  or  all")
    p.add_argument("--cooldown-docs",  type=float, default=90.0,
                   help="Seconds between document uploads (default: 90)")
    p.add_argument("--cooldown-chats", type=float, default=12.0,
                   help="Seconds between chat requests (default: 12)")
    p.add_argument("--dry-run",        action="store_true")
    p.add_argument("--output",         type=Path, default=RESULTS_DIR)
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    try:
        asyncio.run(run_eval(
            suite          = args.suite,
            metrics_filter = args.metrics,
            cooldown_docs  = args.cooldown_docs,
            cooldown_chats = args.cooldown_chats,
            dry_run        = args.dry_run,
            output_dir     = args.output,
        ))
    except ValueError as exc:
        print(f"ERROR: {exc}")
        sys.exit(2)
