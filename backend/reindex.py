import sys
from app.db import SessionLocal
from app.models import Document
from app.services import ingestion, vectorstore

db = SessionLocal()
docs = db.query(Document).all()
print(f"Found {len(docs)} documents to index...")

for d in docs:
    print(f"Indexing doc {d.id}: {d.filename} (user {d.user_id})...")
    # Reset status to pending so process_document claims and indexes it
    d.status = "pending"
    db.commit()
    ingestion.process_document(d.id)

print("Reindex complete! Checking Weaviate Cloud count...")
c = vectorstore.client()
if c:
    col = c.collections.get("DocChunk")
    count = col.aggregate.over_all(total_count=True).total_count
    print("Total objects in Weaviate Cloud:", count)

# Test query for user 2
from app.services import retrieval
q = "According to our enterprise architecture PDF, what are our disaster recovery RTO and RPO targets"
hits = retrieval.retrieve(q, 2)
print("Retrieval test for user 2:", len(hits), "chunks found!")
for h in hits:
    print(f"[{h['score']}] {h['filename']}: {h['content'][:100]}")

db.close()

