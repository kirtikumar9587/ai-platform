import logging
from sqlalchemy.orm import Session
from app.models import ActivityLog

logger = logging.getLogger("app.activity")


def log_activity(db: Session, user_id: int | None, action: str, detail: str = "") -> None:
    try:
        db.add(ActivityLog(user_id=user_id, action=action, detail=detail[:1000]))
        db.commit()
        logger.info("user=%s action=%s %s", user_id, action, detail[:200])
    except Exception:  # logging must never break a request
        db.rollback()
