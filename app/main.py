from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.api.routes.user_routes import user_router
from app.api.routes.auth_routes import auth_router
from app.database.session import SessionLocal
from app.repositories.token_blacklist_repository import cleanup_expired_tokens


@asynccontextmanager
async def lifespan(app: FastAPI):
    db = SessionLocal()
    try:
        cleanup_expired_tokens(db)
    finally:
        db.close()
    yield


app = FastAPI(lifespan=lifespan)


app.include_router(user_router, prefix="/api")
app.include_router(auth_router, prefix="/api")









