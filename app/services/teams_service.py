from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException, status
from uuid import UUID
from app.models.user import User, UserRole
from app.models.team import Team
from app.schemas.teams import (
    TeamCreate, InviteRequest,
    UpdateRoleRequest, JoinTeamRequest
)

from sqlalchemy.orm import selectinload

async def create_team(
    payload: TeamCreate,
    current_user: User,
    db: AsyncSession
):
    if current_user.team_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You are already part of a team"
        )

    new_team = Team(name=payload.name)
    db.add(new_team)
    await db.flush()

    current_user.team_id = new_team.id
    current_user.role = UserRole.admin

    await db.commit()

    # reload team with members eagerly loaded
    result = await db.execute(
        select(Team)
        .options(selectinload(Team.members))
        .where(Team.id == new_team.id)
    )
    team = result.scalar_one()
    return team

#get team
async def get_team(
        team_id: UUID,
        current_user: User,
        db: AsyncSession
):
    #cannot view a team you're not in
    if current_user.team_id != team_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this team"
        )
    
    result = await db.execute(
        select(Team)
        .options(selectinload(Team.members))
        .where(Team.id == team_id)
    )
    team = result.scalar_one_or_none()

    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team not found"
        )
    
    return team

#invite a member
async def invite_member(
        payload: InviteRequest,
        current_user: User,
        db: AsyncSession
):
    #check if inviter has a team
    if not current_user.team_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You are not part of a team"
        )
    
    #find user being invitedf
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User is already part of a team"
        )
    
    #if found add to team (default role = rep)
    user.team_id = current_user.team_id
    user.role = UserRole.rep

    await db.commit()
    await db.refresh(user)

    return {"message": f"{user.full_name} added to team"}

#join existing team
async def join_existing_team(
    payload: JoinTeamRequest,
    current_user: User,
    db: AsyncSession
):
    if current_user.team_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You are already part of a team"
        )

    #find team by invite code
    result = await db.execute(
        select(Team).where(Team.invite_code == payload.invite_code)
    )
    team = result.scalar_one_or_none()

    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invalid invite code"
        )

    #add user to team
    current_user.team_id = team.id
    current_user.role = UserRole.rep

    await db.commit()
    await db.refresh(current_user)

    return {"message": f"Successfully joined {team.name}"}

#update member role
async def update_member_role(
    team_id: UUID,
    user_id: UUID,
    payload: UpdateRoleRequest,
    current_user: User,
    db: AsyncSession
):
    #admin must belong to same team
    if current_user.team_id != team_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this team"
        )

    result = await db.execute(
        select(User).where(User.id == user_id, User.team_id == team_id)
    )
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found in this team"
        )

    #prevent admin from demoting themselves
    if user.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot change your own role"
        )

    user.role = payload.role
    await db.commit()
    await db.refresh(user)

    return {"message": f"Role updated to {payload.role.value}"}

#remove team member
async def remove_member(
    team_id: UUID,
    user_id: UUID,
    current_user: User,
    db: AsyncSession
):
    if current_user.team_id != team_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this team"
        )

    result = await db.execute(
        select(User).where(User.id == user_id, User.team_id == team_id)
    )
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found in this team"
        )

    #prevent removing yourself
    if user.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot remove yourself from the team"
        )

    user.team_id = None
    user.role = UserRole.rep

    await db.commit()

    return {"message": f"{user.full_name} removed from team"}

#get team invite code
async def get_team_invite_code(
    team_id: UUID,
    current_user: User,
    db: AsyncSession
):
    if current_user.team_id != team_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this team"
        )

    result = await db.execute(
        select(Team).where(Team.id == team_id)
    )
    team = result.scalar_one_or_none()

    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team not found"
        )

    return {"invite_code": team.invite_code}