from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.database.session import get_db
from app.api.dependencies.auth_dependency import require_role
from app.schemas.admin_schema import ChangeRoleRequest, DisableUserRequest, InviteUserRequest
from app.schemas.users_schema import UserRead
from app.services.admin_services import change_user_role, disable_user, enable_user, force_password_reset, invite_user
from app.api.dependencies.rate_limiter import force_reset_limiter, invite_user_limiter
from app.repositories.user_repository import list_users
from app.models.user import User
from typing import Optional
import uuid
import logging

logger = logging.getLogger(__name__)

admin_router = APIRouter(prefix="/users", tags=["admin"])

admin_dependency = require_role("admin")


@admin_router.patch("/{user_id}/role")
def route_change_user_role(
    user_id: uuid.UUID,
    body: ChangeRoleRequest,
    current_user: User = Depends(admin_dependency),
    db: Session = Depends(get_db),
):
    change_user_role(db, user_id, body.role)
    return {"message": "Role updated successfully"}


@admin_router.get("/", response_model=list[UserRead])
def route_list_users(
    role: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    current_user: User = Depends(admin_dependency),
    db: Session = Depends(get_db),
):
    return list_users(db, role_filter=role, skip=skip, limit=limit)


@admin_router.patch("/{user_id}/status")
def route_update_user_status(
    user_id: uuid.UUID,
    body: DisableUserRequest,
    current_user: User = Depends(admin_dependency),
    db: Session = Depends(get_db),
):
    if body.is_disabled:
        disable_user(db, user_id, current_user.id)
        return {"message": "User disabled"}
    else:
        enable_user(db, user_id)
        return {"message": "User enabled"}


@admin_router.post("/{user_id}/force-password-reset")
async def route_force_password_reset(
    user_id: uuid.UUID,
    current_user: User = Depends(admin_dependency),
    db: Session = Depends(get_db),
    _rate_limit=Depends(force_reset_limiter),
):
    await force_password_reset(db, user_id)
    return {"message": "Password reset email sent"}


@admin_router.post("/invite", status_code=201)
def route_invite_user(
    body: InviteUserRequest,
    current_user: User = Depends(admin_dependency),
    db: Session = Depends(get_db),
    _rate_limit=Depends(invite_user_limiter),
):
    invite_user(db, body.email)
    return {"message": "Invitation sent"}
