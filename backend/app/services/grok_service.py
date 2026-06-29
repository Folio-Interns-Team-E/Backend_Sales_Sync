# File: backend/app/services/grok_service.py
# Copy this entire file as-is

import logging
import json
from typing import Optional, Dict, Any
import httpx
from app.config import settings

logger = logging.getLogger(__name__)


class GrokService:
    """Service to call Grok API for ICP generation"""
    
    BASE_URL = "https://api.groq.com/openai/v1"
    MODEL = "llama-3.3-70b-versatile"
    
    @staticmethod
    async def generate_icp(
        product_description: str,
        target_market_description: str,
        product_name: Optional[str] = None,
        company_description: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Call Grok API to analyze product description and generate ICP
        
        Args:
            product_description: What the product does
            target_market_description: Who the ideal customer is
            product_name: Name of product (optional)
            company_description: Company info (optional)
        
        Returns:
            Dict with:
            - target_industries: List of industries
            - company_size_range: Employee count range
            - target_revenues: Revenue range
            - decision_maker_titles: Job titles of decision makers
            - pain_points: List of pain points the product solves
            - key_characteristics: Other important characteristics
            - analysis: Full text analysis
        """
        
        # Build prompt for Grok
        prompt = f"""You are an expert in identifying Ideal Customer Profiles (ICPs) for B2B SaaS products.

Analyze the following product and target market description, and provide a detailed ICP analysis.

PRODUCT INFORMATION:
{f"Product Name: {product_name}" if product_name else ""}
Product Description: {product_description}
{f"Company Description: {company_description}" if company_description else ""}

TARGET MARKET DESCRIPTION:
{target_market_description}

Please provide your analysis in the following JSON format:
{{
    "target_industries": ["Industry1", "Industry2", "Industry3"],
    "company_size_range": "X-Y employees" or "X+ employees",
    "target_revenues": "Revenue range e.g. $1M-$10M",
    "decision_maker_titles": ["Title1", "Title2", "Title3"],
    "pain_points": ["Pain point 1", "Pain point 2", "Pain point 3"],
    "key_characteristics": ["Characteristic 1", "Characteristic 2"],
    "analysis": "Detailed paragraph explaining the ICP analysis"
}}

IMPORTANT: Return ONLY valid JSON, no additional text."""

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{GrokService.BASE_URL}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {settings.grok_api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": GrokService.MODEL,
                        "messages": [
                            {
                                "role": "user",
                                "content": prompt
                            }
                        ],
                        "temperature": 0.7,
                        "max_tokens": 1500
                    },
                    timeout=30.0
                )
                
                response.raise_for_status()
                result = response.json()
                
                # Extract content from response
                if "choices" not in result or not result["choices"]:
                    raise ValueError("Invalid Grok response: no choices")
                
                content = result["choices"][0]["message"]["content"]
                
                # Parse JSON from response
                try:
                    icp_data = json.loads(content)
                except json.JSONDecodeError:
                    # Try to extract JSON if Grok added extra text
                    import re
                    json_match = re.search(r'\{.*\}', content, re.DOTALL)
                    if json_match:
                        icp_data = json.loads(json_match.group())
                    else:
                        logger.error(f"Could not parse Grok response: {content}")
                        raise ValueError(f"Could not parse JSON from Grok response: {content}")
                
                logger.info(f"Successfully generated ICP via Grok")
                
                return {
                    "target_industries": icp_data.get("target_industries", []),
                    "company_size_range": icp_data.get("company_size_range"),
                    "target_revenues": icp_data.get("target_revenues"),
                    "decision_maker_titles": icp_data.get("decision_maker_titles", []),
                    "pain_points": icp_data.get("pain_points", []),
                    "key_characteristics": icp_data.get("key_characteristics", []),
                    "analysis": icp_data.get("analysis", ""),
                    "full_response": icp_data  # Store full response
                }
        
        except httpx.HTTPError as e:
            logger.error(f"Grok API error: {str(e)}")
            raise ValueError(f"Failed to generate ICP: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error in generate_icp: {str(e)}")
            raise ValueError(f"Error generating ICP: {str(e)}")


    @staticmethod
    async def refine_icp(
        current_icp_data: Dict[str, Any],
        refinement_request: str
    ) -> Dict[str, Any]:
        """
        Refine existing ICP based on user feedback
        
        Args:
            current_icp_data: Current ICP data
            refinement_request: What the user wants to refine
        
        Returns:
            Updated ICP data
        """
        
        prompt = f"""You are an expert in refining Ideal Customer Profiles (ICPs).

Current ICP Analysis:
Industries: {current_icp_data.get('target_industries', [])}
Company Size: {current_icp_data.get('company_size_range')}
Decision Makers: {current_icp_data.get('decision_maker_titles', [])}
Pain Points: {current_icp_data.get('pain_points', [])}

User Refinement Request: {refinement_request}

Please provide an updated ICP analysis incorporating this feedback.

Return ONLY valid JSON in this format:
{{
    "target_industries": [...],
    "company_size_range": "...",
    "target_revenues": "...",
    "decision_maker_titles": [...],
    "pain_points": [...],
    "key_characteristics": [...],
    "analysis": "Updated analysis..."
}}"""

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{GrokService.BASE_URL}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {settings.grok_api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": GrokService.MODEL,
                        "messages": [
                            {
                                "role": "user",
                                "content": prompt
                            }
                        ],
                        "temperature": 0.7,
                        "max_tokens": 1500
                    },
                    timeout=30.0
                )
                
                response.raise_for_status()
                result = response.json()
                
                content = result["choices"][0]["message"]["content"]
                
                try:
                    icp_data = json.loads(content)
                except json.JSONDecodeError:
                    import re
                    json_match = re.search(r'\{.*\}', content, re.DOTALL)
                    if json_match:
                        icp_data = json.loads(json_match.group())
                    else:
                        raise ValueError(f"Could not parse JSON from Grok response")
                
                logger.info(f"Successfully refined ICP via Grok")
                
                return {
                    "target_industries": icp_data.get("target_industries", []),
                    "company_size_range": icp_data.get("company_size_range"),
                    "target_revenues": icp_data.get("target_revenues"),
                    "decision_maker_titles": icp_data.get("decision_maker_titles", []),
                    "pain_points": icp_data.get("pain_points", []),
                    "key_characteristics": icp_data.get("key_characteristics", []),
                    "analysis": icp_data.get("analysis", ""),
                    "full_response": icp_data
                }
        
        except Exception as e:
            logger.error(f"Error refining ICP: {str(e)}")
            raise ValueError(f"Failed to refine ICP: {str(e)}")