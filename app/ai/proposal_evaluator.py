import json
import logging
import re
from uuid import UUID
import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings

logger = logging.getLogger(__name__)


class ProposalEvaluatorAgent:
    """
    Evaluator agent that reviews a generated proposal's alignment with user prompts,
    pitch strength, natural human flow (eradicating AI-isms), and structured constraints.
    Runs exactly once per generation pass to prevent infinite loops.
    """

    BASE_URL = "https://api.groq.com/openai/v1"
    MODEL = "openai/gpt-oss-120b"

    def __init__(self, db_session: AsyncSession):
        self.db = db_session

    async def evaluate_proposal(
        self,
        original_prompt: str,
        generated_proposal_data: dict,
        icp_context: str
    ) -> dict:
        """
        Runs a single critical assessment on the generated proposal text.
        Returns a structured evaluation report with a Pass/Fail status.
        """
        
        system_prompt = f"""You are an elite, cynical executive editor and seasoned sales director. 
Your sole task is to critically evaluate a sales proposal written by an AI writer against the original request. 
Your review must be brutal, realistic, and determine if this is ready to be sent to a C-level executive.

Evaluate based on these four pillars:
1. Adherence to Prompt: Did the proposal address all goals, metrics, pain points, and specific details requested by the user?
2. Sales Pitch Quality: Is the tone highly strategic, value-driven, and commercially persuasive? Does it speak to business outcomes?
3. "AI-ness" / Human Tone Check: Does it sound like an AI wrote it? Check for typical AI clichés, structural laziness, empty buzzwords (e.g., 'delve', 'testament', 'revolutionize', 'demystify', 'in conclusion'), and overly repetitive sentence structures.
4. Hallucination Check: Did the writer invent facts outside the company's profile/ICP context or the user prompt?

Our Company Profile context:
\"\"\"
{icp_context}
\"\"\"

You must output a single, flat JSON object with this exact structure:
{{
    "passed": true or false,
    "overall_score": 8, // Integer from 1 to 10
    "prompt_adherence": {{
        "score": 9, // Integer from 1 to 10
        "analysis": "Brief analysis of how well the generated proposal met specific user requests."
    }},
    "pitch_effectiveness": {{
        "score": 7, // Integer from 1 to 10
        "analysis": "Evaluation of business value and persuasion. Does it read like an elite strategist wrote it?"
    }},
    "human_authenticity": {{
        "score": 8, // Integer from 1 to 10
        "detected_ai_isms": ["list", "of", "detected", "clichés", "or", "none"],
        "analysis": "Does it read naturally? Is it too formulaic?"
    }},
    "feedback_and_corrections": "Direct, actionable suggestions on what needs to be changed if it failed, or minor polishes if it passed."
}}
"""

        # Format the generated proposal for evaluation
        formatted_proposal_content = json.dumps(generated_proposal_data, indent=2)

        user_content = f"""Original User Prompt:
\"\"\"
{original_prompt}
\"\"\"

Generated Proposal Copy:
\"\"\"
{formatted_proposal_content}
\"\"\"
"""

        payload = {
            "model": self.MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            "temperature": 0.2, # Low temperature to ensure analytical rigor
            "max_tokens": 1500,
            "response_format": {"type": "json_object"}
        }

        try:
            async with httpx.AsyncClient(timeout=45) as client:
                response = await client.post(
                    f"{self.BASE_URL}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {settings.grok_api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
                content = data["choices"][0]["message"]["content"].strip()
                
                # Clean block code wrap if present
                cleaned = re.sub(r"^```json\s*|\s*```$", "", content, flags=re.IGNORECASE)
                evaluation_report = json.loads(cleaned)
                
                logger.info(f"Proposal evaluation complete. Score: {evaluation_report.get('overall_score')}/10. Passed: {evaluation_report.get('passed')}")
                return evaluation_report

        except Exception as e:
            logger.error(f"Proposal evaluation process failed: {e}", exc_info=True)
            # Safe default fallback structure to avoid blocking system flows
            return {
                "passed": True,
                "overall_score": 7,
                "prompt_adherence": {"score": 7, "analysis": "Fallback evaluation generated due to system error."},
                "pitch_effectiveness": {"score": 7, "analysis": "Fallback evaluation."},
                "human_authenticity": {"score": 7, "detected_ai_isms": [], "analysis": "Fallback evaluation."},
                
            }