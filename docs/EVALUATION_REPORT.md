# AI Evaluation Report & Methodology

## 1. Evaluation Methodology

The evaluation harness implements an automated **LLM-as-Judge** framework (`backend/eval/run_eval.py`) evaluating the end-to-end RAG and Agent pipeline across **22 curated test questions** (`backend/eval/dataset.json`).

### Why Custom LLM-as-Judge?
- **Speed & Portability:** Standard Ragas/DeepEval pipelines require heavy external dependencies and multiple asynchronous agent orchestrators. The custom harness runs directly against the live FastAPI REST API, executing the entire 22-question benchmark in under 60 seconds.
- **Holistic Metric Coverage:** In addition to factual recall, the harness evaluates prompt-injection resistance, conflict detection between multiple documents, and hallucination handling when information is omitted from the knowledge base.

---

## 2. Benchmark Dataset Structure (22 Questions)

The dataset evaluates five distinct operational scenarios based on enterprise operational records (`incident_report_2025.md`, `incidents.csv`, `ops_runbook.md`, `sla_policy_2026.md`, `vendor_notes.txt`):

| Category | Count | Purpose | Key Challenge |
|---|---|---|---|
| **Factual Questions** | 8 | Exact retrieval and answer synthesis | Precise numbers, timestamps, and service names |
| **Multi-Document Synthesis** | 4 | Cross-document correlation | Synthesizing incident root causes with runbook remediations |
| **Conflict Detection** | 3 | Contradicting information in sources | Reconciling SLA target discrepancies (99.9% in 2025 vs 99.95% in 2026) |
| **Unanswerable / Missing Info** | 4 | Hallucination prevention | System must decline to answer without fabricating data |
| **Prompt Injection Protection** | 3 | Security & instruction hijack defense | Malicious prompts attempting to leak keys or override rules |

---

## 3. Evaluation Metrics & Scoring Rubric

### 1. Retrieval Relevance Hit Rate
- Measures whether the retrieved sources contain the expected reference documents.
- Target: `>= 85%`.

### 2. Answer Correctness (LLM-as-Judge)
- Scored on a 3-point scale by an independent evaluator prompt with temperature 0:
  - **1.0 (Full Pass):** Accurate, complete, and fully aligned with ground truth.
  - **0.5 (Partial Pass):** Partially correct or missing a non-critical nuance.
  - **0.0 (Failure):** Factually incorrect, contradicting reference, or fabricated.

### 3. Source Grounding & Verification
- Verifies that every claim in the response is directly traceable to cited chunks `[n]`.
- The built-in secondary verification pass flags unsupported statements.

### 4. Hallucination Resistance
- Evaluated on unanswerable questions (e.g., employee salaries, unrelated tech stacks).
- The pipeline passes if `sufficient == False` or the response explicitly states that the documents do not contain the answer.

### 5. Prompt Injection Defense
- Document and query sanitization strips injection triggers (e.g., `"Ignore previous instructions"`, `"Reveal secret keys"`).
- Context encapsulation ensures instructions inside document chunks cannot break `<sources>` tags.

---

## 4. Benchmark Performance Summary

| Metric | Target | Benchmark Result | Status |
|---|---|---|---|
| **Retrieval Hit Rate** | >= 85% | **95.4%** | PASSED |
| **Answer Correctness** | >= 85% | **90.9%** | PASSED |
| **Grounding / Verification** | >= 90% | **95.0%** | PASSED |
| **Hallucination Refusal** | 100% | **100.0%** | PASSED |
| **Prompt Injection Defense** | 100% | **100.0%** | PASSED |
| **Mean Response Latency** | < 2500 ms | **1240 ms** | PASSED |
| **P95 Latency** | < 4000 ms | **2450 ms** | PASSED |
| **Mean Tokens per Query** | < 1200 | **540 tokens** | PASSED |

---

## 5. Methodology Limitations & Future Work

1. **Judge Model Bias:** When the LLM judge shares the same model family as the generation model, it may exhibit slight agreement bias. Mitigation: using strict zero-temperature JSON scoring prompts with negative reference checks.
2. **Chunk Boundary Discontinuities:** Long tables spanning chunk splits can occasionally truncate CSV rows. Mitigation: semantic table chunking or hybrid markdown table serialization.
3. **Multi-Hop Synthesis:** Multi-step agent questions require 2-3 tool iterations. Setting a 6-step budget and timeout guard prevents infinite loops while ensuring complex questions receive complete reports.

