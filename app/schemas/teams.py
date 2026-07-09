from pydantic import BaseModel, EmailStr
from uuid import UUID
from datetime import datetime
from app.models.team_member import MemberRole


class TeamCreate(BaseModel):
    name: str


class JoinTeamRequest(BaseModel):
    invite_code: str


class InviteRequest(BaseModel):
    email: EmailStr


class UpdateRoleRequest(BaseModel):
    role: MemberRole


class MemberResponse(BaseModel):
    id: UUID
    full_name: str
    email: EmailStr
    role: MemberRole

    class Config:
        from_attributes = True


class TeamResponse(BaseModel):
    id: UUID
    name: str
    invite_code: str
    created_at: datetime
    members: list[MemberResponse] = []

    class Config:
        from_attributes = True


class UserTeamResponse(BaseModel):
    id: UUID
    name: str
    invite_code: str
    created_at: datetime
    role: MemberRole

    class Config:
        from_attributes = True