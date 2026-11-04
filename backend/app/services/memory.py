"""Conversation memory: send only a rolling summary + the last N messages (not the whole history)."""
import logging
from sqlalchemy.orm import Session
from app.config import settings
from app.models import Conversation, Message
from app.services import llm

logger = logging.getLogger("app.memory")


def _compact(m: Message) -> dict:
    text = m.content[:1200]
    if m.role == "assistant" and m.sources:
        files = sorted({s["filename"] for s in m.sources if s.get("cited")} or {s["filename"] for s in m.sources})
        if files:
            text += f" [sources: {', '.join(files)}]"  # lets follow-ups refer to 'that document'
    return {"role": m.role, "content": text}


def build_history(db: Session, conv: Conversation) -> tuple[str | None, list[dict]]:
    msgs = (db.query(Message).filter(Message.conversation_id == conv.id, Message.id > conv.summary_upto)
            .order_by(Message.id.desc()).limit(settings.HISTORY_MESSAGES).all())
    return conv.summary, [_compact(m) for m in reversed(msgs)]


def maybe_summarize(db: Session, conv: Conversation, user_id: int) -> None:
    n = settings.HISTORY_MESSAGES
    pending = (db.query(Message).filter(Message.conversation_id == conv.id, Message.id > conv.summary_upto)
               .order_by(Message.id).all())
    if len(pending) <= 2 * n:
        return
    to_sum = pending[:-n]
    transcript = "\n".join(f"{m.role}: {_compact(m)['content']}" for m in to_sum)
    prompt = (f"Previous summary: {conv.summary or '(none)'}\n\nNew messages:\n{transcript}\n\n"
              "Write an updated summary in under 150 words. Keep document names, key facts and open questions.")
    try:
        r = llm.generate(prompt, kind="summary", user_id=user_id, temperature=0.1)
        conv.summary = r.text.strip()
        conv.summary_upto = to_sum[-1].id
        db.commit()
    except llm.LLMError:
        logger.warning("Summarisation failed; keeping raw history")
