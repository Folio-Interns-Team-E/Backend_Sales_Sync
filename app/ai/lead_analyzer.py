import json
import re
import logging
import httpx
from typing import Dict, Any

logger = logging.getLogger(__name__)

class LeadAnalyzerAgent:
    """
    Dedicated agent responsible for evaluating target lead profiles 
    against the company's Ideal Customer Profile (ICP).
    """
    def __init__(self, model: str, base_url: str, api_key: str):
        self.model = model
        self.base_url = base_url
        self.api_key = api_key

    async def analyze_fit(self, lead_info: Dict[str, Any], icp: str) -> Dict[str, Any]:
        """Compares a fetched lead profile against the ICP to yield an objective score."""
        prompt = f"""You are an expert sales operations analyst. Evaluate the target lead data against the company's Ideal Customer Profile (ICP).

Company ICP:
\"\"\"
{icp}
\"\"\"

Target Lead Data:
\"\"\"
{json.dumps(lead_info, indent=2)}
\"\"\"

Provide an objective analysis. Return ONLY a valid JSON object matching this schema:
{{
    "score": 85,
    "justification": "A clear, concise 2-sentence explanation of why they received this score based on the ICP context."
}}
"""
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "max_tokens": 300,
            "response_format": {"type": "json_object"}
        }

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"].strip()
            
            cleaned = re.sub(r"^```json\s*|\s*```$", "", content, flags=re.IGNORECASE)
            parsed = json.loads(cleaned)
            
            logger.info(f"Raw LLM Qualification Output: {parsed}")
            
            raw_score = parsed.get("score") or parsed.get("fit_score") or 0
            try:
                score_val = int(raw_score)
            except (ValueError, TypeError):
                score_val = 0
                
            return {
                "score": score_val,
                "justification": parsed.get("justification", "No evaluation details provided.")
            }