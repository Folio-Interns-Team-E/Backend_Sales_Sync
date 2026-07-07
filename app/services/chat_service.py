import logging
import traceback
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.config import settings
from app.models.team import Team
from app.models.team_member import TeamMember


logger = logging.getLogger(__name__)


class ChatService:
    BASE_URL = "https://api.groq.com/openai/v1"
    MODEL = "llama-3.3-70b-versatile"

    def __init__(self, db: AsyncSession):
        self.db = db


    async def _get_user_team(self, user_id: UUID) -> Team:
        result = await self.db.execute(
            select(TeamMember)
            .where(TeamMember.user_id == user_id)
        )

        membership = result.scalar_one_or_none()

        if not membership:
            raise ValueError("User has no team")

        result = await self.db.execute(
            select(Team)
            .where(Team.id == membership.team_id)
        )

        team = result.scalar_one_or_none()

        if not team:
            raise ValueError("Team not found")

        return team
    
    async def update_icp(self, user_id: UUID, new_icp: str):
        team = await self._get_user_team(user_id)

        if not team:
            raise ValueError("Team not found")

        team.icp = new_icp

        await self.db.commit()
        await self.db.refresh(team)

        return team.icp


    async def _get_icp_context(self, user_id: UUID) -> str:
        try:
            team = await self._get_user_team(user_id)

            if not team.icp:
                return "No ICP information available."

            return team.icp

        except Exception as e:
            print("ICP CONTEXT ERROR:")
            print(repr(e))
            traceback.print_exc()
            raise


    async def send_message(self, user_id: UUID, message: str) -> str:

        try:
            print("CHAT REQUEST")
            print("User:", user_id)
            print("Message:", message)


            if not settings.grok_api_key:
                return (
                    "AI is not configured. "
                    "Please add GROK_API_KEY."
                )


            icp = await self._get_icp_context(user_id)


            print("ICP:")
            print(icp)


            system_prompt = f"""
You are an expert B2B sales assistant.

You manage and use the company's Ideal Customer Profile (ICP).

You can:
- Answer questions using the ICP
- Analyze prospects against the ICP
- Suggest improvements to the ICP
- Update the ICP when the user explicitly requests changes

Current ICP:

{icp}

If the user wants to update the ICP, return your response in this format:

UPDATE_ICP:
<new ICP text>

Otherwise answer normally.
"""


            payload = {
                "model": self.MODEL,
                "messages": [
                    {
                        "role": "system",
                        "content": system_prompt
                    },
                    {
                        "role": "user",
                        "content": message
                    }
                ],
                "temperature": 0.5,
                "max_tokens": 1024
            }


            async with httpx.AsyncClient(timeout=60) as client:

                response = await client.post(
                    f"{self.BASE_URL}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {settings.grok_api_key}",
                        "Content-Type": "application/json"
                    },
                    json=payload
                )


                print("Groq status:", response.status_code)
                print("Groq response:", response.text[:500])


                response.raise_for_status()


                data = response.json()


                ai_response = data["choices"][0]["message"]["content"]


                if ai_response.startswith("UPDATE_ICP:"):

                    new_icp = ai_response.replace(
                        "UPDATE_ICP:",
                        ""
                    ).strip()

                    await self.update_icp(
                        user_id,
                        new_icp
                    )

                    return (
                        "Your ICP has been updated successfully.\n\n"
                        f"New ICP:\n{new_icp}"
                    )


                return ai_response


        except Exception as e:

            print("\n========== CHAT ERROR ==========")
            print(repr(e))
            traceback.print_exc()
            print("================================\n")

            raise