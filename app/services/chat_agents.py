import io
import json
import logging
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel, Field

from crewai import Agent, Task, Crew, Process, LLM
from crewai.tools import tool


from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, String

from app.config import settings
from app.models.leads_pool import LeadPool
from app.models.lead import Lead

from docx import Document
from docx.shared import Inches, Pt, RGBColor

logger = logging.getLogger(__name__)

# =====================================================
# 1. STRUCTURED OUTPUT SCHEMAS (Replaces regex/JSON strings)
# =====================================================

class FitScoreResult(BaseModel):
    score: int = Field(description="Objective fit score between 0 and 100.")
    justification: str = Field(description="A clear, concise 2-sentence explanation of why they received this score.")

class CustomEmailResult(BaseModel):
    subject: str = Field(description="Compelling, short email subject line.")
    body: str = Field(description="The personalized body text of the email.")

class ProposalDataResult(BaseModel):
    document_title: str = Field(description="A short clean file-safe title (e.g., SalesSync_Acme_Growth_Proposal).")
    executive_summary: str = Field(description="Deep, highly persuasive 1-2 paragraph executive hook highlighting key business drivers.")
    problem_statement: str = Field(description="A technical breakdown of client operational pain points and functional bottlenecks.")
    proposed_solution: str = Field(description="A detailed step-by-step resolution strategy highlighting technical architecture and deliverables.")
    investment_and_pricing: str = Field(description="Clear commercial pricing packages, implementation tier estimates, or milestone billing timelines.")

class ActionExtractionResult(BaseModel):
    action: str = Field(description="Must be one of: UPDATE_ICP, GET_LEADS, ANALYZE_LEAD, DRAFT_EMAIL, CREATE_MEETING, CANCEL_MEETING, GENERATE_PROPOSAL, NORMAL")
    keywords: Optional[List[str]] = Field(default=[], description="List of titles/roles/queries/names parsed from user message.")
    industry: Optional[List[str]] = Field(default=[], description="List of industries parsed from user message.")
    country: Optional[List[str]] = Field(default=[], description="List of countries parsed from user message.")
    limit: int = Field(default=20, description="Limit of search results requested, max 50.")
    start_time: Optional[str] = Field(default=None, description="ISO 8601 timestamp (YYYY-MM-DDTHH:MM:SS) if scheduling a meeting.")


# =====================================================
# 2. THE CREWAI SERVICE CLASS
# =====================================================

