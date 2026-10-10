from datetime import datetime, timedelta, timezone
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.middleware.auth_middleware import TeamContext, get_current_user, get_team_context
from app.models.lead import Lead
from app.models.sequence import Sequence, SequenceDelivery, SequenceEnrollment, SequenceStep
from app.models.team_member import MemberRole
from app.models.user import User
from app.schemas.common import ApiResponse
from app.schemas.sequences import EnrollmentInput, SequenceInput, SequenceResponse, SequenceStatusInput

router = APIRouter(prefix="/sequences", tags=["sequences"])


async def owned_sequence(db, sequence_id, team_id):
    row = await db.scalar(select(Sequence).where(Sequence.id == sequence_id, Sequence.team_id == team_id))
    if not row: raise HTTPException(status.HTTP_404_NOT_FOUND, "Sequence not found")
    return row


async def serialize(db, row):
    steps = (await db.execute(select(SequenceStep).where(SequenceStep.sequence_id == row.id).order_by(SequenceStep.position))).scalars().all()
    count = await db.scalar(select(func.count()).select_from(SequenceEnrollment).where(SequenceEnrollment.sequence_id == row.id, SequenceEnrollment.status == "Active"))
    sent = await db.scalar(select(func.count()).select_from(SequenceDelivery).where(SequenceDelivery.sequence_id == row.id, SequenceDelivery.status == "Sent"))
    failed = await db.scalar(select(func.count()).select_from(SequenceDelivery).where(SequenceDelivery.sequence_id == row.id, SequenceDelivery.status == "Failed"))
    row.steps = steps; row.active_enrollments = count or 0; row.sent_deliveries = sent or 0; row.failed_deliveries = failed or 0
    return row


@router.get("/", response_model=ApiResponse[list[SequenceResponse]])
async def list_sequences(db: AsyncSession = Depends(get_db), team_ctx: TeamContext = Depends(get_team_context)):
    rows = (await db.execute(select(Sequence).where(Sequence.team_id == team_ctx.team_id).order_by(Sequence.updated_at.desc()))).scalars().all()
    return ApiResponse(success=True, message="Sequences fetched", data=[await serialize(db, row) for row in rows])


@router.post("/", response_model=ApiResponse[SequenceResponse], status_code=201)
async def create_sequence(payload: SequenceInput, db: AsyncSession = Depends(get_db), team_ctx: TeamContext = Depends(get_team_context), user: User = Depends(get_current_user)):
    row = Sequence(team_id=team_ctx.team_id, owner_id=user.id, name=payload.name, timezone=payload.timezone, daily_limit=payload.daily_limit, stop_on_reply=payload.stop_on_reply)
    db.add(row); await db.flush()
    for step in sorted(payload.steps, key=lambda item: item.position): db.add(SequenceStep(sequence_id=row.id, **step.model_dump()))
    await db.commit(); await db.refresh(row)
    return ApiResponse(success=True, message="Sequence created", data=await serialize(db, row))


@router.put("/{sequence_id}", response_model=ApiResponse[SequenceResponse])
async def update_sequence(sequence_id: UUID, payload: SequenceInput, db: AsyncSession = Depends(get_db), team_ctx: TeamContext = Depends(get_team_context), user: User = Depends(get_current_user)):
    row = await owned_sequence(db, sequence_id, team_ctx.team_id)
    if team_ctx.role == MemberRole.rep and row.owner_id != user.id: raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not own this sequence")
    if row.status == "Active": raise HTTPException(status.HTTP_409_CONFLICT, "Pause the sequence before editing")
    row.name = payload.name; row.timezone = payload.timezone; row.daily_limit = payload.daily_limit; row.stop_on_reply = payload.stop_on_reply
    await db.execute(delete(SequenceStep).where(SequenceStep.sequence_id == row.id))
    for step in sorted(payload.steps, key=lambda item: item.position): db.add(SequenceStep(sequence_id=row.id, **step.model_dump()))
    await db.commit(); await db.refresh(row)
    return ApiResponse(success=True, message="Sequence updated", data=await serialize(db, row))


@router.patch("/{sequence_id}/status", response_model=ApiResponse[SequenceResponse])
async def change_status(sequence_id: UUID, payload: SequenceStatusInput, db: AsyncSession = Depends(get_db), team_ctx: TeamContext = Depends(get_team_context)):
    row = await owned_sequence(db, sequence_id, team_ctx.team_id)
    if payload.status == "Active" and not await db.scalar(select(func.count()).select_from(SequenceStep).where(SequenceStep.sequence_id == row.id)): raise HTTPException(status.HTTP_409_CONFLICT, "Add at least one step")
    row.status = payload.status; await db.commit(); await db.refresh(row)
    return ApiResponse(success=True, message="Sequence status updated", data=await serialize(db, row))


@router.post("/{sequence_id}/enroll", response_model=ApiResponse[dict])
async def enroll(sequence_id: UUID, payload: EnrollmentInput, db: AsyncSession = Depends(get_db), team_ctx: TeamContext = Depends(get_team_context), user: User = Depends(get_current_user)):
    row = await owned_sequence(db, sequence_id, team_ctx.team_id)
    valid = set((await db.execute(select(Lead.id).where(Lead.team_id == team_ctx.team_id, Lead.id.in_(payload.lead_ids), Lead.email.is_not(None)))).scalars().all())
    existing = set((await db.execute(select(SequenceEnrollment.lead_id).where(SequenceEnrollment.sequence_id == row.id, SequenceEnrollment.lead_id.in_(valid)))).scalars().all())
    first = await db.scalar(select(SequenceStep).where(SequenceStep.sequence_id == row.id).order_by(SequenceStep.position))
    if not first: raise HTTPException(status.HTTP_409_CONFLICT, "Sequence has no steps")
    now = datetime.now(timezone.utc)
    for lead_id in valid - existing: db.add(SequenceEnrollment(sequence_id=row.id, lead_id=lead_id, owner_id=user.id, next_send_at=now + timedelta(days=first.delay_days)))
    await db.commit()
    return ApiResponse(success=True, message="Leads enrolled", data={"enrolled": len(valid-existing), "skipped": len(payload.lead_ids)-len(valid-existing)})
