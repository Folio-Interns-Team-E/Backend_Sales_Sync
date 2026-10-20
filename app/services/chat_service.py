import logging
import re
import traceback
from uuid import UUID
from datetime import datetime, timezone
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import uuid
from app.models.team import Team
from app.models.chat import Chat, ChatMessage, ChatRole
from app.models.proposal import Proposal, ProposalTemplate
from sqlalchemy import desc
from app.models.lead import Lead, LeadStatus
from app.models.meeting import Meeting, MeetingStatus
from app.models.email import Email
from app.services.chat_agents import ChatAgentsService
from app.ai.meeting_agent import MeetingAgent
from app.ai.proposal_evaluator import ProposalEvaluatorAgent
from app.ai.lead_analyzer import LeadAnalyzerAgent
from sqlalchemy.exc import IntegrityError
import asyncio
from app.ai.supervisor_agent import SupervisorAgent
from app.config import settings
from app.models.user import User
from app.ai.icp_agent import ICPAgent
from app.ai.email_agent import EmailAgent
from app.services.knowledge_base_rag_service import KnowledgeBaseRAGService
from app.services.plan_service import enforce_limit



logger = logging.getLogger(__name__)


class EmailQualityError(Exception):
    """Safe, user-facing failure raised when an AI draft misses quality gates."""


class LeadClarificationError(Exception):
    """Safe failure used when an action could target the wrong prospect."""


