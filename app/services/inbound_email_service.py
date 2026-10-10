import logging
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.google_credentials import GoogleCredentials
from app.models.lead import Lead
from app.models.sequence import EmailSuppression, Sequence, SequenceEnrollment
from app.services.gmail_service import google_refresh_token, search_gmail_messages

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