class ChatAgentsService:
    MODEL = "llama-3.3-70b-versatile"
    def __init__(self, db: AsyncSession):
        self.db = db
        # Set up LLM utilizing Groq API credentials through LangChain's OpenAI adaptation
        self.llm = LLM(
            model="groq/llama-3.3-70b-versatile",
            api_key=settings.grok_api_key,
            temperature=0.0
        )

    # =====================================================
    # DATABASE UTILITIES (Decorated as CrewAI Tools)
    # =====================================================
    @tool("Search Prospects Tool")
    async def search_leads(self, filters: dict, limit: int = 20) -> list:
        """Search prospect pool using keywords, industries, and countries."""
        conditions = []
        keywords = filters.get("keywords", [])
        industries = filters.get("industry", [])
        countries = filters.get("country", [])

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
        return [
            {"id": str(lead.id), "title": lead.title, "company_name": lead.company_name, "industry": lead.industry, "country": lead.country}
            for lead in leads
        ]

    # =====================================================
    # AGENTIC WORKFLOWS
    # =====================================================

    async def generate_fit_score(self, lead_info: dict, icp: str) -> FitScoreResult:
        """Evaluates a lead profile against target ICP and produces an objective score."""
        analyst_agent = Agent(
            role="Sales Operations Analyst",
            goal="Analyze prospect compatibility objectively against our Ideal Customer Profile.",
            backstory="You are a data-driven sales ops expert who scores incoming opportunities based on strategic alignment.",
            verbose=False,
            allow_delegation=False,
            llm=self.llm
        )

        qualification_task = Task(
            description=(
                f"Evaluate the target lead data against the company's Ideal Customer Profile (ICP).\n\n"
                f"Company ICP:\n{icp}\n\n"
                f"Target Lead Data:\n{json.dumps(lead_info, indent=2)}\n\n"
                "Provide an objective analysis and score."
            ),
            expected_output="A structured objective analysis containing fit score and 2-sentence justification.",
            agent=analyst_agent,
            output_json=FitScoreResult
        )

        crew = Crew(
            agents=[analyst_agent],
            tasks=[qualification_task],
            process=Process.sequential
        )

        result = crew.kickoff()
        # Returns parsed Pydantic object
        return result.json_dict if hasattr(result, 'json_dict') else json.loads(result.raw)


    async def generate_custom_email(self, lead_info: dict, icp: str) -> CustomEmailResult:
        """Generates a highly personalized cold outbound email based on lead data."""
        sdr_agent = Agent(
            role="Elite B2B Sales Development Representative",
            goal="Draft high-converting personalized cold emails to prospects based on targeting criteria.",
            backstory="You write clear, short, personalized outreach emails with strong hooks that never sound templated.",
            verbose=False,
            allow_delegation=False,
            llm=self.llm
        )

        email_task = Task(
            description=(
                f"Write a tailored B2B outreach email to the target lead below based on company ICP context.\n\n"
                f"Company ICP Context:\n{icp}\n\n"
                f"Target Lead Data:\n{json.dumps(lead_info, indent=2)}\n\n"
                "Guidelines:\n"
                "1. Keep it professional, relevant, and short (under 150 words).\n"
                "2. Directly hook their specific role, company, or background details.\n"
                "3. Do not use generic placeholders."
            ),
            expected_output="A structured cold outreach subject line and body text.",
            agent=sdr_agent,
            output_json=CustomEmailResult
        )

        crew = Crew(agents=[sdr_agent], tasks=[email_task])
        result = crew.kickoff()
        return result.json_dict if hasattr(result, 'json_dict') else json.loads(result.raw)


    async def compile_proposal_data(self, user_prompt: str, icp_context: str) -> tuple[str, dict]:
        """Drafts a beautifully written, structured business proposal context object."""
        strategist_agent = Agent(
            role="Enterprise B2B Sales Strategist",
            goal="Formulate high-value corporate growth and sales proposals.",
            backstory="You are an expert sales executive specializing in deep technical problem-solving and corporate structuring. The current year is 2026.",
            verbose=False,
            allow_delegation=False,
            llm=self.llm
        )

        proposal_task = Task(
            description=(
                f"Take the user's prompt request and draft a highly persuasive, detailed business proposal.\n"
                f"User request: '{user_prompt}'\n\n"
                f"Our Company Profile context:\n{icp_context}"
            ),
            expected_output="An executive-level structured business proposal structure containing strategy and commercial targets.",
            agent=strategist_agent,
            output_json=ProposalDataResult
        )

        crew = Crew(agents=[strategist_agent], tasks=[proposal_task])
        result = crew.kickoff()
        
        parsed_data = result.json_dict if hasattr(result, 'json_dict') else json.loads(result.raw)
        title = parsed_data.pop("document_title", "Business_Proposal")
        return title, parsed_data


    async def extract_action(self, message: str, icp: str) -> ActionExtractionResult:
        """Classifies client intent and parses necessary routing parameters from natural language."""
        routing_agent = Agent(
            role="B2B Sales Operations Router",
            goal="Analyze inbound messages, classify specific user actions, and extract operational parameters.",
            backstory="You are an efficient digital coordinator. Your absolute goal is mapping client intent to explicit parameters. The current year is 2026.",
            verbose=False,
            allow_delegation=False,
            llm=self.llm
        )

        routing_task = Task(
            description=(
                f"Extract routing action and parameters from this user message:\n"
                f"'{message}'\n\n"
                f"Current Company ICP Context:\n{icp}\n\n"
                "Intent Guidelines:\n"
                "- UPDATE_ICP: Explicit intent to change / modify corporate targeting profile.\n"
                "- GET_LEADS: Broad search/lookup requests.\n"
                "- ANALYZE_LEAD: Deep dive/qualification on a specific person or brand.\n"
                "- DRAFT_EMAIL: Composing cold outbound strategies.\n"
                "- CREATE_MEETING: Booking/scheduling. Extract target person to 'keywords' and parse ISO timestamp details to 'start_time'.\n"
                "- CANCEL_MEETING: Dropping/deleting slots.\n"
                "- GENERATE_PROPOSAL: Compiling business proposals for targets."
            ),
            expected_output="A structured routing schema containing action parameters.",
            agent=routing_agent,
            output_json=ActionExtractionResult
        )

        crew = Crew(agents=[routing_agent], tasks=[routing_task])
        result = crew.kickoff()
        return result.json_dict if hasattr(result, 'json_dict') else json.loads(result.raw)

    # =====================================================
    # STANDARD UTILITY METHODS (Unchanged database/IO operations)
    # =====================================================
    def create_proposal_document(self, proposal_title: str, proposal_data: dict) -> io.BytesIO:
        """Generates a professional corporate Word file using document builder structures."""
        doc = Document()
        for section in doc.sections:
            section.top_margin = Inches(1)
            section.bottom_margin = Inches(1)
            section.left_margin = Inches(1)
            section.right_margin = Inches(1)

        style_normal = doc.styles['Normal']
        style_normal.font.name = 'Arial'
        style_normal.font.size = Pt(11)
        style_normal.font.color.rgb = RGBColor(0x33, 0x33, 0x33)

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