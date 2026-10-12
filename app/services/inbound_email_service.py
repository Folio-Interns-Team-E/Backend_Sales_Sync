import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

import httpx
from sqlalchemy import DateTime, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.google_credentials import GoogleCredentials
from app.models.lead import Lead
from app.models.email import Email, EmailStatus
from app.models.sequence import EmailSuppression, Sequence, SequenceEnrollment
from app.services.gmail_service import google_refresh_token, search_gmail_messages, get_gmail_thread_id
from app.services.notification_service import create_notification

logger = logging.getLogger(__name__)


def gmail_after(value: datetime) -> int:
    return int(value.timestamp())


async def detect_sequence_replies_and_bounces(db: AsyncSession, batch_size: int = 50) -> dict[str, int]:
    """Poll Gmail for responses to active sequence enrollments and stop future sends."""
    rows = (await db.execute(
        select(SequenceEnrollment, Sequence, Lead, GoogleCredentials)
        .join(Sequence, Sequence.id == SequenceEnrollment.sequence_id)
        .join(Lead, Lead.id == SequenceEnrollment.lead_id)
        .join(GoogleCredentials, GoogleCredentials.user_id == SequenceEnrollment.owner_id)
        .where(
            SequenceEnrollment.status.in_(["Active", "Completed"]),
            SequenceEnrollment.last_sent_at.is_not(None),
            SequenceEnrollment.last_sent_at >= datetime.now(timezone.utc) - timedelta(days=30),
            Sequence.stop_on_reply.is_(True),
        )
        .order_by(SequenceEnrollment.last_sent_at)
        .limit(batch_size)
    )).all()
    result = {"checked": 0, "replied": 0, "bounced": 0, "permission_errors": 0}
    now = datetime.now(timezone.utc)

    for enrollment, sequence, lead, credentials in rows:
        result["checked"] += 1
        after = gmail_after(enrollment.last_sent_at)
        try:
            refresh_token = google_refresh_token(credentials)
            replies = await search_gmail_messages(refresh_token, f'from:{lead.email} after:{after}', 1)
            if replies:
                lead.status = "Replied"
                enrollment.status = "Replied"
                enrollment.next_send_at = None
                enrollment.completed_at = now
                create_notification(db, sequence.team_id, enrollment.owner_id, "lead_replied", "Lead replied", f"{lead.name} replied to your sequence email.", "/sequences")
                result["replied"] += 1
                continue

            bounces = await search_gmail_messages(
                refresh_token,
                f'from:(mailer-daemon@googlemail.com OR postmaster@google.com) "{lead.email}" after:{after}',
                1,
            )
            if bounces:
                existing = await db.scalar(select(EmailSuppression).where(
                    EmailSuppression.team_id == sequence.team_id,
                    EmailSuppression.email == lead.email.lower(),
                ))
                if not existing:
                    db.add(EmailSuppression(team_id=sequence.team_id, email=lead.email.lower(), reason="Bounce"))
                enrollment.status = "Bounced"
                enrollment.next_send_at = None
                enrollment.completed_at = now
                create_notification(db, sequence.team_id, enrollment.owner_id, "email_bounced", "Email bounced", f"Email to {lead.email} bounced and was added to suppressions.", "/sequences")
                result["bounced"] += 1
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in {401, 403}:
                result["permission_errors"] += 1
                logger.warning("Gmail read permission missing for user %s", enrollment.owner_id)
            else:
                logger.exception("Gmail inbox check failed for enrollment %s", enrollment.id)
        except Exception:
            logger.exception("Gmail inbox check failed for enrollment %s", enrollment.id)

    await db.commit()
    return result


async def detect_outreach_replies(db: AsyncSession, batch_size: int = 50) -> dict[str, int]:
    """Notify the sender once when a prospect replies in the same Gmail thread."""
    rows = (await db.execute(
        select(Email, Lead)
        .join(Lead, Lead.id == Email.lead_id)
        .where(
            Email.status == EmailStatus.SENT,
            Email.sent_at >= datetime.now(timezone.utc) - timedelta(days=30),
            Email.ai_metadata.has_key("provider_message_id"),  # noqa: W601
            ~Email.ai_metadata.has_key("reply_notified_at"),  # noqa: W601
        )
        .order_by(func.coalesce(cast(Email.ai_metadata["last_reply_check_at"].astext, DateTime(timezone=True)), Email.sent_at))
        .limit(batch_size)
    )).all()
    result = {"checked": 0, "replied": 0, "permission_errors": 0}
    for email, lead in rows:
        metadata = email.ai_metadata or {}
        try:
            sender_id = UUID(metadata["sender_user_id"])
        except (KeyError, ValueError, TypeError):
            continue
        credentials = await db.scalar(select(GoogleCredentials).where(GoogleCredentials.user_id == sender_id))
        if not credentials:
            continue
        result["checked"] += 1
        checked_at = datetime.now(timezone.utc).isoformat()
        email.ai_metadata = {**metadata, "last_reply_check_at": checked_at}
        try:
            refresh_token = google_refresh_token(credentials)
            sent_thread = await get_gmail_thread_id(refresh_token, metadata["provider_message_id"])
            if not sent_thread:
                continue
            replies = await search_gmail_messages(
                refresh_token, f'from:{lead.email} after:{gmail_after(email.sent_at)}', 20
            )
            for reply in replies:
                if await get_gmail_thread_id(refresh_token, reply["id"]) == sent_thread:
                    lead.status = "Replied"
                    email.ai_metadata = {**email.ai_metadata, "reply_notified_at": datetime.now(timezone.utc).isoformat(), "reply_message_id": reply["id"]}
                    create_notification(db, lead.team_id, sender_id, "lead_replied", "Prospect replied", f"{lead.name} replied to your email.", "/outreach")
                    result["replied"] += 1
                    break
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in {401, 403}:
                result["permission_errors"] += 1
                logger.warning("Gmail read permission missing for user %s", sender_id)
            else:
                logger.exception("Gmail inbox check failed for email %s", email.id)
        except Exception:
            logger.exception("Gmail inbox check failed for email %s", email.id)
    await db.commit()
    return result
