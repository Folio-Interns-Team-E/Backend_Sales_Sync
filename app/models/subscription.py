from sqlalchemy import Column, String, DateTime, ForeignKey, Integer, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base
import uuid
import enum

# Keep your Enums...
class SubscriptionTier(str, enum.Enum):
    FREE = "free"
    GROWTH = "growth"
    ENTERPRISE = "enterprise"

class SubscriptionStatus(str, enum.Enum):
    ACTIVE = "active"
    CANCELED = "canceled" # Note: Stripe spells it "canceled" (one 'l')
    PAST_DUE = "past_due"
    UNPAID = "unpaid"
    TRIALING = "trialing"





class Subscription(Base):
    """
    Tracks the history and current state of a team's subscriptions.
    """
    __tablename__ = "subscriptions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    team_id = Column(UUID(as_uuid=True), ForeignKey("teams.id"), nullable=False)
    
    # Stripe identifiers
    stripe_subscription_id = Column(String, nullable=False, unique=True)
    stripe_price_id = Column(String, nullable=False) # Maps to the product tier
    
    # State tracking
    tier = Column(String, default=SubscriptionTier.FREE.value, nullable=False)
    status = Column(String, default=SubscriptionStatus.TRIALING.value, nullable=False)
    
    # Period dates (Crucial for verifying access if webhooks delay)
    current_period_start = Column(DateTime(timezone=True), nullable=False)
    current_period_end = Column(DateTime(timezone=True), nullable=False)
    
    # Cancellation handling
    cancel_at_period_end = Column(Boolean, default=False, nullable=False)
    canceled_at = Column(DateTime(timezone=True), nullable=True)
    ended_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    team = relationship("Team", back_populates="subscriptions")


class Invoice(Base):
    """
    Tracks individual payment receipts/attempts for billing history UIs.
    """
    __tablename__ = "invoices"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    team_id = Column(UUID(as_uuid=True), ForeignKey("teams.id"), nullable=False)
    
    stripe_invoice_id = Column(String, nullable=False, unique=True)
    stripe_payment_intent_id = Column(String, nullable=True) # For tracking specific charges
    
    amount_due = Column(Integer, nullable=False) # Store in cents (Stripe default)
    amount_paid = Column(Integer, nullable=False)
    currency = Column(String, default="usd", nullable=False)
    status = Column(String, nullable=False) # paid, open, void, uncollectible
    
    hosted_invoice_url = Column(String, nullable=True) # Great for "Download Invoice" buttons
    invoice_pdf = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False) # When stripe generated it

    team = relationship("Team", back_populates="invoices")