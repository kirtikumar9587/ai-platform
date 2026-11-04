"""Local embeddings with all-MiniLM-L6-v2 (384 dims) via fastembed (ONNX, no PyTorch needed)."""
import numpy as np
from app.config import settings

_model = None


def _get_model():
    global _model
    if _model is None:
        from fastembed import TextEmbedding
        _model = TextEmbedding(model_name=settings.EMBEDDING_MODEL)
    return _model


def embed_texts(texts: list[str]) -> list[list[float]]:
    vectors = []
    for v in _get_model().embed(texts):
        arr = np.asarray(v, dtype=np.float32)
        norm = np.linalg.norm(arr)
        vectors.append((arr / norm if norm else arr).tolist())
    return vectors


def embed_query(text: str) -> list[float]:
    return embed_texts([text])[0]


def cosine(a, b) -> float:
    a = np.asarray(a, dtype=np.float32)
    b = np.asarray(b, dtype=np.float32)
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    return float(np.dot(a, b) / denom) if denom else 0.0