class ChatService(ChatAgentsService):

    DEFAULT_CHAT_NAMES = {"new chat", "untitled chat"}

    ICP_QUESTIONS = (
        "I can refine that into an ICP. Please tell me: (1) target countries or cities, "
        "(2) restaurant type and size, (3) buyer roles, (4) their problems, and "
        "(5) what you sell. I won't change your active ICP until you approve a draft."
    )

    @staticmethod
    def _icp_confirmation(message: str) -> bool:
        return message.strip().lower() in {"yes, save it", "save it", "approve and save", "confirm and save"}

    @staticmethod
    def _action_confirmation(message: str) -> bool:
        return message.strip().lower() in {"confirm", "yes, confirm", "proceed", "yes, proceed"}

    @staticmethod
    def _action_cancellation(message: str) -> bool:
        return message.strip().lower() in {"cancel", "no", "stop", "do not proceed", "don't proceed"}

    @staticmethod
    def _resolve_lead_candidate(candidates: list, keywords: list, message: str):
        """Resolve one lead deterministically, never by arbitrary database order."""
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]

        normalize = lambda value: re.sub(r"\s+", " ", str(value or "").strip().casefold())
        requested = {normalize(value) for value in keywords if normalize(value)}
        combined_request = normalize(" ".join(str(value) for value in keywords))
        if combined_request:
            requested.add(combined_request)
        exact = [lead for lead in candidates if normalize(lead.name) in requested]
        if len(exact) == 1:
            return exact[0]
        if exact:
            candidates = exact

        normalized_message = normalize(message)
        scored = []
        for lead in candidates:
            discriminators = (lead.name, lead.email, lead.company_name, lead.job_title)
            score = sum(
                1
                for value in discriminators
                if normalize(value) and normalize(value) in normalized_message
            )
            scored.append((score, lead))
        best_score = max(score for score, _lead in scored)
        winners = [lead for score, lead in scored if score == best_score and score > 0]
        return winners[0] if len(winners) == 1 else None

    @staticmethod
    def _lead_clarification_message(candidates: list, action_label: str) -> str:
        options = []
        for lead in candidates[:5]:
            details = " · ".join(
                value for value in (lead.company_name, lead.job_title, lead.email) if value
            )
            options.append(f"- {lead.name}" + (f" — {details}" if details else ""))
        return (
            f"I found multiple matching prospects and won't guess which one to {action_label}. "
            "Please repeat the request with the full name and company or email:\n\n"
            + "\n".join(options)
        )

    @staticmethod
    def derive_chat_name(message: str, max_words: int = 8, max_length: int = 60) -> str:
        """Create a stable, useful title without adding another AI call."""
        cleaned = re.sub(r"https?://\S+", "", message)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" \t\r\n.,!?;:-")
        if not cleaned:
            return "New Chat"

        words = cleaned.split()
        title = " ".join(words[:max_words])
        if len(title) > max_length:
            title = title[:max_length].rsplit(" ", 1)[0] or title[:max_length]
        if len(words) > max_words or len(cleaned) > len(title):
            title = title.rstrip(".,!?;:-") + "…"
        return title[0].upper() + title[1:]

    async def _get_team(self, team_id: UUID):
        result = await self.db.execute(select(Team).where(Team.id == team_id))
        team = result.scalar_one_or_none()
        if not team:
            raise ValueError("Team not found")
        return team

    async def _get_chat(self, chat_id: UUID, team_id: UUID):
        result = await self.db.execute(
            select(Chat).where(Chat.id == chat_id, Chat.team_id == team_id)
        )
        chat = result.scalar_one_or_none()
        if not chat:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat not found")
        return chat

    async def update_icp(self, team_id: UUID, new_icp: str):
        team = await self._get_team(team_id)
        team.icp = new_icp
        await self.db.commit()
        return team.icp

    async def _get_icp_context(self, team_id: UUID):
        team = await self._get_team(team_id)
        return team.icp if team.icp else "No ICP available"

    async def _build_lead_sales_context(self, team_id: UUID, lead_id: UUID) -> dict:
        """Return a small tenant-scoped timeline for grounded AI writing."""
        email_result = await self.db.execute(
            select(Email)
            .join(Lead, Email.lead_id == Lead.id)
            .where(Email.lead_id == lead_id, Lead.team_id == team_id)
            .order_by(desc(Email.sent_at))
            .limit(5)
        )
        meeting_result = await self.db.execute(
            select(Meeting)
            .join(Lead, Meeting.lead_id == Lead.id)
            .where(Meeting.lead_id == lead_id, Lead.team_id == team_id)
            .order_by(desc(Meeting.date), desc(Meeting.time))
            .limit(5)
        )
        proposal_result = await self.db.execute(
            select(Proposal)
            .where(Proposal.lead_id == lead_id, Proposal.team_id == team_id)
            .order_by(desc(Proposal.created_at))
            .limit(5)
        )

        emails = email_result.scalars().all()
        meetings = meeting_result.scalars().all()
        proposals = proposal_result.scalars().all()
        return {
            "recent_outreach": [
                {
                    "status": getattr(email.status, "value", str(email.status)),
                    "subject": email.subject[:200],
                    "body": email.body[:800],
                    "sent_at": email.sent_at.isoformat() if email.sent_at else None,
                }
                for email in emails
            ],
            "meetings": [
                {
                    "date": meeting.date.isoformat(),
                    "time": meeting.time.isoformat(),
                    "timezone": meeting.timezone,
                    "status": meeting.status,
                    "agenda": (meeting.agenda or "")[:500],
                    "notes": (meeting.notes or "")[:500],
                }
                for meeting in meetings
            ],
            "proposals": [
                {
                    "status": proposal.status,
                    "outcome": proposal.outcome,
                    "title": str((proposal.ai_metadata or {}).get("document_title") or "Proposal")[:200],
                    "created_at": proposal.created_at.isoformat() if proposal.created_at else None,
                }
                for proposal in proposals
            ],
        }

    # =====================================================
    # CHAT CRUD
    # =====================================================
    async def list_chats(self, team_id: UUID):
        result = await self.db.execute(
            select(Chat)
            .where(Chat.team_id == team_id)
            .order_by(desc(Chat.created_at))
        )
        chats = result.scalars().all()

        # Backfill legacy conversations that predate automatic titles. Empty
        # conversations correctly remain named "New Chat".
        untitled = [
            chat for chat in chats
            if (chat.chat_name or "").strip().casefold() in self.DEFAULT_CHAT_NAMES
        ]
        if untitled:
            message_result = await self.db.execute(
                select(ChatMessage.chat_id, ChatMessage.content)
                .where(
                    ChatMessage.chat_id.in_([chat.id for chat in untitled]),
                    ChatMessage.team_id == team_id,
                    ChatMessage.sent_by == ChatRole.USER.value,
                )
                .order_by(ChatMessage.created_at.asc())
            )
            first_messages = {}
            for message_chat_id, content in message_result.all():
                first_messages.setdefault(message_chat_id, content)

            changed = False
            for chat in untitled:
                first_message = first_messages.get(chat.id)
                if first_message:
                    chat.chat_name = self.derive_chat_name(first_message)
                    changed = True
            if changed:
                await self.db.commit()

        return chats

    async def create_chat(self, team_id: UUID, chat_name: str = "New Chat"):
        await self._get_team(team_id)
        chat = Chat(team_id=team_id, chat_name=chat_name)
        self.db.add(chat)
        await self.db.commit()
        await self.db.refresh(chat)
        return chat

    async def rename_chat(self, chat_id: UUID, team_id: UUID, chat_name: str):
        chat = await self._get_chat(chat_id, team_id)
        chat.chat_name = chat_name
        await self.db.commit()
        await self.db.refresh(chat)
        return chat

    async def delete_chat(self, chat_id: UUID, team_id: UUID):
        chat = await self._get_chat(chat_id, team_id)
        await self.db.delete(chat)
        await self.db.commit()

    # =====================================================
    # MESSAGE OPERATIONS
    # =====================================================
    async def list_messages(self, chat_id: UUID, team_id: UUID):
        await self._get_chat(chat_id, team_id)
        result = await self.db.execute(
            select(ChatMessage, User.full_name)
            .join(User, ChatMessage.user_id == User.id)
            .where(ChatMessage.chat_id == chat_id, ChatMessage.team_id == team_id)
            .order_by(desc(ChatMessage.created_at))
        )
        rows = result.all()
        data = []
        for msg, user_name in rows:
            data.append({
                "id": str(msg.id),
                "chat_id": str(msg.chat_id),
                "team_id": str(msg.team_id),
                "user_id": str(msg.user_id),
                "user_name": user_name,
                "sent_by": msg.sent_by,
                "content": msg.content,
                "metadata_log": msg.metadata_log or {},
                "created_at": msg.created_at.isoformat() if msg.created_at else None,
            })
        return data

    async def get_message(self, message_id: UUID, team_id: UUID):
        result = await self.db.execute(
            select(ChatMessage).where(
                ChatMessage.id == message_id,
                ChatMessage.team_id == team_id,
            )
        )
        message = result.scalar_one_or_none()
        if not message:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")
        return message

    async def update_message(self, message_id: UUID, team_id: UUID, content: str):
        message = await self.get_message(message_id, team_id)
        if message.sent_by != ChatRole.USER.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only user messages can be edited"
            )
        message.content = content
        message.metadata_log = {**(message.metadata_log or {}), "edited": True}
        await self.db.commit()
        await self.db.refresh(message)
        return message

    async def delete_message(self, message_id: UUID, team_id: UUID):
        message = await self.get_message(message_id, team_id)
        await self.db.delete(message)
        await self.db.commit()

    async def rate_message(
        self,
        message_id: UUID,
        team_id: UUID,
        user_id: UUID,
        rating: str,
        reason: str | None = None,
    ) -> str:
        if rating not in {"up", "down"}:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Rating must be up or down",
            )
        valid_reasons = {"incorrect", "incomplete", "irrelevant", "action_failed"}
        if rating == "down" and reason not in valid_reasons:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="A valid reason is required for negative feedback",
            )
        message = await self.get_message(message_id, team_id)
        if message.sent_by != ChatRole.AI.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only assistant messages can be rated",
            )

        metadata = dict(message.metadata_log or {})
        feedback_by_user = dict(metadata.get("feedback_by_user") or {})
        feedback_by_user[str(user_id)] = {
            "rating": rating,
            "reason": reason if rating == "down" else None,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        metadata["feedback_by_user"] = feedback_by_user
        message.metadata_log = metadata
        await self.db.commit()
        await self.db.refresh(message)
        return rating

    # =====================================================
    # MAIN CHAT ROUTER
    # =====================================================
    async def send_message(self, user_id: UUID, team_id: UUID, chat_id: UUID, message: str):
        try:
            team = await self._get_team(team_id)
            team_uuid = team.id
            chat = await self._get_chat(chat_id, team_id)
            chat_uuid = chat.id
            icp = team.icp if team.icp else "No ICP available"

            supervisor = SupervisorAgent(self.db)

            # 1. Fetch User Info
            user_res = await self.db.execute(select(User).where(User.id == user_id))
            user_obj = user_res.scalar_one_or_none()
            user_info = {
                "full_name": user_obj.full_name if user_obj else "Unknown",
                "email": user_obj.email if user_obj else "Unknown",
                "company": getattr(user_obj, "company", None) or "Not specified",
                "job_title": getattr(user_obj, "job_title", None) or "Not specified",
            }

            # 2. Fetch the Last 5 Chat Messages for Context (Prior to storing new incoming)
            history_res = await self.db.execute(
                select(ChatMessage)
                .where(ChatMessage.chat_id == chat_uuid)
                .order_by(desc(ChatMessage.created_at))
                .limit(5)
            )
            db_history = history_res.scalars().all()
            last_assistant = db_history[0] if db_history and db_history[0].sent_by == ChatRole.AI.value else None
            icp_flow = (last_assistant.metadata_log or {}).get("icp_flow") if last_assistant else None
            pending_action = (last_assistant.metadata_log or {}).get("pending_action") if last_assistant else None
            if not isinstance(pending_action, dict):
                pending_action = None

            messages_history = [
                {
                    "sent_by": msg.sent_by,
                    "content": msg.content,
                    "timestamp": msg.created_at.isoformat() if msg.created_at else None
                }
                for msg in reversed(db_history)
            ]

            # 3. Save the Incoming User Message
            new_chat_msg = ChatMessage(
                chat_id=chat_uuid,
                team_id=team.id,
                user_id=user_id,
                sent_by=ChatRole.USER.value,
                content=message,
                metadata_log={},
            )
            self.db.add(new_chat_msg)
            if (getattr(chat, "chat_name", "New Chat") or "").strip().casefold() in self.DEFAULT_CHAT_NAMES:
                chat.chat_name = self.derive_chat_name(message)
            await self.db.commit()

            # 4. AI processing — wrapped so a fallback message is always saved
            response_metadata = {}
            action = "NORMAL"
            try:
                ai_response = (
                    {"action": "ICP_FOLLOWUP", "parameters": {}}
                    if icp_flow
                    else {"action": "CONFIRM_PENDING", "parameters": {}}
                    if pending_action
                    else await supervisor.extract_action(message, icp)
                )
                action = ai_response.get("action", "NORMAL")
                params = ai_response.get("parameters", {})

                print("==================AI ACTION==================")
                print(ai_response)
                print("==================AI ACTION==================")

                if action == "CONFIRM_PENDING":
                    if self._action_cancellation(message):
                        response = "Okay, I cancelled that action. Nothing was changed."
                    elif not self._action_confirmation(message):
                        response = "Please reply **confirm** to perform the pending action or **cancel** to stop it."
                        response_metadata = {"pending_action": pending_action}
                    elif pending_action.get("type") == "meeting":
                        meeting_agent = MeetingAgent(db_session=self.db)
                        response = await meeting_agent.execute_prepared(
                            pending_action,
                            team.id,
                            user_id,
                        )
                        if meeting_agent.action_result:
                            response_metadata = {"action_result": meeting_agent.action_result}
                    else:
                        response = "That pending action is no longer supported. Please start the request again."

                elif action == "UPDATE_ICP":
                    response = self.ICP_QUESTIONS
                    response_metadata = {"icp_flow": {"phase": "details", "request": message[:2000]}}

                elif action == "ICP_FOLLOWUP":
                    phase = icp_flow.get("phase")
                    if message.strip().lower() in {"cancel", "stop", "never mind"}:
                        response = "Okay, I won't change your ICP."
                    elif phase == "details":
                        details = (icp_flow.get("details", "") + "\n" + message).strip()
                        if len(details) < 25:
                            response = "I need a little more detail before drafting. " + self.ICP_QUESTIONS
                            response_metadata = {"icp_flow": icp_flow}
                        else:
                            try:
                                draft = await ICPAgent().refine_icp(
                                    f"Original request: {icp_flow.get('request', '')}\n"
                                    f"User's targeting details: {details[:6000]}"
                                )
                                if not draft.startswith("Firmographics:") or len(draft) < 150:
                                    raise ValueError("ICP draft did not match the required format")
                            except Exception:
                                logger.exception("Unable to draft ICP")
                                response = "I couldn't prepare a reliable ICP draft right now, so I haven't changed your active ICP. Please try again in a moment."
                            else:
                                response = (
                                    "Here's a proposed ICP based on your details:\n\n"
                                    f"{draft}\n\n"
                                    "Review it carefully. Reply **yes, save it** to activate it, "
                                    "or tell me what to revise. Nothing has been saved yet."
                                )
                                response_metadata = {"icp_flow": {"phase": "confirm", "request": icp_flow.get("request", ""), "details": details[:6000], "draft": draft[:12000]}}
                    elif phase == "confirm" and self._icp_confirmation(message):
                        await self.update_icp(team_id, icp_flow["draft"])
                        response = "Your approved ICP is now active. You can review it on the dashboard."
                    elif phase == "confirm":
                        response = "Please give me the changes you'd like, and I'll prepare a revised draft for approval."
                        response_metadata = {"icp_flow": {"phase": "details", "request": icp_flow.get("request", ""), "details": icp_flow.get("details", "")}}
                    else:
                        response = self.ICP_QUESTIONS
                        response_metadata = {"icp_flow": {"phase": "details", "request": message[:2000]}}

                elif action == "GET_LEADS":
                    limit = params.get("limit", 20)
                    pool_leads = await self.search_leads(params, limit=limit)

                    if not pool_leads:
                        response = "No matching leads found."
                    else:
                        response = f"Found and saved {len(pool_leads)} leads to your workspace:\n\n"
                        for pool_lead in pool_leads:
                            name = pool_lead.full_name or f"{pool_lead.first_name or ''} {pool_lead.last_name or ''}".strip() or "Unknown"
                            email = pool_lead.email or "no-email@provided.com"
                            team_id_val = team.id

                            email_filter = (Lead.email == email) & (Lead.team_id == team_id_val) if email != "no-email@provided.com" else False
                            name_filter = (Lead.name == name) & (Lead.team_id == team_id_val)

                            stmt = select(Lead).where(name_filter | email_filter)
                            result = await self.db.execute(stmt)
                            exists = result.scalar_one_or_none()

                            if exists:
                                continue

                            new_lead = Lead(
                                team_id=team_id_val,
                                name=name,
                                email=email,
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

                elif action == "ANALYZE_LEAD":

                    name_keywords = params.get("keywords", [])
                    limit = min(params.get("limit", 10), 10)

                    current_leads = await self.search_current_leads_by_name(team.id, name_keywords, limit=limit)

                    if not current_leads:
                        target_name = name_keywords[0] if name_keywords else "the requested prospects"
                        response = f"Could not find any leads matching '{target_name}' in your current workspace pipeline to analyze."

                    else:
                        analyzer_agent = LeadAnalyzerAgent(
                            model=self.MODEL,
                            base_url=self.BASE_URL,
                            api_key=settings.grok_api_key
                        )

                        semaphore = asyncio.Semaphore(2)

                        async def analyze_lead_task(lead) -> dict:
                            async with semaphore:
                                raw_context = lead.ai_context_data if lead.ai_context_data else {}
                                profile_payload = {
                                    "name": lead.name,
                                    "title": lead.job_title,
                                    "company": lead.company_name,
                                    "email": lead.email,
                                    "raw_data": raw_context.get("raw_pool_data", {})
                                }

                                try:
                                    analysis = await analyzer_agent.analyze_fit(profile_payload, icp)
                                    return {
                                        "lead_id": lead.id,
                                        "success": True,
                                        "score": analysis.get("score", 0),
                                        "justification": analysis.get("justification", "No evaluation details provided.")
                                    }
                                except Exception as e:
                                    logger.error(f"Error analyzing lead {lead.name}: {str(e)}")
                                    return {
                                        "lead_id": lead.id,
                                        "success": False,
                                        "error": str(e)
                                    }

                        tasks = [analyze_lead_task(lead) for lead in current_leads]
                        analysis_results = await asyncio.gather(*tasks)

                        results_by_id = {res["lead_id"]: res for res in analysis_results}

                        summary_lines = []
                        summary_lines.append(f"Successfully processed {len(current_leads)} leads using parallel workers.\n")

                        try:
                            for idx, lead in enumerate(current_leads, start=1):
                                res = results_by_id.get(lead.id)

                                if res and res["success"]:
                                    lead.status = LeadStatus.ANALYZED.value
                                    lead.score = res["score"]

                                    raw_context = lead.ai_context_data if lead.ai_context_data else {}
                                    updated_context = dict(raw_context)
                                    updated_context["evaluation_justification"] = res["justification"]
                                    lead.ai_context_data = updated_context

                                    self.db.add(lead)

                                    summary_lines.append(
                                        f"{idx}. {lead.name}\n"
                                        f"Status: `{LeadStatus.ANALYZED.value}`\n"
                                        f"ICP Fit Score: `{res['score']}/100`\n"
                                        f"Justification: {res['justification']}\n"
                                    )
                                else:
                                    error_msg = res["error"] if res else "Unknown analysis failure."
                                    summary_lines.append(
                                        f"{idx}. {lead.name}\n"
                                        f"Status: `FAILED`\n"
                                        f"Error: {error_msg}\n"
                                    )

                            await self.db.commit()

                        except Exception as db_err:
                            await self.db.rollback()
                            logger.error(f"Database update failed, rolling back: {str(db_err)}")
                            summary_lines = [f"An error occurred while saving analysis details to the database: `{str(db_err)}`"]

                        summary_lines.append("\n*Lead records successfully qualified and updated in your workspace.*")
                        response = "\n".join(summary_lines)

                elif action == "DRAFT_EMAIL":
                    from app.services.emails_service import EmailService

                    name_keywords = params.get("keywords", [])
                    current_leads = await self.search_current_leads_by_name(team.id, name_keywords, limit=10)

                    if not current_leads:
                        target_name = name_keywords[0] if name_keywords else "the requested prospect"
                        response = f"Could not find any lead named '{target_name}' in your current workspace pipeline to draft an email for."
                    else:
                        existing_lead = self._resolve_lead_candidate(
                            current_leads,
                            name_keywords,
                            message,
                        )
                        if not existing_lead:
                            raise LeadClarificationError(
                                self._lead_clarification_message(current_leads, "draft an email for")
                            )

                        profile_payload = {
                            "name": existing_lead.name,
                            "title": existing_lead.job_title,
                            "company": existing_lead.company_name,
                            "email": existing_lead.email,
                            "raw_data": (existing_lead.ai_context_data or {}).get("raw_pool_data", {}),
                            "sales_context": await self._build_lead_sales_context(
                                team.id,
                                existing_lead.id,
                            ),
                        }

                        email_agent = EmailAgent()

                        email_content = await email_agent.generate_custom_email(profile_payload, icp, message)

                        evaluation = await email_agent.evaluate_email(email_content, profile_payload, icp, message)

                        if not evaluation.get("approved", True):
                            email_content = await email_agent.generate_custom_email(
                                profile_payload,
                                icp,
                                message,
                                revision_feedback=evaluation.get("feedback", "")
                            )

                        remaining_problems = email_agent.validate_email(email_content)
                        if remaining_problems:
                            raise EmailQualityError(
                                "I couldn't produce a draft that passed the outreach quality checks, "
                                "so nothing was saved. Please add more prospect context and try again."
                            )

                        subject = email_content.get("subject", "Quick Question")
                        body = email_content.get("body", "")

                        email_service = EmailService(self.db)
                        drafted_record = await email_service.draft_email(
                            team_id=team_id,
                            lead_id=existing_lead.id,
                            subject=subject,
                            body=body
                        )

                        # Let clients open the exact draft created by the assistant. Without
                        # this metadata Email Studio can only refresh whichever lead happened
                        # to be selected before the chat action.
                        response_metadata = {
                            "draft_email": {
                                "email_id": str(drafted_record.id),
                                "lead_id": str(existing_lead.id),
                            }
                        }

                        response = (
                            f"Draft Created for {existing_lead.name}\n"
                            f"I have successfully generated a personalized outreach template and saved it as a draft in your pipeline system.\n\n"
                        )

                elif action == "MEETING_OPERATION":
                    meeting_agent = MeetingAgent(db_session=self.db)
                    prepared_action, response = await meeting_agent.prepare(message, team.id)
                    if prepared_action:
                        response_metadata = {"pending_action": prepared_action}



                elif action == "GENERATE_PROPOSAL":
                    from app.core.s3 import upload_to_s3
                    from app.models.proposal import Proposal, ProposalStatus, ProposalOutcome
                    from app.ai.proposal_agent import ProposalAgent
                    from sqlalchemy.exc import DBAPIError, IntegrityError

                    await enforce_limit(self.db, team.id, "proposals_monthly")

                    name_keywords = params.get("keywords", [])
                    lead_id = None
                    if name_keywords:
                        current_leads = await self.search_current_leads_by_name(
                            team.id, name_keywords, limit=10
                        )
                        if current_leads:
                            matched_lead = self._resolve_lead_candidate(
                                current_leads,
                                name_keywords,
                                message,
                            )
                            if not matched_lead:
                                raise LeadClarificationError(
                                    self._lead_clarification_message(current_leads, "generate a proposal for")
                                )
                            lead_id = matched_lead.id

                    template_query = (
                        select(ProposalTemplate)
                        .where(ProposalTemplate.team_id == team.id)
                        .order_by(ProposalTemplate.created_at.desc())
                        .limit(1)
                    )
                    template_res = await self.db.execute(template_query)
                    team_template = template_res.scalar_one_or_none()
                    template_id = team_template.id if team_template else None

                    if template_id:
                        logger.info(f"Using found team template ID: {template_id}")
                    else:
                        logger.info("No custom team template found. Falling back to default layout.")


                    proposal_agent = ProposalAgent(self.db)
                    filename, file_bytes_stream, raw_proposal_json, _styles = await proposal_agent.run(
                        user_prompt=message,
                        team_id=team.id,
                        lead_id=lead_id,
                        template_id=template_id
                    )

                    file_bytes = file_bytes_stream.getvalue()
                    file_url = await upload_to_s3(
                        file_bytes=file_bytes,
                        filename=filename,
                        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        prefix="proposals",
                        user_id=str(user_id),
                    )

                    logger.info("Initializing proposal single-pass evaluation...")
                    evaluator = ProposalEvaluatorAgent(self.db)
                    evaluation_report = await evaluator.evaluate_proposal(
                        original_prompt=message,
                        generated_proposal_data=raw_proposal_json,
                        icp_context=team.icp if team.icp else "Standard Enterprise B2B SaaS and Professional Solutions."
                    )

                    print("===================Proposal===================\n\n")
                    print(raw_proposal_json)
                    print("======================================\n\n")

                    print(f"--- Creating Proposal ---")
                    print(f"Lead ID:     {lead_id}")
                    print(f"File URL:    {file_url}")
                    print(f"File Type:   docx")
                    print(f"File Size:   {len(file_bytes)} bytes")
                    print(f"AI Metadata: {raw_proposal_json}")
                    print(f"Version:     1")
                    print(f"Status:      {ProposalStatus.DRAFT.value}")
                    print(f"Outcome:     {ProposalOutcome.OPEN.value}")
                    print(f"-------------------------")


                    proposal = Proposal(
                        id=uuid.uuid4(),
                        team_id=team_id,
                        lead_id=lead_id,
                        file_url=file_url,
                        template_id=template_id,
                        file_type="docx",
                        file_size=len(file_bytes),
                        ai_metadata=raw_proposal_json,
                        version=1,
                        status=ProposalStatus.DRAFT.value,
                        outcome=ProposalOutcome.OPEN.value,
                    )

                    try:
                        if not self.db.is_active:
                            await self.db.rollback()

                        self.db.add(proposal)
                        await self.db.commit()
                        await self.db.refresh(proposal)

                        logger.info("--- DATABASE COMMIT & REFRESH SUCCESSFUL ---")

                    except Exception as db_err:
                        logger.error("=" * 80)
                        logger.error("DATABASE INSERTION FAILED!\n")
                        logger.error(f"Error Type: {type(db_err)}\n\n")
                        logger.error(f"Detailed Error: {str(db_err)}\n\n")
                        if hasattr(db_err, "orig"):
                            logger.error(f"Underlying Driver Error: {db_err.orig}")
                        logger.error("=" * 80)
                        await self.db.rollback()
                        raise db_err

                    logger.info(f"Proposal successfully flushed and saved to S3: {file_url}")

                    badge = "Passed" if evaluation_report.get("passed") else "Warning (Needs Manual Polish)"
                    proposal_title = filename.replace(".docx", "").replace("_", " ")
                    response = (
                        f"Your proposal, {proposal_title}, has been generated and saved as a draft. "
                        "You can review and download it from the Proposals tab. "
                        f"Quality check: {badge} ({evaluation_report.get('overall_score')}/10)."
                    )
                    response_metadata = {
                        "action_result": {
                            "type": "proposal_created",
                            "proposal_id": str(proposal.id),
                        }
                    }
                else:
                    rag_service = KnowledgeBaseRAGService(self.db)
                    kb_answer = await rag_service.answer_query(team.id, message)

                    if kb_answer.get("sources"):
                        response = kb_answer["answer"]
                        response_metadata = {
                            "knowledge_sources": [
                                {
                                    "asset_id": str(source["asset_id"]),
                                    "title": source["asset_title"],
                                    "chunk_index": source["chunk_index"],
                                    "score": round(float(source["score"]), 4),
                                }
                                for source in kb_answer["sources"][:5]
                            ]
                        }
                    else:
                        response = "I can help you search for prospects, analyze individuals, modify your ICP, or answer questions from your knowledge base. What would you like to do?"


                if action in {"UPDATE_ICP", "ICP_FOLLOWUP", "CONFIRM_PENDING", "MEETING_OPERATION", "GENERATE_PROPOSAL"}:
                    final_response = response
                else:
                    final_response = await supervisor.run(
                        user_prompt=message,
                        execution_result=response,
                        team_id=team.id,
                        messages_history=messages_history,
                        user_info=user_info
                    )

            except Exception as ai_err:
                logger.error(f"AI processing failed: {repr(ai_err)}")
                traceback.print_exc()
                try:
                    await self.db.rollback()
                except Exception:
                    pass
                if isinstance(ai_err, LeadClarificationError):
                    final_response = str(ai_err)
                elif isinstance(ai_err, EmailQualityError):
                    final_response = str(ai_err)
                    response_metadata = {
                        "assistant_error": {
                            "code": "draft_quality_failed",
                            "retryable": True,
                        }
                    }
                elif action == "GENERATE_PROPOSAL" and isinstance(ai_err, RuntimeError):
                    final_response = (
                        "I couldn't generate the proposal because a required service failed: "
                        f"{ai_err}. Please try again shortly."
                    )
                    response_metadata = {
                        "assistant_error": {
                            "code": "proposal_service_failed",
                            "retryable": True,
                        }
                    }
                else:
                    final_response = (
                        "I encountered an error while processing your request. "
                        "Please try again or rephrase your question."
                    )
                    response_metadata = {
                        "assistant_error": {
                            "code": "assistant_processing_failed",
                            "retryable": True,
                        }
                    }

            ai_msg = ChatMessage(
                chat_id=chat_uuid,
                team_id=team_uuid,
                user_id=user_id,
                sent_by=ChatRole.AI.value,
                content=final_response,
                metadata_log=response_metadata,
            )
            self.db.add(ai_msg)
            await self.db.commit()
            await self.db.refresh(ai_msg)

            return final_response

        except Exception as e:
            print("\n========== CHAT ERROR ==========")
            print(repr(e))
            traceback.print_exc()
            print("================================")
            raise
