"""Idempotent, workspace-scoped prospect conversion and CRM context."""

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crm import Account, Contact, SalesTask
from app.models.email import Email
from app.models.lead import Lead, LeadStatus
from app.models.meeting import Meeting
from app.models.opportunity import Opportunity


def _business_domain(email: str) -> str | None:
    domain = email.rsplit("@", 1)[-1].lower()
    consumer = {"gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "icloud.com", "live.com", "aol.com"}
    return domain if "." in domain and domain not in consumer else None


async def convert_lead(db: AsyncSession, team_id: UUID, user_id: UUID, lead_id: UUID) -> dict:
    lead = (await db.execute(select(Lead).where(Lead.id == lead_id, Lead.team_id == team_id).with_for_update())).scalar_one_or_none()
    if not lead:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Prospect not found in this workspace")
    if lead.crm_contact_id:
        contact = await db.scalar(select(Contact).where(Contact.id == lead.crm_contact_id, Contact.team_id == team_id))
        if contact:
            return {"contact_id": contact.id, "account_id": contact.account_id, "already_converted": True}
    eligible = {LeadStatus.QUALIFIED.value, LeadStatus.DRAFTED.value, LeadStatus.SENT.value, LeadStatus.REPLIED.value, LeadStatus.CONVERTED.value}
    if lead.status not in eligible:
        raise HTTPException(status.HTTP_409_CONFLICT, "Qualify the prospect before converting it to CRM")

    email = (lead.email or "").strip().lower()
    if not email:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "A prospect email is required for duplicate-safe conversion")
    company = (lead.company_name or "").strip()
    domain = _business_domain(email)
    lock_keys = [f"crm-contact:{team_id}:{email}"]
    if company:
        lock_keys.append(f"crm-account-name:{team_id}:{company.lower()}")
        if domain:
            lock_keys.append(f"crm-account-domain:{team_id}:{domain}")
    for key in sorted(lock_keys):
        await db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": key})
    contact = await db.scalar(select(Contact).where(Contact.team_id == team_id, func.lower(Contact.email) == email).order_by(Contact.created_at))
    account = None
    if contact and contact.account_id:
        account = await db.scalar(select(Account).where(Account.id == contact.account_id, Account.team_id == team_id))
    if not account and company:
        if domain:
            account = await db.scalar(select(Account).where(Account.team_id == team_id, func.lower(Account.domain) == domain).order_by(Account.created_at))
        if not account:
            account = await db.scalar(select(Account).where(Account.team_id == team_id, func.lower(Account.name) == company.lower()).order_by(Account.created_at))
        if not account:
            account = Account(team_id=team_id, owner_id=user_id, name=company, domain=domain)
            db.add(account)
            await db.flush()

    if not contact:
        names = lead.name.strip().split(None, 1)
        contact = Contact(
            team_id=team_id, account_id=account.id if account else None, owner_id=user_id,
            first_name=names[0] if names else "Prospect", last_name=names[1] if len(names) > 1 else "",
            email=email, job_title=lead.job_title, lifecycle_stage="Sales Qualified",
        )
        db.add(contact)
        await db.flush()
    elif account and not contact.account_id:
        contact.account_id = account.id

    lead.crm_contact_id = contact.id
    lead.status = LeadStatus.CONVERTED.value
    await db.commit()
    return {"contact_id": contact.id, "account_id": contact.account_id, "already_converted": False}


async def contact_context(db: AsyncSession, team_id: UUID, contact_id: UUID) -> dict:
    contact = await db.scalar(select(Contact).where(Contact.id == contact_id, Contact.team_id == team_id))
    if not contact:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Contact not found")
    leads = (await db.execute(select(Lead).where(Lead.team_id == team_id, Lead.crm_contact_id == contact_id).order_by(Lead.created_at.desc()))).scalars().all()
    lead_ids = [lead.id for lead in leads]
    emails = (await db.execute(select(Email).where(Email.lead_id.in_(lead_ids)).order_by(Email.sent_at.desc()).limit(20))).scalars().all() if lead_ids else []
    meetings = (await db.execute(select(Meeting).where(Meeting.lead_id.in_(lead_ids)).order_by(Meeting.date.desc()).limit(20))).scalars().all() if lead_ids else []
    deals = (await db.execute(select(Opportunity).where(Opportunity.team_id == team_id, Opportunity.lead_id.in_(lead_ids)).order_by(Opportunity.created_at.desc()).limit(20))).scalars().all() if lead_ids else []
    tasks = (await db.execute(select(SalesTask).where(SalesTask.team_id == team_id, SalesTask.contact_id == contact_id).order_by(SalesTask.created_at.desc()).limit(20))).scalars().all()
    return {
        "leads": [{"id": str(row.id), "name": row.name, "status": row.status, "score": row.score} for row in leads],
        "emails": [{"id": str(row.id), "subject": row.subject, "status": row.status.value if hasattr(row.status, "value") else row.status, "sent_at": row.sent_at} for row in emails],
        "meetings": [{"id": str(row.id), "date": row.date, "time": row.time, "status": row.status, "meet_url": row.meet_url} for row in meetings],
        "deals": [{"id": str(row.id), "name": row.name, "stage": row.stage, "amount": str(row.amount)} for row in deals],
        "tasks": [{"id": str(row.id), "title": row.title, "status": row.status, "due_at": row.due_at} for row in tasks],
    }
