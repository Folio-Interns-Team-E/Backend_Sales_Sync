import httpx
import logging
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.config import settings
from app.models.meeting import Meeting, MeetingStatus
import os
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from cryptography.fernet import Fernet
from app.models.calcom_credentials import CalComIntegration
from app.schemas.calcom import CalComIntegrationCreate
from uuid import UUID


logger = logging.getLogger(__name__)


CAL_BASE_URL = "https://api.cal.com/v2"


class CalComService:

    def __init__(self, db: AsyncSession):
        self.db = db

        self.headers = {
            "Authorization": f"Bearer {settings.cal_api_key}",
            "Content-Type": "application/json",
            "cal-api-version": "2026-02-25"
        }


    async def create_booking(
        self,
        *,
        lead_id,
        start_time: datetime,
        name: str,
        email: str,
        agenda: list[str] = []
    ):

        payload = {
            "start": start_time.isoformat(),
            "attendee": {
                "name": name,
                "timeZone": "Asia/Karachi",
                "language": "en",
                "email": email
            },
            "eventTypeId": int(settings.cal_event_type_id)
        }


        async with httpx.AsyncClient(timeout=30.0) as client:

            response = await client.post(
                f"{CAL_BASE_URL}/bookings",
                headers=self.headers,
                json=payload
            )


        if response.status_code not in [200, 201]:
            logger.error(response.text)
            raise Exception(
                f"Cal.com booking failed: {response.text}"
            )


        data = response.json()


        booking = data.get("data", {})


        booking_uid = (
            booking.get("uid")
            or booking.get("id")
        )


        # Save local meeting

        meeting = Meeting(
            lead_id=lead_id,

           

            date=start_time.date(),

            time=start_time.time(),

            timezone="Asia/Karachi",

            calendar_event_id=booking_uid,

            agenda=agenda,

            status=MeetingStatus.SCHEDULED.value
        )


        self.db.add(meeting)

        await self.db.commit()

        await self.db.refresh(meeting)


        return {
            "meeting_id": meeting.id,
            "cal_booking_uid": booking_uid,
            "status": "scheduled"
        }



    async def cancel_booking(
        self,
        booking_uid: str,
        meeting_id
    ):


        payload = {
            "cancellationReason": "User requested cancellation",
            "cancelSubsequentBookings": True
        }


        async with httpx.AsyncClient() as client:

            response = await client.post(
                f"{CAL_BASE_URL}/bookings/{booking_uid}/cancel",
                headers=self.headers,
                json=payload
            )


        if response.status_code not in [200, 204]:

            logger.error(response.text)

            raise Exception(
                f"Cal cancellation failed: {response.text}"
            )


        # Update local meeting

        result = await self.db.execute(
            select(Meeting)
            .where(Meeting.id == meeting_id)
        )

        meeting = result.scalar_one_or_none()


        if meeting:

            meeting.status = MeetingStatus.CANCELLED.value

            await self.db.commit()


        return {
            "status": "cancelled",
            "booking_uid": booking_uid
        }
    


ENCRYPTION_KEY = os.getenv("DB_ENCRYPTION_KEY")
cipher = Fernet(ENCRYPTION_KEY.encode() if ENCRYPTION_KEY else Fernet.generate_key())

def encrypt_key(plain_text: str) -> str:
    return cipher.encrypt(plain_text.encode()).decode()

def decrypt_key(encrypted_text: str) -> str:
    return cipher.decrypt(encrypted_text.encode()).decode()


async def save_or_update_calcom(db: AsyncSession, user_id: UUID, payload: CalComIntegrationCreate):
    """Saves or updates a user's Cal.com integration config securely."""
    # Check if integration configuration already exists for this user
    query = select(CalComIntegration).where(CalComIntegration.user_id == user_id)
    result = await db.execute(query)
    integration = result.scalar_one_or_none()

    encrypted_key = encrypt_key(payload.cal_api_key)

    if integration:
        # Update existing config
        integration.encrypted_api_key = encrypted_key
        integration.event_type_id = payload.cal_event_type_id
    else:
        # Create new config record
        integration = CalComIntegration(
            user_id=user_id,
            encrypted_api_key=encrypted_key,
            event_type_id=payload.cal_event_type_id
        )
        db.add(integration)

    await db.commit()
    await db.refresh(integration)
    return integration


async def get_calcom_credentials(db: AsyncSession, user_id: UUID):
    """Fetches credentials and returns decrypted API key for backend utility processing."""
    query = select(CalComIntegration).where(CalComIntegration.user_id == user_id)
    result = await db.execute(query)
    integration = result.scalar_one_or_none()

    if not integration:
        return None

    return {
        "api_key": decrypt_key(integration.encrypted_api_key),
        "event_type_id": integration.event_type_id
    }