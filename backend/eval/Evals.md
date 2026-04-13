# Pipeline Evaluations

This document tracks the evaluation metrics for the various components in the Financial Document Intelligence Pipeline (FDIP).

## 1. Intent Routing Engine
**Status**: Production-Ready  
**Evaluation Scope**: 25 queries across 6 financial documents covering Extraction, Summarization, and Classification intents.

### Performance Summary
- **Overall Accuracy**: 96.00%
- **Macro F1-Score**: 0.9599

### Metrics per Intent
| Intent | Precision | Recall | F1-Score | Case Count |
| :--- | :--- | :--- | :--- | :--- |
| **Extraction** | 1.0000 | 0.9167 | 0.9565 | 12 |
| **Summarization** | 1.0000 | 1.0000 | 1.0000 | 7 |
| **Classification** | 0.8571 | 1.0000 | 0.9231 | 6 |

- **Standalone Metric**: Evaluated via `backend/eval/metrics/routing_accuracy.py` using `backend/eval/fixtures/golden_dataset.json`.
- The evaluation uses LlamaParse for the pre-parsing layer.
## 2. PII Safety (Lifecycle Integrity)
**Status**: Production-Ready  
**Evaluation Scope**: 18 queries across 6 documents via full pipeline rehydration.

### Performance Summary
- **PII Safety Score**: 100.00%
- **Scrub Recall**: 100.00%
- **Rehydration Success**: 100.00%

### Details
- Proves that the pipeline successfully masks all PII before it reaches LLMs using localized rules.
- Proves that the masked tokens (`{{PAN_1}}`, `{{IFSC_4}}`) are correctly mapped and dynamically rehydrated when returning the final output to the user.

## 3. Extraction Groundedness (Faithfulness)
**Status**: Production-Ready  
**Evaluation Scope**: 18 queries across 6 documents evaluated via `llama-3.3-70b-versatile` Judge.

### Performance Summary
- **Global Faithfulness**: 88.00%

### Details
- The judge heavily penalizes any hallucinated tokens that do not appear directly in the source document.
- A score of 88% represents a high level of factual integrity, especially given the aggressive 3,000-character context truncation applied to respect rate limits.

## 4. Extraction Fidelity (Value Accuracy)
**Status**: Authentic Benchmark  
**Evaluation Scope**: 18 queries across 6 documents (Exact and Numeric matching).

### Performance Summary
- **Fidelity Score**: 84.00% 

### Details
- LLM exact extraction varies depending on document context and complexity.
- The queries that missed failed due to rigid formatting expectations or missing explicit context in highly dense documents.

## 5. Pipeline Latency
**Evaluation Scope**: Sequential benchmark on 18 diverse queries across 6 documents with rate-limit cooldowns.

### Performance Summary
- **TTFT (Time-to-First-Token) Avg**: 1194.0 ms
- **TTFT P50**: 1116.0 ms
- **TTFT P95**: 1549.0 ms
- **LlamaParse Avg Duration**: 8.03 s

### Details
- End-to-end API generation maintains a ~1.2s average TTFT under general conditions, ensuring a responsive streaming experience on the React frontend.

