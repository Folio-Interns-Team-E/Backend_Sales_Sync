from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from fastapi import HTTPException, status
from uuid import UUID
from app.models.user import User, UserRole
from app.models.team import Team
from app.models.team_member import TeamMember
from app.schemas.teams import (
    TeamCreate, InviteRequest,
    UpdateRoleRequest, JoinTeamRequest,
    TeamResponse, MemberResponse,
    UserTeamResponse
)


def _build_team_response(team: Team) -> TeamResponse:
    members = []
    for tm in team.members:
        members.append(MemberResponse(
            id=tm.user.id,
            full_name=tm.user.full_name,
            email=tm.user.email,
            role=tm.role
        ))
    return TeamResponse(
        id=team.id,
        name=team.name,
        invite_code=team.invite_code,
        created_at=team.created_at,
        members=members
    )


async def _get_team_with_members(team_id: UUID, db: AsyncSession) -> Team | None:
    result = await db.execute(
        select(Team)
        .options(selectinload(Team.members).selectinload(TeamMember.user))
        .where(Team.id == team_id)
    )
    return result.scalar_one_or_none()


async def _get_membership(user_id: UUID, team_id: UUID, db: AsyncSession) -> TeamMember | None:
    result = await db.execute(
        select(TeamMember).where(
            TeamMember.user_id == user_id,
            TeamMember.team_id == team_id
        )
    )
    return result.scalar_one_or_none()


async def _get_user_any_membership(user_id: UUID, db: AsyncSession) -> TeamMember | None:
    result = await db.execute(
        select(TeamMember).where(TeamMember.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def create_team(
    payload: TeamCreate,
    current_user: User,
    db: AsyncSession
):
    if await _get_user_any_membership(current_user.id, db):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You are already part of a team"
        )

    new_team = Team(name=payload.name)
    db.add(new_team)
    await db.flush()

    membership = TeamMember(
        user_id=current_user.id,
        team_id=new_team.id,
        role=UserRole.admin
    )
    db.add(membership)
    await db.commit()

    team = await _get_team_with_members(new_team.id, db)
    return _build_team_response(team)


async def get_team(
        team_id: UUID,
        current_user: User,
        db: AsyncSession
):
    membership = await _get_membership(current_user.id, team_id, db)
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this team"
        )

    team = await _get_team_with_members(team_id, db)
    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team not found"
        )
    return _build_team_response(team)


async def invite_member(
        payload: InviteRequest,
        current_user: User,
        db: AsyncSession
):
    inviter_membership = await _get_user_any_membership(current_user.id, db)
    if not inviter_membership:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You are not part of a team"
        )

    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User must register before they can be added to a team"
        )

    if await _get_user_any_membership(user.id, db):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User is already part of a team"
        )

    membership = TeamMember(
        user_id=user.id,
        team_id=inviter_membership.team_id,
        role=UserRole.rep
    )
    db.add(membership)
    await db.commit()

    team = await _get_team_with_members(inviter_membership.team_id, db)
    return _build_team_response(team)


async def join_existing_team(
    payload: JoinTeamRequest,
    current_user: User,
    db: AsyncSession
):
    if await _get_user_any_membership(current_user.id, db):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You are already part of a team"
        )

    result = await db.execute(
        select(Team).where(Team.invite_code == payload.invite_code)
    )
    team = result.scalar_one_or_none()

    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invalid invite code"
        )

    membership = TeamMember(
        user_id=current_user.id,
        team_id=team.id,
        role=UserRole.rep
    )
    db.add(membership)
    await db.commit()

    team = await _get_team_with_members(team.id, db)
    return _build_team_response(team)


async def update_member_role(
    team_id: UUID,
    user_id: UUID,
    payload: UpdateRoleRequest,
    current_user: User,
    db: AsyncSession
):
    membership = await _get_membership(current_user.id, team_id, db)
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this team"
        )

    target = await _get_membership(user_id, team_id, db)
    if not target:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found in this team"
        )

    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot change your own role"
        )

    target.role = payload.role
    await db.commit()

    team = await _get_team_with_members(team_id, db)
    return _build_team_response(team)


async def remove_member(
    team_id: UUID,
    user_id: UUID,
    current_user: User,
    db: AsyncSession
):
    membership = await _get_membership(current_user.id, team_id, db)
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this team"
        )

    target = await _get_membership(user_id, team_id, db)
    if not target:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found in this team"
        )

    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot remove yourself from the team"
        )

    await db.delete(target)
    await db.commit()

    team = await _get_team_with_members(team_id, db)
    return _build_team_response(team)


async def get_team_invite_code(
    team_id: UUID,
    current_user: User,
    db: AsyncSession
):
    membership = await _get_membership(current_user.id, team_id, db)
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this team"
        )

    result = await db.execute(select(Team).where(Team.id == team_id))
    team = result.scalar_one_or_none()

    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team not found"
        )

    return {"invite_code": team.invite_code}


async def check_user_has_team(user_id: UUID, db: AsyncSession) -> bool:
    result = await db.execute(
        select(TeamMember).where(TeamMember.user_id == user_id)
    )
    return result.scalar_one_or_none() is not None


async def get_user_teams(current_user: User, db: AsyncSession) -> list[UserTeamResponse]:
    result = await db.execute(
        select(TeamMember)
        .options(selectinload(TeamMember.team))
        .where(TeamMember.user_id == current_user.id)
    )
    memberships = result.scalars().all()

    return [
        UserTeamResponse(
            id=tm.team.id,
            name=tm.team.name,
            invite_code=tm.team.invite_code,
            created_at=tm.team.created_at,
            role=tm.role,
        )
        for tm in memberships
    ]