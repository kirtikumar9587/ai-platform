from collections import defaultdict
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.auth import get_current_user
from app.db import get_db
from app.models import ActivityLog, Conversation, Document, LLMLog, Message, User

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("/summary")
def summary(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    docs = db.query(Document).filter(Document.user_id == user.id).all()
    logs = db.query(LLMLog).filter(LLMLog.user_id == user.id).all()
    ok = [l for l in logs if l.success and not l.cached]
    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=6)
    daily = defaultdict(int)
    for l in logs:
        if l.created_at and l.created_at >= since.replace(hour=0, minute=0, second=0):
            daily[l.created_at.strftime("%Y-%m-%d")] += l.prompt_tokens + l.completion_tokens
    days = [(since + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]
    return {
        "documents": {"total": len(docs), "ready": sum(d.status == "ready" for d in docs),
                      "processing": sum(d.status in ("pending", "processing") for d in docs),
                      "failed": sum(d.status == "failed" for d in docs), "chunks": sum(d.chunk_count for d in docs)},
        "conversations": db.query(func.count(Conversation.id)).filter(Conversation.user_id == user.id).scalar(),
        "messages": db.query(func.count(Message.id)).join(Conversation, Message.conversation_id == Conversation.id)
                      .filter(Conversation.user_id == user.id).scalar(),
        "llm": {"calls": len(logs), "errors": sum(not l.success for l in logs), "cached": sum(l.cached for l in logs),
                "fallback_calls": sum(l.fallback_used and l.success for l in logs),
                "prompt_tokens": sum(l.prompt_tokens for l in logs), "completion_tokens": sum(l.completion_tokens for l in logs),
                "avg_latency_ms": int(sum(l.latency_ms for l in ok) / len(ok)) if ok else 0},
        "tokens_by_day": [{"day": d, "tokens": daily.get(d, 0)} for d in days],
    }


@router.get("/logs")
def llm_logs(limit: int = 100, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = (db.query(LLMLog).filter(LLMLog.user_id == user.id).order_by(LLMLog.id.desc())
            .limit(min(max(limit, 1), 500)).all())
    return [{"id": r.id, "kind": r.kind, "model": r.model, "prompt_tokens": r.prompt_tokens,
             "completion_tokens": r.completion_tokens, "latency_ms": r.latency_ms, "success": r.success,
             "cached": r.cached, "fallback_used": r.fallback_used, "error": r.error,
             "created_at": r.created_at.isoformat() if r.created_at else None} for r in rows]


@router.get("/activity")
def activity(limit: int = 100, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = (db.query(ActivityLog).filter(ActivityLog.user_id == user.id).order_by(ActivityLog.id.desc())
            .limit(min(max(limit, 1), 500)).all())
    return [{"id": r.id, "action": r.action, "detail": r.detail,
             "created_at": r.created_at.isoformat() if r.created_at else None} for r in rows]
