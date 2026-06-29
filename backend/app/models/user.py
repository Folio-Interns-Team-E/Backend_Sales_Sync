from sqlalchemy import Column, String, DateTime, ForeignKey, Enum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base
import uuid
import enum

class UserRole(enum.Enum):
    admin = "admin"
    manager = "manager"
    rep = "rep"

class User(Base):
    __tablename__ = "users"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    full_name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=False)
    role = Column(Enum(UserRole), nullable=False, default=UserRole.rep)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    team_id = Column(UUID(as_uuid=True), ForeignKey("teams.id"), nullable=True)
    team = relationship("Team", back_populates="members")
    
    # Added this line
    icp = relationship("ICP", back_populates="user", uselist=False, cascade="all, delete-orphan")