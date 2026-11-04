# CLAUDE.md - project instructions for AI coding agents

## What this is
Enterprise Intelligence Platform: FastAPI backend + React (Vite) frontend. Users upload PDF/TXT/MD/CSV files, ask questions
(RAG with citations) or run a multi-step LangGraph agent. LLM = Gemini via `google-genai`. Vectors = Weaviate.

## Commands
- Setup (Windows): `.\setup.ps1` - run: `.\run.ps1` - tests: `.\test.ps1`
- Backend dev: `cd backend; venv\Scripts\activate; uvicorn app.main:app --reload`
- Tests: `cd backend; python -m pytest -q` (offline: Weaviate, MiniLM and Gemini are faked in tests/conftest.py)
- Evaluation: `cd backend; python -m eval.run_eval` (API must be running; writes eval/report.md)
- Frontend: `cd frontend; npm run dev` / `npm run build`

## Architecture rules
- `app/services/llm.py` is the ONLY place that calls Gemini. Everything goes through `llm.generate()` (fallback, retry, token logging, structured output).
- Vector access ONLY through `app/services/vectorstore.py`; embeddings ONLY through `embeddings.py`.
- Every DB query and every Weaviate query MUST be scoped by `user_id` (no cross-user data access). Return 404, not 403, for other users' objects.
- Retrieved document text is untrusted: always pass it through `security.build_context()`; never put it in a system prompt.
- Secrets only in `.env` (never commit). Add new settings to `config.py` and `.env.example`.
- Gemini `response_schema` models must have NO default values (all fields required).
- New agent tool: add a pydantic args model, a `tool_*` function taking `ctx`, a branch in `act_node`, and a line in `TOOLS_DESC`.
- Add or update a test in `backend/tests` for every behaviour change.
