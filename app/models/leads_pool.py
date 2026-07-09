import uuid
from sqlalchemy import Column, String, DateTime, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from app.database import Base # Connected to your Postgres DB

class LeadPool(Base):
    __tablename__ = "leads_pool"

    # Standard Postgres auto-generating UUID
    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    )

    # ==========================
    # Person Information
    # ==========================
    first_name = Column(String(255), nullable=True)
    last_name = Column(String(255), nullable=True)
    full_name = Column(String(255), nullable=True)
    email = Column(String(255), nullable=True)
    title = Column(String(255), nullable=True)

    # ==========================
    # Company Information
    # ==========================
    company_name = Column(String(255), nullable=True)
    website = Column(String(255), nullable=True)

    # ==========================
    # Classification & Location
    # ==========================
    industry = Column(String(255), nullable=True)
    seniority = Column(String(255), nullable=True)
    department = Column(String(255), nullable=True)
    city = Column(String(255), nullable=True)
    state = Column(String(255), nullable=True)
    country = Column(String(255), nullable=True)

    # ==========================
    # AI Search Data (Using native Postgres JSONB)
    # ==========================
    keywords = Column(JSONB, nullable=False, default=list)
    technologies = Column(JSONB, nullable=False, default=list)

    # ==========================
    # Provider Information & Raw Payload
    # ==========================
    provider = Column(String(100), nullable=True)
    provider_id = Column(String(255), nullable=True)
    raw_data = Column(JSONB, nullable=False, default=dict)

    # ==========================
    # Indexes for Quick AI Queries
    # ==========================
    __table_args__ = (
        Index(
            "ix_leads_pool_company_title",
            "company_name",
            "title"
        ),
        Index(
            "ix_leads_pool_location",
            "country",
            "state",
            "city"
        ),
        Index(
            "ix_leads_pool_industry",
            "industry"
        ),
    )