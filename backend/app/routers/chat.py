import time
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from app.auth import get_current_user
from app.db import get_db
from app.models import Conversation, Message, User, Document
from app.services import agent, llm, memory, rag
from app.services.activity import log_activity

router = APIRouter(tags=["chat"])


class SendIn(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    mode: Literal["rag", "agent"] = "rag"
    verify: bool = True
    document_ids: list[int] | None = None


def conv_dict(c: Conversation) -> dict:
    return {"id": c.id, "title": c.title, "created_at": c.created_at.isoformat() if c.created_at else None}


def msg_dict(m: Message) -> dict:
    return {"id": m.id, "role": m.role, "content": m.content, "sources": m.sources or [],
            "agent_steps": m.agent_steps or [], "meta": m.meta or {},
            "created_at": m.created_at.isoformat() if m.created_at else None}


def owned_conv(db: Session, cid: int, user: User) -> Conversation:
    c = db.query(Conversation).filter(Conversation.id == cid, Conversation.user_id == user.id).first()
    if not c:
        raise HTTPException(404, "Conversation not found")
    return c


@router.get("/conversations")
def list_conversations(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.query(Conversation).filter(Conversation.user_id == user.id).order_by(Conversation.id.desc()).all()
    return [conv_dict(c) for c in rows]


@router.post("/conversations", status_code=201)
def create_conversation(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    c = Conversation(user_id=user.id, title="New chat")
    db.add(c)
    db.commit()
    db.refresh(c)
    return conv_dict(c)


@router.delete("/conversations/{cid}", status_code=204)
def delete_conversation(cid: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    c = owned_conv(db, cid, user)
    db.query(Message).filter(Message.conversation_id == c.id).delete()
    db.delete(c)
    db.commit()


@router.get("/conversations/{cid}/messages")
def list_messages(cid: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    c = owned_conv(db, cid, user)
    rows = db.query(Message).filter(Message.conversation_id == c.id).order_by(Message.id).all()
    return [msg_dict(m) for m in rows]


@router.post("/conversations/{cid}/messages")
def send_message(cid: int, body: SendIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    conv = owned_conv(db, cid, user)
    doc_ids = None
    if body.document_ids:  # only allow filtering on the caller's own documents
        doc_ids = [d.id for d in db.query(Document).filter(Document.user_id == user.id, Document.id.in_(body.document_ids))]
        if not doc_ids:
            raise HTTPException(400, "None of the selected documents exist")

    summary, history = memory.build_history(db, conv)  # taken BEFORE adding the new message
    db.add(Message(conversation_id=conv.id, role="user", content=body.content))
    if conv.title == "New chat":
        conv.title = body.content[:60]
    db.commit()

    t0 = time.perf_counter()
    try:
        if body.mode == "agent":
            hist_text = "\n".join(([f"Summary: {summary}"] if summary else []) + [f"{m['role']}: {m['content']}" for m in history])
            res = agent.run_agent(body.content, user.id, hist_text)
        else:
            res = rag.answer_question(body.content, user.id, summary, history, doc_ids, body.verify)
    except llm.LLMError as e:
        log_activity(db, user.id, "chat_error", str(e)[:300])
        raise HTTPException(503, f"All language models are unavailable right now. {str(e)[:200]}")
    latency = int((time.perf_counter() - t0) * 1000)

    meta = {"mode": body.mode, "latency_ms": latency, "sufficient": res["sufficient"], "conflicts": res["conflicts"],
            "verification": res["verification"], "rewritten_question": res["rewritten_question"],
            "report": res.get("report"), **res["usage"]}
    m = Message(conversation_id=conv.id, role="assistant", content=res["answer"], sources=res["sources"],
                agent_steps=res["steps"], meta=meta)
    db.add(m)
    db.commit()
    db.refresh(m)
    log_activity(db, user.id, f"chat_{body.mode}", body.content[:120])
    try:
        memory.maybe_summarize(db, conv, user.id)
    except Exception:
        db.rollback()
    return msg_dict(m)
