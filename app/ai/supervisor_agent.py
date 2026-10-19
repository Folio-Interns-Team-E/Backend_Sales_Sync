# app/ai/supervisor_agent.py

import json
import re
import logging
from datetime import datetime
from uuid import UUID

import httpx
from app.ai.product_context import SALESYNC_PRODUCT_CONTEXT
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.config import settings
from app.models.lead import Lead
from app.models.meeting import Meeting

logger = logging.getLogger(__name__)


class SupervisorAgent:
    """
    Dedicated supervisor agent responsible for synthesizing raw backend 
    execution results, system status, and context into clean, conversational, 
    and highly polished executive-level markdown responses.
    """

    BASE_URL = "https://api.groq.com/openai/v1"
    MODEL = "openai/gpt-oss-120b"
    ACTIONS = {
        "UPDATE_ICP",
        "GET_LEADS",
        "ANALYZE_LEAD",
        "DRAFT_EMAIL",
        "MEETING_OPERATION",
        "GENERATE_PROPOSAL",
        "NORMAL",
    }
    ACTION_ALIASES = {
        "CREATE_MEETING": "MEETING_OPERATION",
        "CANCEL_MEETING": "MEETING_OPERATION",
        "RESCHEDULE_MEETING": "MEETING_OPERATION",
    }

    def __init__(self, db_session: AsyncSession):
        self.db = db_session

    @classmethod
    def normalize_action(cls, payload: object) -> dict:
        """Turn untrusted model output into the small contract used by ChatService."""
        if not isinstance(payload, dict):
            raise ValueError("AI router returned an invalid response")

        raw_action = str(payload.get("action", "NORMAL")).strip().upper()
        action = cls.ACTION_ALIASES.get(raw_action, raw_action)
        if action not in cls.ACTIONS:
            action = "NORMAL"

        raw_parameters = payload.get("parameters")
        parameters = raw_parameters if isinstance(raw_parameters, dict) else {}

        normalized: dict[str, object] = {}
        for key in ("keywords", "industry", "country"):
            value = parameters.get(key, [])
            if isinstance(value, str):
                value = [value]
            if isinstance(value, list):
                normalized[key] = [
                    str(item).strip()[:200]
                    for item in value[:20]
                    if str(item).strip()
                ]
            else:
                normalized[key] = []

        try:
            normalized["limit"] = max(1, min(int(parameters.get("limit", 20)), 50))
        except (TypeError, ValueError):
            normalized["limit"] = 20

        start_time = parameters.get("start_time")
        if isinstance(start_time, str) and start_time.strip():
            normalized["start_time"] = start_time.strip()[:100]

        return {"action": action, "parameters": normalized}

    async def extract_action(self, message: str, icp: str) -> dict:
        """
        Interacts with the LLM to classify user intent and extract routing parameters.
        """
        prompt = f"""You are a B2B sales AI routing assistant. Your job is to classify the user's intent and extract matching parameters.
                Assume the current year context is 2026.

                Current Company ICP:
                \"\"\"
                {icp}
                \"\"\"

                You must respond ONLY with a valid JSON object matching this schema:
                {{
                    "action": "UPDATE_ICP" | "GET_LEADS" | "ANALYZE_LEAD" | "DRAFT_EMAIL" | "MEETING_OPERATION" | "GENERATE_PROPOSAL" | "NORMAL",
                    "parameters": {{
                        "keywords": ["list", "of", "titles/roles/queries/names (used for GET_LEADS, ANALYZE_LEAD, DRAFT_EMAIL, CREATE_MEETING, CANCEL_MEETING)"],
                        "industry": ["list", "of", "industries (only used for GET_LEADS)"],
                        "country": ["list", "of", "countries (only used for GET_LEADS)"],
                        "limit": int (default 20, max 50),
                        "start_time": "string (ISO 8601 timestamp YYYY-MM-DDTHH:MM:SS, only used for CREATE_MEETING)"
                    }}
                }}

                Intent Rules:
                1. UPDATE_ICP: When the user explicitly wants to update, rewrite, change, or modify their Ideal Customer Profile (ICP).
                2. GET_LEADS: When the user wants to search, pull, find, or look up prospects broadly.
                3. ANALYZE_LEAD: When the user explicitly names a specific person or a group of people to analyze or qualify.
                4. DRAFT_EMAIL: When the user asks to write, draft, generate, or compose an email to a specific person.
                5. MEETING_OPERATION: When the user wants to schedule, book, set up, arrange, cancel, delete, or reschedule any meeting or calendar appointment.
                6. NORMAL: For general questions or conversational small talk.
                7. GENERATE_PROPOSAL: When the user asks to write, generate, create, compile, or build a business proposal document for a specific client target or context company name.

                Examples:

                User: "Schedule a meeting with Dharmesh Shah for tomorrow at 2 PM"
                Output: {{"action": "MEETING_OPERATION", "parameters": {{"keywords": ["Dharmesh Shah"], "start_time": "2026-07-09T14:00:00"}}}}

                User: "Cancel my appointment with Dharmesh"
                Output: {{"action": "MEETING_OPERATION", "parameters": {{"keywords": ["Dharmesh"]}}}}

                User message:
                "{message}"
                """

        payload = {
            "model": self.MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "max_tokens": 500,
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
            raw_content = data["choices"][0]["message"]["content"]
            
            cleaned_content = re.sub(r"^```json\s*|\s*```$", "", raw_content.strip(), flags=re.IGNORECASE)
            return self.normalize_action(json.loads(cleaned_content))

    async def run(
        self, 
        user_prompt: str, 
        execution_result: str, 
        team_id: UUID,
        messages_history: list = None,
        user_info: dict = None
    ) -> str:
        """
        Primary entry point to synthesize execution results and reply conversationally.
        """
        # 1. Fetch active pipeline leads for this team to provide context to the supervisor
        try:
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
        except Exception as e:
            logger.warning(f"SupervisorAgent failed to pull database leads context: {e}")
            leads_context = []

        try:
            meeting_rows = (await self.db.execute(
                select(Meeting, Lead)
                .join(Lead, Meeting.lead_id == Lead.id)
                .where(Lead.team_id == team_id)
                .order_by(Meeting.date.desc())
                .limit(20)
            )).all()
            meetings_context = [
                {"prospect": lead.name, "company": lead.company_name, "date": str(meeting.date),
                 "time": str(meeting.time), "timezone": meeting.timezone, "status": meeting.status,
                 "agenda": meeting.agenda, "meet_url": meeting.meet_url}
                for meeting, lead in meeting_rows
            ]
        except Exception as exc:
            logger.warning("SupervisorAgent could not load meeting context: %s", exc)
            meetings_context = []

        # 2. Compile response using the LLM with structured instruction parameters
        try:
            return await self._synthesize_response(
                user_prompt=user_prompt,
                execution_result=execution_result,
                leads_context=leads_context,
                meetings_context=meetings_context,
                messages_history=messages_history or [],
                user_info=user_info or {}
            )
        except Exception as e:
            logger.error(f"SupervisorAgent synthesis failed: {e}", exc_info=True)
            # The execution result is already written for the user. Returning it
            # directly also avoids exposing an internal fallback status message.
            return execution_result

    async def _synthesize_response(
        self, 
        user_prompt: str, 
        execution_result: str, 
        leads_context: list,
        meetings_context: list,
        messages_history: list,
        user_info: dict
    ) -> str:
        """
        Interacts with Groq to synthesize raw data and action logs into a markdown response.
        """
        anchor_time = datetime.now().strftime("%A, %B %d, %Y, %I:%M %p (Asia/Karachi)")

        system_prompt = f"""
            You are SalesSync Assistant, a friendly and capable B2B sales workflow assistant.

            ### PRODUCT IDENTITY (NON-NEGOTIABLE)
            {SALESYNC_PRODUCT_CONTEXT}

            You operate the SalesSync platform for the user. Do not speak as though
            SalesSync itself is selling the workspace's product or service.

            Your primary role is to take raw, technical data from the "Execution Result" (which has already run successfully) and translate it alongside the "User Message" into a polished, conversational, and executive-ready update.

            ---

            ### 🛠️ YOUR TOOLKIT & CAPABILITIES
            You can guide users, trigger, or interpret results for the following operations:
            * 😊 `UPDATE_ICP` (Refining Ideal Customer Profiles)
            * 😄 `GET_LEADS` (Sourcing and compiling potential prospects)
            * 😎 `ANALYZE_LEAD` (Deep-diving into lead insights and data)
            * 🤔 `DRAFT_EMAIL` (Crafting tailored sales outreach)
            * 😉 `MEETING_OPERATION` (Scheduling, rescheduling, or canceling meetings)
            * 👍 `GENERATE_PROPOSAL` (Creating B2B sales proposals)
            * 👋 `NORMAL` (General, friendly B2B sales consulting and chat)

            *Note: If a user asks for something completely outside of these sales domains, politely inform them of your focus areas.*

            ---

            ### 📋 SYSTEM CONTEXT & METADATA
            * Assume the current year is 2026.
            * SYSTEM ANCHOR TIME: "{anchor_time}"

            * CURRENT USER PROFILE:
            - Name: {user_info.get('full_name', 'Valued User')}
            - Email: {user_info.get('email', 'N/A')}
            - Company: {user_info.get('company', 'Not specified')}
            - Role: {user_info.get('job_title', 'Not specified')}

            * RECENT CONVERSATIONAL HISTORY (Last 5 Messages):
            {json.dumps(messages_history, indent=2)}

            * CURRENT TEAM PROSPECTS CONTEXT:
            {json.dumps(leads_context, indent=2)}

            * CURRENT TEAM MEETINGS CONTEXT (only this workspace):
            {json.dumps(meetings_context, indent=2)}

            When asked about meetings, use only these meeting records. Never invent dates, links, attendees, or completed actions. Never expose OAuth tokens or another workspace's data.

            ---

            ### ✍️ TONE AND FORMATTING RULES
            1. **The Style:** Be polite, incredibly helpful, and slightly informal (e.g., skip stiff sign-offs like "Best regards" or "Sincerely"). Speak like a trusted, brilliant peer.
            2. **The Output:** Do NOT return JSON. Write in a simple, easy-to-read, and beautifully clean paragraph format. No dense markdown styling. Keep it short, direct, and to the point.
            3. **Emoji Rule:** You are allowed to use emojis, but keep it tasteful and minimal to keep things professional yet friendly. Use max 1-2 emojis contextually: 🧐 (debugging), 😎/💪 (success), 🎉/🥳 (milestones), or 🙌 (relief/teamwork). 😎
            4. **Data Synthesis:** Translate raw system data, tracking numbers, or event UIDs from the "Execution Result" into conversational, human-friendly sentences.
            5. **Success Framing:** Only claim success when the execution result explicitly confirms it. Explain failures and missing connections plainly.
            6. Dont use "-" and "—"
            """

        user_content = f"""
            User Message:
            \"\"\"
            {user_prompt}
            \"\"\"

            Execution Result:
            \"\"\"
            {execution_result}
            \"\"\"
            """
        payload = {
            "model": self.MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            "temperature": 0.3,
            "max_tokens": 1200
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

            return content
