import uuid

from sqlalchemy import (
    Column,
    String,
    DateTime,
    Index
)

from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func

from app.database import Base



class LeadPool(Base):

    __tablename__ = "leads_pool"


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

    first_name = Column(
        String(255),
        nullable=True
    )


    last_name = Column(
        String(255),
        nullable=True
    )


    full_name = Column(
        String(255),
        nullable=True,
        index=True
    )


    email = Column(
        String(255),
        nullable=True,
        index=True
    )


    title = Column(
        String(255),
        nullable=True,
        index=True
    )



    # ==========================
    # Company Information
    # ==========================

    company_name = Column(
        String(255),
        nullable=True,
        index=True
    )


    website = Column(
        String(255),
        nullable=True
    )



    # ==========================
    # Classification
    # ==========================

    industry = Column(
        String(255),
        nullable=True,
        index=True
    )


    seniority = Column(
        String(255),
        nullable=True
    )


    department = Column(
        String(255),
        nullable=True
    )



    # ==========================
    # Location
    # ==========================

    city = Column(
        String(255),
        nullable=True
    )


    state = Column(
        String(255),
        nullable=True
    )


    country = Column(
        String(255),
        nullable=True,
        index=True
    )



    # ==========================
    # AI Search Data
    # ==========================

    keywords = Column(
        JSONB,
        nullable=False,
        default=list
    )


    technologies = Column(
        JSONB,
        nullable=False,
        default=list
    )



    # ==========================
    # Provider Information
    # ==========================

    provider = Column(
        String(100),
        nullable=True
    )


    provider_id = Column(
        String(255),
        nullable=True,
        index=True
    )



    # ==========================
    # Complete Original Record
    # ==========================

    raw_data = Column(
        JSONB,
        nullable=False,
        default=dict
    )



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

    )