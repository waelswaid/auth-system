from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database.session import get_db
from app.schemas.login_request import LoginRequest
from app.schemas.token_response import TokenResponse
from app.services.auth_services import user_login


auth_router = APIRouter(prefix="/auth", tags=["auth"])

@auth_router.post("/login", response_model= TokenResponse)
def route_login_request(login_data:LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    return user_login(db, login_data)