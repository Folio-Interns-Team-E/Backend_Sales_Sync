import asyncio
from uuid import UUID
from typing import Dict, Any, Type
import traceback

from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from pydantic import BaseModel, Field

from crewai import Agent, Crew, Process, Task, LLM
from crewai.tools import tool, BaseTool

from app.database import get_db
from app.config import settings
from app.models.chat import ChatMessage, ChatRole
from app.models.team import Team
from app.models.team_member import TeamMember

# ==========================================
# 1. DEFINE TOOLS WITH DYNAMIC CONTEXT ACCESSIBILITY
# ==========================================

class ICPGetTool(BaseTool):
    name: str = "Retrieve Current Team ICP"
    description: str = "Retrieves the existing Ideal Customer Profile (ICP) for the active team from the database."

    user_id: Any 
    db_session: Any 
    main_loop: asyncio.AbstractEventLoop

    def _run(self) -> str:
        try:
            future = asyncio.run_coroutine_threadsafe(self._arun(), self.main_loop)
            return future.result()
        except Exception as e:
            return f"Error retrieving ICP: {str(e)}"

    async def _arun(self) -> str:
        team = await self.db_session._get_user_team(self.user_id)
        return team.icp if team.icp else "No ICP available"


class ICPUpdateSchema(BaseModel):
    new_icp: str = Field(
        ..., 
        description="The fully compiled, updated Ideal Customer Profile (ICP) text to overwrite the database record."
    )

class ICPUpdateTool(BaseTool):
    name: str = "Update Current Team ICP"
    description: str = (
        "Updates or overwrites the active team's Ideal Customer Profile (ICP) "
        "in the database with new details."
    )
    args_schema: Type[BaseModel] = ICPUpdateSchema

    user_id: Any
    chat_service: Any  
    main_loop: asyncio.AbstractEventLoop

    def _run(self, new_icp: str) -> str:
        try:
            future = asyncio.run_coroutine_threadsafe(self._arun(new_icp), self.main_loop)
            return future.result()
        except Exception as e:
            return f"Error updating ICP: {str(e)}"

    async def _arun(self, new_icp: str) -> str:
        updated_icp = await self.chat_service.update_icp(self.user_id, new_icp)
        return f"Successfully updated the ICP in the database to: {updated_icp}"


@tool("Lead Search Tool")
def lead_search_tool(icp_criteria: str) -> str:
    """Searches and compiles potential leads matching the ICP criteria."""
    return "Found Leads: 1. Acme Corp (Contact: John Doe, CEO), 2. BetaTech (Contact: Jane Smith, CTO)."

@tool("Draft Email Tool")
def draft_email_tool(recipient: str, context: str) -> str:
    """Drafts a personalized cold outreach email based on lead details."""
    return f"Subject: Optimizing operations at {recipient}\n\nHi {recipient},\n\nI noticed you are scaling. {context}\n\nBest,\n[Your Name]"

@tool("Calendar Booking Link Generator")
def meeting_scheduler_tool(lead_name: str) -> str:
    """Generates a personalized calendar booking link for the lead."""
    return f"Booking Link for {lead_name}: https://calendly.com/yourcompany/intro-meeting?lead={lead_name.replace(' ', '')}"

@tool("Generate Proposal Template")
def proposal_generator_tool(client_name: str, pain_points: str) -> str:
    """Generates a tailored service proposal outline based on identified pain points."""
    return f"--- PROPOSAL FOR {client_name.upper()} ---\nScope: Custom automation workflows resolving: {pain_points}.\nInvestment: $5,000/month."


# ==========================================
# 2. CHAT SERVICE IMPLEMENTATION
# ==========================================

