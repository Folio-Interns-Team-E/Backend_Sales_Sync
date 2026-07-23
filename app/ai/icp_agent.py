# app/ai/icp_agent.py

import json
import logging
import httpx
from app.config import settings

logger = logging.getLogger(__name__)


class ICPAgent:
    """
    Dedicated agent responsible for taking raw user descriptions of their target market
    and refining them into a highly structured, professional B2B Ideal Customer Profile (ICP).
    """

    BASE_URL = "https://api.groq.com/openai/v1"
    MODEL = "llama-3.3-70b-versatile"

    async def refine_icp(self, raw_input: str) -> str:
        """
        Takes raw user input and structures it into a comprehensive, professional B2B ICP markdown format.
        """
        system_prompt = """
            You are an expert B2B Go-To-Market (GTM) and Sales Strategy Consultant.

            Your task is to transform a user's raw, unstructured description of an Ideal Customer Profile (ICP) into a complete, structured, and professional ICP.

            INSTRUCTIONS:
            - Do NOT use markdown syntax (such as #, ##, **, or `) in your final output. 
            - Output pure, raw text using the exact indentation and key structure defined below.
            - Infer missing information where reasonable using industry best practices.
            - Keep the output concise, structured, and easy for both humans and AI agents to consume.
            - Do NOT write long paragraphs.
            - Use bullet points and the YAML-like outline structure shown below.
            - If information is unknown, infer sensible defaults instead of leaving sections empty.
            - Do not include explanations, intro text, or conversational lines.
            - Start directly with the first key (Firmographics:).

            OUTPUT FORMAT SCHEMA (DO NOT USE MARKDOWN):

            Firmographics:
                Industries:
                - 
                Company_Size:
                Employees:
                    Min: 
                    Max: 
                Revenue:
                    Min: 
                    Max: 
                Geography:
                Countries:
                - 
                States:
                - 
                Cities:
                - 

            Buyer_Personas:
                - Title: 
                Department: 
                Seniority: 
                Decision_Maker: true/false

            Pain_Points:
                - 
                - 

            Business_Goals:
                - 
                - 

            Buying_Triggers:
                - 
                - 

            Value_Proposition:
                - 
                - 

            Tech_Stack:
                - 
                - 

            Disqualifiers:
                - 
                - 

            Keywords:
                - 
                - 

            Notes:
                - 


            EXAMPLE RUN:

            User Input:
            "We sell AI automation to healthcare companies in Florida."

            Expected Output:

            Firmographics:
                Industries:
                - Healthcare
                - Hospitals
                - Medical Clinics
                - Healthcare Networks
                Company_Size:
                Employees:
                    Min: 50
                    Max: 1000
                Revenue:
                    Min: "$10M"
                    Max: "$500M"
                Geography:
                Countries:
                - United States
                States:
                - Florida
                Cities:
                - Miami
                - Orlando
                - Tampa
                - Jacksonville

            Buyer_Personas:
                - Title: Chief Operating Officer
                Department: Operations
                Seniority: Executive
                Decision_Maker: true
                - Title: Director of IT
                Department: Information Technology
                Seniority: Director
                Decision_Maker: true
                - Title: Practice Manager
                Department: Administration
                Seniority: Manager
                Decision_Maker: false

            Pain_Points:
                - High administrative workload
                - Manual patient scheduling
                - Inefficient documentation
                - Staffing shortages
                - Legacy systems

            Business_Goals:
                - Reduce operational costs
                - Improve patient experience
                - Automate repetitive workflows
                - Increase staff productivity

            Buying_Triggers:
                - Digital transformation initiatives
                - Rapid business growth
                - Hiring challenges
                - Compliance modernization

            Value_Proposition:
                - AI workflow automation
                - Reduced manual effort
                - Faster response times
                - Lower operating costs

            Tech_Stack:
                - Salesforce
                - Microsoft 365
                - Epic
                - Cerner

            Disqualifiers:
                - Solo practices
                - Companies with fewer than 20 employees
                - Organizations without digital systems

            Keywords:
                - AI Automation
                - Healthcare AI
                - Workflow Automation
                - HIPAA
                - Operational Efficiency

            Notes:
                - Prioritize organizations investing in digital transformation.


            Always follow this raw structure regardless of the user's input. Do not wrap the output in a markdown code block (```).

            """

        payload = {
            "model": self.MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": raw_input}
            ],
            "temperature": 0.4,
            "max_tokens": 1000
        }

        try:
            async with httpx.AsyncClient(timeout=60) as client:
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
                refined_icp = data["choices"][0]["message"]["content"].strip()
                return refined_icp

        except Exception as e:
            logger.error(f"ICPAgent failed to refine ICP: {e}", exc_info=True)
            # Fallback to the raw input if LLM call fails
            return raw_input