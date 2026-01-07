from datetime import datetime, timedelta, timezone
from typing import Optional
from sqlalchemy.orm import Session
import secrets

from app.models.opaque_token import OpaqueToken
from app.core.settings import settings


class OpaqueTokenCRUD:
    """CRUD operations for opaque tokens."""
    
    @staticmethod
    def generate_token() -> str:
        """Generate a secure random opaque token."""
        return secrets.token_urlsafe(32)  # 32 bytes = 43 characters base64url
    
    @staticmethod
    def create_opaque_token(
        db: Session,
        user_id: int,
        token_type: str = "access",
        expires_delta: Optional[timedelta] = None
    ) -> OpaqueToken:
        """Create a new opaque token."""
        token = OpaqueTokenCRUD.generate_token()
        
        if expires_delta is None:
            if token_type == "access":
                expires_delta = timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
            else:
                expires_delta = timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
        
        expires_at = datetime.now(timezone.utc) + expires_delta
        
        db_token = OpaqueToken(
            user_id=user_id,
            token=token,
            token_type=token_type,
            expires_at=expires_at
        )
        db.add(db_token)
        db.commit()
        db.refresh(db_token)
        return db_token
    
    @staticmethod
    def get_opaque_token(
        db: Session,
        token: str,
        token_type: Optional[str] = None
    ) -> Optional[OpaqueToken]:
        """Get an opaque token by token string."""
        query = db.query(OpaqueToken).filter(
            OpaqueToken.token == token,
            OpaqueToken.is_revoked == False
        )
        
        if token_type:
            query = query.filter(OpaqueToken.token_type == token_type)
        
        db_token = query.first()
        
        # Check if token is expired
        if db_token and db_token.expires_at < datetime.now(timezone.utc):
            return None
        
        # Update last_used_at if token is valid
        if db_token:
            db_token.last_used_at = datetime.now(timezone.utc)
            db.commit()
        
        return db_token
    
    @staticmethod
    def validate_opaque_token(
        db: Session,
        token: str,
        token_type: Optional[str] = None
    ) -> Optional[OpaqueToken]:
        """Validate an opaque token and return it if valid."""
        return OpaqueTokenCRUD.get_opaque_token(db, token, token_type)
    
    @staticmethod
    def revoke_opaque_token(
        db: Session,
        token: str
    ) -> bool:
        """Revoke an opaque token."""
        db_token = db.query(OpaqueToken).filter(
            OpaqueToken.token == token
        ).first()
        
        if db_token:
            db_token.is_revoked = True
            db.commit()
            return True
        return False
    
    @staticmethod
    def revoke_all_user_tokens(
        db: Session,
        user_id: int,
        token_type: Optional[str] = None
    ) -> int:
        """Revoke all opaque tokens for a user."""
        query = db.query(OpaqueToken).filter(
            OpaqueToken.user_id == user_id,
            OpaqueToken.is_revoked == False
        )
        
        if token_type:
            query = query.filter(OpaqueToken.token_type == token_type)
        
        count = query.update({"is_revoked": True})
        db.commit()
        return count
    
    @staticmethod
    def cleanup_expired_tokens(db: Session) -> int:
        """Delete expired opaque tokens."""
        count = db.query(OpaqueToken).filter(
            OpaqueToken.expires_at < datetime.now(timezone.utc)
        ).delete()
        db.commit()
        return count

