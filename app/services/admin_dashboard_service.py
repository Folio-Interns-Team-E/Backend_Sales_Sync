from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.email import Email, EmailStatus
from app.models.calcom_credentials import CalComIntegration
from app.models.google_credentials import GoogleCredentials
from app.models.knowledge_base import KnowledgeAsset
from app.models.lead import Lead
from app.models.lead_provider import LeadProviderCredential
from app.models.meeting import Meeting
from app.models.proposal import Proposal
from app.models.team import Team
from app.models.team_member import TeamMember
from app.services.lead_provider_service import reset_usage_if_needed


class AdminDashboardService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _count(self, statement) -> int:
        return int((await self.db.execute(statement)).scalar_one() or 0)

    async def overview(self, team_id: UUID) -> dict:
        team = (await self.db.execute(select(Team).where(Team.id == team_id))).scalar_one()

        member_rows = (await self.db.execute(
            select(TeamMember.role, func.count()).where(TeamMember.team_id == team_id).group_by(TeamMember.role)
        )).all()
        members_by_role = {getattr(role, "value", str(role)): count for role, count in member_rows}

        lead_rows = (await self.db.execute(
            select(Lead.status, func.count()).where(Lead.team_id == team_id).group_by(Lead.status)
        )).all()
        leads_by_status = {status: count for status, count in lead_rows}
        total_leads = sum(leads_by_status.values())
        avg_score = (await self.db.execute(
            select(func.avg(Lead.score)).where(Lead.team_id == team_id, Lead.score.is_not(None))
        )).scalar_one()

        email_rows = (await self.db.execute(
            select(Email.status, func.count())
            .join(Lead, Lead.id == Email.lead_id)
            .where(Lead.team_id == team_id)
            .group_by(Email.status)
        )).all()
        emails_by_status = {getattr(value, "value", str(value)): count for value, count in email_rows}

        meeting_rows = (await self.db.execute(
            select(Meeting.status, func.count())
            .join(Lead, Lead.id == Meeting.lead_id)
            .where(Lead.team_id == team_id)
            .group_by(Meeting.status)
        )).all()
        meetings_by_status = {value: count for value, count in meeting_rows}

        proposal_rows = (await self.db.execute(
            select(Proposal.outcome, func.count()).where(Proposal.team_id == team_id).group_by(Proposal.outcome)
        )).all()
        proposals_by_outcome = {value: count for value, count in proposal_rows}
        total_proposals = sum(proposals_by_outcome.values())

        knowledge_rows = (await self.db.execute(
            select(KnowledgeAsset.status, func.count())
            .where(KnowledgeAsset.team_id == team_id)
            .group_by(KnowledgeAsset.status)
        )).all()
        knowledge_by_status = {value: count for value, count in knowledge_rows}

        provider = (await self.db.execute(select(LeadProviderCredential).where(
            LeadProviderCredential.team_id == team_id,
            LeadProviderCredential.provider == "apollo",
        ))).scalar_one_or_none()
        if provider:
            reset_usage_if_needed(provider)

        gmail_connected = await self._count(select(func.count()).select_from(GoogleCredentials).where(
            GoogleCredentials.team_id == team_id
        )) > 0
        calcom_connected = await self._count(select(func.count()).select_from(CalComIntegration).where(
            CalComIntegration.team_id == team_id
        )) > 0

        recent_leads = (await self.db.execute(
            select(Lead).where(Lead.team_id == team_id).order_by(Lead.created_at.desc()).limit(5)
        )).scalars().all()
        recent_meetings = (await self.db.execute(
            select(Meeting).join(Lead, Lead.id == Meeting.lead_id).where(Lead.team_id == team_id)
            .order_by(Meeting.created_at.desc()).limit(5)
        )).scalars().all()
        recent_proposals = (await self.db.execute(
            select(Proposal).where(Proposal.team_id == team_id).order_by(Proposal.updated_at.desc()).limit(5)
        )).scalars().all()
        activity = [
            {"type": "lead", "label": f"{item.name} added to the pipeline", "detail": item.status, "timestamp": item.created_at}
            for item in recent_leads
        ] + [
            {"type": "meeting", "label": "Sales meeting updated", "detail": item.status, "timestamp": item.created_at}
            for item in recent_meetings
        ] + [
            {"type": "proposal", "label": "Proposal activity", "detail": f"{item.status} · {item.outcome}", "timestamp": item.updated_at}
            for item in recent_proposals
        ]
        activity.sort(key=lambda item: item["timestamp"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)

        qualified = leads_by_status.get("Qualified", 0)
        won = proposals_by_outcome.get("Won", 0)
        await self.db.commit()
        return {
            "workspace": {
                "id": str(team.id), "name": team.name, "created_at": team.created_at,
                "icp_configured": bool(team.icp and team.icp.strip()),
            },
            "members": {"total": sum(members_by_role.values()), "by_role": members_by_role},
            "pipeline": {
                "total_leads": total_leads, "by_status": leads_by_status,
                "average_score": round(float(avg_score or 0), 1),
                "qualification_rate": round((qualified / total_leads * 100) if total_leads else 0, 1),
            },
            "outreach": {
                "drafts": emails_by_status.get(EmailStatus.DRAFT.value, 0),
                "sent": emails_by_status.get(EmailStatus.SENT.value, 0),
            },
            "meetings": {"total": sum(meetings_by_status.values()), "by_status": meetings_by_status},
            "proposals": {
                "total": total_proposals, "by_outcome": proposals_by_outcome,
                "win_rate": round((won / total_proposals * 100) if total_proposals else 0, 1),
            },
            "knowledge_base": {"total": sum(knowledge_by_status.values()), "by_status": knowledge_by_status},
            "integrations": {
                "gmail_connected": gmail_connected,
                "calcom_connected": calcom_connected,
                "apollo_connected": provider is not None,
                "apollo_used": provider.used_this_month if provider else 0,
                "apollo_limit": provider.monthly_limit if provider else 0,
            },
            "billing": {
                "tier": team.subscription_tier, "status": team.subscription_status,
                "renews_or_ends_at": team.subscription_ends_at,
            },
            "recent_activity": activity[:10],
        }
