# Enterprise Intelligence Platform — Development & AI Tool Disclosure Report

## 1. Executive Summary & Architectural Overview
This report documents the architectural decisions, AI coding assistant usage, generated code anomalies identified and fixed, and testing/validation methodology for the **AI-Powered Enterprise Intelligence Platform**.

The platform is designed to ingest multi-format enterprise documentation (PDF, Markdown, TXT, CSV), extract and chunk text with overlapping sliding windows, index embeddings into Weaviate using local `sentence-transformers/all-MiniLM-L6-v2` vectors, perform hybrid BM25 + dense semantic retrieval with cosine relevance gating, and execute multi-step analytical reasoning via a LangGraph state machine.

---

## 2. AI Tool Usage Disclosure (Assessment Rule 2)

| Tool | Tasks Delegated | Human Engineering Oversight & Validation |
|---|---|---|
| **Claude / Antigravity Agent** | Scaffolding FastAPI routes, LangGraph node transitions, React components, and evaluation harness skeleton. | Verified all typing, state immutability, Pydantic v2 validation contracts, database indices, and token counting logic. |
| **Google Gemini 3.8 / Flash** | Code review, edge case identification, query rewriting prompts, and LLM-as-judge evaluation scoring. | Independently designed fallback retry mechanism, prompt-injection defense heuristics, and relevance thresholding. |

### Tasks Delegated vs. Independent Engineering Decisions
- **Delegated to AI:**
  - Generating initial boilerplate Pydantic models for chat requests and document metadata.
  - Generating the React component layout for the dashboard, documents table, and chat bubbles.
  - Authoring the initial 22-question evaluation dataset based on provided sample incidents and runbooks.
- **Engineered Independently:**
  - **Dual-Mode Vector Store Architecture:** Implemented a resilient hybrid store in `vectorstore.py` that queries Weaviate Cloud when credentials are configured, and automatically falls back to an in-memory/local hybrid search (BM25 token overlap + MiniLM cosine similarity) if remote clusters are offline or unconfigured.
  - **Intelligent LLM Fallback:** Designed the two-tier model invocation in `llm.py` (`gemini-3.5-flash` primary -> retry on 429/500/503 -> switch to `gemini-2.5-flash` secondary), with token usage accumulation across graph steps.
  - **Agent State Graph & Reliability:** Designed the LangGraph execution cycle (`plan_node` -> `act_node` -> `plan_node` -> `finish_node`), with step budgets, per-tool timeouts, duplicate tool-call prevention, and Pydantic parameter validation recovery.
  - **Prompt Injection Defense:** Implemented the untrusted source isolation boundary where retrieved document text is stripped of delimiters, flagged for prompt hijacking keywords, and encased in strict `<sources>` boundaries.

---

## 3. Errors in Generated Code Identified & Resolved (Assessment Rule 5)

1. **LangGraph State Loss Across Chained Tools:**
   - *Issue Identified:* Early generated code attempted to store mutated tool outputs (such as retrieved evidence chunks, structured analysis, and generated reports) inside LangGraph's functional state dictionary between node transitions. Because LangGraph passes state copies, nested state mutations were lost before subsequent tool steps could consume them.
   - *Resolution:* Implemented a shared execution context dictionary (`ctx = {"evidence": [], "analysis": None, "report": None}`) initialized in `run_agent()`. Tools write directly into this context, ensuring that `document_analysis` receives the exact evidence accumulated by `knowledge_search`, and `generate_report` consumes the exact themes output by `document_analysis`.

2. **Relevance Thresholding in Test Fixtures:**
   - *Issue Identified:* In `test_agent_multi_step_chains_tools`, the mock search query (`"failure causes pool"`) against the incident document had a mock vector cosine score of `0.21`, which fell below the production `MIN_RELEVANCE = 0.25` cosine gate. This caused the search tool to return 0 chunks, leaving evidence empty and causing subsequent analysis steps to fail.
   - *Resolution:* Updated test query phrasing to reflect full semantic intent (`"most common cause of failures database pool exhaustion"`), resulting in high cosine similarity (`0.687`), properly passing the gate and verifying the full multi-step tool chain.

3. **Python 3.13 Windows DLL & Environment Resolution:**
   - *Issue Identified:* On Windows 11 with split Python installations, virtual environments failed to import `_socket` and `_ssl` due to missing C-extension `.pyd` modules in the isolated binary path.
   - *Resolution:* Consolidated standard library packages, scripts, and DLLs into a clean workspace environment (`D:\Desktop\ai_project\venv`), verified pip wheels, and added resilient execution paths in `run.ps1` and `test.ps1`.

4. **Datetime UTC Deprecation:**
   - *Issue Identified:* `datetime.datetime.utcnow()` triggered Python 3.13 deprecation warnings in stats calculation.
   - *Resolution:* Replaced with timezone-aware `datetime.now(timezone.utc).replace(tzinfo=None)`.

---

## 4. Architectural Decisions & Trade-Offs

1. **Why `all-MiniLM-L6-v2` via `fastembed`?**
   - MiniLM produces high-quality 384-dimensional dense vectors with negligible latency (~8ms per chunk on CPU). Using FastEmbed (ONNX runtime) eliminates heavy PyTorch dependencies (~2GB), allowing the application to start instantly, run in constrained serverless containers, and operate with zero GPU overhead.

2. **Why Weaviate for Vector Database?**
   - Weaviate provides native hybrid search fusing BM25 keyword matching with dense vector cosine similarity via Reciprocal Rank Fusion (RRF) at parameter `alpha=0.6`. This ensures that exact identifiers (e.g., error codes `INC-002`, service names `pgbouncer`) are retrieved with high precision while semantic queries benefit from embedding similarity.

3. **Why Custom LangGraph State Machine?**
   - LangGraph provides a cyclical directed graph where the agent's plan, tool execution, argument validation, and termination conditions are transparent and deterministic. The execution step history is returned to the user in the API response, allowing the React UI to render an expandable timeline of agent thoughts, tool arguments, and execution durations.

---

## 5. Verification & Testing

- **Automated Unit & Integration Tests:** 11 comprehensive tests in `backend/tests/test_api.py` covering:
  - User authentication, JWT issuance, password hashing, and route protection.
  - Document upload, deduplication by SHA-256 hash, and file validation.
  - Multi-tenant document isolation between distinct user IDs.
  - Text chunking sliding-window logic.
  - Prompt injection sanitization and context boundary enforcement.
  - RAG refusal on irrelevant queries (hallucination prevention).
  - Cited RAG answers and verification scoring.
  - Intelligent LLM fallback on 429 rate limits.
  - Fallback on invalid structured JSON output.
  - LangGraph multi-step tool chaining (`knowledge_search` -> `document_analysis` -> `generate_report`).
  - Conversational memory and rolling token metrics.
- **Test Command:**
  ```powershell
  powershell -ExecutionPolicy Bypass -File .\test.ps1
  ```
  **Result:** 11 passed, 0 failures in 9.49s.
