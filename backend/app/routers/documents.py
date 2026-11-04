import hashlib
import os
from pathlib import Path
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.auth import get_current_user
from app.config import settings
from app.db import get_db
from app.models import Document, User
from app.services import vectorstore
from app.services.activity import log_activity
from app.services.ingestion import process_document

router = APIRouter(prefix="/documents", tags=["documents"])
ALLOWED = {".pdf": "pdf", ".txt": "txt", ".md": "md", ".markdown": "md", ".csv": "csv"}


def doc_dict(d: Document) -> dict:
    return {"id": d.id, "filename": d.filename, "file_type": d.file_type, "size_bytes": d.size_bytes,
            "status": d.status, "error": d.error, "chunk_count": d.chunk_count,
            "created_at": d.created_at.isoformat() if d.created_at else None}


def get_owned(db: Session, doc_id: int, user: User) -> Document:
    doc = db.query(Document).filter(Document.id == doc_id, Document.user_id == user.id).first()
    if not doc:  # 404 (not 403) so users cannot probe other users' document ids
        raise HTTPException(404, "Document not found")
    return doc


@router.post("/upload", status_code=202)
async def upload(background: BackgroundTasks, file: UploadFile = File(...),
                 db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    name = os.path.basename(file.filename or "")
    ext = os.path.splitext(name)[1].lower()
    if ext not in ALLOWED:
        raise HTTPException(400, "Unsupported file type. Allowed: PDF, TXT, MD, CSV")
    max_bytes = settings.MAX_UPLOAD_MB * 1024 * 1024
    data = await file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(413, f"File too large (max {settings.MAX_UPLOAD_MB} MB)")
    if not data.strip():
        raise HTTPException(400, "File is empty")
    if ext == ".pdf":
        if not data.startswith(b"%PDF"):
            raise HTTPException(400, "File content is not a valid PDF")
    else:
        try:
            data.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise HTTPException(400, "Text files must be UTF-8 encoded")

    file_hash = hashlib.sha256(data).hexdigest()
    existing = db.query(Document).filter(Document.user_id == user.id, Document.file_hash == file_hash).first()
    if existing:
        raise HTTPException(409, {"message": f"Duplicate upload: identical to '{existing.filename}' (status: {existing.status})",
                                  "document_id": existing.id})

    folder = Path(settings.UPLOAD_DIR) / str(user.id)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{file_hash}{ext}").write_bytes(data)  # stored under hash, never under the user-supplied name

    doc = Document(user_id=user.id, filename=name[:255], file_type=ALLOWED[ext], file_hash=file_hash,
                   size_bytes=len(data), status="pending")
    db.add(doc)
    try:
        db.commit()
    except IntegrityError:  # two simultaneous identical uploads: the unique constraint wins
        db.rollback()
        raise HTTPException(409, "Duplicate upload")
    db.refresh(doc)
    background.add_task(process_document, doc.id)  # runs in a worker thread, request returns immediately
    log_activity(db, user.id, "document_upload", name)
    return doc_dict(doc)


@router.get("")
def list_documents(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    docs = db.query(Document).filter(Document.user_id == user.id).order_by(Document.id.desc()).all()
    return [doc_dict(d) for d in docs]


@router.get("/{doc_id}")
def get_document(doc_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return doc_dict(get_owned(db, doc_id, user))


@router.post("/{doc_id}/reprocess", status_code=202)
def reprocess(doc_id: int, background: BackgroundTasks, db: Session = Depends(get_db),
              user: User = Depends(get_current_user)):
    doc = get_owned(db, doc_id, user)
    if doc.status != "failed":
        raise HTTPException(409, f"Only failed documents can be reprocessed (current status: {doc.status})")
    doc.status, doc.error = "pending", None
    db.commit()
    background.add_task(process_document, doc.id)
    return doc_dict(doc)


@router.delete("/{doc_id}", status_code=204)
def delete_document(doc_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    doc = get_owned(db, doc_id, user)
    if doc.status == "processing":
        raise HTTPException(409, "Document is being processed; try again in a moment")
    try:
        vectorstore.delete_document(doc.id)
    except Exception:
        pass
    path = Path(settings.UPLOAD_DIR) / str(user.id) / f"{doc.file_hash}{Path(doc.filename).suffix.lower()}"
    path.unlink(missing_ok=True)
    name = doc.filename
    db.delete(doc)
    db.commit()
    log_activity(db, user.id, "document_delete", name)
