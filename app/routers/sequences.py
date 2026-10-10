from datetime import datetime, timedelta, timezone
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.middleware.auth_middleware import TeamContext, get_current_user, get_team_context
from app.models.lead import Lead
from app.models.sequence import EmailSuppression, Sequence, SequenceDelivery, SequenceEnrollment, SequenceStep
from app.models.team_member import MemberRole
from app.models.user import User
from app.schemas.common import ApiResponse
from app.schemas.sequences import EnrollmentInput, EnrollmentResponse, RestartEnrollmentInput, SequenceInput, SequenceResponse, SequenceStatusInput, SuppressionInput
from app.services.audit_service import record_audit_event

router = APIRouter(prefix="/sequences", tags=["sequences"])


@router.get("/suppressions", response_model=ApiResponse[list[dict]])
async def list_suppressions(db: AsyncSession = Depends(get_db), team_ctx: TeamContext = Depends(get_team_context)):
    rows = (await db.execute(select(EmailSuppression).where(EmailSuppression.team_id == team_ctx.team_id).order_by(EmailSuppression.created_at.desc()))).scalars().all()
    return ApiResponse(success=True, message="Suppressions fetched", data=[{"id": str(row.id), "email": row.email, "reason": row.reason, "source": row.source, "created_at": row.created_at.isoformat()} for row in rows])


@router.post("/suppressions", response_model=ApiResponse[dict], status_code=201)
async def add_suppression(payload: SuppressionInput, db: AsyncSession = Depends(get_db), team_ctx: TeamContext = Depends(get_team_context), user: User = Depends(get_current_user)):
    if team_ctx.role == MemberRole.rep: raise HTTPException(status.HTTP_403_FORBIDDEN, "Only admins and managers can manage suppressions")
    email = payload.email.strip().lower()
    existing = await db.scalar(select(EmailSuppression).where(EmailSuppression.team_id == team_ctx.team_id, EmailSuppression.email == email))
    if existing:
        return ApiResponse(success=True, message="Address already suppressed", data={"id": str(existing.id)})
    row = EmailSuppression(team_id=team_ctx.team_id, email=email, reason=payload.reason, source="Manual")
    db.add(row); await db.flush(); record_audit_event(db, team_ctx.team_id, user.id, "email.suppressed", "email_suppression", row.id); await db.commit(); await db.refresh(row)
    return ApiResponse(success=True, message="Address suppressed", data={"id": str(row.id)})


@router.delete("/suppressions/{suppression_id}", response_model=ApiResponse[dict])
async def remove_suppression(suppression_id: UUID, db: AsyncSession = Depends(get_db), team_ctx: TeamContext = Depends(get_team_context), user: User = Depends(get_current_user)):
    if team_ctx.role == MemberRole.rep: raise HTTPException(status.HTTP_403_FORBIDDEN, "Only admins and managers can manage suppressions")
    row = await db.scalar(select(EmailSuppression).where(EmailSuppression.id == suppression_id, EmailSuppression.team_id == team_ctx.team_id))
    if not row: raise HTTPException(status.HTTP_404_NOT_FOUND, "Suppression not found")
    await db.delete(row); record_audit_event(db, team_ctx.team_id, user.id, "email.unsuppressed", "email_suppression", suppression_id); await db.commit()
    return ApiResponse(success=True, message="Suppression removed", data={})


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
    record_audit_event(db, team_ctx.team_id, user.id, "sequence.created", "sequence", row.id); await db.commit(); await db.refresh(row)
    return ApiResponse(success=True, message="Sequence created", data=await serialize(db, row))


@router.put("/{sequence_id}", response_model=ApiResponse[SequenceResponse])
async def update_sequence(sequence_id: UUID, payload: SequenceInput, db: AsyncSession = Depends(get_db), team_ctx: TeamContext = Depends(get_team_context), user: User = Depends(get_current_user)):
    row = await owned_sequence(db, sequence_id, team_ctx.team_id)
    if team_ctx.role == MemberRole.rep and row.owner_id != user.id: raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not own this sequence")
    if row.status == "Active": raise HTTPException(status.HTTP_409_CONFLICT, "Pause the sequence before editing")
    row.name = payload.name; row.timezone = payload.timezone; row.daily_limit = payload.daily_limit; row.stop_on_reply = payload.stop_on_reply
    await db.execute(delete(SequenceStep).where(SequenceStep.sequence_id == row.id))
    for step in sorted(payload.steps, key=lambda item: item.position): db.add(SequenceStep(sequence_id=row.id, **step.model_dump()))
    record_audit_event(db, team_ctx.team_id, user.id, "sequence.updated", "sequence", row.id); await db.commit(); await db.refresh(row)
    return ApiResponse(success=True, message="Sequence updated", data=await serialize(db, row))


