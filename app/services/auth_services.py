from app.repositories.user_repository import find_user_by_email
from app.utils.security.password_hash import verify_password
from app.utils.tokens import JWTConfig, JWTUtility
from app.core.config import settings
from app.schemas.token_response import TokenResponse
from app.schemas.login_request import LoginRequest
from fastapi import HTTPException
from sqlalchemy.orm import Session


jwt_config = JWTConfig(

secret_key = settings.JWT_SECRET_KEY,
algorithm = settings.JWT_ALGORITHM,
access_token_expiry_minutes = settings.ACCESS_TOKEN_EXPIRE_MINUTES

)

jwt_gen = JWTUtility(jwt_config)

def user_login(db: Session, login_data : LoginRequest) -> TokenResponse:
    user = find_user_by_email(db, login_data.email)        
    if not user or not verify_password(login_data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid Credentials")
    
    token = jwt_gen.create_access_token(str(user.id))
    return TokenResponse(access_token=token, token_type="bearer")

        
    