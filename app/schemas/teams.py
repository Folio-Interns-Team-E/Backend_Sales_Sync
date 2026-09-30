from pydantic import BaseModel, ConfigDict, EmailStr, Field
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


class TeamUpdate(BaseModel):
    name: str | None = None


class MemberResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    full_name: str
    email: EmailStr
    role: MemberRole

class TeamResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    invite_code: str | None = None
    created_at: datetime
    members: list[MemberResponse] = Field(default_factory=list)


class UserTeamResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    invite_code: str | None = None
    created_at: datetime
    role: MemberRole
