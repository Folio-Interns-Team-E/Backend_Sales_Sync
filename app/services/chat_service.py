import asyncio
from uuid import UUID
from typing import Dict, Any, Literal
from pydantic import BaseModel, Field
import traceback

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_groq import ChatGroq
from langgraph.graph import StateGraph, END

from app.config import settings
from app.models.chat import ChatMessage, ChatRole
from app.models.team import Team
from app.models.team_member import TeamMember

# ==========================================
# 1. DEFINE THE GRAPH STATE
# ==========================================
class AgentState(BaseModel):
    user_id: UUID
    user_message: str
    current_icp: str
    next_step: str = ""
    final_response: str = ""


# ==========================================
# 2. CHAT SERVICE WITH LANGGRAPH INTEGRATION
# ==========================================
class ChatService:
    def __init__(self, db: AsyncSession):
        self.db = db
        # Instantiating the LangChain Groq model directly
        self.llm = ChatGroq(
            model="llama-3.3-70b-versatile",
            api_key=settings.grok_api_key,
            temperature=0.0
        )
        self.workflow = self._build_workflow()

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

    async def _get_icp_context(self, user_id: UUID) -> str:
        team = await self._get_user_team(user_id)
        return team.icp if team.icp else "No ICP available"
    
    async def update_icp(self, user_id: UUID, new_icp: str) -> str:
        team = await self._get_user_team(user_id)
        team.icp = new_icp
        await self.db.commit()
        return team.icp

    # ==========================================
    # 3. GRAPH NODE ACTIONS (NO CONVERSATIONAL FILLER)
    # ==========================================
    
    async def router_node(self, state: AgentState) -> Dict[str, Any]:
        """Classifies intent dynamically without hardcoding."""
        prompt = (
            f"Analyze this user message: '{state.user_message}'\n\n"
            f"If the user wants to update, change, modify, or add targets to their ICP, reply with 'UPDATE_ICP'.\n"
            f"If it is a general question, greeting, or casual chat, reply with 'CHAT'.\n"
            f"Reply with EXACTLY one of those two terms."
        )
        response = await self.llm.ainvoke([HumanMessage(content=prompt)])
        decision = response.content.strip().upper()
        
        # Fallback safeguard
        if "UPDATE" in decision:
            return {"next_step": "update_icp"}
        return {"next_step": "casual_chat"}

    async def update_icp_node(self, state: AgentState) -> Dict[str, Any]:
        """
        Merges the user's edits with the current ICP, executes the DB write,
        and directly outputs the confirmation string.
        """
        merge_prompt = (
            f"You are a database compiler. Update the current ICP by integrating the user's modifications.\n\n"
            f"Current ICP Context:\n{state.current_icp}\n\n"
            f"User Modification Request:\n{state.user_message}\n\n"
            f"Generate the complete, updated ICP profile text. Do not include introductory notes, "
            f"do not ask questions, and do not provide conversational pleasantries. Output ONLY the updated ICP text."
        )
        
        # Generate the merged ICP text
        llm_response = await self.llm.ainvoke([HumanMessage(content=merge_prompt)])
        new_icp_text = llm_response.content.strip()

        # Direct, guaranteed DB write (no agent choice required!)
        updated_icp = await self.update_icp(state.user_id, new_icp_text)
        
        return {
            "final_response": f"Successfully updated the ICP in the database to:\n{updated_icp}"
        }

    async def casual_chat_node(self, state: AgentState) -> Dict[str, Any]:
        """Handles greetings and general questions directly."""
        prompt = (
            f"You are a helpful B2B sales assistant. Respond directly and helpfully to the user's message: "
            f"'{state.user_message}'"
        )
        response = await self.llm.ainvoke([HumanMessage(content=prompt)])
        return {"final_response": response.content.strip()}

    # ==========================================
    # 4. GRAPH COMPOSITION & ASSEMBLY
    # ==========================================
    def _build_workflow(self):
        builder = StateGraph(AgentState)

        # Register our nodes
        builder.add_node("router", self.router_node)
        builder.add_node("update_icp", self.update_icp_node)
        builder.add_node("casual_chat", self.casual_chat_node)

        # Set entrypoint
        builder.set_entry_point("router")

        # Define conditional routing from router to execution nodes
        def routing_decision(state: AgentState) -> Literal["update_icp", "casual_chat"]:
            return state.next_step

        builder.add_conditional_edges(
            "router",
            routing_decision,
            {
                "update_icp": "update_icp",
                "casual_chat": "casual_chat"
            }
        )

        # Execution nodes terminate the graph execution
        builder.add_edge("update_icp", END)
        builder.add_edge("casual_chat", END)

        return builder.compile()

    # ==========================================
    # 5. ENTRYPOINT: EXECUTE MESSAGES
    # ==========================================
    async def send_message(self, user_id: UUID, message: str):
        try:
            team = await self._get_user_team(user_id)
            icp = await self._get_icp_context(user_id)

            # 1. Store incoming message
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

            # 2. Initialize and run LangGraph State Machine
            initial_state = AgentState(
                user_id=user_id,
                user_message=message,
                current_icp=icp
            )
            
            final_state_output = await self.workflow.ainvoke(initial_state)
            final_response = final_state_output["final_response"]

            # 3. Store outgoing response
            ai_message = ChatMessage(
                team_id=team.id,
                user_id=user_id,
                sent_by=ChatRole.AI.value,
                content=final_response,
                metadata_log={"run_type": "langgraph_state_execution"},
            )
            self.db.add(ai_message)
            await self.db.commit()

            return final_response

        except Exception as e:
            await self.db.rollback()
            print(f"Error in send_message: {e}")
            traceback.print_exc()
            raise e