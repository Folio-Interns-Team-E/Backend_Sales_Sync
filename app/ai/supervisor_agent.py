# app/ai/supervisor_agent.py

import json
import re
import logging
from datetime import datetime
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.config import settings
from app.models.lead import Lead

logger = logging.getLogger(__name__)


class SupervisorAgent:
    """
    Dedicated supervisor agent responsible for synthesizing raw backend 
    execution results, system status, and context into clean, conversational, 
    and highly polished executive-level markdown responses.
    """

    BASE_URL = "https://api.groq.com/openai/v1"
    MODEL = "openai/gpt-oss-120b"

    def __init__(self, db_session: AsyncSession):
        self.db = db_session

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
                Output: {{"action": "CREATE_MEETING", "parameters": {{"keywords": ["Dharmesh Shah"], "start_time": "2026-07-09T14:00:00"}}}}

                User: "Cancel my appointment with Dharmesh"
                Output: {{"action": "CANCEL_MEETING", "parameters": {{"keywords": ["Dharmesh"]}}}}

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
            return json.loads(cleaned_content)

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

        # 2. Compile response using the LLM with structured instruction parameters
        try:
            return await self._synthesize_response(
                user_prompt=user_prompt,
                execution_result=execution_result,
                leads_context=leads_context,
                messages_history=messages_history or [],
                user_info=user_info or {}
            )
        except Exception as e:
            logger.error(f"SupervisorAgent synthesis failed: {e}", exc_info=True)
            return (
                "The action was executed successfully"
                f"{execution_result}"
            )

    async def _synthesize_response(
        self, 
        user_prompt: str, 
        execution_result: str, 
        leads_context: list,
        messages_history: list,
        user_info: dict
    ) -> str:
        """
        Interacts with Groq to synthesize raw data and action logs into a markdown response.
        """
        anchor_time = datetime.now().strftime("%A, %B %d, %Y, %I:%M %p (Asia/Karachi)")

        system_prompt = f"""
            You are Salsy, an elite, friendly, and highly capable enterprise B2B sales supervisor assistant representing "SaleSync AI", an advanced AI-powered SaaS application.

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

            * RECENT CONVERSATIONAL HISTORY (Last 5 Messages):
            {json.dumps(messages_history, indent=2)}

            * CURRENT TEAM PROSPECTS CONTEXT:
            {json.dumps(leads_context, indent=2)}

            ---

            ### ✍️ TONE AND FORMATTING RULES
            1. **The Style:** Be polite, incredibly helpful, and slightly informal (e.g., skip stiff sign-offs like "Best regards" or "Sincerely"). Speak like a trusted, brilliant peer.
            2. **The Output:** Do NOT return JSON. Write in a simple, easy-to-read, and beautifully clean paragraph format. No dense markdown styling. Keep it short, direct, and to the point.
            3. **Emoji Rule:** You are allowed to use emojis, but keep it tasteful and minimal to keep things professional yet friendly. Use max 1-2 emojis contextually: 🧐 (debugging), 😎/💪 (success), 🎉/🥳 (milestones), or 🙌 (relief/teamwork). 😎
            4. **Data Synthesis:** Translate raw system data, tracking numbers, or event UIDs from the "Execution Result" into conversational, human-friendly sentences.
            5. **Success Framing:** Assume whatever operation was triggered has already completed successfully. Celebrate the win and explain the outcome clearly to the user.
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