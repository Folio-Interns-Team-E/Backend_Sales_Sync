import logging
from typing import List, Optional, Tuple
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.icp import ICP
from app.models.lead import Lead
from app.schemas.leads import GenerateLeadsRequest, ManualLeadCreate
from app.services.apollo_service import ApolloService
from app.services.grok_service import GrokService
from app.services.lead_scoring_service import LeadScoringService

logger = logging.getLogger(__name__)


class LeadsService:

    def __init__(self, db: AsyncSession):
        self.db = db

    # ─────────────────────────────────────────────────────────────────
    # Generation
    # ─────────────────────────────────────────────────────────────────

    async def generate_from_icp(
        self,
        user_id: UUID,
        team_id: Optional[UUID],
        request: GenerateLeadsRequest,
    ) -> Tuple[List[Lead], int]:
        """
        Pull candidates from Apollo → score each → persist new leads.
        Returns (created_leads, skipped_duplicate_count).
        """
        icp = await self._get_icp_or_raise(user_id)

        titles = list(icp.decision_maker_titles or [])
        if request.extra_titles:
            titles.extend(request.extra_titles)
        if not titles:
            raise ValueError(
                "Your ICP has no decision_maker_titles. "
                "Finish onboarding at POST /onboarding/icp first."
            )

        locations = request.locations or icp.target_regions or None

        raw_people = await ApolloService.search_people(
            titles=titles,
            locations=locations,
            company_size_range=icp.company_size_range,
            per_page=request.limit,
        )

        if not raw_people:
            return [], 0

        existing_emails = await self._get_existing_emails(user_id)
        created: List[Lead] = []
        skipped = 0

        for raw in raw_people:
            norm = ApolloService.normalize_person(raw)

            email = (norm.get("email") or "").lower()
            if email and email in existing_emails:
                skipped += 1
                continue

            scoring = await LeadScoringService.score_lead(norm, icp)
            lead    = self._build_lead(user_id, team_id, icp.id, norm, scoring, "Apollo")

            self.db.add(lead)
            created.append(lead)
            if email:
                existing_emails.add(email)

        if created:
            await self.db.commit()
            for lead in created:
                await self.db.refresh(lead)

        logger.info(
            "Generated %d leads (%d dupes skipped) for user %s",
            len(created), skipped, user_id,
        )
        return created, skipped

    async def create_manual_lead(
        self,
        user_id: UUID,
        team_id: Optional[UUID],
        payload: ManualLeadCreate,
    ) -> Lead:
        """Add a lead manually with optional Apollo enrichment."""
        icp = await self._get_icp_or_raise(user_id)

        lead_data = {
            "name":           payload.name,
            "title":          payload.title,
            "email":          payload.email,
            "linkedin_url":   payload.linkedin_url,
            "company":        payload.company,
            "company_domain": payload.company_domain,
            "company_size":   None,
            "company_industry": None,
            "location":       None,
            "phone":          None,
        }

        # Best-effort Apollo enrichment
        if payload.email or payload.company_domain:
            try:
                first, _, last = payload.name.partition(" ")
                enriched = await ApolloService.enrich_person(
                    email=payload.email,
                    first_name=first or None,
                    last_name=last or None,
                    domain=payload.company_domain,
                )
                if enriched:
                    norm = ApolloService.normalize_person(enriched)
                    lead_data.update({k: v for k, v in norm.items() if v is not None})
            except Exception as exc:
                logger.warning("Manual lead Apollo enrichment skipped: %s", exc)

        scoring = await LeadScoringService.score_lead(lead_data, icp)
        lead    = self._build_lead(user_id, team_id, icp.id, lead_data, scoring, payload.source)

        self.db.add(lead)
        await self.db.commit()
        await self.db.refresh(lead)
        return lead

    # ─────────────────────────────────────────────────────────────────
    # CRUD
    # ─────────────────────────────────────────────────────────────────

    async def list_leads(
        self,
        user_id: UUID,
        status: Optional[str] = None,
        min_score: Optional[int] = None,
    ) -> List[Lead]:
        status_value = (status or "").strip()
        if status_value.lower() in {"", "all", "any", "string", "none", "null", "undefined"}:
            status_value = ""

        q = select(Lead).where(Lead.user_id == user_id)
        if status_value:
            q = q.where(func.lower(Lead.status) == status_value.lower())
        if min_score is not None:
            q = q.where(Lead.score >= min_score)
        q = q.order_by(Lead.score.desc())
        result = await self.db.execute(q)
        leads = list(result.scalars().all())
        logger.info(
            "list_leads user=%s status=%s min_score=%s count=%d",
            user_id,
            status_value or None,
            min_score,
            len(leads),
        )
        return leads

    async def get_lead(self, user_id: UUID, lead_id: UUID) -> Optional[Lead]:
        result = await self.db.execute(
            select(Lead).where(Lead.id == lead_id, Lead.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def update_status(
        self, user_id: UUID, lead_id: UUID, new_status: str
    ) -> Optional[Lead]:
        lead = await self.get_lead(user_id, lead_id)
        if not lead:
            return None
        lead.status = new_status
        await self.db.commit()
        await self.db.refresh(lead)
        return lead

    async def qualify_lead(self, user_id: UUID, lead_id: UUID) -> Optional[Lead]:
        return await self.update_status(user_id, lead_id, "Qualified")

    async def discard_lead(self, user_id: UUID, lead_id: UUID) -> Optional[Lead]:
        return await self.update_status(user_id, lead_id, "Discarded")

    async def draft_email(self, user_id: UUID, lead_id: UUID) -> Optional[Lead]:
        return await self.update_status(user_id, lead_id, "Drafted")

    async def send_email(self, user_id: UUID, lead_id: UUID) -> Optional[Lead]:
        return await self.update_status(user_id, lead_id, "Sent")

    async def rescore_lead(self, user_id: UUID, lead_id: UUID) -> Optional[Lead]:
        """Re-run the full scoring pipeline for one lead (e.g. after editing ICP)."""
        lead = await self.get_lead(user_id, lead_id)
        if not lead:
            return None

        icp = await self._get_icp_or_raise(user_id)
        lead_data = {
            "name":             lead.name,
            "title":            lead.title,
            "email":            lead.email,
            "company":          lead.company,
            "company_industry": lead.company_industry,
            "company_size":     lead.company_size,
            "company_revenue":  lead.company_revenue,
            "location":         lead.location,
            "linkedin_url":     lead.linkedin_url,
            "phone":            lead.phone,
        }
        scoring = await LeadScoringService.score_lead(lead_data, icp)
        self._apply_scoring(lead, scoring)
        await self.db.commit()
        await self.db.refresh(lead)
        return lead

    async def generate_outreach_email(
        self,
        user_id: UUID,
        lead_id: UUID,
        sender_name: str,
        tone: str = "friendly",
    ) -> Optional[dict]:
        """Draft a personalised outreach email via Groq and save it on the lead."""
        lead = await self.get_lead(user_id, lead_id)
        if not lead:
            return None

        icp = await self._get_icp_or_raise(user_id)
        icp_data = {
            "target_industries":    icp.target_industries,
            "pain_points":          icp.pain_points,
            "decision_maker_titles": icp.decision_maker_titles,
        }
        lead_data = {
            "name":             lead.name,
            "title":            lead.title,
            "company":          lead.company,
            "company_industry": lead.company_industry,
            "company_size":     lead.company_size,
            "score":            lead.score,
        }

        email = await GrokService.generate_outreach_email(
            lead_data=lead_data,
            icp_data=icp_data,
            sender_name=sender_name,
            tone=tone,
        )

        lead.email_subject = email["subject"]
        lead.email_body    = email["body"]
        lead.status        = "Drafted"
        await self.db.commit()
        await self.db.refresh(lead)
        return email

    async def save_outreach_email(
        self,
        user_id: UUID,
        lead_id: UUID,
        subject: str,
        body: str,
    ) -> Optional[Lead]:
        """Persist a manually edited outreach email draft."""
        lead = await self.get_lead(user_id, lead_id)
        if not lead:
            return None
        lead.email_subject = subject
        lead.email_body    = body
        lead.status        = "Drafted"
        await self.db.commit()
        await self.db.refresh(lead)
        return lead

    async def delete_lead(self, user_id: UUID, lead_id: UUID) -> bool:
        lead = await self.get_lead(user_id, lead_id)
        if not lead:
            return False
        await self.db.delete(lead)
        await self.db.commit()
        return True

    # ─────────────────────────────────────────────────────────────────
    # Private helpers
    # ─────────────────────────────────────────────────────────────────

    async def _get_icp_or_raise(self, user_id: UUID) -> ICP:
        result = await self.db.execute(select(ICP).where(ICP.user_id == user_id))
        icp = result.scalar_one_or_none()
        if not icp:
            raise ValueError(
                "No ICP found. Complete onboarding at POST /onboarding/icp before generating leads."
            )
        return icp

    async def _get_existing_emails(self, user_id: UUID) -> set:
        result = await self.db.execute(
            select(Lead.email).where(Lead.user_id == user_id, Lead.email.isnot(None))
        )
        return {email.lower() for (email,) in result.all()}

    @staticmethod
    def _make_initials(name: str) -> str:
        parts = [p for p in name.split() if p]
        if not parts:
            return "?"
        if len(parts) == 1:
            return parts[0][0].upper()
        return (parts[0][0] + parts[-1][0]).upper()

    def _build_lead(
        self,
        user_id: UUID,
        team_id: Optional[UUID],
        icp_id,
        data: dict,
        scoring: dict,
        source: str,
    ) -> Lead:
        lead = Lead(
            user_id=user_id, team_id=team_id, icp_id=icp_id,
            name=data["name"], company=data["company"],
            title=data.get("title"), email=data.get("email"),
            source=source, initials=self._make_initials(data["name"]),
            company_domain=data.get("company_domain"),
            company_size=data.get("company_size"),
            company_industry=data.get("company_industry"),
            company_revenue=data.get("company_revenue"),
            linkedin_url=data.get("linkedin_url"),
            phone=data.get("phone"), location=data.get("location"),
            apollo_person_id=data.get("apollo_person_id"),
            apollo_org_id=data.get("apollo_org_id"),
            raw_apollo_data=data.get("raw_apollo_data"),
        )
        self._apply_scoring(lead, scoring)
        return lead

    @staticmethod
    def _apply_scoring(lead: Lead, s: dict) -> None:
        lead.score    = s["score"]
        lead.status   = s["status"]
        lead.reasoning = s["reasoning"]
        lead.icp_fit_score        = s.get("icp_fit_score")
        lead.is_disqualified      = "true" if s.get("is_disqualified") else "false"
        lead.disqualify_reasons   = s.get("disqualify_reasons", [])
        lead.bant_budget_score    = s.get("bant_budget_score")
        lead.bant_authority_score = s.get("bant_authority_score")
        lead.bant_need_score      = s.get("bant_need_score")
        lead.bant_timeline_score  = s.get("bant_timeline_score")
        lead.bant_total_score     = s.get("bant_total_score")
        lead.bant_notes           = s.get("bant_notes")
        lead.meddic_metrics_score          = s.get("meddic_metrics_score")
        lead.meddic_economic_buyer_score   = s.get("meddic_economic_buyer_score")
        lead.meddic_decision_criteria_score = s.get("meddic_decision_criteria_score")
        lead.meddic_decision_process_score = s.get("meddic_decision_process_score")
        lead.meddic_identify_pain_score    = s.get("meddic_identify_pain_score")
        lead.meddic_champion_score         = s.get("meddic_champion_score")
        lead.meddic_total_score            = s.get("meddic_total_score")
        lead.meddic_notes                  = s.get("meddic_notes")
        lead.grok_scoring_response         = s.get("grok_scoring_response")