"""Retrieval: Weaviate hybrid search (BM25 + vectors) followed by a cosine relevance gate and rerank."""
from app.config import settings
from app.services import vectorstore
from app.services.embeddings import embed_query, cosine


def retrieve(question: str, user_id: int, document_ids: list[int] | None = None, k: int | None = None) -> list[dict]:
    k = k or settings.TOP_K
    qv = embed_query(question)
    hits = vectorstore.hybrid_search(question, qv, user_id, limit=k * 3, document_ids=document_ids)
    scored = []
    for h in hits:
        sim = cosine(qv, h["vector"]) if h.get("vector") is not None else 0.0
        scored.append({"document_id": h["document_id"], "filename": h["filename"], "page": h["page"],
                       "chunk_index": h["chunk_index"], "content": h["content"], "score": round(sim, 4)})
    # Relevance gate: chunks below MIN_RELEVANCE are treated as irrelevant -> answer can become "insufficient info"
    scored = [s for s in scored if s["score"] >= settings.MIN_RELEVANCE]
    scored.sort(key=lambda s: -s["score"])  # rerank by true semantic similarity
    top = scored[:k]
    for i, c in enumerate(top, 1):
        c["n"] = i
    return top
