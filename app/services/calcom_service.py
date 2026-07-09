import httpx
import logging
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.config import settings
from app.models.meeting import Meeting, MeetingStatus


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