"""Document parsing, chunking, embedding and storage (runs as a background job)."""
import csv
import logging
import os
import re
from pathlib import Path
from app.config import settings
from app.db import SessionLocal
from app.models import Document
from app.services import embeddings, vectorstore
from app.services.activity import log_activity

logger = logging.getLogger("app.ingestion")


def _sanitize_text(text: str) -> str:
    """Remove non-printable / binary characters that corrupt vector store entries."""
    import unicodedata
    # Replace surrogate codepoints and non-printable control chars (keep \n \t)
    cleaned = []
    for ch in text:
        cp = ord(ch)
        if cp == 0xFFFD or (0xD800 <= cp <= 0xDFFF):
            continue  # skip replacement char and surrogates
        cat = unicodedata.category(ch)
        if cat == 'Cc' and ch not in ('\n', '\t', '\r'):
            continue  # skip control chars except newline/tab
        cleaned.append(ch)
    result = "".join(cleaned)
    # Collapse runs of whitespace-only lines
    result = re.sub(r'\n{3,}', '\n\n', result)
    return result.strip()


def extract_pages(path: str, ext: str) -> list[tuple[int | None, str]]:
    if ext == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(path)
        if reader.is_encrypted:
            raise ValueError("Encrypted PDFs are not supported")
        pages = [(i + 1, _sanitize_text(p.extract_text() or "")) for i, p in enumerate(reader.pages)]
    elif ext == ".csv":
        with open(path, newline="", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        lines = [" | ".join(f"{k}: {v}" for k, v in r.items()) for r in rows]
        pages = [(None, _sanitize_text("\n".join(lines)))]
    else:
        with open(path, encoding="utf-8", errors="replace") as f:
            pages = [(None, _sanitize_text(f.read()))]
    pages = [(p, t) for p, t in pages if t.strip()]
    if not pages:
        raise ValueError("No extractable text found (scanned PDF or empty file)")
    return pages


def _split_unit(unit: str, size: int) -> list[str]:
    if len(unit) <= size:
        return [unit]
    out = []
    for sent in re.split(r"(?<=[.!?])\s+", unit):
        while len(sent) > size:
            out.append(sent[:size])
            sent = sent[size:]
        if sent:
            out.append(sent)
    return out


def chunk_text(text: str, size: int | None = None, overlap: int | None = None) -> list[str]:
    size = size or settings.CHUNK_SIZE
    overlap = settings.CHUNK_OVERLAP if overlap is None else overlap
    text = re.sub(r"[ \t]+", " ", text).strip()
    units: list[str] = []
    for para in re.split(r"\n{2,}", text):
        para = para.strip()
        if not para:
            continue
        if len(para) <= size:
            units.append(para)
        else:
            for line in para.split("\n"):
                line = line.strip()
                if line:
                    units.extend(_split_unit(line, size))
    chunks, cur = [], ""
    for u in units:
        if cur and len(cur) + len(u) + 1 > size:
            chunks.append(cur)
            tail = cur[-overlap:] if overlap else ""
            cur = f"{tail}\n{u}" if tail else u
        else:
            cur = f"{cur}\n{u}" if cur else u
    if cur:
        chunks.append(cur)
    return chunks


def process_document(doc_id: int) -> None:
    db = SessionLocal()
    try:
        # Atomic claim: only ONE worker can move a document pending -> processing (prevents duplicate jobs).
        claimed = (db.query(Document)
                   .filter(Document.id == doc_id, Document.status == "pending")
                   .update({"status": "processing", "error": None}, synchronize_session=False))
        db.commit()
        if claimed == 0:
            logger.info("Document %s already claimed/processed - skipping", doc_id)
            return
        doc = db.get(Document, doc_id)
        path = str(Path(settings.UPLOAD_DIR) / str(doc.user_id) / f"{doc.file_hash}{Path(doc.filename).suffix.lower()}")
        try:
            pages = extract_pages(path, doc.file_type)
            records = []
            for page, text in pages:
                for ch in chunk_text(text):
                    records.append((page, ch))
            if not records:
                raise ValueError("Document produced no chunks")
            rows = []
            for i in range(0, len(records), 64):
                batch = records[i:i + 64]
                vecs = embeddings.embed_texts([c for _, c in batch])
                for j, ((page, content), vec) in enumerate(zip(batch, vecs)):
                    rows.append({"props": {"user_id": doc.user_id, "document_id": doc.id, "filename": doc.filename,
                                           "chunk_index": i + j, "page": page or 0, "content": content},
                                 "vector": vec})
            vectorstore.add_chunks(rows)
            doc.status, doc.chunk_count = "ready", len(rows)
            db.commit()
            log_activity(db, doc.user_id, "document_ready", f"{doc.filename} ({len(rows)} chunks)")
        except Exception as e:  # failed processing must never crash the worker
            logger.exception("Processing failed for document %s", doc_id)
            try:
                vectorstore.delete_document(doc_id)  # remove partial vectors
            except Exception:
                pass
            doc.status, doc.error = "failed", str(e)[:500]
            db.commit()
            log_activity(db, doc.user_id, "document_failed", f"{doc.filename}: {str(e)[:200]}")
    finally:
        db.close()
