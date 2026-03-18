from fastapi import HTTPException
from sqlalchemy.orm import Session
from app.enums import UserRole
from app.repositories.user_repository import find_user_by_id, update_user_role
import uuid
import logging

logger = logging.getLogger(__name__)


def change_user_role(db: Session, user_id: uuid.UUID, new_role: str) -> None:
    if new_role not in [r.value for r in UserRole]:
        raise HTTPException(status_code=400, detail=f"Invalid role: {new_role}")

    user = find_user_by_id(db, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    if user.role == new_role:
        raise HTTPException(status_code=400, detail=f"User already has role '{new_role}'")

    old_role = user.role
    update_user_role(db, user, new_role)
    logger.info("audit: event=role_changed user_id=%s old_role=%s new_role=%s", user_id, old_role, new_role)