@router.patch("/{sequence_id}/status", response_model=ApiResponse[SequenceResponse])
async def change_status(sequence_id: UUID, payload: SequenceStatusInput, db: AsyncSession = Depends(get_db), team_ctx: TeamContext = Depends(get_team_context), user: User = Depends(get_current_user)):
    row = await owned_sequence(db, sequence_id, team_ctx.team_id)
    if team_ctx.role == MemberRole.rep and row.owner_id != user.id: raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not own this sequence")
    if payload.status == "Active" and not await db.scalar(select(func.count()).select_from(SequenceStep).where(SequenceStep.sequence_id == row.id)): raise HTTPException(status.HTTP_409_CONFLICT, "Add at least one step")
    row.status = payload.status; record_audit_event(db, team_ctx.team_id, user.id, "sequence.status_changed", "sequence", row.id); await db.commit(); await db.refresh(row)
    return ApiResponse(success=True, message="Sequence status updated", data=await serialize(db, row))


@router.delete("/{sequence_id}", response_model=ApiResponse[dict])
async def delete_sequence(
    sequence_id: UUID,
    db: AsyncSession = Depends(get_db),
    team_ctx: TeamContext = Depends(get_team_context),
    user: User = Depends(get_current_user),
):
    row = await owned_sequence(db, sequence_id, team_ctx.team_id)
    if team_ctx.role == MemberRole.rep and row.owner_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not own this sequence")
    await db.delete(row)
    record_audit_event(db, team_ctx.team_id, user.id, "sequence.deleted", "sequence", sequence_id)
    await db.commit()
    return ApiResponse(success=True, message="Sequence deleted", data={})


@router.post("/{sequence_id}/enroll", response_model=ApiResponse[dict])
async def enroll(sequence_id: UUID, payload: EnrollmentInput, db: AsyncSession = Depends(get_db), team_ctx: TeamContext = Depends(get_team_context), user: User = Depends(get_current_user)):
    row = await owned_sequence(db, sequence_id, team_ctx.team_id)
    if team_ctx.role == MemberRole.rep and row.owner_id != user.id: raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not own this sequence")
    valid = set((await db.execute(select(Lead.id).where(Lead.team_id == team_ctx.team_id, Lead.id.in_(payload.lead_ids), Lead.email.is_not(None)))).scalars().all())
    existing = set((await db.execute(select(SequenceEnrollment.lead_id).where(SequenceEnrollment.sequence_id == row.id, SequenceEnrollment.lead_id.in_(valid)))).scalars().all())
    first = await db.scalar(select(SequenceStep).where(SequenceStep.sequence_id == row.id).order_by(SequenceStep.position))
    if not first: raise HTTPException(status.HTTP_409_CONFLICT, "Sequence has no steps")
    now = datetime.now(timezone.utc)
    for lead_id in valid - existing: db.add(SequenceEnrollment(sequence_id=row.id, lead_id=lead_id, owner_id=user.id, next_send_at=now + timedelta(days=first.delay_days)))
    if valid - existing: record_audit_event(db, team_ctx.team_id, user.id, "sequence.leads_enrolled", "sequence", row.id)
    await db.commit()
    return ApiResponse(success=True, message="Leads enrolled", data={"enrolled": len(valid-existing), "skipped": len(payload.lead_ids)-len(valid-existing)})


@router.get("/{sequence_id}/enrollments", response_model=ApiResponse[list[EnrollmentResponse]])
async def enrollment_history(sequence_id: UUID, db: AsyncSession = Depends(get_db), team_ctx: TeamContext = Depends(get_team_context)):
    await owned_sequence(db, sequence_id, team_ctx.team_id)
    rows = (await db.execute(
        select(SequenceEnrollment, Lead)
        .join(Lead, Lead.id == SequenceEnrollment.lead_id)
        .where(SequenceEnrollment.sequence_id == sequence_id)
        .order_by(SequenceEnrollment.enrolled_at.desc())
    )).all()
    data = []
    for enrollment, lead in rows:
        deliveries = (await db.execute(select(SequenceDelivery).where(SequenceDelivery.enrollment_id == enrollment.id).order_by(SequenceDelivery.created_at))).scalars().all()
        data.append(EnrollmentResponse(
            id=enrollment.id, lead_id=lead.id, lead_name=lead.name, lead_email=lead.email,
            status=enrollment.status, current_step=enrollment.current_step,
            reply_override=enrollment.reply_override, next_send_at=enrollment.next_send_at,
            last_sent_at=enrollment.last_sent_at, enrolled_at=enrollment.enrolled_at,
            completed_at=enrollment.completed_at, deliveries=deliveries,
        ))
    return ApiResponse(success=True, message="Enrollment history fetched", data=data)


async def managed_enrollment(db, sequence_id, enrollment_id, team_id, user, role):
    sequence = await owned_sequence(db, sequence_id, team_id)
    if role == MemberRole.rep and sequence.owner_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not own this sequence")
    enrollment = await db.scalar(select(SequenceEnrollment).where(SequenceEnrollment.id == enrollment_id, SequenceEnrollment.sequence_id == sequence.id))
    if not enrollment: raise HTTPException(status.HTTP_404_NOT_FOUND, "Enrollment not found")
    return sequence, enrollment


