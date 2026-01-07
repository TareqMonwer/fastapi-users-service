from datetime import datetime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import DateTime, func, ForeignKey, String

from app.models.base import Base
from app.models.users import User


class OpaqueToken(Base):
    """Opaque token model - random string tokens stored in database"""
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey(User.id), nullable=False, index=True)
    token: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    token_type: Mapped[str] = mapped_column(String(50), nullable=False, default="access")  # access or refresh
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_revoked: Mapped[bool] = mapped_column(default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
    last_used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )
    
    # Relationship
    user: Mapped["User"] = relationship("User", back_populates="opaque_tokens")

