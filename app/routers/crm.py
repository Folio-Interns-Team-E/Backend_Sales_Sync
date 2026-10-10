from datetime import datetime, timezone
from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth_middleware import TeamContext, get_current_user, get_team_context
from app.models.crm import Account, Contact, SalesTask
from app.models.lead import Lead
from app.models.opportunity import Opportunity
from app.models.team_member import MemberRole, TeamMember
from app.models.user import User
from app.schemas.common import ApiResponse
from app.schemas.crm import AccountPayload, AccountResponse, AccountUpdate, ContactPayload, ContactResponse, ContactUpdate, SearchResult, TaskPayload, TaskResponse, TaskUpdate

router = APIRouter(prefix="/crm", tags=["crm"])


async def ensure_member(db: AsyncSession, team_id: UUID, user_id: Optional[UUID]):
    if user_id and not await db.scalar(select(TeamMember).where(TeamMember.team_id == team_id, TeamMember.user_id == user_id)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Owner is not a workspace member")


async def get_record(db, model, record_id, team_id):
    record = await db.scalar(select(model).where(model.id == record_id, model.team_id == team_id))
    if not record:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Record not found")
    return record


@router.get("/accounts", response_model=ApiResponse[list[AccountResponse]])
async def accounts(db: AsyncSession = Depends(get_db), team_ctx: TeamContext = Depends(get_team_context)):
    rows = (await db.execute(select(Account).where(Account.team_id == team_ctx.team_id).order_by(Account.name))).scalars().all()
    return ApiResponse(success=True, message="Accounts fetched", data=rows)


@router.post("/accounts", response_model=ApiResponse[AccountResponse], status_code=201)
async def create_account(payload: AccountPayload, db: AsyncSession = Depends(get_db), team_ctx: TeamContext = Depends(get_team_context), user: User = Depends(get_current_user)):
    owner_id = payload.owner_id or user.id
    if team_ctx.role == MemberRole.rep and owner_id != user.id: raise HTTPException(status.HTTP_403_FORBIDDEN, "Sales reps cannot assign another owner")
    await ensure_member(db, team_ctx.team_id, owner_id)
    row = Account(team_id=team_ctx.team_id, **payload.model_dump(exclude={"owner_id"}), owner_id=owner_id)
    db.add(row); await db.commit(); await db.refresh(row)
    return ApiResponse(success=True, message="Account created", data=row)


@router.patch("/accounts/{record_id}", response_model=ApiResponse[AccountResponse])
async def update_account(record_id: UUID, payload: AccountUpdate, db: AsyncSession = Depends(get_db), team_ctx: TeamContext = Depends(get_team_context), user: User = Depends(get_current_user)):
    row = await get_record(db, Account, record_id, team_ctx.team_id)
    if team_ctx.role == MemberRole.rep and row.owner_id != user.id: raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not own this account")
    data = payload.model_dump(exclude_unset=True); await ensure_member(db, team_ctx.team_id, data.get("owner_id"))
    for key, value in data.items(): setattr(row, key, value)
    await db.commit(); await db.refresh(row)
    return ApiResponse(success=True, message="Account updated", data=row)


@router.delete("/accounts/{record_id}", response_model=ApiResponse[dict])
async def delete_account(record_id: UUID, db: AsyncSession = Depends(get_db), team_ctx: TeamContext = Depends(get_team_context), user: User = Depends(get_current_user)):
    row = await get_record(db, Account, record_id, team_ctx.team_id)
    if team_ctx.role == MemberRole.rep and row.owner_id != user.id: raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not own this account")
    await db.delete(row); await db.commit()
    return ApiResponse(success=True, message="Account deleted", data={})


@router.get("/contacts", response_model=ApiResponse[list[ContactResponse]])
async def contacts(db: AsyncSession = Depends(get_db), team_ctx: TeamContext = Depends(get_team_context)):
    rows = (await db.execute(select(Contact, Account.name).outerjoin(Account, Contact.account_id == Account.id).where(Contact.team_id == team_ctx.team_id).order_by(Contact.first_name))).all()
    data = []
    for row, account_name in rows:
        row.account_name = account_name; data.append(row)
    return ApiResponse(success=True, message="Contacts fetched", data=data)


@router.post("/contacts", response_model=ApiResponse[ContactResponse], status_code=201)
async def create_contact(payload: ContactPayload, db: AsyncSession = Depends(get_db), team_ctx: TeamContext = Depends(get_team_context), user: User = Depends(get_current_user)):
    owner_id = payload.owner_id or user.id
    await ensure_member(db, team_ctx.team_id, owner_id)
    if payload.account_id: await get_record(db, Account, payload.account_id, team_ctx.team_id)
    row = Contact(team_id=team_ctx.team_id, **payload.model_dump(exclude={"owner_id"}), owner_id=owner_id)
    db.add(row); await db.commit(); await db.refresh(row); row.account_name = None
    return ApiResponse(success=True, message="Contact created", data=row)


@router.patch("/contacts/{record_id}", response_model=ApiResponse[ContactResponse])
async def update_contact(record_id: UUID, payload: ContactUpdate, db: AsyncSession = Depends(get_db), team_ctx: TeamContext = Depends(get_team_context), user: User = Depends(get_current_user)):
    row = await get_record(db, Contact, record_id, team_ctx.team_id)
    if team_ctx.role == MemberRole.rep and row.owner_id != user.id: raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not own this contact")
    data = payload.model_dump(exclude_unset=True); await ensure_member(db, team_ctx.team_id, data.get("owner_id"))
    if data.get("account_id"): await get_record(db, Account, data["account_id"], team_ctx.team_id)
    for key, value in data.items(): setattr(row, key, value)
    await db.commit(); await db.refresh(row); row.account_name = None
    return ApiResponse(success=True, message="Contact updated", data=row)


@router.delete("/contacts/{record_id}", response_model=ApiResponse[dict])
async def delete_contact(record_id: UUID, db: AsyncSession = Depends(get_db), team_ctx: TeamContext = Depends(get_team_context), user: User = Depends(get_current_user)):
    row = await get_record(db, Contact, record_id, team_ctx.team_id)
    if team_ctx.role == MemberRole.rep and row.owner_id != user.id: raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not own this contact")
    await db.delete(row); await db.commit()
    return ApiResponse(success=True, message="Contact deleted", data={})


@router.get("/tasks", response_model=ApiResponse[list[TaskResponse]])
async def tasks(scope: Literal["mine", "team"] = Query("mine"), db: AsyncSession = Depends(get_db), team_ctx: TeamContext = Depends(get_team_context), user: User = Depends(get_current_user)):
    query = select(SalesTask).where(SalesTask.team_id == team_ctx.team_id)
    if scope == "mine" or team_ctx.role == MemberRole.rep: query = query.where(SalesTask.owner_id == user.id)
    rows = (await db.execute(query.order_by(SalesTask.status, SalesTask.due_at.asc().nullslast()))).scalars().all()
    return ApiResponse(success=True, message="Tasks fetched", data=rows)


@router.post("/tasks", response_model=ApiResponse[TaskResponse], status_code=201)
async def create_task(payload: TaskPayload, db: AsyncSession = Depends(get_db), team_ctx: TeamContext = Depends(get_team_context), user: User = Depends(get_current_user)):
    owner_id = payload.owner_id or user.id
    if team_ctx.role == MemberRole.rep and owner_id != user.id: raise HTTPException(status.HTTP_403_FORBIDDEN, "Sales reps cannot assign another owner")
    await ensure_member(db, team_ctx.team_id, owner_id)
    if payload.contact_id: await get_record(db, Contact, payload.contact_id, team_ctx.team_id)
    if payload.opportunity_id: await get_record(db, Opportunity, payload.opportunity_id, team_ctx.team_id)
    row = SalesTask(team_id=team_ctx.team_id, **payload.model_dump(exclude={"owner_id"}), owner_id=owner_id)
    if row.status == "Completed": row.completed_at = datetime.now(timezone.utc)
    db.add(row); await db.commit(); await db.refresh(row)
    return ApiResponse(success=True, message="Task created", data=row)


@router.patch("/tasks/{record_id}", response_model=ApiResponse[TaskResponse])
async def update_task(record_id: UUID, payload: TaskUpdate, db: AsyncSession = Depends(get_db), team_ctx: TeamContext = Depends(get_team_context), user: User = Depends(get_current_user)):
    row = await get_record(db, SalesTask, record_id, team_ctx.team_id)
    if team_ctx.role == MemberRole.rep and row.owner_id != user.id: raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not own this task")
    data = payload.model_dump(exclude_unset=True); await ensure_member(db, team_ctx.team_id, data.get("owner_id"))
    for key, value in data.items(): setattr(row, key, value)
    if data.get("status") == "Completed" and not row.completed_at: row.completed_at = datetime.now(timezone.utc)
    elif data.get("status") and data["status"] != "Completed": row.completed_at = None
    await db.commit(); await db.refresh(row)
    return ApiResponse(success=True, message="Task updated", data=row)


@router.delete("/tasks/{record_id}", response_model=ApiResponse[dict])
async def delete_task(record_id: UUID, db: AsyncSession = Depends(get_db), team_ctx: TeamContext = Depends(get_team_context), user: User = Depends(get_current_user)):
    row = await get_record(db, SalesTask, record_id, team_ctx.team_id)
    if team_ctx.role == MemberRole.rep and row.owner_id != user.id: raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not own this task")
    await db.delete(row); await db.commit()
    return ApiResponse(success=True, message="Task deleted", data={})


@router.get("/search", response_model=ApiResponse[list[SearchResult]])
async def search_workspace(q: str = Query(min_length=2, max_length=100), db: AsyncSession = Depends(get_db), team_ctx: TeamContext = Depends(get_team_context)):
    term = f"%{q.strip()}%"
    account_rows = (await db.execute(select(Account).where(Account.team_id == team_ctx.team_id, or_(Account.name.ilike(term), Account.domain.ilike(term))).limit(5))).scalars().all()
    contact_rows = (await db.execute(select(Contact).where(Contact.team_id == team_ctx.team_id, or_(Contact.first_name.ilike(term), Contact.last_name.ilike(term), Contact.email.ilike(term))).limit(5))).scalars().all()
    lead_rows = (await db.execute(select(Lead).where(Lead.team_id == team_ctx.team_id, or_(Lead.name.ilike(term), Lead.company_name.ilike(term), Lead.email.ilike(term))).limit(5))).scalars().all()
    deal_rows = (await db.execute(select(Opportunity).where(Opportunity.team_id == team_ctx.team_id, or_(Opportunity.name.ilike(term), Opportunity.company_name.ilike(term))).limit(5))).scalars().all()
    results = [SearchResult(id=row.id, type="Account", title=row.name, subtitle=row.domain or row.industry or "Company", url="/crm?tab=accounts") for row in account_rows]
    results += [SearchResult(id=row.id, type="Contact", title=f"{row.first_name} {row.last_name}".strip(), subtitle=row.email or row.job_title or "Contact", url="/crm?tab=contacts") for row in contact_rows]
    results += [SearchResult(id=row.id, type="Lead", title=row.name, subtitle=row.company_name or row.email, url="/lead-generation") for row in lead_rows]
    results += [SearchResult(id=row.id, type="Deal", title=row.name, subtitle=row.company_name, url="/deals") for row in deal_rows]
    return ApiResponse(success=True, message="Search complete", data=results[:15])
