import logging
from typing import Optional
from uuid import UUID
from datetime import date, time
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from fastapi import HTTPException, status
from app.models.meeting import Meeting
from app.models.lead import Lead
from app.models.team import Team
from app.models.team_member import TeamMember

logger = logging.getLogger(__name__)


class MeetingService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _get_user_team(self, user_id: UUID) -> Team:
        result = await self.db.execute(
            select(TeamMember).where(TeamMember.user_id == user_id)
        )
        membership = result.scalar_one_or_none()
        if not membership:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User has no team")
        result = await self.db.execute(select(Team).where(Team.id == membership.team_id))
        team = result.scalar_one_or_none()
        if not team:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
        return team

    async def list_meetings(self, user_id: UUID):
        team = await self._get_user_team(user_id)
        query = (
            select(Meeting)
            .join(Lead, Meeting.lead_id == Lead.id)
            .where(Lead.team_id == team.id)
            .order_by(desc(Meeting.date))
        )
        result = await self.db.execute(query)
        return result.scalars().all()

    async def get_meeting(self, meeting_id: UUID, user_id: UUID):
        team = await self._get_user_team(user_id)
        result = await self.db.execute(
            select(Meeting)
            .join(Lead, Meeting.lead_id == Lead.id)
            .where(Meeting.id == meeting_id, Lead.team_id == team.id)
        )
        meeting = result.scalar_one_or_none()
        if not meeting:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")
        return meeting

    async def create_meeting(self, user_id: UUID, lead_id: UUID,
                              meeting_date: date, meeting_time: time,
                              timezone: str = "UTC",
                              calendar_event_id: Optional[str] = None,
                              agenda: Optional[str] = None,
                              notes: Optional[str] = None):
        team = await self._get_user_team(user_id)
        meeting = Meeting(
            lead_id=lead_id,
            created_by=user_id,
            date=meeting_date,
            time=meeting_time,
            timezone=timezone,
            calendar_event_id=calendar_event_id,
            agenda=agenda,
            notes=notes,
        )
        self.db.add(meeting)
        await self.db.commit()
        await self.db.refresh(meeting)
        return meeting

    async def update_meeting(self, meeting_id: UUID, user_id: UUID,
                              status: Optional[str] = None,
                              notes: Optional[str] = None,
                              agenda: Optional[str] = None,
                              meeting_date: Optional[date] = None,
                              meeting_time: Optional[time] = None,
                              timezone: Optional[str] = None,
                              calendar_event_id: Optional[str] = None):
        meeting = await self.get_meeting(meeting_id, user_id)
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

    async def delete_meeting(self, meeting_id: UUID, user_id: UUID):
        meeting = await self.get_meeting(meeting_id, user_id)
        await self.db.delete(meeting)
        await self.db.commit()
