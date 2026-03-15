from app.schemas.users_schema import UserCreate
from sqlalchemy.orm import Session
from app.repositories import user_repository
from app.services.auth_services import send_verification_email_for_user
from fastapi import HTTPException
import requests


def user_create(db: Session, user: UserCreate):
    new_user = user_repository.create_user(db=db, user_in=user)
    try:
        send_verification_email_for_user(str(new_user.id), new_user.email)
    except requests.RequestException:
        raise HTTPException(
            status_code=500,
            detail="Account created but verification email could not be sent. Please contact support.",
        )
    return new_user

