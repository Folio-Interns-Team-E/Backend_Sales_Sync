import json
import re
import logging
from uuid import UUID

import httpx

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from sqlalchemy import String

from app.config import settings
from app.models.leads_pool import LeadPool
from app.models.lead import Lead
import io
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH


logger = logging.getLogger(__name__)


class ChatAgentsService:

    BASE_URL = "https://api.groq.com/openai/v1"
    MODEL = "openai/gpt-oss-120b"

    def __init__(self, db: AsyncSession):
        self.db = db

    # =====================================================
    # LEAD SEARCH FUNCTION (Kept exactly as original)
    # =====================================================

    async def search_leads(self, filters: dict, limit: int = 20):
        conditions = []

        keywords = filters.get("keywords", [])
        industries = filters.get("industry", [])
        countries = filters.get("country", [])

        # Search titles + keywords + company
        for word in keywords:
            conditions.append(LeadPool.title.ilike(f"%{word}%"))
            conditions.append(LeadPool.company_name.ilike(f"%{word}%"))
            conditions.append(LeadPool.raw_data.cast(String).ilike(f"%{word}%"))

        if industries:
            for industry in industries:
                conditions.append(LeadPool.industry.ilike(f"%{industry}%"))

        if countries:
            for country in countries:
                conditions.append(LeadPool.country.ilike(f"%{country}%"))

        query = select(LeadPool).where(or_(*conditions)).limit(limit)

        result = await self.db.execute(query)
        leads = result.scalars().all()

        return leads
        

    # =====================================================
    # AI CUSTOM EMAIL GENERATOR
    # =====================================================
    async def _generate_custom_email(
        self,
        lead_info: dict,
        icp: str,
        message: str,
        revision_feedback: str = ""
    ) -> dict:
        """Generates a highly customized outreach email draft based on lead data and ICP.

        If revision_feedback is provided, the prompt asks the model to rewrite the
        email addressing that feedback specifically (used for the single allowed
        revision pass after evaluation).
        """
        revision_block = ""
        if revision_feedback:
            revision_block = f"""
                IMPORTANT — This is a revision. A prior draft was reviewed and rejected for the following reason(s):
                \"\"\"
                {revision_feedback}
                \"\"\"
                Rewrite the email from scratch, fixing these issues while still following all rules below.
            """

        prompt = f"""You are an elite, hyper-efficient B2B sales development representative. 
            Write a highly tailored, razor-sharp cold outreach email to the target lead below based on our company's Ideal Customer Profile (ICP).
            {revision_block}
            Company ICP Context:
            \"\"\"
            {icp}
            \"\"\"

            Target Lead Data:
            \"\"\"
            {json.dumps(lead_info, indent=2)}
            \"\"\"

            Strict Writing Rules:
            1. Brevity is King: Keep the entire email under 100 words. Cut all fluff.
            2. Format: The email must consist of exactly 3 single-sentence paragraphs. 
            - Separate paragraphs with exactly two newlines (\\n\\n).
            - DO NOT indent paragraphs. No leading spaces, tabs, or whitespace on any line. Every paragraph must start completely flat against the left margin.
            3. No Clichés: Never start with "Hope this email finds you well," "My name is," or "I stumbled upon your profile." Start directly with a relevant hook.
            4. Structure: 
            - Paragraph 1 (The Hook): A highly specific, personalized observation about their role, recent company news, or a current pain point.
            - Paragraph 2 (The Value): Connect our value proposition (from our ICP) directly to solving that specific challenge in one clear sentence.
            - Paragraph 3 (Low-Friction CTA): Ask a single open-ended, low-commitment question.

            Example of Perfect Formatting (Copy this structure exactly):
            {{
                "subject": "Acme's pipeline infrastructure",
                "body": "Saw your recent update on upgrading Acme's real-time data ingestion pipelines, Sarah.\\n\\nWe help high-growth platforms scale their event streaming without the typical database bottleneck or latency spikes.\\n\\nAre you open to exploring if this could optimize your processing speeds next week?"
            }}

            Return ONLY a valid JSON object matching this schema:
            {{
                "subject": "Short, pattern-interrupting subject line (under 5 words, no clickbait)",
                "body": "The personalized body text of the email containing exactly 3 distinct paragraphs separated by \\n\\n."
            }}

            
            """
            
        payload = {
                "model": self.MODEL,
                "messages": [{"role": "system", "content": prompt}, {
                    "role": "user", 
                    "content": message
                }],
                "temperature": 0.3,  # Lowered to ensure precision and prevent sales-y rambling
                "max_tokens": 350,
                "response_format": {"type": "json_object"}
            }

        async with httpx.AsyncClient(timeout=30) as client:
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
            #cleaned = re.sub(r"^```json\s*|\s*```$", "", content, flags=re.IGNORECASE)
            return json.loads(content)

    async def _evaluate_email(self, email_content: dict, lead_info: dict, icp: str, message) -> dict:
        """Evaluation agent: reviews a drafted email against the ICP and the copywriter's
        own formatting/content rules, and decides whether it needs a revision.

        Returns: {"approved": bool, "feedback": str}
        On any failure (network, malformed JSON), fails open and approves the draft
        as-is so a transient evaluator issue never blocks the whole DRAFT_EMAIL flow.
        """
        subject = email_content.get("subject", "")
        body = email_content.get("body", "")

        prompt = f"""You are a strict quality reviewer for B2B cold outreach emails. Evaluate the DRAFT below
            against the Ideal Customer Profile (ICP) and the required rules. Be critical — vague, generic,
            or rule-breaking drafts should be rejected.

            Company ICP Context:
            \"\"\"
            {icp}
            \"\"\"

            Target Lead Data:
            \"\"\"
            {json.dumps(lead_info, indent=2)}
            \"\"\"

            Draft Subject:
            \"\"\"
            {subject}
            \"\"\"

            Draft Body:
            \"\"\"
            {body}
            \"\"\"

            Check the draft against ALL of these criteria:
            1. It should adhere to ICP
            2. Users recommendations should be followed in the email.
            3. No clichés such as "Hope this email finds you well", "My name is", "I stumbled upon your profile".
            4. Paragraph 1 is a specific, personalized hook tied to the lead's real data (not generic).
            5. Paragraph 2 clearly ties the ICP's value proposition to the lead's specific situation.
            6. Paragraph 3 is a single low-commitment, open-ended question.
            7. Subject line is under 5 words and not clickbait-y.

            Return ONLY a valid JSON object matching this schema:
            {{
                "approved": true or false,
                "feedback": "If not approved, a short, specific, actionable list of what to fix. Empty string if approved."
            }}
            """

        payload = {
            "model": self.MODEL,
            "messages": [{"role": "system", "content": prompt}, {
                    "role": "user", 
                    "content": message
                }],
            "temperature": 0.0,
            "max_tokens": 250,
            "response_format": {"type": "json_object"}
        }

        try:
            async with httpx.AsyncClient(timeout=30) as client:
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
                #cleaned = re.sub(r"^```json\s*|\s*```$", "", content, flags=re.IGNORECASE)
                result = json.loads(content)
                return {
                    "approved": bool(result.get("approved", True)),
                    "feedback": result.get("feedback", "")
                }
        except (httpx.HTTPError, KeyError, json.JSONDecodeError):
            # Fail open: don't let a broken evaluator block drafting.
            return {"approved": True, "feedback": ""}
        

    async def search_current_leads_by_name(self, team_id: UUID, name_keywords: list,  limit: int = 1, email: str = None):
        if not name_keywords and not email:
            return []

        conditions = []
        if name_keywords:
            name_conditions = [Lead.name.ilike(f"%{k}%") for k in name_keywords]
            conditions.append(or_(*name_conditions))
            
        # If a valid email is provided, prioritize matching by email OR name
        if email and email != "no-email@provided.com":
            conditions.append(Lead.email == email)

        query = (
            select(Lead)
            .where(Lead.team_id == team_id, or_(*conditions))
            .limit(limit)
        )
        
        result = await self.db.execute(query)
        return result.scalars().all()