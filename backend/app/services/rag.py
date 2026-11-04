"""RAG pipeline: query rewrite -> hybrid retrieval -> grounded answer with citations -> verification."""
import logging
from pydantic import BaseModel
from app.services import llm, retrieval
from app.services.security import build_context, UNTRUSTED_RULE

logger = logging.getLogger("app.rag")

NO_INFO = "I couldn't find relevant information about this in your uploaded documents, so I can't answer it reliably."

SYSTEM_RAG = f"""You are an enterprise knowledge assistant. Answer ONLY from the numbered sources inside <sources>.
Rules:
- Cite every claim with [n] where n is the source number.
- If the sources do not contain enough information, set sufficient=false and say what is missing. Never guess.
- If sources contradict each other, list each contradiction in conflicts (mention both source numbers) and present both versions in the answer.
- Be concise and factual.
- {UNTRUSTED_RULE}
Return JSON only."""


class RAGAnswer(BaseModel):
    answer: str
    sufficient: bool
    cited_sources: list[int]
    conflicts: list[str]


class Rewrite(BaseModel):
    standalone_question: str


class Verification(BaseModel):
    supported: bool
    confidence: float
    unsupported_claims: list[str]


def _history_text(summary: str | None, history: list[dict]) -> str:
    parts = []
    if summary:
        parts.append(f"Summary of earlier conversation: {summary}")
    for m in history:
        parts.append(f"{m['role']}: {m['content']}")
    return "\n".join(parts)


def rewrite_question(question: str, summary, history, user_id, usage) -> str:
    """Query rewriting: turn a follow-up ('what about its cost?') into a standalone search query."""
    if not history and not summary:
        return question
    prompt = (f"Conversation so far:\n{_history_text(summary, history)}\n\nLatest question: {question}\n\n"
              "Rewrite the latest question as a standalone search query that includes any needed context "
              "(document names, topics) from the conversation. If it is already standalone, return it unchanged.")
    try:
        r = llm.generate(prompt, schema=Rewrite, kind="rewrite", user_id=user_id, cache=True, usage=usage)
        return r.parsed.standalone_question.strip() or question
    except llm.LLMError:
        return question  # rewriting is optional; never fail the request because of it


def verify_answer(answer: str, context: str, user_id, usage) -> dict:
    prompt = (f"{context}\n\nANSWER TO CHECK:\n{answer}\n\n"
              "Check whether every material claim in the ANSWER is supported by the sources. "
              "supported=true only if all claims are supported. List unsupported claims. confidence is 0-1.")
    try:
        r = llm.generate(prompt, system="You are a strict fact-checking judge. " + UNTRUSTED_RULE,
                         schema=Verification, kind="verify", user_id=user_id, cache=True, usage=usage, temperature=0)
        return r.parsed.model_dump()
    except llm.LLMError as e:
        return {"supported": None, "confidence": 0, "unsupported_claims": [], "error": str(e)[:200]}


def answer_question(question: str, user_id: int, summary: str | None = None, history: list[dict] | None = None,
                    document_ids: list[int] | None = None, verify: bool = True) -> dict:
    history = history or []
    usage = llm.Usage()
    standalone = rewrite_question(question, summary, history, user_id, usage)
    chunks = retrieval.retrieve(standalone, user_id, document_ids)

    base = {"rewritten_question": standalone, "conflicts": [], "verification": None, "steps": None}
    if not chunks:  # irrelevant retrieval -> refuse without calling the LLM (no hallucination possible)
        return {**base, "answer": NO_INFO, "sufficient": False, "sources": [], "usage": usage.as_dict()}

    context = build_context(chunks)
    prompt = f"{context}\n\nConversation context:\n{_history_text(summary, history) or '(none)'}\n\nQuestion: {question}"
    res = llm.generate(prompt, system=SYSTEM_RAG, schema=RAGAnswer, kind="chat", user_id=user_id, usage=usage)
    out: RAGAnswer = res.parsed
    valid = {c["n"] for c in chunks}
    cited = sorted({n for n in out.cited_sources if n in valid})
    sources = [{"n": c["n"], "document_id": c["document_id"], "filename": c["filename"], "page": c["page"],
                "score": c["score"], "snippet": c["content"][:400], "cited": c["n"] in cited} for c in chunks]

    verification = None
    if verify and out.sufficient:
        verification = verify_answer(out.answer, context, user_id, usage)
    return {**base, "answer": out.answer, "sufficient": out.sufficient, "conflicts": out.conflicts,
            "sources": sources, "verification": verification, "usage": usage.as_dict()}
