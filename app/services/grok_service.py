import json
import logging
import re
from typing import Any, Dict, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class GrokService:
    """
    Wrapper around Groq LLM (llama-3.3-70b-versatile).
    Used for:
      - ICP generation / refinement
      - BANT + MEDDIC lead scoring
      - Outreach email generation
    """

    BASE_URL = "https://api.groq.com/openai/v1"
    MODEL = "llama-3.3-70b-versatile"

    # ──────────────────────────────────────────────────────────────
    # Private helper
    # ──────────────────────────────────────────────────────────────

    @staticmethod
    async def _call_llm(prompt: str) -> Dict[str, Any]:
        """
        Fire a single-turn prompt at Groq and return the parsed JSON response.
        Raises ValueError on network error or malformed JSON.
        """
        if not settings.grok_api_key:
            raise ValueError("GROK_API_KEY is not configured.")

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
            "response_format": {"type": "json_object"}
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
                    raise ValueError(f"Model returned invalid JSON:\n{content}")
                return json.loads(match.group())

    # ──────────────────────────────────────────────────────────────
    # ICP generation
    # ──────────────────────────────────────────────────────────────

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

        if not settings.grok_api_key:
            return GrokService._fallback_icp(
                product_description=product_description,
                target_market_description=target_market_description,
                goals=goals,
            )

        try:
            icp_data = await GrokService._call_llm(prompt)
            logger.info("Successfully generated ICP via Groq")

            return {
                "target_industries": icp_data.get("target_industries", []),
                "company_size_range": icp_data.get("company_size_range"),
                "target_revenues": icp_data.get("target_revenues"),
                "decision_maker_titles": icp_data.get("decision_maker_titles", []),
                "pain_points": icp_data.get("pain_points", []),
                "key_characteristics": icp_data.get("key_characteristics", []),
                "icp_summary": icp_data.get("icp_summary", []),
                "analysis": icp_data.get("analysis", ""),
                "full_response": icp_data,
            }

        except httpx.HTTPStatusError as e:
            logger.error("Groq HTTP Error")
            logger.error("Status Code: %s", e.response.status_code)
            logger.error("Response: %s", e.response.text)
            raise ValueError(f"Groq API Error: {e.response.text}")

        except Exception as e:
            logger.exception("ICP generation failed")
            raise ValueError(str(e))

    @staticmethod
    async def refine_icp(
        existing_icp: Dict[str, Any],
        feedback: str,
        product_description: Optional[str] = None,
    ) -> Dict[str, Any]:
        prompt = f"""
You are an expert ICP consultant.

The user already has an ICP.
Refine it based on the user's request.

Current ICP:

Industries:
{existing_icp.get("target_industries", [])}

Company Size:
{existing_icp.get("company_size_range")}

Revenue:
{existing_icp.get("target_revenues")}

Decision Makers:
{existing_icp.get("decision_maker_titles", [])}

Pain Points:
{existing_icp.get("pain_points", [])}

Characteristics:
{existing_icp.get("key_characteristics", [])}

Summary:
{existing_icp.get("icp_summary", [])}

Product Description:
{product_description or "Not provided"}

User refinement request:

{feedback}

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
- Return JSON only.
"""

        if not settings.grok_api_key:
            return GrokService._fallback_icp(
                product_description=product_description or "",
                target_market_description=", ".join(existing_icp.get("target_industries", [])),
                goals=feedback,
            )

        try:
            icp_data = await GrokService._call_llm(prompt)
            logger.info("Successfully refined ICP via Groq")

            return {
                "target_industries": icp_data.get("target_industries", []),
                "company_size_range": icp_data.get("company_size_range"),
                "target_revenues": icp_data.get("target_revenues"),
                "decision_maker_titles": icp_data.get("decision_maker_titles", []),
                "pain_points": icp_data.get("pain_points", []),
                "key_characteristics": icp_data.get("key_characteristics", []),
                "icp_summary": icp_data.get("icp_summary", []),
                "analysis": icp_data.get("analysis", ""),
                "full_response": icp_data,
            }

        except httpx.HTTPStatusError as e:
            logger.error("Groq HTTP Error")
            logger.error("Status Code: %s", e.response.status_code)
            logger.error("Response Body: %s", e.response.text)
            raise ValueError(f"Groq API Error: {e.response.text}")

        except Exception as e:
            logger.exception("ICP refinement failed")
            raise ValueError(str(e))

    # ──────────────────────────────────────────────────────────────
    # BANT + MEDDIC lead scoring
    # ──────────────────────────────────────────────────────────────

    @staticmethod
    async def score_lead_bant_meddic(
        lead_data: Dict[str, Any],
        icp_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Score one enriched lead against the ICP using BANT + MEDDIC.
        Only firmographic / title signals are available at this stage.
        Returns a flat dict of bant_*, meddic_*, reasoning, full_response.
        """
        prompt = f"""
You are a senior B2B sales qualification expert. Score ONE prospect against
the seller's Ideal Customer Profile using BANT and MEDDIC frameworks.

You only have firmographic and title signals at this stage (no call transcript yet).
Infer each dimension from company size, industry, job title, seniority, and ICP match.
Be honest when a dimension is unknown — score it 40-55 rather than guessing high.

=== SELLER ICP ===
Target industries:        {icp_data.get("target_industries", [])}
Company size range:       {icp_data.get("company_size_range")}
Target revenue:           {icp_data.get("target_revenues")}
Decision-maker titles:    {icp_data.get("decision_maker_titles", [])}
Pain points the product solves: {icp_data.get("pain_points", [])}
Key characteristics:      {icp_data.get("key_characteristics", [])}

=== PROSPECT ===
Name:             {lead_data.get("name")}
Title:            {lead_data.get("title")}
Company:          {lead_data.get("company")}
Industry:         {lead_data.get("company_industry")}
Company size:     {lead_data.get("company_size")}
Revenue:          {lead_data.get("company_revenue")}
Location:         {lead_data.get("location")}

Return ONLY valid JSON with this exact structure (all scores 0-100 integers):
{{
  "bant": {{
    "budget": 0,
    "authority": 0,
    "need": 0,
    "timeline": 0,
    "notes": {{
      "budget": "one sentence",
      "authority": "one sentence",
      "need": "one sentence",
      "timeline": "one sentence"
    }}
  }},
  "meddic": {{
    "metrics": 0,
    "economic_buyer": 0,
    "decision_criteria": 0,
    "decision_process": 0,
    "identify_pain": 0,
    "champion": 0,
    "notes": {{
      "metrics": "one sentence",
      "economic_buyer": "one sentence",
      "decision_criteria": "one sentence",
      "decision_process": "one sentence",
      "identify_pain": "one sentence",
      "champion": "one sentence"
    }}
  }},
  "reasoning": "2-3 sentence summary for a sales rep skimming a lead list"
}}

Scoring rules:
- authority / economic_buyer: high (75+) ONLY if title matches ICP decision_maker_titles
- need / identify_pain: high if company likely faces ICP pain points given industry + size
- budget: reflects whether company size/revenue suggests affordability
- timeline / decision_process / decision_criteria / champion / metrics: default 45-55
  unless a strong signal is present in the data above
"""
        try:
            result = await GrokService._call_llm(prompt)
            bant = result.get("bant", {}) or {}
            meddic = result.get("meddic", {}) or {}

            return {
                "bant_budget_score": bant.get("budget"),
                "bant_authority_score": bant.get("authority"),
                "bant_need_score": bant.get("need"),
                "bant_timeline_score": bant.get("timeline"),
                "bant_notes": bant.get("notes", {}),
                "meddic_metrics_score": meddic.get("metrics"),
                "meddic_economic_buyer_score": meddic.get("economic_buyer"),
                "meddic_decision_criteria_score": meddic.get("decision_criteria"),
                "meddic_decision_process_score": meddic.get("decision_process"),
                "meddic_identify_pain_score": meddic.get("identify_pain"),
                "meddic_champion_score": meddic.get("champion"),
                "meddic_notes": meddic.get("notes", {}),
                "reasoning": result.get("reasoning", ""),
                "full_response": result,
            }

        except httpx.HTTPStatusError as exc:
            logger.error("Groq HTTP %s during scoring: %s", exc.response.status_code, exc.response.text)
            raise ValueError(f"Groq API Error: {exc.response.text}")

        except Exception as exc:
            logger.exception("BANT/MEDDIC scoring failed")
            raise ValueError(str(exc))

    # ──────────────────────────────────────────────────────────────
    # Outreach email generation
    # ──────────────────────────────────────────────────────────────

    @staticmethod
    async def generate_outreach_email(
        lead_data: Dict[str, Any],
        icp_data: Dict[str, Any],
        sender_name: str,
        tone: str = "friendly",
    ) -> Dict[str, str]:
        """
        Draft a personalised outreach email for a qualified lead.
        tone: "professional" | "friendly" | "direct"
        Returns {"subject": "...", "body": "..."}
        """
        pain_points_str = ", ".join(icp_data.get("pain_points", [])[:3])
        prompt = f"""
You are an expert B2B sales copywriter. Write a short, personalised cold outreach email.

SELLER INFO
  Sender name:    {sender_name}
  Product solves: {pain_points_str}

PROSPECT
  Name:     {lead_data.get("name")}
  Title:    {lead_data.get("title")}
  Company:  {lead_data.get("company")}
  Industry: {lead_data.get("company_industry")}
  Size:     {lead_data.get("company_size")} employees
  Score:    {lead_data.get("score")}/100 ICP fit

TONE: {tone}

Rules:
- Subject line: max 10 words, no clickbait
- Body: 3-4 short paragraphs, mention the prospect's company by name
- Reference one specific pain point relevant to their industry/size
- End with a soft CTA for a 15-minute call
- Do NOT use placeholder text like [INSERT] — write the real thing
- Return ONLY valid JSON: {{"subject": "...", "body": "..."}}
"""
        try:
            result = await GrokService._call_llm(prompt)
            return {
                "subject": result.get("subject", "Quick question for you"),
                "body": result.get("body", ""),
            }

        except Exception as exc:
            logger.exception("Outreach email generation failed")
            raise ValueError(str(exc))

    # ──────────────────────────────────────────────────────────────
    # Fallback
    # ──────────────────────────────────────────────────────────────

    @staticmethod
    def _fallback_icp(
        product_description: str,
        target_market_description: str,
        goals: str,
    ) -> Dict[str, Any]:
        target = target_market_description or "B2B revenue teams"
        goal_text = goals or "faster sales execution"
        return {
            "target_industries": ["B2B SaaS", "Technology Services", "Revenue Operations"],
            "company_size_range": "20-500 employees",
            "target_revenues": "$1M-$50M",
            "decision_maker_titles": [
                "VP of Sales",
                "Head of Revenue Operations",
                "Chief Revenue Officer",
                "Founder",
                "Sales Operations Manager",
            ],
            "pain_points": [
                "Fragmented prospect research",
                "Slow discovery-to-proposal handoff",
                "Inconsistent follow-up",
                "Low visibility into buying context",
                "Manual sales administration",
            ],
            "key_characteristics": [
                target,
                "Active outbound sales motion",
                "Multiple sales tools in use",
                "Need for repeatable sales process",
                "Clear ownership of revenue targets",
            ],
            "icp_summary": [
                target,
                f"Clear pain around {goal_text.lower()}",
                "Sales, RevOps, founder, or GTM leadership buyer",
                "Teams that need faster and more consistent follow-up",
                "Companies where contextual proposal quality affects conversion",
            ],
            "analysis": (
                "Generated locally because GROK_API_KEY is not configured. "
                f"The ICP is based on the submitted product context: {product_description}"
            ),
            "full_response": {"source": "local_fallback"},
        }