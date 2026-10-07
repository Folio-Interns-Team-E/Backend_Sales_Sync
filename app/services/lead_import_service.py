import csv
import io
import re
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead import Lead, LeadStatus
from app.models.team import Team
from app.services.lead_generation_service import LeadGenerationService


EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_CSV_BYTES = 2 * 1024 * 1024
MAX_CSV_ROWS = 500


class LeadImportService:
    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def parse_csv(content: bytes) -> tuple[list[dict], int]:
        if len(content) > MAX_CSV_BYTES:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "CSV must be 2 MB or smaller")
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "CSV must use UTF-8 encoding") from exc
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "CSV header row is required")
        aliases = {str(name).strip().lower().replace(" ", "_"): name for name in reader.fieldnames}
        email_key = next((aliases[key] for key in ("email", "work_email", "business_email") if key in aliases), None)
        name_key = next((aliases[key] for key in ("name", "full_name", "contact_name") if key in aliases), None)
        if not email_key or not name_key:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "CSV requires name and email columns")
        company_key = next((aliases[key] for key in ("company", "company_name", "organization") if key in aliases), None)
        title_key = next((aliases[key] for key in ("title", "job_title", "position") if key in aliases), None)
        parsed, invalid = [], 0
        for index, row in enumerate(reader, start=1):
            if index > MAX_CSV_ROWS:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, f"CSV cannot contain more than {MAX_CSV_ROWS} rows")
            email = str(row.get(email_key) or "").strip().lower()
            name = str(row.get(name_key) or "").strip()
            if not name or not EMAIL_PATTERN.fullmatch(email):
                invalid += 1
                continue
            parsed.append({
                "apollo_id": f"csv:{index}",
                "name": name[:255],
                "email": email[:255],
                "company": str(row.get(company_key) or "").strip()[:255] if company_key else None,
                "title": str(row.get(title_key) or "").strip()[:255] if title_key else None,
                "country": None,
                "city": None,
            })
        return parsed, invalid

    async def import_csv(self, team_id: UUID, content: bytes) -> tuple[list[Lead], int, int]:
        rows, invalid = self.parse_csv(content)
        team = (await self.db.execute(select(Team).where(Team.id == team_id))).scalar_one_or_none()
        if not team or not team.icp or not team.icp.strip():
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Complete your ICP before importing leads")
        if not rows:
            return [], 0, invalid
        emails = [row["email"] for row in rows]
        existing = set((await self.db.execute(
            select(func.lower(Lead.email)).where(Lead.team_id == team_id, func.lower(Lead.email).in_(emails))
        )).scalars().all())
        unique, seen = [], set(existing)
        for row in rows:
            if row["email"] not in seen:
                seen.add(row["email"])
                unique.append(row)
        duplicate_count = len(rows) - len(unique)
        if not unique:
            return [], duplicate_count, invalid
        scores = await LeadGenerationService(self.db)._score(team.icp, unique)
        leads = []
        for row in unique:
            assessment = scores.get(row["apollo_id"], {"score": 0, "reasoning": "Not scored"})
            lead = Lead(
                team_id=team_id,
                name=row["name"],
                email=row["email"],
                company_name=row["company"],
                job_title=row["title"],
                source="CSV Import",
                score=assessment["score"],
                status=LeadStatus.ANALYZED.value,
                ai_context_data={"reasoning": assessment["reasoning"], "provider": "csv"},
            )
            self.db.add(lead)
            leads.append(lead)
        await self.db.commit()
        for lead in leads:
            await self.db.refresh(lead)
        return leads, duplicate_count, invalid
