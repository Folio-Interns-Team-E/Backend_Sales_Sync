import logging
import traceback
from uuid import UUID
from datetime import datetime
import asyncio

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

# CrewAI imports
from crewai import Agent, Task, Crew, Process
from crewai.tools import tool

# Models & Schemas
from app.models.team import Team
from app.models.team_member import TeamMember
from app.models.chat import ChatMessage, ChatRole
from app.models.lead import Lead, LeadStatus
from app.models.meeting import Meeting, MeetingStatus
from app.schemas.chat import ChatMessageResponse

# Core services
from app.services.chat_agents import ChatAgentsService
from app.services.calcom_service import CalComService
from app.services.emails_service import EmailService
from app.core.cache import cache_get, cache_set, cache_delete
from app.core.s3 import upload_to_s3
from app.models.proposal import Proposal, ProposalStatus, ProposalOutcome

logger = logging.getLogger(__name__)


class ChatService(ChatAgentsService):
    MODEL = "llama-3.3-70b-versatile"

    def __init__(self, db: AsyncSession):
        super().__init__(db)
        self.db = db

    # =====================================================
    # HELPERS & BASE DB OPERATIONS
    # =====================================================
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

    async def list_messages(self, user_id: UUID):
        team = await self._get_user_team(user_id)
        cache_key = f"chat_messages:{team.id}:list"
        cached = cache_get(cache_key)
        if cached is not None:
            return cached

        result = await self.db.execute(
            select(ChatMessage)
            .where(ChatMessage.team_id == team.id)
            .order_by(desc(ChatMessage.created_at))
        )
        messages = result.scalars().all()
        data = [ChatMessageResponse.model_validate(m).model_dump(mode="json") for m in messages]
        cache_set(cache_key, data, ttl=60)
        return data

    async def get_message(self, message_id: UUID, user_id: UUID):
        team = await self._get_user_team(user_id)
        result = await self.db.execute(
            select(ChatMessage).where(
                ChatMessage.id == message_id,
                ChatMessage.team_id == team.id,
            )
        )
        message = result.scalar_one_or_none()
        if not message:
            raise Exception("Message not found")
        return message

    async def update_message(self, message_id: UUID, user_id: UUID, content: str):
        message = await self.get_message(message_id, user_id)
        if message.sent_by != ChatRole.USER.value:
            raise Exception("Only user messages can be edited")
        message.content = content
        message.metadata_log = {**(message.metadata_log or {}), "edited": True}
        await self.db.commit()
        await self.db.refresh(message)
        team = await self._get_user_team(user_id)
        cache_delete(f"chat_messages:{team.id}:list")
        return message

    async def delete_message(self, message_id: UUID, user_id: UUID):
        message = await self.get_message(message_id, user_id)
        team = await self._get_user_team(user_id)
        await self.db.delete(message)
        await self.db.commit()
        cache_delete(f"chat_messages:{team.id}:list")

    # =====================================================
    # MAIN AGENTIC SEND_MESSAGE ROUTE
    # =====================================================
    async def send_message(self, user_id: UUID, message: str):
        try:
            team = await self._get_user_team(user_id)
            icp = await self._get_icp_context(user_id)

            # 1. Save the incoming user message
            self.db.add(
                ChatMessage(
                    team_id=team.id,
                    user_id=user_id,
                    sent_by=ChatRole.USER.value,
                    content=message,
                    metadata_log={},
                )
            )
            await self.db.flush()

            # 2. Define CrewAI Tools capturing DB and Service scopes
            @tool("Update ICP Tool")
            def update_icp_tool(new_icp: str) -> str:
                """Updates the Ideal Customer Profile (ICP) for the team's workspace."""
                async def run():
                    await self.update_icp(user_id, new_icp)
                    return "ICP updated successfully."
                return asyncio.run(run())

            @tool("Search Prospects Tool")
            def search_prospects_tool(query: str, limit: int = 5) -> str:
                """Searches the global B2B leads pool and imports matching candidates into the workspace."""
                async def run():
                    # Constructs standard parameters matching your search signatures
                    params = {"query": query}
                    pool_leads = await self.search_leads(params, limit=limit)
                    if not pool_leads:
                        return "No matching leads found."
                    
                    response_text = f"Found and saved {len(pool_leads)} leads to your workspace:\n"
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
                        response_text += f"- {new_lead.name} | {new_lead.job_title} | {new_lead.company_name} | {new_lead.email}\n"
                    await self.db.flush()
                    return response_text
                return asyncio.run(run())

            @tool("Analyze Pipeline Lead Tool")
            def analyze_lead_tool(name_keyword: str) -> str:
                """Evaluates an existing pipeline lead's profile fit score against the current active ICP."""
                async def run():
                    current_leads = await self.search_current_leads_by_name(team.id, [name_keyword], limit=1)
                    if not current_leads:
                        return f"Could not find any lead named '{name_keyword}' in your active workspace pipeline."
                    
                    existing_lead = current_leads[0]
                    profile_payload = {
                        "name": existing_lead.name,
                        "title": existing_lead.job_title,
                        "company": existing_lead.company_name,
                        "email": existing_lead.email,
                        "raw_data": existing_lead.ai_context_data.get("raw_pool_data", {})
                    }
                    
                    analysis = await self._generate_fit_score(profile_payload, icp)
                    fit_score = analysis.get("score", 0)
                    justification = analysis.get("justification", "No evaluation details provided.")
                    
                    existing_lead.status = LeadStatus.ANALYZED.value
                    existing_lead.score = fit_score
                    
                    updated_context = dict(existing_lead.ai_context_data) if existing_lead.ai_context_data else {}
                    updated_context["evaluation_justification"] = justification
                    existing_lead.ai_context_data = updated_context
                    
                    self.db.add(existing_lead)
                    await self.db.flush()
                    
                    return (
                        f"### Analysis Complete for {existing_lead.name}\n"
                        f"**Status Updated To:** {LeadStatus.ANALYZED.value}\n"
                        f"**ICP Fit Score:** `{fit_score}/100`\n\n"
                        f"**Justification:**\n{justification}"
                    )
                return asyncio.run(run())

            @tool("Draft Outreach Email Tool")
            def draft_email_tool(name_keyword: str) -> str:
                """Generates a hyper-personalized sales outreach email and automatically saves it as a local workspace draft."""
                async def run():
                    current_leads = await self.search_current_leads_by_name(team.id, [name_keyword], limit=1)
                    if not current_leads:
                        return f"Could not find any lead named '{name_keyword}' in your pipeline to draft an email for."
                    
                    existing_lead = current_leads[0]
                    profile_payload = {
                        "name": existing_lead.name,
                        "title": existing_lead.job_title,
                        "company": existing_lead.company_name,
                        "email": existing_lead.email,
                        "raw_data": existing_lead.ai_context_data.get("raw_pool_data", {})
                    }
                    
                    email_content = await self._generate_custom_email(profile_payload, icp)
                    subject = email_content.get("subject", "Quick Question")
                    body = email_content.get("body", "")
                    
                    email_service = EmailService(self.db)
                    await email_service.draft_email(
                        user_id=user_id,
                        lead_id=existing_lead.id,
                        subject=subject,
                        body=body
                    )
                    
                    return (
                        f"### 📝 Draft Created for {existing_lead.name}\n"
                        f"Saved as draft template in your pipeline tracking dashboard.\n\n"
                        f"**Subject:** {subject}\n"
                        f"**Body:**\n{body}"
                    )
                return asyncio.run(run())

            @tool("Schedule Cal.com Meeting Tool")
            def schedule_meeting_tool(name_keyword: str, iso_start_time: str) -> str:
                """Schedules a video appointment with a specific lead via Cal.com."""
                async def run():
                    current_leads = await self.search_current_leads_by_name(team.id, [name_keyword], limit=1)
                    if not current_leads:
                        return f"Could not find any lead named '{name_keyword}' to book an appointment with."
                    
                    existing_lead = current_leads[0]
                    try:
                        start_time_dt = datetime.fromisoformat(iso_start_time)
                    except ValueError:
                        return "Failed to parse scheduled time format. Please provide dates in clean ISO format (YYYY-MM-DDTHH:MM:SS)."

                    cal_service = CalComService(self.db)
                    booking_info = await cal_service.create_booking(
                        lead_id=existing_lead.id,
                        start_time=start_time_dt,
                        name=existing_lead.name,
                        email=existing_lead.email,
                        agenda=[f"Automated Routing Session with {existing_lead.company_name}"]
                    )
                    
                    return (
                        f"### 📅 Meeting Scheduled!\n"
                        f"**Attendee:** {existing_lead.name}\n"
                        f"**Time:** {start_time_dt.strftime('%Y-%m-%d %I:%M %p')} (Asia/Karachi)\n"
                        f"**Cal Booking UID:** `{booking_info['cal_booking_uid']}`"
                    )
                return asyncio.run(run())

            @tool("Cancel Active Meeting Tool")
            def cancel_meeting_tool(name_keyword: str) -> str:
                """Cancels an upcoming active appointment associated with a lead on Cal.com."""
                async def run():
                    current_leads = await self.search_current_leads_by_name(team.id, [name_keyword], limit=1)
                    if not current_leads:
                        return f"Could not locate a pipeline lead matching '{name_keyword}'."
                    
                    existing_lead = current_leads[0]
                    meeting_res = await self.db.execute(
                        select(Meeting).where(
                            Meeting.lead_id == existing_lead.id,
                            Meeting.status == MeetingStatus.SCHEDULED.value
                        ).limit(1)
                    )
                    active_meeting = meeting_res.scalar_one_or_none()
                    if not active_meeting:
                        return f"No scheduled appointments found for {existing_lead.name}."
                    
                    cal_service = CalComService(self.db)
                    await cal_service.cancel_booking(
                        booking_uid=active_meeting.calendar_event_id,
                        meeting_id=active_meeting.id
                    )
                    return f"### ❌ Meeting Canceled\nSuccessfully canceled booking `{active_meeting.calendar_event_id}` for {existing_lead.name}."
                return asyncio.run(run())

            @tool("Generate Executive Proposal Tool")
            def generate_proposal_tool(name_keyword: str) -> str:
                """Generates a full-scope .docx business proposal, uploads it to S3, and links it in the database."""
                async def run():
                    lead_id = None
                    current_leads = await self.search_current_leads_by_name(team.id, [name_keyword], limit=1)
                    if current_leads:
                        lead_id = current_leads[0].id

                    title, raw_proposal_json = await self._compile_proposal_data(message, icp)
                    file_bytes_stream = self.create_proposal_document(title, raw_proposal_json)
                    
                    safe_title = title.replace(" ", "_").replace("/", "_")
                    file_name = f"{safe_title}.docx"
                    file_bytes = file_bytes_stream.getvalue()
                    
                    file_url = await upload_to_s3(
                        file_bytes=file_bytes,
                        filename=file_name,
                        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        prefix="proposals",
                        user_id=str(user_id),
                    )

                    proposal = Proposal(
                        lead_id=lead_id,
                        file_url=file_url,
                        file_type="docx",
                        file_size=len(file_bytes),
                        ai_metadata=raw_proposal_json,
                        version=1,
                        status=ProposalStatus.DRAFT.value,
                        outcome=ProposalOutcome.OPEN.value,
                    )
                    self.db.add(proposal)
                    await self.db.flush()

                    exec_summary = raw_proposal_json.get("executive_summary", "")
                    problem_stmt = raw_proposal_json.get("problem_statement", "")
                    solution = raw_proposal_json.get("proposed_solution", "")
                    pricing = raw_proposal_json.get("investment_and_pricing", "")

                    return (
                        f"### 📄 Generated Proposal: {title.replace('_', ' ')}\n"
                        f"📎 **Document Link:** {file_url}\n\n"
                        f"**1. Executive Summary:**\n{exec_summary}\n\n"
                        f"**2. Problem Statement:**\n{problem_stmt}\n\n"
                        f"**3. Strategic Solution:**\n{solution}\n\n"
                        f"**4. Commercial Pricing:**\n{pricing}"
                    )
                return asyncio.run(run())

            # =====================================================
            # CREWAI AGENT & TASK DEFINITIONS
            # =====================================================
            sales_assistant_agent = Agent(
                role="Workspace Sales Operations Director",
                goal="Act as an interface between the user and their local B2B sales development workspace pipeline.",
                backstory=(
                    "You are an elite workspace assistant. You manage prospects, update ideal customer profiles (ICPs), "
                    "score leads, coordinate calendar events via Cal.com tools, draft highly personalized email "
                    "outreach, and assemble corporate documents such as proposals. "
                    "You choose the perfect tool to complete user instructions directly."
                ),
                tools=[
                    update_icp_tool,
                    search_prospects_tool,
                    analyze_lead_tool,
                    draft_email_tool,
                    schedule_meeting_tool,
                    cancel_meeting_tool,
                    generate_proposal_tool,
                ],
                verbose=True,
                llm=self.llm,  # Uses the instance-level LLM configured via Groq/LiteLLM
            )

            orchestration_task = Task(
                description=(
                    f"Process the following user instruction: '{message}'\n\n"
                    f"**Current Workspace ICP:** {icp}\n"
                    f"**Current Timestamp Context:** {datetime.now().isoformat()}\n\n"
                    "Select the correct tool matching the user's intent to fulfill the task. "
                    "If the query is conversational or asks questions outside your direct tool suite, "
                    "rely on your knowledge to formulate a friendly, precise guidance response."
                ),
                expected_output="A beautiful, Markdown-formatted summary of the action you took or a detailed response answering the user's request.",
                agent=sales_assistant_agent,
            )

            # Assemble and run the Crew
            crew = Crew(
                agents=[sales_assistant_agent],
                tasks=[orchestration_task],
                process=Process.sequential,
            )

            # Kickoff the Crew execution loop
            crew_result = crew.kickoff()
            
            # CrewAI returns a CrewOutput instance, grab the raw string representation
            response = str(crew_result)

            # 3. Save the Assistant's response to the database
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
            cache_delete(f"chat_messages:{team.id}:list")
            return response

        except Exception as e:
            print("\n========== CHAT SERVICE ERROR ==========")
            print(repr(e))
            traceback.print_exc()
            print("========================================")
            await self.db.rollback()
            raise