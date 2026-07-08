from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from app.database import get_db
from app.schemas.teams import TeamCreate, TeamResponse, InviteRequest, UpdateRoleRequest, JoinTeamRequest, UserTeamResponse
from app.schemas.common import ApiResponse
from app.services.teams_service import create_team, get_team, invite_member, update_member_role, remove_member, join_existing_team, get_team_invite_code, get_user_teams
from app.middleware.auth_middleware import get_current_user, require_role
from app.models.team_member import MemberRole

router = APIRouter(prefix="/teams", tags=["teams"])

#list user's teams
@router.get("/", response_model=ApiResponse[list[UserTeamResponse]])
async def list_user_teams(
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    teams = await get_user_teams(current_user, db)
    return ApiResponse(success=True, message="Teams fetched successfully", data=teams)

#create new team
@router.post("/", response_model=ApiResponse[TeamResponse], status_code=201)
async def create_new_team(
    payload: TeamCreate,
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    team = await create_team(payload, current_user, db)
    return ApiResponse(success=True, message="Team created successfully", data=team)

#get team details
@router.get("/{team_id}", response_model=ApiResponse[TeamResponse])
async def get_team_details(
    team_id: UUID,
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db) 
):
    team = await get_team(team_id, current_user, db)
    return ApiResponse(success=True, message="Team fetched successfully", data=team)

#team invitation
@router.post("/invite", response_model=ApiResponse[TeamResponse])
async def invite_user(
    payload: InviteRequest,
    current_user = Depends(require_role(MemberRole.admin, MemberRole.manager)),
    db: AsyncSession = Depends(get_db)
):
    team = await invite_member(payload, current_user, db)
    return ApiResponse(success=True, message="Team member added successfully", data=team)

#change member role
@router.put("/{team_id}/members/{user_id}/role", response_model=ApiResponse[TeamResponse])
async def change_member_role(
    team_id: UUID,
    user_id: UUID,
    payload: UpdateRoleRequest,
    current_user=Depends(require_role(MemberRole.admin)),
    db: AsyncSession = Depends(get_db)
):
    team = await update_member_role(team_id, user_id, payload, current_user, db)
    return ApiResponse(success=True, message="Member role updated successfully", data=team)

#delete member
@router.delete("/{team_id}/members/{user_id}", response_model=ApiResponse[TeamResponse])
async def remove_team_member(
    team_id: UUID,
    user_id: UUID,
    current_user=Depends(require_role(MemberRole.admin, MemberRole.manager)),
    db: AsyncSession = Depends(get_db)
):
    team = await remove_member(team_id, user_id, current_user, db)
    return ApiResponse(success=True, message="Member removed successfully", data=team)

#join existing team
@router.post("/join", response_model=ApiResponse[TeamResponse])
async def join_team(
    payload: JoinTeamRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    team = await join_existing_team(payload, current_user, db)
    return ApiResponse(success=True, message=f"Successfully joined {team.name}", data=team)

#get invite code
@router.get("/{team_id}/invite-code", response_model=ApiResponse[dict])
async def get_invite_code(
    team_id: UUID,
    current_user=Depends(require_role(MemberRole.admin)),
    db: AsyncSession = Depends(get_db)
):
    invite_code = await get_team_invite_code(team_id, current_user, db)
    return ApiResponse(success=True, message="Invite code fetched successfully", data=invite_code)
