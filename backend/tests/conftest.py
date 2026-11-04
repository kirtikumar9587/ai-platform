import os
import tempfile

_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["UPLOAD_DIR"] = f"{_tmp}/uploads"
os.environ["GEMINI_API_KEY"] = "test"
os.environ["JWT_SECRET"] = "test-secret"

import re
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import embeddings, vectorstore


def fake_embed(text: str):
    v = np.zeros(256, dtype=np.float32)
    for w in re.findall(r"[a-z0-9]+", text.lower()):
        v[hash(w) % 256] += 1
    n = np.linalg.norm(v)
    return (v / n if n else v).tolist()


STORE: list[dict] = []


@pytest.fixture(autouse=True)
def fakes(monkeypatch):
    """Replace Weaviate + MiniLM with in-memory fakes so tests run offline."""
    STORE.clear()
    monkeypatch.setattr(embeddings, "embed_texts", lambda texts: [fake_embed(t) for t in texts])
    monkeypatch.setattr(embeddings, "embed_query", fake_embed)
    import app.services.retrieval as retrieval
    import app.services.ingestion as ingestion
    monkeypatch.setattr(retrieval, "embed_query", fake_embed)
    monkeypatch.setattr(ingestion.embeddings, "embed_texts", lambda texts: [fake_embed(t) for t in texts])
    monkeypatch.setattr(vectorstore, "add_chunks", lambda rows: STORE.extend(rows))
    monkeypatch.setattr(vectorstore, "delete_document",
                        lambda did: STORE.__setitem__(slice(None), [r for r in STORE if r["props"]["document_id"] != did]))

    def hybrid(query, vector, user_id, limit, document_ids=None):
        out = []
        for r in STORE:
            p = r["props"]
            if p["user_id"] != user_id or (document_ids and p["document_id"] not in document_ids):
                continue
            out.append({"document_id": p["document_id"], "filename": p["filename"], "chunk_index": p["chunk_index"],
                        "page": p["page"] or None, "content": p["content"], "vector": r["vector"]})
        return out[:limit]

    monkeypatch.setattr(vectorstore, "hybrid_search", hybrid)
    monkeypatch.setattr(vectorstore, "get_document_chunks",
                        lambda did, uid, limit=12: [h for h in hybrid("", [], uid, 99, [did])][:limit])


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def register_login(client, email):
    client.post("/auth/register", json={"email": email, "password": "password123"})
    r = client.post("/auth/login", data={"username": email, "password": "password123"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
