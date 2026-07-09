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
    MODEL = "llama-3.3-70b-versatile"

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
        

    async def _compile_proposal_data(self, user_prompt: str, icp_context: str) -> tuple[str, dict]:
        """
        Processes a raw generation prompt and constructs a beautifully written,
        structured business proposal JSON context object.
        """
        system_prompt = f"""You are an elite enterprise B2B sales strategist. 
        Take the user's prompt request and draft a highly persuasive, detailed business proposal.
        Assume the current context year is 2026.

        Our Company Context / Profile:
        \"\"\"
        {icp_context}
        \"\"\"

        Return ONLY a valid JSON object matching this exact schema layout structure:
        {{
            "document_title": "A short clean file-safe title (e.g., SalesSync_Acme_Growth_Proposal)",
            "executive_summary": "Deep, highly persuasive 1-2 paragraph executive hook highlighting key business drivers.",
            "problem_statement": "A technical breakdown of client operational pain points and functional bottlenecks.",
            "proposed_solution": "A detailed step-by-step resolution strategy highlighting technical architecture and deliverables.",
            "investment_and_pricing": "Clear commercial pricing packages, implementation tier estimates, or milestone billing timelines."
        }}
        """
        
        payload = {
            "model": self.MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.5,
            "max_tokens": 2000,
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
            parsed_proposal = json.loads(cleaned)
            title = parsed_proposal.pop("document_title", "Business_Proposal")
            return title, parsed_proposal

    # =====================================================
    # NEW: DOCX DOCUMENT BUILDER FROM SCRATCH
    # =====================================================
    def create_proposal_document(self, proposal_title: str, proposal_data: dict) -> io.BytesIO:
        """Generates a professional corporate Word file using code structures from LLM blocks."""
        doc = Document()

        # Set 1-inch uniform page borders
        for section in doc.sections:
            section.top_margin = Inches(1)
            section.bottom_margin = Inches(1)
            section.left_margin = Inches(1)
            section.right_margin = Inches(1)

        # Baseline Font Definitions
        style_normal = doc.styles['Normal']
        style_normal.font.name = 'Arial'
        style_normal.font.size = Pt(11)
        style_normal.font.color.rgb = RGBColor(0x33, 0x33, 0x33)

        # Document Header Layout Block
        title_p = doc.add_paragraph()
        title_run = title_p.add_run(proposal_title.replace("_", " ").upper())
        title_run.font.size = Pt(24)
        title_run.font.bold = True
        title_run.font.color.rgb = RGBColor(0x1B, 0x36, 0x5D) # Deep Navy
        
        meta_p = doc.add_paragraph()
        meta_run = meta_p.add_run("Strategic Growth Proposal\nGenerated Systematically by Sales AI Engine")
        meta_run.font.size = Pt(10)
        meta_run.font.italic = True
        meta_run.font.color.rgb = RGBColor(0x77, 0x77, 0x77)
        
        doc.add_paragraph().add_run("_" * 60).font.color.rgb = RGBColor(0xD3, 0xD3, 0xD3)
        doc.add_paragraph() 

        # Content Generation Mapping Loop
        sections_map = {
            "executive_summary": "1. Executive Summary",
            "problem_statement": "2. Problem Statement & Operational Context",
            "proposed_solution": "3. Strategic Roadmap & Proposed Implementation",
            "investment_and_pricing": "4. Commercial Terms & Financial Scope"
        }

        for key, section_heading in sections_map.items():
            text_block = proposal_data.get(key, "Section contents skipped.")
            
            heading_p = doc.add_paragraph()
            heading_run = heading_p.add_run(section_heading)
            heading_run.font.size = Pt(14)
            heading_run.font.bold = True
            heading_run.font.color.rgb = RGBColor(0x1B, 0x36, 0x5D)
            heading_p.paragraph_format.space_before = Pt(16)
            heading_p.paragraph_format.space_after = Pt(6)
            
            body_p = doc.add_paragraph()
            body_p.add_run(text_block)
            body_p.paragraph_format.space_after = Pt(12)
            body_p.paragraph_format.line_spacing = 1.15

        out_stream = io.BytesIO()
        doc.save(out_stream)
        out_stream.seek(0)
        return out_stream

    # =====================================================
    # ENHANCED AI PROMPT WITH ANALYZE ACTION ADDED
    # =====================================================
    async def extract_action(self, message: str, icp: str) -> dict:
        prompt = f"""You are a B2B sales AI routing assistant. Your job is to classify the user's intent and extract matching parameters.
                Assume the current year context is 2026.

                Current Company ICP:
                \"\"\"
                {icp}
                \"\"\"

                You must respond ONLY with a valid JSON object matching this schema:
                {{
                    "action": "UPDATE_ICP" | "GET_LEADS" | "ANALYZE_LEAD" | "DRAFT_EMAIL" | "CREATE_MEETING" | "CANCEL_MEETING" | "GENERATE_PROPOSAL" | "NORMAL",
                    "parameters": {{
                        "new_icp": "string (only used for UPDATE_ICP)",
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
                3. ANALYZE_LEAD: When the user explicitly names a specific person or company to analyze or qualify.
                4. DRAFT_EMAIL: When the user asks to write, draft, generate, or compose an email to a specific person.
                5. CREATE_MEETING: When the user wants to book, schedule, set up, or arrange a meeting/call with a specific prospect. Extract the target person's name into 'keywords' and parse the requested timestamp into 'start_time' as an ISO format string.
                6. CANCEL_MEETING: When the user wants to cancel, remove, or drop a scheduled meeting with a specific person. Extract the person's name into 'keywords'.
                7. NORMAL: For general questions or conversational small talk.
                8. GENERATE_PROPOSAL: When the user asks to write, generate, create, compile, or build a business proposal document for a specific client target or context company name.

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
