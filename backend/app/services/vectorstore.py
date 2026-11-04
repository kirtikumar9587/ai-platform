"""Weaviate vector store with resilient fallback.
Supports Weaviate Cloud (WCD) and local Weaviate instances.
If Weaviate is not yet configured or temporarily unreachable, falls back to a high-speed local store."""
import json
import logging
import os
import re
from pathlib import Path
import numpy as np
from app.config import settings

logger = logging.getLogger("app.vectorstore")
_client = None
_weaviate_enabled = None
_fallback_store: list[dict] = []
_fallback_file = Path(settings.UPLOAD_DIR) / "vector_fallback_store.json"

PROPS = ["user_id", "document_id", "filename", "chunk_index", "page", "content"]


def _load_fallback():
    global _fallback_store
    if _fallback_file.exists():
        try:
            with open(_fallback_file, "r", encoding="utf-8") as f:
                _fallback_store = json.load(f)
        except Exception:
            pass


def _save_fallback():
    try:
        _fallback_file.parent.mkdir(parents=True, exist_ok=True)
        with open(_fallback_file, "w", encoding="utf-8") as f:
            json.dump(_fallback_store, f)
    except Exception as e:
        logger.warning("Could not persist fallback vector store: %s", e)


_load_fallback()


def _connect():
    global _weaviate_enabled
    if settings.WEAVIATE_API_KEY and settings.WEAVIATE_URL:
        try:
            import weaviate
            from weaviate.classes.init import Auth
            url = settings.WEAVIATE_URL.strip()
            if not url.startswith("http"):
                url = "https://" + url
            cl = weaviate.connect_to_weaviate_cloud(
                cluster_url=url,
                auth_credentials=Auth.api_key(settings.WEAVIATE_API_KEY),
                skip_init_checks=True
            )
            if cl.is_live():
                _weaviate_enabled = True
                logger.info("Connected to Weaviate Cloud at %s", url)
                return cl
        except Exception as e:
            logger.warning("Failed to connect to Weaviate Cloud: %s. Using local store fallback.", e)
            _weaviate_enabled = False
            return None

    # Check local Weaviate if explicitly requested or default
    try:
        import weaviate
        cl = weaviate.connect_to_local(skip_init_checks=True)
        if cl.is_live():
            _weaviate_enabled = True
            logger.info("Connected to local Weaviate instance.")
            return cl
    except Exception:
        pass

    _weaviate_enabled = False
    logger.info("Weaviate credentials not set or cluster unreachable. Using local vector store fallback.")
    return None


def _ensure_collection(c):
    if c is None:
        return
    try:
        from weaviate.classes.config import Configure, Property, DataType
        name = settings.WEAVIATE_COLLECTION
        if c.collections.exists(name):
            return
        kwargs = {}
        if hasattr(Configure, "Vectors"):
            kwargs["vector_config"] = Configure.Vectors.self_provided()
        else:
            kwargs["vectorizer_config"] = Configure.Vectorizer.none()
        c.collections.create(
            name,
            properties=[
                Property(name="user_id", data_type=DataType.INT),
                Property(name="document_id", data_type=DataType.INT),
                Property(name="filename", data_type=DataType.TEXT),
                Property(name="chunk_index", data_type=DataType.INT),
                Property(name="page", data_type=DataType.INT),
                Property(name="content", data_type=DataType.TEXT),
            ],
            **kwargs,
        )
        logger.info("Created Weaviate collection %s", name)
    except Exception as e:
        logger.error("Could not ensure Weaviate collection: %s", e)


def client():
    global _client
    if _client is None and _weaviate_enabled is not False:
        _client = _connect()
        if _client:
            _ensure_collection(_client)
    return _client


def _col():
    c = client()
    if c is None:
        return None
    try:
        return c.collections.get(settings.WEAVIATE_COLLECTION)
    except Exception:
        return None


def _vec(o):
    v = o.vector
    if isinstance(v, dict):
        v = v.get("default") or next(iter(v.values()), None)
    return v


def _to_hit(o) -> dict:
    p = o.properties
    return {
        "document_id": p.get("document_id"),
        "filename": p.get("filename"),
        "chunk_index": p.get("chunk_index"),
        "page": p.get("page") or None,
        "content": p.get("content", ""),
        "vector": _vec(o),
    }


