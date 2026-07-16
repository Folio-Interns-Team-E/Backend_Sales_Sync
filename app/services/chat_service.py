import logging
import traceback
from uuid import UUID
from datetime import datetime
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import uuid
from app.models.team import Team
from app.models.team_member import TeamMember
from app.models.chat import ChatMessage, ChatRole
from app.models.proposal import Proposal, ProposalTemplate
from sqlalchemy import desc
from app.models.lead import Lead, LeadStatus
from app.models.meeting import Meeting, MeetingStatus
from app.services.chat_agents import ChatAgentsService
from app.services.calcom_service import CalComService
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

        result = await self.db.execute(
            select(ChatMessage)
            .where(ChatMessage.team_id == team.id)
            .order_by(desc(ChatMessage.created_at))
        )
        messages = result.scalars().all()
        from app.schemas.chat import ChatMessageResponse
        data = [ChatMessageResponse.model_validate(m).model_dump(mode="json") for m in messages]
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
        return message

    async def delete_message(self, message_id: UUID, user_id: UUID):
        message = await self.get_message(message_id, user_id)
        team = await self._get_user_team(user_id)
        await self.db.delete(message)
        await self.db.commit()

    # =====================================================
    # MAIN CHAT ROUTER
    # =====================================================
    async def send_message(self, user_id: UUID, message: str):
        try:
            team = await self._get_user_team(user_id)
            icp = await self._get_icp_context(user_id)

            supervisor = SupervisorAgent(self.db)

            # 1. Fetch User Info
            user_res = await self.db.execute(select(User).where(User.id == user_id))
            user_obj = user_res.scalar_one_or_none()
            user_info = {
                "full_name": user_obj.full_name if user_obj else "Unknown",
                "email": user_obj.email if user_obj else "Unknown"
            }

            # 2. Fetch the Last 5 Chat Messages for Context (Prior to storing new incoming)
            history_res = await self.db.execute(
                select(ChatMessage)
                .where(ChatMessage.team_id == team.id)
                .order_by(desc(ChatMessage.created_at))
                .limit(5)
            )
            db_history = history_res.scalars().all()
            
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
                team_id=team.id,
                user_id=user_id,
                sent_by=ChatRole.USER.value,
                content=message,
                metadata_log={},
            )
            self.db.add(new_chat_msg)
            await self.db.commit()

            # 4. Use the new router extracted into SupervisorAgent
            ai_response = await supervisor.extract_action(message, icp)
            action = ai_response.get("action", "NORMAL")
            params = ai_response.get("parameters", {})

            print("==================AI ACTION==================")
            print(ai_response)
            print("==================AI ACTION==================")

            if action == "UPDATE_ICP":
                
                    
                    # 1. Instantiate the new ICP Agent
                icp_agent = ICPAgent()
                    
                    # 2. Refine the raw user input into a professional GTM profile
                refined_icp = await icp_agent.refine_icp(message)
                    
                    # 3. Update the database record with the highly structured ICP
                await self.update_icp(user_id, refined_icp)

                print("===================NEW ICP===================\n\n")
                print(refined_icp)
                print("======================================\n\n")
                    
                response = (
                        "### Profile Refined & Updated Successfully\n\n"
                        f"{refined_icp}\n\n"
                        "*This target framework is now set as your active system ICP.*"
                    )
          
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
             
                # 1. Gather configuration and parameters
                name_keywords = params.get("keywords", [])
                limit = min(params.get("limit", 10), 10)  # Allow up to 10 leads concurrently
                
                # 2. Search for the requested leads
                current_leads = await self.search_current_leads_by_name(team.id, name_keywords, limit=limit)
                
                if not current_leads:
                    target_name = name_keywords[0] if name_keywords else "the requested prospects"
                    response = f"Could not find any leads matching '{target_name}' in your current workspace pipeline to analyze."
                
                else:
                    # Instantiate our isolated Agent
                    analyzer_agent = LeadAnalyzerAgent(
                        model=self.MODEL,
                        base_url=self.BASE_URL,
                        api_key=settings.grok_api_key
                    )
                    
                    # Concurrency Gate: Limit only the LLM API calls to 2 parallel worker agents
                    semaphore = asyncio.Semaphore(2)
                    
                    async def analyze_lead_task(lead) -> dict:
                        """
                        Runs only the external API call concurrently. 
                        Does NOT touch the DB session inside the parallel task.
                        """
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
                                # Execute the external LLM profiling agent
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

                    # Step 1: Fire off the parallel LLM API workers (Capped at 2)
                    tasks = [analyze_lead_task(lead) for lead in current_leads]
                    analysis_results = await asyncio.gather(*tasks)
                    
                    # Map analysis results by lead ID for fast lookup
                    results_by_id = {res["lead_id"]: res for res in analysis_results}
                    
                    # Step 2: Update the DB models sequentially on the main thread session
                    summary_lines = []
                    summary_lines.append(f"Successfully processed {len(current_leads)} leads using parallel workers.\n")
                    
                    try:
                        for idx, lead in enumerate(current_leads, start=1):
                            res = results_by_id.get(lead.id)
                            
                            if res and res["success"]:
                                # Modify properties on the lead object safely
                                lead.status = LeadStatus.ANALYZED.value
                                lead.score = res["score"]
                                
                                raw_context = lead.ai_context_data if lead.ai_context_data else {}
                                updated_context = dict(raw_context)
                                updated_context["evaluation_justification"] = res["justification"]
                                lead.ai_context_data = updated_context
                                
                                # Track changes in session
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
                        
                        # Step 3: Explicitly commit the transaction to persist updates
                        await self.db.commit()
                        
                    except Exception as db_err:
                        # Rollback transaction if database save fails
                        await self.db.rollback()
                        logger.error(f"Database update failed, rolling back: {str(db_err)}")
                        summary_lines = [f"An error occurred while saving analysis details to the database: `{str(db_err)}`"]

                    summary_lines.append("\n*Lead records successfully qualified and updated in your workspace.*")
                    response = "\n".join(summary_lines)

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
                    
                    # Instantiate the isolated EmailAgent
                    email_agent = EmailAgent()

                    # 1. Generate customized email text
                    email_content = await email_agent.generate_custom_email(profile_payload, icp, message)

                    # 2. Evaluate the output using the self-review model
                    evaluation = await email_agent.evaluate_email(email_content, profile_payload, icp, message)

                    # 3. Revision pass if rejection triggers
                    if not evaluation.get("approved", True):
                        email_content = await email_agent.generate_custom_email(
                            profile_payload,
                            icp,
                            message,
                            revision_feedback=evaluation.get("feedback", "")
                        )

                    subject = email_content.get("subject", "Quick Question")
                    body = email_content.get("body", "")
                    
                    # 4. Store the draft using your existing EmailService
                    email_service = EmailService(self.db)
                    drafted_record = await email_service.draft_email(
                        user_id=user_id,
                        lead_id=existing_lead.id,
                        subject=subject,
                        body=body
                    )
                    
                    response = (
                        f"Draft Created for {existing_lead.name}\n"
                        f"I have successfully generated a personalized outreach template and saved it as a draft in your pipeline system.\n\n"
                    )

            elif action == "MEETING_OPERATION":
                meeting_agent = MeetingAgent(db_session=self.db)
    
                response = await meeting_agent.run(
                    user_prompt=message, 
                    team_id=team.id
                )
                


            elif action == "GENERATE_PROPOSAL":
                from app.core.s3 import upload_to_s3
                from app.models.proposal import Proposal, ProposalStatus, ProposalOutcome
                from app.ai.proposal_agent import ProposalAgent
                from sqlalchemy.exc import DBAPIError, IntegrityError
                import traceback

                name_keywords = params.get("keywords", [])
                lead_id = None
                if name_keywords:
                    current_leads = await self.search_current_leads_by_name(
                        team.id, name_keywords, limit=1
                    )
                    if current_leads:
                        lead_id = current_leads[0].id

                # 1. Initialize dedicated ProposalAgent & compile proposal + binary docx stream

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
                filename, file_bytes_stream = await proposal_agent.run(
                    user_prompt=message,
                    team_id=team.id,
                    lead_id=lead_id,
                    template_id=template_id
                )

                # 2. Upload file stream to S3
                file_bytes = file_bytes_stream.getvalue()
                file_url = await upload_to_s3(
                    file_bytes=file_bytes,
                    filename=filename,
                    content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    prefix="proposals",
                    user_id=str(user_id),
                )



                # 3. Save a Proposal record in the database
                await asyncio.sleep(1)
                _, raw_proposal_json, styles = await proposal_agent._compile_proposal_data(
                    user_prompt=message, 
                    icp_context=team.icp if team.icp else "",
                    has_template=bool(template_id)
                )

                logger.info("Initializing proposal single-pass evaluation...")
                evaluator = ProposalEvaluatorAgent(self.db)
                await asyncio.sleep(1)
                evaluation_report = await evaluator.evaluate_proposal(
                    original_prompt=message,
                    generated_proposal_data=raw_proposal_json,
                    icp_context=team.icp if team.icp else "Standard Enterprise B2B SaaS and Professional Solutions."
                )

                print("===================Proposal===================\n\n")
                print(raw_proposal_json)
                print("======================================\n\n")

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
                    # 1. Ensure any prior transactions are clean
                    if not self.db.is_active:
                        await self.db.rollback()

                    # 2. Add the proposal record
                    self.db.add(proposal)
                    
                    # 3. Commit the database changes
                    await self.db.commit() 
                    
                    # 4. CRITICAL: Refresh the model to keep its attributes loaded in memory 
                    # so FastAPI can safely read them for the response serialization
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
                response = (
                    f"Generated Proposal: {filename.replace('.docx', '').replace('_', ' ')}\n"
                    f"URL: ({file_url})\n\n"
                    f"--- Quality Assurance Report ---\n"
                    f"Quality Grade: {badge} ({evaluation_report.get('overall_score')}/10)\n"
                    f"Tone Check: {evaluation_report.get('human_authenticity', {}).get('analysis')}\n"
                    f"Actionable Polish: {evaluation_report.get('feedback_and_corrections')}\n"
                )
            else:
                rag_service = KnowledgeBaseRAGService(self.db)
                kb_answer = await rag_service.answer_query(team.id, message)

                if kb_answer.get("sources"):
                    response = kb_answer["answer"]
                else:
                    response = "I can help you search for prospects, analyze individuals, modify your ICP, or answer questions from your knowledge base. What would you like to do?"

                response = "No execution steps required. This is a standard user query."

            supervisor = SupervisorAgent(self.db)
            final_response = await supervisor.run(
                user_prompt=message,
                execution_result=response,
                team_id=team.id,
                messages_history=messages_history,
                user_info=user_info
            )
            
            # Save the AI's generated response to the DB to preserve conversational context
            self.db.add(
                ChatMessage(
                    team_id=team.id,
                    user_id=user_id,
                    sent_by=ChatRole.AI.value,
                    content=final_response,
                    metadata_log={},
                )
            )
            await self.db.commit()

            return final_response

        except Exception as e:
            print("\n========== CHAT ERROR ==========")
            print(repr(e))
            traceback.print_exc()
            print("================================")
            raise