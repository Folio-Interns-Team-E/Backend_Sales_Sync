from sqlalchemy import Column, String, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base


class OAuthIdentity(Base):
    __tablename__ = "oauth_identities"
    provider = Column(String(16), primary_key=True)
    subject = Column(String(255), primary_key=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    __table_args__ = (UniqueConstraint("user_id", "provider", name="uq_oauth_user_provider"),)
