from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.token_blacklist import TokenBlacklist


def add_to_blacklist(db: Session, jti: str, expires_at: datetime, commit: bool = True) -> None:
    db.add(TokenBlacklist(jti=jti, expires_at=expires_at))
    if commit:
        db.commit()


def is_blacklisted(db: Session, jti: str) -> bool:
    return db.query(TokenBlacklist).filter(TokenBlacklist.jti == jti).first() is not None


def cleanup_expired_tokens(db: Session) -> None:
    db.query(TokenBlacklist).filter(
        TokenBlacklist.expires_at < datetime.now(timezone.utc)
    ).delete()
    db.commit()
