import logging
from typing import Optional
from uuid import UUID
from datetime import date, time
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from fastapi import HTTPException, status
from app.models.meeting import Meeting
from app.models.lead import Lead
from app.schemas.meetings import MeetingResponse
from app.services.google_calendar_service import create_calendar_meeting, delete_calendar_meeting

logger = logging.getLogger(__name__)


class MeetingService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_meetings(self, team_id: UUID):
        query = (
            select(Meeting, Lead)
            .join(Lead, Meeting.lead_id == Lead.id)
            .where(Lead.team_id == team_id)
            .order_by(desc(Meeting.date))
        )
        result = await self.db.execute(query)
        data = [
            {**MeetingResponse.model_validate(meeting).model_dump(mode="json"), "client": lead.name, "company": lead.company_name}
            for meeting, lead in result.all()
        ]
        return data

    async def get_meeting(self, meeting_id: UUID, team_id: UUID):
        result = await self.db.execute(
            select(Meeting)
            .join(Lead, Meeting.lead_id == Lead.id)
            .where(Meeting.id == meeting_id, Lead.team_id == team_id)
        )
        meeting = result.scalar_one_or_none()
        if not meeting:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")
        return meeting

    async def create_meeting(self, team_id: UUID, user_id: UUID, lead_id: UUID,
                              meeting_date: date, meeting_time: time,
                              timezone: str = "UTC",
                              duration_minutes: int = 30,
                              agenda: Optional[str] = None,
                              notes: Optional[str] = None):
        result = await self.db.execute(
            select(Lead).where(Lead.id == lead_id, Lead.team_id == team_id)
        )
        lead = result.scalar_one_or_none()
        if not lead:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")

        description = f"SalesSync meeting with {lead.name} ({lead.company_name or 'prospect'})."
        if agenda:
            description += f"\nAgenda: {agenda}"
        calendar = await create_calendar_meeting(
            self.db, user_id, title=f"Meeting with {lead.name}", description=description,
            meeting_date=meeting_date, meeting_time=meeting_time,
            timezone_name=timezone, duration_minutes=duration_minutes,
        )
        meeting = Meeting(
            lead_id=lead_id,
            created_by=user_id,
            date=meeting_date,
            time=meeting_time,
            timezone=timezone,
            calendar_event_id=calendar["event_id"],
            calendar_provider="google",
            meet_url=calendar["meet_url"],
            duration_minutes=duration_minutes,
            agenda=agenda,
            notes=notes,
        )
        self.db.add(meeting)
        try:
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            try:
                await delete_calendar_meeting(self.db, user_id, calendar["event_id"])
            except Exception:
                logger.exception("Could not compensate failed meeting save in Google Calendar")
            raise
        await self.db.refresh(meeting)
        return meeting

    async def update_meeting(self, meeting_id: UUID, team_id: UUID,
                              status: Optional[str] = None,
                              notes: Optional[str] = None,
                              agenda: Optional[str] = None,
                              meeting_date: Optional[date] = None,
                              meeting_time: Optional[time] = None,
                              timezone: Optional[str] = None,
                              calendar_event_id: Optional[str] = None):
        meeting = await self.get_meeting(meeting_id, team_id)
        if meeting.calendar_provider == "google" and any(value is not None for value in (meeting_date, meeting_time, timezone, calendar_event_id)):
            raise HTTPException(status.HTTP_409_CONFLICT, "Rescheduling Google Calendar meetings is not available yet; cancel and create a new meeting")
        if meeting.calendar_provider == "google" and status == "Cancelled":
            await delete_calendar_meeting(self.db, meeting.created_by, meeting.calendar_event_id)
        if status:
            meeting.status = status
        if notes is not None:
            meeting.notes = notes
        if agenda is not None:
            meeting.agenda = agenda
        if meeting_date is not None:
            meeting.date = meeting_date
        if meeting_time is not None:
            meeting.time = meeting_time
        if timezone is not None:
            meeting.timezone = timezone
        if calendar_event_id is not None:
            meeting.calendar_event_id = calendar_event_id
        await self.db.commit()
        await self.db.refresh(meeting)
        return meeting

    async def delete_meeting(self, meeting_id: UUID, team_id: UUID):
        meeting = await self.get_meeting(meeting_id, team_id)
        if meeting.calendar_provider == "google" and meeting.calendar_event_id:
            await delete_calendar_meeting(self.db, meeting.created_by, meeting.calendar_event_id)
        await self.db.delete(meeting)
        await self.db.commit()
