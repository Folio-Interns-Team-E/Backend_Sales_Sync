import logging
import re
from uuid import UUID

import httpx
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead import Lead, LeadStatus
from app.models.team import Team
from app.services.lead_generation_service import LeadGenerationService
from app.services.lead_provider_service import get_provider, provider_key, reset_usage_if_needed

logger = logging.getLogger(__name__)
BASE_URL = "https://api.hunter.io/v2"
DOMAIN = re.compile(r"^(?:[a-z0-9-]+\.)+[a-z]{2,}$", re.I)
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def hunter_error(response: httpx.Response):
    if response.status_code == 401:
        raise HTTPException(401, "Hunter API key is invalid")
    if response.status_code == 403:
        raise HTTPException(403, "Hunter rate limit or plan restriction reached")
    if response.status_code == 429:
        raise HTTPException(429, "Hunter credits or monthly quota exhausted")
    if response.status_code >= 400:
        logger.warning("Hunter request failed: %s", response.status_code)
        raise HTTPException(502, "Hunter could not complete this request")


class HunterService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _key(self, team_id: UUID):
        record = await get_provider(self.db, team_id, "hunter")
        if not record:
            raise HTTPException(409, "Connect Hunter in Settings first")
        reset_usage_if_needed(record)
        return record, provider_key(record)

    async def discover(self, team_id: UUID, query: str):
        _, key = await self._key(team_id)
        async with httpx.AsyncClient(timeout=30) as client:
            try:
                response = await client.post(f"{BASE_URL}/discover", headers={"X-API-KEY": key}, json={"query": query})
            except httpx.RequestError as exc:
                raise HTTPException(502, "Hunter is temporarily unreachable") from exc
        hunter_error(response)
        return [
            {"domain": item["domain"], "name": item.get("organization") or item["domain"],
             "email_count": (item.get("emails_count") or {}).get("total", 0)}
            for item in response.json().get("data", [])
            if isinstance(item, dict) and DOMAIN.fullmatch(str(item.get("domain") or ""))
        ][:100]

    async def reveal(self, team_id: UUID, domains: list[str]):
        record, key = await self._key(team_id)
        normalized = list(dict.fromkeys(domain.strip().lower() for domain in domains))
        if not normalized or len(normalized) > 3 or any(not DOMAIN.fullmatch(domain) for domain in normalized):
            raise HTTPException(400, "Select one to three valid company domains")
        if record.used_this_month + len(normalized) > record.monthly_limit:
            raise HTTPException(429, "Workspace Hunter safety limit reached")
        team = await self.db.get(Team, team_id)
        if not team or not team.icp or not team.icp.strip():
            raise HTTPException(400, "Complete your ICP before importing contacts")
        prospects = []
        async with httpx.AsyncClient(timeout=30) as client:
            for domain in normalized:
                try:
                    response = await client.get(f"{BASE_URL}/domain-search", headers={"X-API-KEY": key}, params={"domain": domain, "limit": 1, "type": "personal"})
                except httpx.RequestError as exc:
                    raise HTTPException(502, "Hunter is temporarily unreachable") from exc
                hunter_error(response)
                record.used_this_month += 1  # Conservative local cap; Hunter determines actual billing.
                await self.db.commit()  # Preserve the cap even if a later lookup or scoring fails.
                data = response.json().get("data") or {}
                for person in (data.get("emails") or [])[:1]:
                    email = str(person.get("value") or "").strip().lower()
                    if not EMAIL.fullmatch(email):
                        continue
                    name = " ".join(filter(None, [person.get("first_name"), person.get("last_name")])).strip()
                    prospects.append({"apollo_id": f"hunter:{email}", "name": name or email.split("@")[0],
                                      "email": email, "title": person.get("position"),
                                      "company": data.get("organization") or domain,
                                      "country": None, "city": None,
                                      "domain": domain, "verification": (person.get("verification") or {}).get("status")})
        emails = [person["email"] for person in prospects]
        existing = set((await self.db.execute(select(func.lower(Lead.email)).where(
            Lead.team_id == team_id, func.lower(Lead.email).in_(emails)
        ))).scalars().all()) if emails else set()
        unique = [person for person in prospects if person["email"] not in existing]
        try:
            scores = await LeadGenerationService(self.db)._score(team.icp, unique) if unique else {}
        except Exception:
            logger.exception("Hunter leads imported without ICP scores")
            scores = {}
        leads = []
        for person in unique:
            score = scores.get(person["apollo_id"], {"score": 0, "reasoning": "Not scored"})
            lead = Lead(team_id=team_id, name=person["name"], email=person["email"],
                        company_name=person["company"], job_title=person["title"], source="Hunter",
                        score=score["score"], status=LeadStatus.ANALYZED.value,
                        ai_context_data={"reasoning": score["reasoning"], "provider": "hunter",
                                         "domain": person["domain"], "verification": person["verification"]})
            self.db.add(lead)
            leads.append(lead)
        await self.db.commit()
        for lead in leads:
            await self.db.refresh(lead)
        return leads, len(prospects) - len(unique)
