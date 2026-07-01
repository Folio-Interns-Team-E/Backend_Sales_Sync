import logging
from typing import Any, Dict, List, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class ApolloService:
    """
    Thin wrapper around the Apollo.io API.

    Apollo has two relevant endpoints for us:
      - POST /v1/mixed_people/search   -> find people matching titles/industries/locations
      - POST /v1/people/match          -> enrich a single person by email/name+domain

    Docs: https://docs.apollo.io/reference
    """

    BASE_URL = "https://api.apollo.io/v1"

    @staticmethod
    def _headers() -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Cache-Control": "no-cache",
            "X-Api-Key": settings.apollo_api_key,
        }

    @staticmethod
    async def search_people(
        titles: List[str],
        industries: Optional[List[str]] = None,
        locations: Optional[List[str]] = None,
        company_size_range: Optional[str] = None,
        per_page: int = 25,
    ) -> List[Dict[str, Any]]:
        """
        Search Apollo's database for people matching the ICP's decision-maker
        titles, target industries, and target regions.

        Returns a list of raw Apollo "person" dicts (already merged with
        their organization info under person["organization"]).
        """
        payload: Dict[str, Any] = {
            "person_titles": titles,
            "page": 1,
            "per_page": per_page,
        }

        if industries:
            payload["organization_industry_tag_ids"] = industries
        if locations:
            payload["person_locations"] = locations
        if company_size_range:
            # Apollo expects e.g. ["1,10", "11,50", "51,200"] - we pass through
            # whatever range string the ICP stored; callers normalize.
            payload["organization_num_employees_ranges"] = [company_size_range]

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.post(
                    f"{ApolloService.BASE_URL}/mixed_people/search",
                    headers=ApolloService._headers(),
                    json=payload,
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as e:
                logger.error("Apollo search failed: %s - %s", e.response.status_code, e.response.text)
                raise ValueError(f"Apollo API error: {e.response.text}")
            except httpx.RequestError as e:
                logger.error("Apollo search request error: %s", str(e))
                raise ValueError(f"Could not reach Apollo API: {str(e)}")

            data = response.json()
            people = data.get("people", [])
            logger.info("Apollo search returned %d people", len(people))
            return people

    @staticmethod
    async def enrich_person(
        email: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        domain: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Enrich/verify a single person by email (preferred) or name + company domain.
        Used when a lead is added manually and needs firmographic backfill.
        """
        payload: Dict[str, Any] = {}
        if email:
            payload["email"] = email
        if first_name:
            payload["first_name"] = first_name
        if last_name:
            payload["last_name"] = last_name
        if domain:
            payload["domain"] = domain

        if not payload:
            return None

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.post(
                    f"{ApolloService.BASE_URL}/people/match",
                    headers=ApolloService._headers(),
                    json=payload,
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as e:
                logger.error("Apollo enrich failed: %s - %s", e.response.status_code, e.response.text)
                return None
            except httpx.RequestError as e:
                logger.error("Apollo enrich request error: %s", str(e))
                return None

            data = response.json()
            return data.get("person")

    @staticmethod
    def normalize_person(raw: Dict[str, Any]) -> Dict[str, Any]:
        """
        Map Apollo's raw person/organization payload into the flat fields
        our Lead model stores. Keeps all the messy Apollo-specific key
        names contained to this one function.
        """
        org = raw.get("organization") or {}

        first = raw.get("first_name") or ""
        last = raw.get("last_name") or ""
        full_name = (raw.get("name") or f"{first} {last}").strip() or "Unknown"

        return {
            "name": full_name,
            "title": raw.get("title"),
            "email": raw.get("email"),
            "linkedin_url": raw.get("linkedin_url"),
            "phone": (raw.get("phone_numbers") or [{}])[0].get("raw_number") if raw.get("phone_numbers") else None,
            "location": ", ".join(filter(None, [raw.get("city"), raw.get("state"), raw.get("country")])) or None,
            "company": org.get("name") or "Unknown Company",
            "company_domain": org.get("primary_domain") or org.get("website_url"),
            "company_size": str(org.get("estimated_num_employees")) if org.get("estimated_num_employees") else None,
            "company_industry": org.get("industry"),
            "company_revenue": org.get("annual_revenue_printed") or org.get("organization_revenue_printed"),
            "apollo_person_id": raw.get("id"),
            "apollo_org_id": org.get("id"),
            "raw_apollo_data": raw,
        }