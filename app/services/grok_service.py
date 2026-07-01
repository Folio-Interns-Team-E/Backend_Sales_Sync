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
      - ICP generation / refinement  (existing)
      - BANT + MEDDIC lead scoring   (new)
      - Outreach email generation    (new)
    """

    BASE_URL = "https://api.groq.com/openai/v1"
    MODEL = "llama-3.3-70b-versatile"

    # ─────────────────────────────────────────────────────────────────
    # Private helper
    # ─────────────────────────────────────────────────────────────────

    @staticmethod
    async def _call_llm(prompt: str) -> Dict[str, Any]:
        """
        Fire a single-turn prompt at Groq and return the parsed JSON response.
        Raises ValueError on network error or malformed JSON.
        """
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{GrokService.BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.grok_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": GrokService.MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3,
                    "max_tokens": 2048,
                },
            )
            resp.raise_for_status()

        content = resp.json()["choices"][0]["message"]["content"].strip()

        # Strip markdown fences if present
        clean = re.sub(r"^```(?:json)?\s*", "", content)
        clean = re.sub(r"\s*```$", "", clean).strip()

        try:
            return json.loads(clean, strict=False)
        except json.JSONDecodeError as exc:
            logger.error("Groq returned non-JSON: %s", content[:500])
            raise ValueError(f"Groq response was not valid JSON: {exc}")

    # ─────────────────────────────────────────────────────────────────
    # ICP generation (existing)
    # ─────────────────────────────────────────────────────────────────

    @staticmethod
    async def generate_icp(
        product_description: str,
        target_market_description: str,
        goals: str,
        product_name: Optional[str] = None,
        company_description: Optional[str] = None,
    ) -> Dict[str, Any]:
        prompt = f"""
You are an expert B2B sales strategist. Generate a detailed Ideal Customer Profile (ICP)
based on the following information:

Product Name: {product_name or "Not specified"}
Product Description: {product_description}
Company Description: {company_description or "Not specified"}
Target Market: {target_market_description}
Sales Goals: {goals}

Return ONLY a JSON object with this exact structure (no explanation, no markdown):
{{
  "target_industries": ["industry1", "industry2", "industry3"],
  "company_size_range": "10-50",
  "target_revenues": "$1M-10M",
  "decision_maker_titles": ["Title1", "Title2", "Title3"],
  "pain_points": ["pain1", "pain2", "pain3"],
  "key_characteristics": ["characteristic1", "characteristic2"],
  "target_regions": ["North America", "Europe"],
  "icp_summary": [
    "B2B SaaS companies with 10-50 employees",
    "VP Sales or Revenue Operations decision-maker",
    "Pain around manual prospecting and slow follow-up",
    "Active outbound motion with budget for tooling"
  ],
  "analysis": "2-3 paragraph analysis of the ICP"
}}
"""
        try:
            result = await GrokService._call_llm(prompt)
            return {
                "target_industries":    result.get("target_industries", []),
                "company_size_range":   result.get("company_size_range"),
                "target_revenues":      result.get("target_revenues"),
                "decision_maker_titles": result.get("decision_maker_titles", []),
                "pain_points":          result.get("pain_points", []),
                "key_characteristics":  result.get("key_characteristics", []),
                "target_regions":       result.get("target_regions", []),
                "icp_summary":          result.get("icp_summary", []),
                "analysis":             result.get("analysis", ""),
                "full_response":        result,
            }
        except httpx.HTTPStatusError as exc:
            logger.error("Groq HTTP %s: %s", exc.response.status_code, exc.response.text)
            raise ValueError(f"Groq API Error: {exc.response.text}")
        except Exception as exc:
            logger.exception("ICP generation failed")
            raise ValueError(str(exc))

    @staticmethod
    async def refine_icp(
        existing_icp: Dict[str, Any],
        feedback: str,
        product_description: str,
    ) -> Dict[str, Any]:
        prompt = f"""
You are an expert B2B sales strategist. Refine the existing ICP based on user feedback.

Current ICP: {json.dumps(existing_icp, indent=2)}
Product Description: {product_description}
User Feedback / Refinement Request: {feedback}

Return ONLY a JSON object with the same structure as the input ICP. No markdown, no explanation.
"""
        try:
            icp_data = await GrokService._call_llm(prompt)
            return {
                "target_industries":    icp_data.get("target_industries", []),
                "company_size_range":   icp_data.get("company_size_range"),
                "target_revenues":      icp_data.get("target_revenues"),
                "decision_maker_titles": icp_data.get("decision_maker_titles", []),
                "pain_points":          icp_data.get("pain_points", []),
                "key_characteristics":  icp_data.get("key_characteristics", []),
                "target_regions":       icp_data.get("target_regions", []),
                "icp_summary":          icp_data.get("icp_summary", []),
                "analysis":             icp_data.get("analysis", ""),
                "full_response":        icp_data,
            }
        except httpx.HTTPStatusError as exc:
            logger.error("Groq HTTP %s: %s", exc.response.status_code, exc.response.text)
            raise ValueError(f"Groq API Error: {exc.response.text}")
        except Exception as exc:
            logger.exception("ICP refinement failed")
            raise ValueError(str(exc))

    # ─────────────────────────────────────────────────────────────────
    # BANT + MEDDIC lead scoring  (new)
    # ─────────────────────────────────────────────────────────────────

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
            bant   = result.get("bant", {}) or {}
            meddic = result.get("meddic", {}) or {}

            return {
                "bant_budget_score":             bant.get("budget"),
                "bant_authority_score":          bant.get("authority"),
                "bant_need_score":               bant.get("need"),
                "bant_timeline_score":           bant.get("timeline"),
                "bant_notes":                    bant.get("notes", {}),
                "meddic_metrics_score":          meddic.get("metrics"),
                "meddic_economic_buyer_score":   meddic.get("economic_buyer"),
                "meddic_decision_criteria_score": meddic.get("decision_criteria"),
                "meddic_decision_process_score": meddic.get("decision_process"),
                "meddic_identify_pain_score":    meddic.get("identify_pain"),
                "meddic_champion_score":         meddic.get("champion"),
                "meddic_notes":                  meddic.get("notes", {}),
                "reasoning":                     result.get("reasoning", ""),
                "full_response":                 result,
            }
        except httpx.HTTPStatusError as exc:
            logger.error("Groq HTTP %s during scoring: %s", exc.response.status_code, exc.response.text)
            raise ValueError(f"Groq API Error: {exc.response.text}")
        except Exception as exc:
            logger.exception("BANT/MEDDIC scoring failed")
            raise ValueError(str(exc))

    # ─────────────────────────────────────────────────────────────────
    # Outreach email generation  (new)
    # ─────────────────────────────────────────────────────────────────

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
                "body":    result.get("body", ""),
            }
        except Exception as exc:
            logger.exception("Outreach email generation failed")
            raise ValueError(str(exc))