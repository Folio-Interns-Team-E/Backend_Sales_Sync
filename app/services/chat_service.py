import logging
import traceback
import json
import re
from uuid import UUID

import httpx

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from sqlalchemy import String

from app.config import settings
from app.models.team import Team
from app.models.team_member import TeamMember
from app.models.chat import ChatMessage, ChatRole
from app.models.leads_pool import LeadPool
from app.models.lead import Lead, LeadStatus


logger = logging.getLogger(__name__)


class ChatService:

    BASE_URL = "https://api.groq.com/openai/v1"
    MODEL = "llama-3.3-70b-versatile"

    def __init__(self, db: AsyncSession):
        self.db = db

    async def _get_user_team(self, user_id: UUID):
        result = await self.db.execute(
            select(TeamMember).where(TeamMember.user_id == user_id)
        )
        membership = result.scalar_one_or_none()

        if not membership:
            raise ValueError("User has no team")

        result = await self.db.execute(
            select(Team).where(Team.id == membership.team_id)
        )
        team = result.scalar_one_or_none()

        if not team:
            raise ValueError("Team not found")

        return team

    async def update_icp(self, user_id: UUID, new_icp: str):
        team = await self._get_user_team(user_id)
        team.icp = new_icp
        await self.db.commit()
        return team.icp

    async def _get_icp_context(self, user_id: UUID):
        team = await self._get_user_team(user_id)
        return team.icp if team.icp else "No ICP available"

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
    # NEW: AI FIT SCORING GENERATOR
    # =====================================================
    async def _generate_fit_score(self, lead_info: dict, icp: str) -> dict:
        """Compares a fetched lead profile against the ICP to yield an objective score."""
        prompt = f"""You are an expert sales operations analyst. Evaluate the target lead data against the company's Ideal Customer Profile (ICP).

                Company ICP:
                \"\"\"
                {icp}
                \"\"\"

                Target Lead Data:
                \"\"\"
                {json.dumps(lead_info, indent=2)}
                \"\"\"

                Provide an objective analysis. Return ONLY a valid JSON object matching this schema:
                {{
                    "score": 85,
                    "justification": "A clear, concise 2-sentence explanation of why they received this score based on the ICP context."
                }}
                """
        payload = {
            "model": self.MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "max_tokens": 300,
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
            
            cleaned = re.sub(r"^```json\s*|\s*```$", "", content, flags=re.IGNORECASE)
            parsed = json.loads(cleaned)
            
            # 🔍 Debug log to inspect raw LLM behavior in your console
            logger.info(f"Raw LLM Qualification Output: {parsed}")
            
            # Extract score safely even if the LLM names it 'fit_score' or returns a string
            raw_score = parsed.get("score") or parsed.get("fit_score") or 0
            try:
                score_val = int(raw_score)
            except (ValueError, TypeError):
                score_val = 0
                
            return {
                "score": score_val,
                "justification": parsed.get("justification", "No evaluation details provided.")
            }
        

    # =====================================================
    # AI CUSTOM EMAIL GENERATOR
    # =====================================================
    async def _generate_custom_email(self, lead_info: dict, icp: str) -> dict:
        """Generates a highly customized outreach email draft based on lead data and ICP."""
        prompt = f"""You are an elite B2B sales development representative. Write a highly tailored, personalized cold outreach email to the target lead below based on our company's Ideal Customer Profile (ICP).

                Company ICP Context:
                \"\"\"
                {icp}
                \"\"\"

                Target Lead Data:
                \"\"\"
                {json.dumps(lead_info, indent=2)}
                \"\"\"

                Guidelines:
                1. Make it professional, relevant, and short (under 150 words).
                2. Directly hook their specific role, company, or background data.
                3. Do not use generic placeholders.

                Return ONLY a valid JSON object matching this schema:
                {{
                    "subject": "Compelling, short email subject line",
                    "body": "The personalized body text of the email."
                }}
                """
        payload = {
            "model": self.MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7,  # slightly higher for creative writing variance
            "max_tokens": 500,
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
            cleaned = re.sub(r"^```json\s*|\s*```$", "", content, flags=re.IGNORECASE)
            return json.loads(cleaned)
    # =====================================================
    # ENHANCED AI PROMPT WITH ANALYZE ACTION ADDED
    # =====================================================
    async def extract_action(self, message: str, icp: str) -> dict:
        prompt = f"""You are a B2B sales AI routing assistant. Your job is to classify the user's intent and extract matching parameters.

                Current Company ICP:
                \"\"\"
                {icp}
                \"\"\"

                You must respond ONLY with a valid JSON object matching this schema:
                {{
                    "action": "UPDATE_ICP" | "GET_LEADS" | "ANALYZE_LEAD" | "DRAFT_EMAIL" | "NORMAL",
                    "parameters": {{
                        "new_icp": "string (only used for UPDATE_ICP)",
                        "keywords": ["list", "of", "titles/roles/queries/names (used for GET_LEADS, ANALYZE_LEAD, or DRAFT_EMAIL)"],
                        "industry": ["list", "of", "industries (only used for GET_LEADS)"],
                        "country": ["list", "of", "countries (only used for GET_LEADS)"],
                        "limit": int (default 20, max 50)
                    }}
                }}

                Intent Rules:
                1. UPDATE_ICP: When the user explicitly wants to update, rewrite, change, or modify their Ideal Customer Profile (ICP).
                2. GET_LEADS: When the user wants to search, pull, find, or look up prospects broadly.
                3. ANALYZE_LEAD: When the user explicitly names a specific person or company to analyze or qualify.
                4. DRAFT_EMAIL: When the user asks to write, draft, generate, or compose an email to a specific person or lead name (e.g., "write an email to Dharmesh Shah", "draft a message for Elon Musk"). Put the person's name in the "keywords" array parameter.
                5. NORMAL: For general questions or conversational small talk.

                Examples:

                User: "Find SaaS founders in America"
                Output: {{"action": "GET_LEADS", "parameters": {{"keywords": ["founder", "CEO"], "industry": ["SaaS"], "country": ["USA"], "limit": 20}}}}

                User: "analyze Dharmesh Shah"
                Output: {{"action": "ANALYZE_LEAD", "parameters": {{"keywords": ["Dharmesh Shah"], "limit": 1}}}}

                User: "Change my target market to healthcare startups"
                Output: {{"action": "UPDATE_ICP", "parameters": {{"new_icp": "Healthcare startups"}} }}

                User: "draft an email to Dharmesh Shah"
                Output: {{"action": "DRAFT_EMAIL", "parameters": {{"keywords": ["Dharmesh Shah"], "limit": 1}}}}

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


    async def search_current_leads_by_name(self, team_id: UUID, name_keywords: list, limit: int = 1):
        """Searches the permanent Lead table for a lead matching the team_id and name."""
        if not name_keywords:
            return []
            
        conditions = []
        for keyword in name_keywords:
            conditions.append(Lead.name.ilike(f"%{keyword}%"))
            
        query = (
            select(Lead)
            .where(Lead.team_id == team_id, or_(*conditions))
            .limit(limit)
        )
        
        result = await self.db.execute(query)
        return result.scalars().all()
    
    
    
    # =====================================================
    # MAIN CHAT ROUTER
    # =====================================================
    async def send_message(self, user_id: UUID, message: str):
        try:
            team = await self._get_user_team(user_id)
            icp = await self._get_icp_context(user_id)

            self.db.add(
                ChatMessage(
                    team_id=team.id,
                    user_id=user_id,
                    sent_by=ChatRole.USER.value,
                    content=message,
                    metadata_log={},
                )
            )

            ai_response = await self.extract_action(message, icp)
            action = ai_response.get("action", "NORMAL")
            params = ai_response.get("parameters", {})

            if action == "UPDATE_ICP":
                new_icp = params.get("new_icp", "").strip()
                if new_icp:
                    await self.update_icp(user_id, new_icp)
                    response = "ICP updated successfully."
                else:
                    response = "I couldn't identify the new ICP text to update."

            elif action == "GET_LEADS":
                limit = params.get("limit", 20)
                pool_leads = await self.search_leads(params, limit=limit)

                if not pool_leads:
                    response = "No matching leads found."
                else:
                    response = f"Found and saved {len(pool_leads)} leads to your workspace:\n\n"
                    for pool_lead in pool_leads:
                        new_lead = Lead(
                            team_id=team.id,
                            name=pool_lead.full_name or f"{pool_lead.first_name or ''} {pool_lead.last_name or ''}".strip() or "Unknown",
                            email=pool_lead.email or "no-email@provided.com",
                            status=LeadStatus.NEW.value,
                            company_name=pool_lead.company_name,
                            job_title=pool_lead.title,
                            source="AI Search Pool",
                            score=0,
                            ai_context_data={
                                "industry": pool_lead.industry,
                                "seniority": pool_lead.seniority,
                                "country": pool_lead.country,
                                "city": pool_lead.city,
                                "raw_pool_data": pool_lead.raw_data
                            }
                        )
                        self.db.add(new_lead)
                        response += f"- {new_lead.name} | {new_lead.job_title} | {new_lead.company_name} | {new_lead.email}\n"

            # =====================================================
            # ACTION SUBROUTINE: ANALYZE_LEAD
            # =====================================================
            elif action == "ANALYZE_LEAD":
                # Search directly in current team leads by name keywords
                name_keywords = params.get("keywords", [])
                current_leads = await self.search_current_leads_by_name(team.id, name_keywords, limit=1)
                
                if not current_leads:
                    target_name = name_keywords[0] if name_keywords else "the requested prospect"
                    response = f"Could not find any lead named '{target_name}' in your current workspace pipeline to analyze."
                else:
                    existing_lead = current_leads[0]
                    
                    # Package existing lead metrics for comparison call
                    profile_payload = {
                        "name": existing_lead.name,
                        "title": existing_lead.job_title,
                        "company": existing_lead.company_name,
                        "email": existing_lead.email,
                        "raw_data": existing_lead.ai_context_data.get("raw_pool_data", {})
                    }
                    
                    # Generate metrics via LLM
                    analysis = await self._generate_fit_score(profile_payload, icp)
                    fit_score = analysis.get("score", 0)
                    justification = analysis.get("justification", "No evaluation details provided.")
                    
                    # Update the existing permanent Lead record directly
                    existing_lead.status = LeadStatus.ANALYZED.value
                    existing_lead.score = fit_score
                    
                    # Update JSONB context tracking without wiping out prior fields
                    updated_context = dict(existing_lead.ai_context_data) if existing_lead.ai_context_data else {}
                    updated_context["evaluation_justification"] = justification
                    existing_lead.ai_context_data = updated_context
                    
                    # Flag instance dirty for explicit session tracking update
                    self.db.add(existing_lead)
                    
                    response = (
                        f"### Analysis Complete for {existing_lead.name}\n"
                        f"**Status Updated To:** {LeadStatus.ANALYZED.value}\n"
                        f"**ICP Fit Score:** `{fit_score}/100`\n\n"
                        f"**Justification:**\n{justification}\n\n"
                        f"*Lead records successfully qualified and updated in your workspace.*"
                    )

            elif action == "DRAFT_EMAIL":
                from app.services.emails_service import EmailService
                
                name_keywords = params.get("keywords", [])
                current_leads = await self.search_current_leads_by_name(team.id, name_keywords, limit=1)
                
                if not current_leads:
                    target_name = name_keywords[0] if name_keywords else "the requested prospect"
                    response = f"Could not find any lead named '{target_name}' in your current workspace pipeline to draft an email for."
                else:
                    existing_lead = current_leads[0]
                    
                    # Package lead context for the LLM copywriter
                    profile_payload = {
                        "name": existing_lead.name,
                        "title": existing_lead.job_title,
                        "company": existing_lead.company_name,
                        "email": existing_lead.email,
                        "raw_data": existing_lead.ai_context_data.get("raw_pool_data", {})
                    }
                    
                    # 1. Generate customized email text
                    email_content = await self._generate_custom_email(profile_payload, icp)
                    subject = email_content.get("subject", "Quick Question")
                    body = email_content.get("body", "")
                    
                    # 2. Store the draft using your existing EmailService
                    email_service = EmailService(self.db)
                    drafted_record = await email_service.draft_email(
                        user_id=user_id,
                        lead_id=existing_lead.id,
                        subject=subject,
                        body=body
                    )
                    
                    response = (
                        f"### 📝 Draft Created for {existing_lead.name}\n"
                        f"I have successfully generated a personalized outreach template and saved it as a draft in your pipeline system.\n\n"
                        f"**Subject:** {subject}\n"
                        f"--- \n"
                        f"{body}\n"
                    )

            else:
                response = "I can help you search for prospects, analyze individuals, or modify your ICP. What would you like to do?"

            self.db.add(
                ChatMessage(
                    team_id=team.id,
                    user_id=user_id,
                    sent_by=ChatRole.AI.value,
                    content=response,
                    metadata_log={"model": self.MODEL},
                )
            )

            await self.db.commit()
            return response

        except Exception as e:
            print("\n========== CHAT ERROR ==========")
            print(repr(e))
            traceback.print_exc()
            print("================================")
            raise