@router.post("/{sequence_id}/enrollments/{enrollment_id}/cancel", response_model=ApiResponse[dict])
async def cancel_enrollment(sequence_id: UUID, enrollment_id: UUID, db: AsyncSession = Depends(get_db), team_ctx: TeamContext = Depends(get_team_context), user: User = Depends(get_current_user)):
    _, enrollment = await managed_enrollment(db, sequence_id, enrollment_id, team_ctx.team_id, user, team_ctx.role)
    if enrollment.status != "Active": raise HTTPException(status.HTTP_409_CONFLICT, "Only active enrollments can be cancelled")
    enrollment.status = "Cancelled"; enrollment.next_send_at = None; enrollment.completed_at = datetime.now(timezone.utc)
    record_audit_event(db, team_ctx.team_id, user.id, "sequence.enrollment_cancelled", "sequence_enrollment", enrollment.id)
    await db.commit()
    return ApiResponse(success=True, message="Enrollment cancelled", data={})


@router.post("/{sequence_id}/enrollments/{enrollment_id}/restart", response_model=ApiResponse[dict], status_code=201)
async def restart_enrollment(sequence_id: UUID, enrollment_id: UUID, payload: RestartEnrollmentInput, db: AsyncSession = Depends(get_db), team_ctx: TeamContext = Depends(get_team_context), user: User = Depends(get_current_user)):
    sequence, enrollment = await managed_enrollment(db, sequence_id, enrollment_id, team_ctx.team_id, user, team_ctx.role)
    if enrollment.status == "Active": raise HTTPException(status.HTTP_409_CONFLICT, "Cancel the active enrollment before restarting")
    if await db.scalar(select(SequenceEnrollment.id).where(SequenceEnrollment.sequence_id == sequence.id, SequenceEnrollment.lead_id == enrollment.lead_id, SequenceEnrollment.status == "Active")):
        raise HTTPException(status.HTTP_409_CONFLICT, "This lead already has an active enrollment")
    lead = await db.scalar(select(Lead).where(Lead.id == enrollment.lead_id, Lead.team_id == team_ctx.team_id))
    if not lead: raise HTTPException(status.HTTP_404_NOT_FOUND, "Lead not found")
    if lead.status == "Replied" and not payload.allow_replied:
        raise HTTPException(status.HTTP_409_CONFLICT, "Confirm that you want to contact this replied lead again")
    if await db.scalar(select(EmailSuppression.id).where(EmailSuppression.team_id == team_ctx.team_id, EmailSuppression.email == lead.email.lower())):
        raise HTTPException(status.HTTP_409_CONFLICT, "Remove this address from the suppression list before restarting")
    first = await db.scalar(select(SequenceStep).where(SequenceStep.sequence_id == sequence.id).order_by(SequenceStep.position))
    if not first: raise HTTPException(status.HTTP_409_CONFLICT, "Sequence has no steps")
    restarted = SequenceEnrollment(sequence_id=sequence.id, lead_id=lead.id, owner_id=user.id, reply_override=payload.allow_replied, next_send_at=datetime.now(timezone.utc) + timedelta(days=first.delay_days))
    db.add(restarted); await db.flush(); record_audit_event(db, team_ctx.team_id, user.id, "sequence.enrollment_restarted", "sequence_enrollment", restarted.id); await db.commit(); await db.refresh(restarted)
    return ApiResponse(success=True, message="Lead re-enrolled", data={"enrollment_id": str(restarted.id)})


@router.post("/{sequence_id}/enrollments/{enrollment_id}/retry", response_model=ApiResponse[dict])
async def retry_failed_enrollment(sequence_id: UUID, enrollment_id: UUID, db: AsyncSession = Depends(get_db), team_ctx: TeamContext = Depends(get_team_context), user: User = Depends(get_current_user)):
    sequence, enrollment = await managed_enrollment(db, sequence_id, enrollment_id, team_ctx.team_id, user, team_ctx.role)
    if enrollment.status != "Failed":
        raise HTTPException(status.HTTP_409_CONFLICT, "Only failed enrollments can be retried")
    if sequence.status != "Active":
        raise HTTPException(status.HTTP_409_CONFLICT, "Activate the sequence before retrying this delivery")
    failed_delivery = await db.scalar(
        select(SequenceDelivery)
        .where(SequenceDelivery.enrollment_id == enrollment.id, SequenceDelivery.status == "Failed")
        .order_by(SequenceDelivery.updated_at.desc())
    )
    if not failed_delivery:
        raise HTTPException(status.HTTP_409_CONFLICT, "No failed delivery is available to retry")
    enrollment.status = "Active"
    enrollment.next_send_at = datetime.now(timezone.utc)
    enrollment.completed_at = None
    record_audit_event(db, team_ctx.team_id, user.id, "sequence.delivery_retry_requested", "sequence_delivery", failed_delivery.id)
    await db.commit()
    return ApiResponse(success=True, message="Failed delivery queued for retry", data={})
