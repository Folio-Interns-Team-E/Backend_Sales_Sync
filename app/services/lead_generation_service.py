import asyncio
import json
import logging
import re
from typing import Any
from uuid import UUID

import httpx
from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.lead import Lead, LeadStatus
from app.models.team import Team
from app.services.lead_provider_service import get_provider, provider_key, reset_usage_if_needed


logger = logging.getLogger(__name__)


class LeadGenerationService:
    APOLLO_BASE_URL = "https://api.apollo.io/api/v1"
    GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
    MODEL = "openai/gpt-oss-120b"

    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def _json_content(response: httpx.Response) -> dict[str, Any]:
        response.raise_for_status()
        return response.json()

    async def _groq_json(self, prompt: str, max_tokens: int) -> dict[str, Any]:
        if not settings.grok_api_key:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "AI lead scoring is not configured")
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                self.GROQ_URL,
                headers={"Authorization": f"Bearer {settings.grok_api_key}"},
                json={
                    "model": self.MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0,
                    "max_tokens": max_tokens,
                    "response_format": {"type": "json_object"},
                },
            )
        payload = self._json_content(response)
        return json.loads(payload["choices"][0]["message"]["content"])

    async def _criteria_from_icp(self, icp: str) -> dict[str, Any]:
        result = await self._groq_json(
            f"""Convert this B2B ideal customer profile into Apollo people-search filters.
Return only JSON with keys: titles (max 8 strings), seniorities (values only from owner, founder, c_suite, partner, vp, head, director, manager, senior, entry, intern), locations (max 5 country/city strings), and keywords (one short string).
ICP:\n{icp}""",
            600,
        )
        allowed = {"owner", "founder", "c_suite", "partner", "vp", "head", "director", "manager", "senior", "entry", "intern"}
        return {
            "titles": [str(value)[:100] for value in result.get("titles", []) if str(value).strip()][:8],
            "seniorities": [value for value in result.get("seniorities", []) if value in allowed][:6],
            "locations": [str(value)[:100] for value in result.get("locations", []) if str(value).strip()][:5],
            "keywords": str(result.get("keywords", ""))[:200],
        }

    async def _search_apollo(self, criteria: dict[str, Any], limit: int, api_key: str | None = None) -> list[dict[str, Any]]:
        api_key = api_key or settings.apollo_api_key
        if not api_key:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Apollo lead generation is not configured")
        params: list[tuple[str, str | int | bool]] = [("page", 1), ("per_page", limit), ("include_similar_titles", True)]
        params.extend(("person_titles[]", value) for value in criteria["titles"])
        params.extend(("person_seniorities[]", value) for value in criteria["seniorities"])
        params.extend(("person_locations[]", value) for value in criteria["locations"])
        if criteria["keywords"]:
            params.append(("q_keywords", criteria["keywords"]))
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{self.APOLLO_BASE_URL}/mixed_people/api_search",
                params=params,
                headers={"x-api-key": api_key, "Accept": "application/json"},
            )
        try:
            return list(self._json_content(response).get("people") or [])
        except httpx.HTTPStatusError as exc:
            logger.warning("Apollo people search failed with status %s", exc.response.status_code)
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Apollo could not complete the lead search") from exc

    async def _enrich_person(self, person: dict[str, Any], api_key: str) -> dict[str, Any] | None:
        person_id = person.get("id") or person.get("person_id")
        if not person_id:
            return None
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{self.APOLLO_BASE_URL}/people/match",
                params={"id": person_id},
                headers={"x-api-key": api_key, "Accept": "application/json"},
            )
        if response.status_code != 200:
            logger.info("Skipping Apollo prospect that could not be enriched")
            return None
        enriched = response.json().get("person") or {}
        email = str(enriched.get("email") or "").strip().lower()
        if not email or email == "email_not_unlocked@domain.com" or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            return None
        organization = enriched.get("organization") or person.get("organization") or {}
        return {
            "apollo_id": str(person_id),
            "name": enriched.get("name") or " ".join(filter(None, [enriched.get("first_name"), enriched.get("last_name")])).strip(),
            "email": email,
            "title": enriched.get("title") or person.get("title"),
            "company": organization.get("name"),
            "country": enriched.get("country"),
            "city": enriched.get("city"),
            "linkedin_url": enriched.get("linkedin_url"),
            "raw": enriched,
        }

    async def _score(self, icp: str, prospects: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        compact = [{key: item.get(key) for key in ("apollo_id", "name", "title", "company", "country", "city")} for item in prospects]
        result = await self._groq_json(
            f"""Score each prospect against the ICP from 0 to 100. Return only JSON shaped as {{"scores":[{{"apollo_id":"...","score":85,"reasoning":"one concise evidence-based sentence"}}]}}. Do not invent facts.
ICP:\n{icp}\nProspects:\n{json.dumps(compact)}""",
            1800,
        )
        scores = {}
        for item in result.get("scores", []):
            prospect_id = str(item.get("apollo_id", ""))
            if prospect_id:
                scores[prospect_id] = {
                    "score": max(0, min(100, int(item.get("score", 0)))),
                    "reasoning": str(item.get("reasoning", ""))[:500],
                }
        return scores

    async def generate(self, team_id: UUID, limit: int = 10) -> tuple[list[Lead], int]:
        team = (await self.db.execute(select(Team).where(Team.id == team_id))).scalar_one_or_none()
        if not team or not team.icp or not team.icp.strip():
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Complete your ICP before generating leads")

        provider = await get_provider(self.db, team_id)
        if provider:
            reset_usage_if_needed(provider)
            remaining = provider.monthly_limit - provider.used_this_month
            if remaining <= 0:
                await self.db.commit()
                raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "This workspace has reached its monthly Apollo limit")
            limit = min(limit, remaining)
            api_key = provider_key(provider)
        else:
            api_key = settings.apollo_api_key
        if not api_key:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Connect Apollo in Settings before generating leads")

        criteria = await self._criteria_from_icp(team.icp)
        people = await self._search_apollo(criteria, limit, api_key)
        if provider:
            provider.used_this_month += len(people)
        semaphore = asyncio.Semaphore(3)

        async def enrich(person):
            async with semaphore:
                return await self._enrich_person(person, api_key)

        prospects = [item for item in await asyncio.gather(*(enrich(person) for person in people)) if item]
        if not prospects:
            await self.db.commit()
            return [], len(people)

        emails = [item["email"] for item in prospects]
        existing = set((await self.db.execute(
            select(func.lower(Lead.email)).where(Lead.team_id == team_id, func.lower(Lead.email).in_(emails))
        )).scalars().all())
        unique = []
        seen = set(existing)
        for prospect in prospects:
            if prospect["email"] not in seen:
                seen.add(prospect["email"])
                unique.append(prospect)
        if not unique:
            await self.db.commit()
            return [], len(prospects)

        scores = await self._score(team.icp, unique)
        leads = []
        for prospect in unique:
            assessment = scores.get(prospect["apollo_id"], {"score": 0, "reasoning": "Not scored"})
            lead = Lead(
                team_id=team_id,
                name=prospect["name"] or prospect["email"].split("@")[0],
                email=prospect["email"],
                company_name=prospect["company"],
                job_title=prospect["title"],
                source="Apollo",
                score=assessment["score"],
                status=LeadStatus.ANALYZED.value,
                ai_context_data={
                    "reasoning": assessment["reasoning"],
                    "provider": "apollo",
                    "provider_id": prospect["apollo_id"],
                    "country": prospect["country"],
                    "city": prospect["city"],
                    "linkedin_url": prospect["linkedin_url"],
                },
            )
            self.db.add(lead)
            leads.append(lead)
        await self.db.commit()
        for lead in leads:
            await self.db.refresh(lead)
        return leads, len(prospects) - len(unique)
