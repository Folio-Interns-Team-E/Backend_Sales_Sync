# app/ai/email_agent.py

import json
import re
import logging
import httpx
from app.config import settings

logger = logging.getLogger(__name__)


class EmailAgent:
    """
    Dedicated agent responsible for generating highly customized sales outreach emails
    and critical, strict self-evaluations against the company ICP and strict parameters.
    """

    BASE_URL = "https://api.groq.com/openai/v1"
    MODEL = "openai/gpt-oss-120b"

    DRAFT_FORMAT = {
        "type": "json_schema",
        "json_schema": {
            "name": "outreach_email",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {"subject": {"type": "string"}, "body": {"type": "string"}},
                "required": ["subject", "body"],
                "additionalProperties": False,
            },
        },
    }

    @staticmethod
    def validate_email(email_content: object) -> list[str]:
        """Apply deterministic quality gates before an AI draft can be persisted."""
        if not isinstance(email_content, dict):
            return ["The provider did not return an email object."]
        subject = email_content.get("subject")
        body = email_content.get("body")
        if not isinstance(subject, str) or not subject.strip():
            return ["The subject is missing."]
        if not isinstance(body, str) or not body.strip():
            return ["The email body is missing."]

        problems = []
        if len(subject.split()) >= 5:
            problems.append("Keep the subject under five words.")
        if len(body.split()) > 100:
            problems.append("Keep the body under 100 words.")
        paragraphs = [part.strip() for part in body.split("\n\n") if part.strip()]
        if len(paragraphs) != 3:
            problems.append("Use exactly three paragraphs separated by blank lines.")
        forbidden = (
            "hope this email finds you well",
            "my name is",
            "i stumbled upon your profile",
        )
        if any(phrase in body.lower() for phrase in forbidden):
            problems.append("Remove generic cold-email clichés.")
        return problems

    def _extract_json(self, text: str) -> dict:
        """
        Helper method to extract and parse the first valid JSON object from raw LLM output,
        bypassing conversational prefixes, markdown wrappers, or trailing text.
        """
        match = re.search(r"(\{.*\})", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass
        
        cleaned = re.sub(r"^```json\s*|\s*```$", "", text, flags=re.IGNORECASE).strip()
        return json.loads(cleaned)

    async def generate_custom_email(
        self,
        lead_info: dict,
        icp: str,
        message: str,
        revision_feedback: str = ""
    ) -> dict:
        """Generates a highly customized outreach email draft based on lead data and ICP.

        If revision_feedback is provided, the prompt asks the model to rewrite the
        email addressing that feedback specifically.
        """
        revision_block = ""
        if revision_feedback:
            revision_block = f"""
                IMPORTANT — This is a revision. A prior draft was reviewed and rejected for the following reason(s):
                \"\"\"
                {revision_feedback}
                \"\"\"
                Rewrite the email from scratch, fixing these issues while still following all rules below.
            """

        prompt = f"""You are an elite, hyper-efficient B2B sales development representative. 
            Write a highly tailored, razor-sharp cold outreach email to the target lead below based on our company's Ideal Customer Profile (ICP).
            {revision_block}
            Company ICP Context:
            \"\"\"
            {icp}
            \"\"\"

            Target Lead Data:
            \"\"\"
            {json.dumps(lead_info, indent=2)}
            \"\"\"

            Strict Writing Rules:
            1. Brevity is King: Keep the entire email under 100 words. Cut all fluff.
            2. Format: The email must consist of exactly 3 single-sentence paragraphs. 
            - Separate paragraphs with exactly two newlines (\\n\\n).
            - DO NOT indent paragraphs. No leading spaces, tabs, or whitespace on any line. Every paragraph must start completely flat against the left margin.
            3. No Clichés: Never start with "Hope this email finds you well," "My name is," or "I stumbled upon your profile." Start directly with a relevant hook.
            4. Structure: 
            - Paragraph 1 (The Hook): A highly specific, personalized observation about their role, recent company news, or a current pain point.
            - Paragraph 2 (The Value): Connect our value proposition (from our ICP) directly to solving that specific challenge in one clear sentence.
            - Paragraph 3 (Low-Friction CTA): Ask a single open-ended, low-commitment question.

            Example of Perfect Formatting (Copy this structure exactly):
            {{
                "subject": "Acme's pipeline infrastructure",
                "body": "Saw your recent update on upgrading Acme's real-time data ingestion pipelines, Sarah.\\n\\nWe help high-growth platforms scale their event streaming without the typical database bottleneck or latency spikes.\\n\\nAre you open to exploring if this could optimize your processing speeds next week?"
            }}

            You must return a valid json object matching this exact schema:
            {{
                "subject": "Short, pattern-interrupting subject line (under 5 words, no clickbait)",
                "body": "The personalized body text of the email containing exactly 3 distinct paragraphs separated by \\n\\n."
            }}
            """

        payload = {
            "model": self.MODEL,
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": message or "Generate the email draft json object."} # Explicitly requesting "json" prevents API 400 errors
            ],
            "temperature": 0.3,
            "max_completion_tokens": 1024,
            "reasoning_effort": "low",
            "response_format": self.DRAFT_FORMAT,
        }

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{self.BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.grok_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            if response.is_error:
                try:
                    provider_error = response.json().get("error", {})
                    error_detail = {
                        "type": provider_error.get("type"),
                        "code": provider_error.get("code"),
                        "message": str(provider_error.get("message", ""))[:500],
                    }
                except (ValueError, AttributeError):
                    error_detail = {"type": "unparseable_provider_error"}
                logger.error("Groq email draft rejected: status=%s error=%s", response.status_code, error_detail)
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"].strip()
            
            result = self._extract_json(content)
            structural_problems = self.validate_email(result)
            if structural_problems and any(
                problem in {"The provider did not return an email object.", "The subject is missing.", "The email body is missing."}
                for problem in structural_problems
            ):
                raise ValueError("Invalid email draft returned by AI provider")
            return result

    async def evaluate_email(self, email_content: dict, lead_info: dict, icp: str, message: str) -> dict:
        """Evaluation agent: reviews a drafted email against the ICP and the copywriter's
        own formatting/content rules, and decides whether it needs a revision.

        Returns: {"approved": bool, "feedback": str}
        On any failure (network, malformed JSON), fails open and approves the draft
        as-is so a transient evaluator issue never blocks the whole DRAFT_EMAIL flow.
        """
        subject = email_content.get("subject", "")
        body = email_content.get("body", "")

        prompt = f"""You are a strict quality reviewer for B2B cold outreach emails. Evaluate the DRAFT below
            against the Ideal Customer Profile (ICP) and the required rules. Be critical — vague, generic,
            or rule-breaking drafts should be rejected.

            Company ICP Context:
            \"\"\"
            {icp}
            \"\"\"

            Target Lead Data:
            \"\"\"
            {json.dumps(lead_info, indent=2)}
            \"\"\"

            Draft Subject:
            \"\"\"
            {subject}
            \"\"\"

            Draft Body:
            \"\"\"
            {body}
            \"\"\"

            Check the draft against ALL of these criteria:
            1. It should adhere to ICP
            2. Users recommendations should be followed in the email.
            3. No clichés such as "Hope this email finds you well", "My name is", "I stumbled upon your profile".
            4. Paragraph 1 is a specific, personalized hook tied to the lead's real data (not generic).
            5. Paragraph 2 clearly ties the ICP's value proposition to the lead's specific situation.
            6. Paragraph 3 is a single low-commitment, open-ended question.
            7. Subject line is under 5 words and not clickbait-y.

            You must return a valid json object matching this exact schema:
            {{
                "approved": true or false,
                "feedback": "If not approved, a short, specific, actionable list of what to fix. Empty string if approved."
            }}
            """

        payload = {
            "model": self.MODEL,
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": message or "Evaluate the email draft and return a json evaluation."} # Explicitly requesting "json" prevents API 400 errors
            ],
            "temperature": 0.0,
            "max_completion_tokens": 1024,
            "reasoning_effort": "low",
            "response_format": {"type": "json_object"}
        }

        try:
            async with httpx.AsyncClient(timeout=30) as client:
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
                
                result = self._extract_json(content)
                structural_problems = self.validate_email(email_content)
                feedback = str(result.get("feedback", "")).strip()
                if structural_problems:
                    feedback = " ".join(structural_problems + ([feedback] if feedback else []))
                return {
                    "approved": bool(result.get("approved", True)) and not structural_problems,
                    "feedback": feedback,
                }
        except (httpx.HTTPError, KeyError, json.JSONDecodeError) as e:
            structural_problems = self.validate_email(email_content)
            logger.error("Email evaluation failed; applying deterministic quality gates: %s", e, exc_info=True)
            return {
                "approved": not structural_problems,
                "feedback": " ".join(structural_problems),
            }
