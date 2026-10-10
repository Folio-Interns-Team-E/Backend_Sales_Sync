import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead import Lead
from app.models.sequence import Sequence, SequenceDelivery, SequenceEnrollment, SequenceStep
from app.services.gmail_service import send_email_on_behalf_of_user

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 3


def render_message(template: str, lead: Lead) -> str:
    first_name = lead.name.split()[0] if lead.name else "there"
    values = {"first_name": first_name, "name": lead.name or "", "company": lead.company_name or "your company", "job_title": lead.job_title or ""}
    for key, value in values.items():
        template = template.replace("{{" + key + "}}", value)
    return template


def sequence_day_start(now: datetime, timezone_name: str) -> datetime:
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        zone = timezone.utc
    local = now.astimezone(zone).replace(hour=0, minute=0, second=0, microsecond=0)
    return local.astimezone(timezone.utc)


async def process_due_enrollments(db: AsyncSession, batch_size: int = 20) -> dict[str, int]:
    """Claim and deliver a bounded batch. PostgreSQL row locks make parallel workers safe."""
    now = datetime.now(timezone.utc)
    rows = (await db.execute(
        select(SequenceEnrollment, Sequence, Lead)
        .join(Sequence, Sequence.id == SequenceEnrollment.sequence_id)
        .join(Lead, Lead.id == SequenceEnrollment.lead_id)
        .where(
            SequenceEnrollment.status == "Active",
            SequenceEnrollment.next_send_at <= now,
            Sequence.status == "Active",
        )
        .order_by(SequenceEnrollment.next_send_at)
        .limit(batch_size)
        .with_for_update(skip_locked=True, of=SequenceEnrollment)
    )).all()
    result = {"claimed": len(rows), "sent": 0, "failed": 0, "stopped": 0, "limited": 0}

    for enrollment, sequence, lead in rows:
        if sequence.stop_on_reply and lead.status == "Replied":
            enrollment.status = "Replied"
            enrollment.next_send_at = None
            enrollment.completed_at = now
            result["stopped"] += 1
            continue

        day_start = sequence_day_start(now, sequence.timezone)
        sent_today = await db.scalar(
            select(func.count()).select_from(SequenceDelivery).where(
                SequenceDelivery.sequence_id == sequence.id,
                SequenceDelivery.status == "Sent",
                SequenceDelivery.sent_at >= day_start,
            )
        ) or 0
        if sent_today >= sequence.daily_limit:
            enrollment.next_send_at = day_start + timedelta(days=1)
            result["limited"] += 1
            continue

        steps = (await db.execute(
            select(SequenceStep).where(SequenceStep.sequence_id == sequence.id).order_by(SequenceStep.position)
        )).scalars().all()
        if enrollment.current_step >= len(steps):
            enrollment.status = "Completed"
            enrollment.next_send_at = None
            enrollment.completed_at = now
            continue
        step = steps[enrollment.current_step]
        delivery = await db.scalar(select(SequenceDelivery).where(
            SequenceDelivery.enrollment_id == enrollment.id,
            SequenceDelivery.step_id == step.id,
        ))
        if delivery and delivery.status == "Sent":
            enrollment.current_step += 1
            continue
        if not delivery:
            delivery = SequenceDelivery(sequence_id=sequence.id, enrollment_id=enrollment.id, step_id=step.id)
            db.add(delivery)
        else:
            delivery.status = "Processing"
            delivery.attempt_count += 1
            delivery.error = None
        await db.flush()

        try:
            delivery.provider_message_id = await send_email_on_behalf_of_user(
                db, enrollment.owner_id, lead.email, render_message(step.subject, lead), render_message(step.body, lead)
            )
            delivery.status = "Sent"
            delivery.sent_at = now
            enrollment.last_sent_at = now
            enrollment.current_step += 1
            if enrollment.current_step >= len(steps):
                enrollment.status = "Completed"
                enrollment.completed_at = now
                enrollment.next_send_at = None
            else:
                enrollment.next_send_at = now + timedelta(days=steps[enrollment.current_step].delay_days)
            lead.status = "Sent"
            result["sent"] += 1
        except Exception as exc:
            logger.exception("Sequence delivery failed for enrollment %s", enrollment.id)
            delivery.status = "Failed"
            delivery.error = str(exc)[:2000]
            if delivery.attempt_count >= MAX_ATTEMPTS:
                enrollment.status = "Failed"
                enrollment.next_send_at = None
            else:
                enrollment.next_send_at = now + timedelta(minutes=5 * (2 ** (delivery.attempt_count - 1)))
            result["failed"] += 1

    await db.commit()
    return result
