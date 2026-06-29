import json
import logging
import re
from typing import Any, Dict, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class GrokService:
    """
    Service responsible for generating and refining ICPs using Groq LLM.
    """

    BASE_URL = "https://api.groq.com/openai/v1"
    MODEL = "llama-3.3-70b-versatile"

    @staticmethod
    async def _call_llm(prompt: str) -> Dict[str, Any]:
        """
        Internal helper to call Groq Chat Completions API.
        """

        payload = {
            "model": GrokService.MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are an expert B2B SaaS GTM strategist and ICP consultant. "
                        "Always return valid JSON only. Never wrap JSON inside markdown."
                    ),
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            "temperature": 0.4,
            "max_tokens": 1800,
            "response_format": {
                "type": "json_object"
            }
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{GrokService.BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.grok_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )

            try:
                response.raise_for_status()
            except httpx.HTTPStatusError:
                logger.error("Groq Status: %s", response.status_code)
                logger.error("Groq Response: %s", response.text)
                raise

            result = response.json()

            if "choices" not in result or len(result["choices"]) == 0:
                raise ValueError("Groq returned no choices.")

            content = result["choices"][0]["message"]["content"]

            try:
                return json.loads(content)

            except json.JSONDecodeError:
                logger.warning("Trying regex JSON extraction...")

                match = re.search(r"\{.*\}", content, re.DOTALL)

                if not match:
                    raise ValueError(
                        f"Model returned invalid JSON:\n{content}"
                    )

                return json.loads(match.group())

    @staticmethod
    async def generate_icp(
        product_description: str,
        target_market_description: str,
        goals: str,
        product_name: Optional[str] = None,
        company_description: Optional[str] = None,
    ) -> Dict[str, Any]:

        prompt = f"""
You are a senior B2B SaaS Go-To-Market strategist.

Generate an Ideal Customer Profile (ICP).

=========================
PRODUCT INFORMATION
=========================

Product Name:
{product_name or "Not provided"}

Product Description:
{product_description}

Company Description:
{company_description or "Not provided"}

=========================
TARGET CUSTOMER
=========================

{target_market_description}

=========================
BUSINESS GOALS
=========================

{goals}

Use the goals to influence your recommendations.

For example:

• Revenue Growth → prioritize high-value accounts.

• Faster Sales Cycles → prioritize SMBs.

• Enterprise Expansion → prioritize large companies.

• Pipeline Growth → prioritize buyers with urgent pain points.

Return ONLY JSON.
Return EXACTLY this schema:

{{
  "target_industries": [
    ""
  ],
  "company_size_range": "",
  "target_revenues": "",
  "decision_maker_titles": [
    ""
  ],
  "pain_points": [
    ""
  ],
  "key_characteristics": [
    ""
  ],
  "icp_summary": [
    "",
    "",
    "",
    "",
    ""
  ],
  "analysis": ""
}}

Requirements:

- target_industries: 5-8 industries
- decision_maker_titles: 5-8 roles
- pain_points: 6-10 pain points
- key_characteristics: 6-10 characteristics
- icp_summary: 5 concise bullet points summarizing the ICP
- analysis: 2-4 detailed paragraphs

Return valid JSON only.
"""

        try:
            icp_data = await GrokService._call_llm(prompt)

            logger.info("Successfully generated ICP via Groq")

            return {
                "target_industries": icp_data.get(
                    "target_industries", []
                ),
                "company_size_range": icp_data.get(
                    "company_size_range"
                ),
                "target_revenues": icp_data.get(
                    "target_revenues"
                ),
                "decision_maker_titles": icp_data.get(
                    "decision_maker_titles", []
                ),
                "pain_points": icp_data.get(
                    "pain_points", []
                ),
                "key_characteristics": icp_data.get(
                    "key_characteristics", []
                ),
                "icp_summary": icp_data.get(
                    "icp_summary", []
                ),
                "analysis": icp_data.get(
                    "analysis", ""
                ),
                "full_response": icp_data,
            }

        except httpx.HTTPStatusError as e:
            logger.error("Groq HTTP Error")
            logger.error("Status Code: %s", e.response.status_code)
            logger.error("Response: %s", e.response.text)

            raise ValueError(
                f"Groq API Error: {e.response.text}"
            )

        except Exception as e:
            logger.exception("ICP generation failed")
            raise ValueError(str(e))

    @staticmethod
    async def refine_icp(
        current_icp_data: Dict[str, Any],
        refinement_request: str,
        goals: Optional[str] = None,
    ) -> Dict[str, Any]:

        prompt = f"""
You are an expert ICP consultant.

The user already has an ICP.

Refine it based on the user's request.

Current ICP:

Industries:
{current_icp_data.get("target_industries", [])}

Company Size:
{current_icp_data.get("company_size_range")}

Revenue:
{current_icp_data.get("target_revenues")}

Decision Makers:
{current_icp_data.get("decision_maker_titles", [])}

Pain Points:
{current_icp_data.get("pain_points", [])}

Characteristics:
{current_icp_data.get("key_characteristics", [])}

Summary:
{current_icp_data.get("icp_summary", [])}

Business Goals:
{goals or "Not provided"}

User refinement request:

{refinement_request}

Return ONLY valid JSON.
Return EXACTLY this JSON schema:

{{
  "target_industries": [
    ""
  ],
  "company_size_range": "",
  "target_revenues": "",
  "decision_maker_titles": [
    ""
  ],
  "pain_points": [
    ""
  ],
  "key_characteristics": [
    ""
  ],
  "icp_summary": [
    "",
    "",
    "",
    "",
    ""
  ],
  "analysis": ""
}}

Requirements:

- Preserve useful information from the existing ICP.
- Modify only what is necessary based on the refinement request.
- Ensure recommendations align with the business goals.
- Return JSON only.
"""

        try:
            icp_data = await GrokService._call_llm(prompt)

            logger.info("Successfully refined ICP via Groq")

            return {
                "target_industries": icp_data.get(
                    "target_industries", []
                ),
                "company_size_range": icp_data.get(
                    "company_size_range"
                ),
                "target_revenues": icp_data.get(
                    "target_revenues"
                ),
                "decision_maker_titles": icp_data.get(
                    "decision_maker_titles", []
                ),
                "pain_points": icp_data.get(
                    "pain_points", []
                ),
                "key_characteristics": icp_data.get(
                    "key_characteristics", []
                ),
                "icp_summary": icp_data.get(
                    "icp_summary", []
                ),
                "analysis": icp_data.get(
                    "analysis", ""
                ),
                "full_response": icp_data,
            }

        except httpx.HTTPStatusError as e:
            logger.error("Groq HTTP Error")
            logger.error("Status Code: %s", e.response.status_code)
            logger.error("Response Body: %s", e.response.text)

            raise ValueError(
                f"Groq API Error: {e.response.text}"
            )

        except Exception as e:
            logger.exception("ICP refinement failed")
            raise ValueError(str(e))