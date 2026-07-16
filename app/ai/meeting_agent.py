import json
import re
import logging
from datetime import datetime
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, cast, String

from app.config import settings
from app.models.lead import Lead
from app.models.meeting import Meeting, MeetingStatus
from app.services.calcom_service import CalComService

logger = logging.getLogger(__name__)


class MeetingAgent:
    """
    Dedicated agent responsible for parsing, qualifying, scheduling,
    and canceling meetings. Mirroring the B2B proposal agent structure,
    this agent parses unstructured requests using the Groq LLM API.
    """

    BASE_URL = "https://api.groq.com/openai/v1"
    MODEL = "openai/gpt-oss-120b"

    def __init__(self, db_session: AsyncSession):
        self.db = db_session

    async def run(self, user_prompt: str, team_id: UUID) -> str:
        """
        Primary entry point for resolving and executing calendar-related intents.
        """
        # 1. Fetch active pipeline leads for this team to pass to the LLM as context
        leads_query = select(Lead).where(Lead.team_id == team_id)
        res = await self.db.execute(leads_query)
        leads = res.scalars().all()

        leads_context = [
            {
                "id": str(lead.id),
                "name": lead.name,
                "company_name": lead.company_name,
                "email": lead.email
            }
            for lead in leads
        ]

        # 2. Ask LLM to determine intent and map parameters
        try:
            parsed_decision = await self._compile_meeting_decision(
                user_prompt=user_prompt,
                leads_context=leads_context
            )
        except Exception as e:
            logger.error(f"MeetingAgent structured parsing failed: {e}", exc_info=True)
            return "MeetingAgent was unable to successfully parse your request context."

        decision = parsed_decision.get("decision")
        lead_id_str = parsed_decision.get("matched_lead_id")

        if decision == "NEED_CLARIFICATION":
            return parsed_decision.get("clarification_message") or "Could you clarify the details?"

        if not lead_id_str:
            return "MeetingAgent Error: Action decided but no lead profile was matched."

        try:
            lead_uuid = UUID(lead_id_str)
        except ValueError:
            return "MeetingAgent Error: Invalid lead ID format received."

        target_lead = next((l for l in leads if l.id == lead_uuid), None)
        if not target_lead:
            return "MeetingAgent Error: Lead missing in workspace database."

        # Handle Decision: CREATE
        if decision == "CREATE":
            start_time_str = parsed_decision.get("start_time")
            return await self._execute_create(target_lead, start_time_str)

        # Handle Decision: CANCEL (Passing the target cancel time)
        if decision == "CANCEL":
            target_cancel_time_str = parsed_decision.get("target_cancel_time")
            return await self._execute_cancel(target_lead, target_cancel_time_str)

        return "MeetingAgent encountered an unhandled operations routing path."

    async def _compile_meeting_decision(self, user_prompt: str, leads_context: list) -> dict:
        """
        Interacts with the LLM to parse and structure the scheduling intent.
        """
        anchor_time = datetime.now().strftime("%A, %B %d, %Y, %I:%M %p (Asia/Karachi)")

        system_prompt = f"""You are an elite enterprise B2B sales scheduling assistant.
        Your job is to parse unstructured calendar scheduling requests and map them to known prospects.
        Assume the current context year is 2026.

        SYSTEM ANCHOR TIME (All of your relative date/time math must resolve relative to this anchor):
        \"\"\"
        {anchor_time}
        \"\"\"

        CURRENT TEAM PROSPECTS:
        \"\"\"
        {json.dumps(leads_context, indent=2)}
        \"\"\"

        Return ONLY a valid JSON object matching this exact schema layout structure:
        {{
            "decision": "CREATE" | "CANCEL" | "NEED_CLARIFICATION",
            "matched_lead_id": "string (UUID, or null)",
            "start_time": "string (ISO 8601 YYYY-MM-DDTHH:MM:SS, for CREATE, otherwise null)",
            "target_cancel_time": "string (ISO 8601 YYYY-MM-DDTHH:MM:SS, only for CANCEL if specified, otherwise null)",
            "clarification_message": "string (or null)"
        }}

        Decision Logic:
        1. CREATE: Use this if the user wants to schedule/book. Requires a matched lead profile and a clean, unambiguous start_time.
        2. CANCEL: Use this if the user wants to remove/cancel a meeting. Requires a matched lead profile.
        3. NEED_CLARIFICATION: Use this if the lead name is missing/unmatched, or if the time context is highly ambiguous. Keep clarification messages brief, friendly, and specific.
        """

        payload = {
            "model": self.MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.2,
            "max_tokens": 1000,
            "response_format": {"type": "json_object"}
        }

        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{self.BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.grok_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"].strip()

            cleaned = re.sub(r"^```json\s*|\s*```$", "", content, flags=re.IGNORECASE)
            return json.loads(cleaned)

    async def _execute_create(self, lead: Lead, start_time_str: str) -> str:
        if not start_time_str:
            return "Meeting Agent could not isolate a valid clean timestamp. Could you specify a time?"

        try:
            start_time_dt = datetime.fromisoformat(start_time_str)
            cal_service = CalComService(self.db)

            await cal_service.create_booking(
                lead_id=lead.id,
                start_time=start_time_dt,
                name=lead.name,
                email=lead.email,
                agenda=f"AI Agent Automated Demo Routing with {lead.company_name or 'Lead'}"
            )

            return (
                f"Meeting Scheduled Successfully!\n"
                f"Attendee: {lead.name} ({lead.email or 'No email'})\n"
                f"Time: {start_time_dt.strftime('%Y-%m-%d %I:%M %p')} \n\n"
                f"The event has been securely updated in your calendar and synced locally to your pipeline tracker."
            )
        except Exception as e:
            logger.error(f"CalCom booking creation failed: {e}", exc_info=True)
            return f"Failed to execute calendar booking on Cal.com: {str(e)}"

    async def _execute_cancel(self, lead: Lead, target_cancel_time_str: str | None) -> str:
        # 1. Build base query
        meeting_query = (
            select(Meeting)
            .where(
                Meeting.lead_id == lead.id,
                Meeting.status == MeetingStatus.SCHEDULED.value
            )
        )

        
        # 2. Match exact date and parse time safely
        if target_cancel_time_str:
            try:
                target_dt = datetime.fromisoformat(target_cancel_time_str)
                target_date = target_dt.date()
                target_time = target_dt.time()  # This yields a Python datetime.time object

                meeting_query = meeting_query.where(
                    Meeting.date == target_date,
                    Meeting.time == target_time
                )
            except ValueError:
                return "MeetingAgent Error: Could not parse target cancel time format."
    
        meeting_res = await self.db.execute(meeting_query)
        meetings = meeting_res.scalars().all()

       


        

        # 3. Fallback error formatting
        if not meetings:
            fallback_query = select(Meeting).where(
                Meeting.lead_id == lead.id,
                Meeting.status == MeetingStatus.SCHEDULED.value
            )
            fallback_res = await self.db.execute(fallback_query)
            all_active = fallback_res.scalars().all()

            time_info = f" at {datetime.fromisoformat(target_cancel_time_str).strftime('%Y-%m-%d %I:%M %p')}" if target_cancel_time_str else ""
            
            if all_active:
                scheduled_list = ", ".join([f"{m.date} at {m.time}" for m in all_active])
                return f"I couldn't find a meeting specifically on **{time_info.strip()}**. However, I found these active bookings for **{lead.name}**: {scheduled_list}."

            return f"No active scheduled appointments found in your database for **{lead.name}**{time_info}."

        if len(meetings) > 1:
            scheduled_times = ", ".join([f"{m.date} {m.time}" for m in meetings])
            return f"I found multiple scheduled meetings for **{lead.name}** on: {scheduled_times}. Which one would you like to cancel?"

        active_meeting = meetings[0]

        # 4. Perform cancellation
        try:
            cal_service = CalComService(self.db)
            await cal_service.cancel_booking(
                booking_uid=active_meeting.calendar_event_id,
                meeting_id=active_meeting.id
            )

            meeting_time_str = f"{active_meeting.date} {active_meeting.time}"
            return (
                f"Meeting Canceled Successfully\n"
                f"The scheduled meeting with {lead.name} on {meeting_time_str} "
                f"(Event UID: `{active_meeting.calendar_event_id}`) has been withdrawn "
                f"and marked as `{MeetingStatus.CANCELLED.value}` locally."
            )
        except Exception as e:
            logger.error(f"CalCom booking cancellation failed: {e}", exc_info=True)
            return f"Failed to cancel meeting: {str(e)}"