class ChatService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.llm = LLM(
            model="groq/llama-3.3-70b-versatile",
            api_key=settings.grok_api_key,
            temperature=0.0
        )

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

    async def _get_icp_context(self, user_id: UUID):
        team = await self._get_user_team(user_id)
        return team.icp if team.icp else "No ICP available"
    
    async def update_icp(self, user_id: UUID, new_icp: str):
        team = await self._get_user_team(user_id)
        team.icp = new_icp
        await self.db.commit()
        return team.icp

    def _run_crew_sync(self, user_message: str, icp_context: str, user_id: UUID, main_loop: asyncio.AbstractEventLoop) -> str:
        # A. Define the specialized agents with strict backstories
        icp_db_tool = ICPGetTool(
            user_id=user_id, 
            db_session=self,
            main_loop=main_loop
        )

        icp_update_tool = ICPUpdateTool(
            user_id=user_id,
            chat_service=self,
            main_loop=main_loop
        )

        icp_agent = Agent(
            role="ICP Specialist",
            goal="Modify the Ideal Customer Profile (ICP) and write it to the database immediately.",
            backstory=(
                "You are an execution-focused system operations expert. "
                "When asked to add, delete, or modify titles or targets in the ICP, you MUST "
                "immediately merge those changes with the existing ICP, and run your "
                "'Update Current Team ICP' tool to save the result. "
                "CRITICAL: Do not write explanations, do not ask the user questions, "
                "and do not seek approval. Just run the tool and return the exact success message."
            ),
            tools=[icp_db_tool, icp_update_tool],
            llm=self.llm,
            allow_delegation=False,
            verbose=True
        )

        lead_agent = Agent(
            role="Lead Generation Expert",
            goal="Find high-quality leads that perfectly match the defined ICP.",
            backstory="You are an expert list-builder and prospector who uncovers hard-to-find contacts.",
            tools=[lead_search_tool],
            llm=self.llm,
            allow_delegation=False,
            verbose=True
        )

        email_agent = Agent(
            role="Cold Outreach Copywriter",
            goal="Draft highly engaging, personalized outreach campaigns.",
            backstory="You write high-converting copy that yields exceptional open and reply rates.",
            tools=[draft_email_tool],
            llm=self.llm,
            allow_delegation=False,
            verbose=True
        )

        meeting_agent = Agent(
            role="Meeting Coordinator",
            goal="Facilitate and schedule introductory discovery calls.",
            backstory="You manage calendar logistics and ensure leads have friction-free scheduling options.",
            tools=[meeting_scheduler_tool],
            llm=self.llm,
            allow_delegation=False,
            verbose=True
        )

        proposal_agent = Agent(
            role="Proposal Writer",
            goal="Create compelling, structured business proposals for qualified leads.",
            backstory="You synthesize client needs into flawless, highly persuasive commercial proposals.",
            tools=[proposal_generator_tool],
            llm=self.llm,
            allow_delegation=False,
            verbose=True
        )

        # B. Task with strict "No Talk, Just Execute" guardrails
        dynamic_coordination_task = Task(
            description=(
                f"User Request: '{user_message}'\n"
                f"Current ICP Context: '{icp_context}'\n\n"
                "CRITICAL OPERATIONAL RULES FOR THE SUPERVISOR:\n"
                "1. If the user is asking to change, add to, or modify their ICP, immediately "
                "delegate the update task to your coworker: 'ICP Specialist'.\n"
                "2. DO NOT engage in casual conversation, ask clarifying questions, or discuss options with the user.\n"
                "3. Your sole metric of success is delegating this task so the tool executes successfully, "
                "and returning the resulting database confirmation response to the user."
            ),
            expected_output="The database success confirmation text returned by the ICP Specialist.",
        )

        sales_crew = Crew(
            agents=[icp_agent, lead_agent, email_agent, meeting_agent, proposal_agent],
            tasks=[dynamic_coordination_task],
            process=Process.sequential,
            manager_llm=self.llm,
            verbose=True
        )

        return sales_crew.kickoff().raw


    async def send_message(self, user_id: UUID, message: str):
        try:
            team = await self._get_user_team(user_id)
            icp = await self._get_icp_context(user_id)

            # 1. Save and COMMIT the incoming user message immediately
            self.db.add(
                ChatMessage(
                    team_id=team.id,
                    user_id=user_id,
                    sent_by=ChatRole.USER.value,
                    content=message,
                    metadata_log={},
                )
            )
            await self.db.commit() 

            # 2. DYNAMIC ROUTER: Use a single LLM call to classify intent without hardcoding
            routing_prompt = (
                f"You are a routing assistant for a B2B sales operations crew.\n"
                f"Analyze this user message: '{message}'\n\n"
                f"Decide if this message requires executing a complex sales operations crew (such as updating/modifying the ICP, searching for leads, drafting outreach, or generating proposals), "
                f"or if it is just casual conversation (greetings, small talk, general questions).\n\n"
                f"Respond with EXACTLY one of these two options:\n"
                f"Option A: 'CREW'\n"
                f"Option B: [A helpful, direct response to the user's message]"
            )
            
            router_response = self.llm.call([{"role": "user", "content": routing_prompt}]).strip()

            if router_response != "CREW":
                final_response = router_response
            else:
                main_loop = asyncio.get_running_loop()
                final_response = await run_in_threadpool(
                    self._run_crew_sync, 
                    user_message=message, 
                    icp_context=icp,
                    user_id=user_id,
                    main_loop=main_loop
                )

            # 3. Save and COMMIT the final response
            ai_message = ChatMessage(
                team_id=team.id,
                user_id=user_id,
                sent_by=ChatRole.AI.value,
                content=final_response,
                metadata_log={"run_type": "dynamic_routed_execution"},
            )
            self.db.add(ai_message)
            await self.db.commit()

            return final_response

        except Exception as e:
            await self.db.rollback()
            print(f"Error in send_message: {e}")
            traceback.print_exc()
            raise e