def add_chunks(rows: list[dict]) -> None:
    """rows: [{'props': {...}, 'vector': [...]}]"""
    col = _col()
    if col is not None:
        try:
            from weaviate.classes.data import DataObject
            res = col.data.insert_many([DataObject(properties=r["props"], vector=r["vector"]) for r in rows])
            if not res.has_errors:
                logger.info("Inserted %d chunks into Weaviate Cloud", len(rows))
                return
            logger.warning("Weaviate insert has errors: %s", list(res.errors.values())[:1])
        except Exception as e:
            logger.warning("Weaviate insert failed: %s. Storing in local fallback.", e)

    # Always keep local fallback updated
    _fallback_store.extend(rows)
    _save_fallback()


def delete_document(document_id: int) -> None:
    col = _col()
    if col is not None:
        try:
            from weaviate.classes.query import Filter
            col.data.delete_many(where=Filter.by_property("document_id").equal(document_id))
        except Exception as e:
            logger.warning("Weaviate delete failed: %s", e)

    global _fallback_store
    _fallback_store = [r for r in _fallback_store if r["props"].get("document_id") != document_id]
    _save_fallback()


def _cosine_sim(a, b):
    a = np.asarray(a, dtype=np.float32)
    b = np.asarray(b, dtype=np.float32)
    norm = np.linalg.norm(a) * np.linalg.norm(b)
    return float(np.dot(a, b) / norm) if norm else 0.0


def _local_hybrid_search(query: str, vector: list[float], user_id: int, limit: int, document_ids: list[int] | None = None) -> list[dict]:
    q_words = set(re.findall(r"\w+", query.lower()))
    scored = []
    for r in _fallback_store:
        p = r["props"]
        if p.get("user_id") != user_id:
            continue
        if document_ids and p.get("document_id") not in document_ids:
            continue
        
        content = p.get("content", "").lower()
        # Keyword score (BM25-like overlap)
        c_words = set(re.findall(r"\w+", content))
        overlap = len(q_words & c_words) / (len(q_words) or 1)
        
        # Vector score
        vec_score = _cosine_sim(vector, r["vector"]) if vector and r.get("vector") else 0.0
        
        combined_score = settings.HYBRID_ALPHA * vec_score + (1 - settings.HYBRID_ALPHA) * overlap
        
        scored.append((combined_score, {
            "document_id": p.get("document_id"),
            "filename": p.get("filename"),
            "chunk_index": p.get("chunk_index"),
            "page": p.get("page") or None,
            "content": p.get("content", ""),
            "vector": r.get("vector"),
        }))

    scored.sort(key=lambda x: -x[0])
    return [hit for _, hit in scored[:limit]]


def hybrid_search(query: str, vector: list[float], user_id: int, limit: int, document_ids: list[int] | None = None) -> list[dict]:
    """Hybrid = BM25 keyword + vector similarity, fused inside Weaviate (or local fallback)."""
    col = _col()
    if col is not None:
        try:
            from weaviate.classes.query import Filter
            f = Filter.by_property("user_id").equal(user_id)
            if document_ids:
                f = f & Filter.by_property("document_id").contains_any(document_ids)
            res = col.query.hybrid(
                query=query, vector=vector, alpha=settings.HYBRID_ALPHA, limit=limit,
                query_properties=["content"], filters=f, include_vector=True,
            )
            hits = [_to_hit(o) for o in res.objects]
            if hits:
                return hits
        except Exception as e:
            logger.warning("Weaviate hybrid search failed (%s), falling back to local search.", e)

    return _local_hybrid_search(query, vector, user_id, limit, document_ids)


def get_document_chunks(document_id: int, user_id: int, limit: int = 12) -> list[dict]:
    col = _col()
    if col is not None:
        try:
            from weaviate.classes.query import Filter
            f = Filter.by_property("user_id").equal(user_id) & Filter.by_property("document_id").equal(document_id)
            res = col.query.fetch_objects(filters=f, limit=200)
            hits = sorted((_to_hit(o) for o in res.objects), key=lambda h: h["chunk_index"] or 0)
            if hits:
                return hits[:limit]
        except Exception as e:
            logger.warning("Weaviate fetch chunks failed: %s", e)

    matches = [
        {
            "document_id": r["props"].get("document_id"),
            "filename": r["props"].get("filename"),
            "chunk_index": r["props"].get("chunk_index"),
            "page": r["props"].get("page") or None,
            "content": r["props"].get("content", ""),
            "vector": r.get("vector")
        }
        for r in _fallback_store
        if r["props"].get("user_id") == user_id and r["props"].get("document_id") == document_id
    ]
    matches.sort(key=lambda h: h["chunk_index"] or 0)
    return matches[:limit]


def ping() -> bool:
    try:
        c = client()
        return bool(c and c.is_live())
    except Exception:
        return False
