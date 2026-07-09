import logging
import traceback
from uuid import UUID
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.team import Team
from app.models.team_member import TeamMember
from app.models.chat import ChatMessage, ChatRole
from sqlalchemy import desc
from app.models.lead import Lead, LeadStatus
from app.models.meeting import Meeting, MeetingStatus
from app.services.chat_agents import ChatAgentsService
from app.services.calcom_service import CalComService
from app.core.cache import cache_get, cache_set, cache_delete


logger = logging.getLogger(__name__)


class ChatService(ChatAgentsService):

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
        from app.schemas.chat import ChatMessageResponse
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
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")
        return message

    async def update_message(self, message_id: UUID, user_id: UUID, content: str):
        message = await self.get_message(message_id, user_id)
        if message.sent_by != ChatRole.USER.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only user messages can be edited"
            )
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

            print("==================AI ACTION==================")
            print(ai_response)
            print("==================AI ACTION==================")

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

            elif action == "CREATE_MEETING":
                name_keywords = params.get("keywords", [])
                start_time_str = params.get("start_time")
                
                current_leads = await self.search_current_leads_by_name(team.id, name_keywords, limit=1)
                
                if not current_leads:
                    target_name = name_keywords[0] if name_keywords else "the requested prospect"
                    response = f"Could not find any lead named '{target_name}' in your workspace to schedule a meeting with."
                elif not start_time_str:
                    response = "I recognized you wanted to book a meeting, but I couldn't isolate a clean time or date context. Could you please specify a time?"
                else:
                    existing_lead = current_leads[0]
                    start_time_dt = datetime.fromisoformat(start_time_str)
                    
                    cal_service = CalComService(self.db)
                    booking_info = await cal_service.create_booking(
                        lead_id=existing_lead.id,
                        start_time=start_time_dt,
                        name=existing_lead.name,
                        email=existing_lead.email,
                        agenda=[f"AI Agent Automated Demo Routing with {existing_lead.company_name}"]
                    )
                    
                    response = (
                        f"### 📅 Meeting Scheduled Successfully!\n"
                        f"**Attendee:** {existing_lead.name} ({existing_lead.email})\n"
                        f"**Time:** {start_time_dt.strftime('%Y-%m-%d %I:%M %p')} (Asia/Karachi)\n"
                        f"**Cal.com Booking UID:** `{booking_info['cal_booking_uid']}`\n\n"
                        f"*The event has been securely updated in Cal.com and synced locally to your pipeline tracker.*"
                    )

            # =====================================================
            # ACTION SUBROUTINE: CANCEL_MEETING
            # =====================================================
            elif action == "CANCEL_MEETING":
                name_keywords = params.get("keywords", [])
                current_leads = await self.search_current_leads_by_name(team.id, name_keywords, limit=1)
                
                if not current_leads:
                    target_name = name_keywords[0] if name_keywords else "the requested prospect"
                    response = f"Could not find any lead named '{target_name}' in your current pipeline records."
                else:
                    existing_lead = current_leads[0]
                    
                    # Fetch active scheduled local meeting records for this lead
                    meeting_query = (
                        select(Meeting)
                        .where(
                            Meeting.lead_id == existing_lead.id,
                            Meeting.status == MeetingStatus.SCHEDULED.value
                        )
                        .limit(1)
                    )
                    meeting_res = await self.db.execute(meeting_query)
                    active_meeting = meeting_res.scalar_one_or_none()
                    
                    if not active_meeting:
                        response = f"No active scheduled appointments found in your workspace tracking database for {existing_lead.name}."
                    else:
                        cal_service = CalComService(self.db)
                        await cal_service.cancel_booking(
                            booking_uid=active_meeting.calendar_event_id,
                            meeting_id=active_meeting.id
                        )
                        
                        response = (
                            f"### ❌ Meeting Canceled Successfully\n"
                            f"The scheduled meeting record associated with **{existing_lead.name}** "
                            f"(Event UID: `{active_meeting.calendar_event_id}`) has been withdrawn from Cal.com "
                            f"and marked as `{MeetingStatus.CANCELLED.value}` locally."
                        )

            elif action == "GENERATE_PROPOSAL":
                from app.core.s3 import upload_to_s3
                from app.models.proposal import Proposal, ProposalStatus, ProposalOutcome

                name_keywords = params.get("keywords", [])
                lead_id = None
                if name_keywords:
                    current_leads = await self.search_current_leads_by_name(
                        team.id, name_keywords, limit=1
                    )
                    if current_leads:
                        lead_id = current_leads[0].id

                # 1. Compile textual layout payload maps via Groq
                title, raw_proposal_json = await self._compile_proposal_data(message, icp)

                # 2. Build the structural .docx stream layout block array in memory
                file_bytes_stream = self.create_proposal_document(title, raw_proposal_json)

                # 3. Upload the file to S3
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

                # 4. Save a Proposal record in the database
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

                logger.info(f"Proposal saved to S3: {file_url}")

                # 5. Extract sections to display preview text in the chat
                exec_summary = raw_proposal_json.get("executive_summary", "")
                problem_stmt = raw_proposal_json.get("problem_statement", "")
                solution = raw_proposal_json.get("proposed_solution", "")
                pricing = raw_proposal_json.get("investment_and_pricing", "")

                response = (
                    f"### 📄 Generated Proposal: {title.replace('_', ' ')}\n"
                    f"📎 **S3 URL:** [Open Document]({file_url})\n\n"
                    f"--- \n\n"
                    f"#### **1. Executive Summary**\n"
                    f"{exec_summary}\n\n"
                    f"#### **2. Problem Statement & Operational Context**\n"
                    f"{problem_stmt}\n\n"
                    f"#### **3. Strategic Roadmap & Proposed Solution**\n"
                    f"{solution}\n\n"
                    f"#### **4. Commercial Terms & Financial Scope**\n"
                    f"{pricing}\n\n"
                    f"--- \n"
                    f"*Proposal saved to S3 and recorded in your workspace.*"
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
            cache_delete(f"chat_messages:{team.id}:list")
            return response

        except Exception as e:
            print("\n========== CHAT ERROR ==========")
            print(repr(e))
            traceback.print_exc()
            print("================================")
            raise