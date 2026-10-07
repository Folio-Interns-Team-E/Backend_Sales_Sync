from datetime import date
from uuid import UUID
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.crypto import decrypt_key, encrypt_key
from app.models.lead_provider import LeadProviderCredential


async def get_provider(db: AsyncSession, team_id: UUID, provider: str = "apollo"):
    return (await db.execute(select(LeadProviderCredential).where(
        LeadProviderCredential.team_id == team_id,
        LeadProviderCredential.provider == provider,
    ))).scalar_one_or_none()


async def save_provider(db: AsyncSession, team_id: UUID, api_key: str, monthly_limit: int):
    if not api_key.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "API key is required")
    record = await get_provider(db, team_id)
    if record:
        record.encrypted_api_key = encrypt_key(api_key.strip())
        record.monthly_limit = monthly_limit
    else:
        record = LeadProviderCredential(
            team_id=team_id, provider="apollo", encrypted_api_key=encrypt_key(api_key.strip()),
            monthly_limit=monthly_limit, used_this_month=0, usage_month=date.today().replace(day=1),
        )
        db.add(record)
    await db.commit()
    await db.refresh(record)
    return record


def provider_key(record: LeadProviderCredential) -> str:
    return decrypt_key(record.encrypted_api_key)


def reset_usage_if_needed(record: LeadProviderCredential):
    current = date.today().replace(day=1)
    if record.usage_month != current:
        record.usage_month = current
        record.used_this_month = 0
