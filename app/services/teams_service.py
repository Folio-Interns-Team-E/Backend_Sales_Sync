from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from fastapi import HTTPException, status
from uuid import UUID
import logging
import resend
from app.models.user import User
from app.models.team import Team
from app.models.team_member import TeamMember, MemberRole
from app.schemas.teams import (
    TeamCreate, InviteRequest,
    UpdateRoleRequest, JoinTeamRequest,
    TeamResponse, MemberResponse,
    UserTeamResponse, TeamUpdate
)
from app.config import settings

logger = logging.getLogger(__name__)


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
    new_team = Team(name=payload.name)
    db.add(new_team)
    await db.flush()

    membership = TeamMember(
        user_id=current_user.id,
        team_id=new_team.id,
        role=MemberRole.admin
    )
    db.add(membership)
    await db.commit()

    team = await _get_team_with_members(new_team.id, db)
    result = _build_team_response(team)
    return result


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
    result = _build_team_response(team)
    return result


async def _send_team_invite_email(
    to_email: str,
    team_name: str,
    invite_code: str,
    inviter_name: str
):
    frontend_url = settings.frontend_origins[0] if settings.frontend_origins else "http://localhost:5173"
    invite_link = f"{frontend_url}/team-setup?invite={invite_code}"
    
    try:
        resend.Emails.send({
            "from": settings.FROM_EMAIL,
            "to": [to_email],
            "subject": f"You've been invited to join {team_name}",
            "html": f"""
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <div style="background: linear-gradient(135deg, #0d1f2d, #1a9ea3); padding: 32px; text-align: center; border-radius: 12px 12px 0 0;">
                    <h1 style="color: white; margin: 0; font-size: 24px;">Team Invitation</h1>
                </div>
                <div style="background: #f8fafc; padding: 32px; border: 1px solid #e2e8f0; border-top: none; border-radius: 0 0 12px 12px;">
                    <p style="color: #334155; font-size: 16px; line-height: 1.6;">
                        <strong>{inviter_name}</strong> has invited you to join the team <strong>"{team_name}"</strong> on SalesSync AI.
                    </p>
                    <div style="text-align: center; margin: 32px 0;">
                        <a href="{invite_link}" style="
                            display: inline-block;
                            background: #1a9ea3;
                            color: white;
                            text-decoration: none;
                            padding: 14px 32px;
                            border-radius: 8px;
                            font-weight: bold;
                            font-size: 16px;
                        ">Accept Invitation</a>
                    </div>
                    <p style="color: #64748b; font-size: 14px; line-height: 1.6;">
                        Or use this invite code: <strong style="color: #1a9ea3;">{invite_code}</strong>
                    </p>
                    <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 24px 0;" />
                    <p style="color: #94a3b8; font-size: 12px; text-align: center;">
                        If you didn't expect this invitation, you can safely ignore this email.
                    </p>
                </div>
            </div>
            """,
        })
        logger.info("Team invite email sent to %s", to_email)
    except Exception:
        logger.exception("Failed to send team invite email to %s", to_email)
        raise


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

    team = await _get_team_with_members(inviter_membership.team_id, db)
    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team not found"
        )

    await _send_team_invite_email(
        to_email=payload.email,
        team_name=team.name,
        invite_code=team.invite_code,
        inviter_name=current_user.full_name
    )

    return _build_team_response(team)


async def join_existing_team(
    payload: JoinTeamRequest,
    current_user: User,
    db: AsyncSession
):
    result = await db.execute(
        select(Team).where(Team.invite_code == payload.invite_code)
    )
    team = result.scalar_one_or_none()

    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invalid invite code"
        )

    existing_membership = await _get_membership(current_user.id, team.id, db)
    if existing_membership:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You are already a member of this team"
        )

    membership = TeamMember(
        user_id=current_user.id,
        team_id=team.id,
        role=MemberRole.rep
    )
    db.add(membership)
    await db.commit()

    team = await _get_team_with_members(team.id, db)
    result = _build_team_response(team)
    return result


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
    result = _build_team_response(team)
    return result


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
    result = _build_team_response(team)
    return result


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

    data = {"invite_code": team.invite_code}
    return data


async def check_user_has_team(user_id: UUID, db: AsyncSession) -> bool:
    result = await db.execute(
        select(TeamMember).where(TeamMember.user_id == user_id)
    )
    return result.scalar_one_or_none() is not None


async def update_team(
    team_id: UUID,
    payload: TeamUpdate,
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

    if payload.name is not None:
        team.name = payload.name
    await db.commit()

    team = await _get_team_with_members(team_id, db)
    return _build_team_response(team)


async def delete_team(
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

    if membership.role != MemberRole.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can delete the team"
        )

    result = await db.execute(select(Team).where(Team.id == team_id))
    team = result.scalar_one_or_none()
    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team not found"
        )

    await db.delete(team)
    await db.commit()


async def get_user_teams(current_user: User, db: AsyncSession) -> list[UserTeamResponse]:
    result = await db.execute(
        select(TeamMember)
        .options(selectinload(TeamMember.team))
        .where(TeamMember.user_id == current_user.id)
    )
    memberships = result.scalars().all()

    teams = [
        UserTeamResponse(
            id=tm.team.id,
            name=tm.team.name,
            invite_code=tm.team.invite_code,
            created_at=tm.team.created_at,
            role=tm.role,
        )
        for tm in memberships
    ]
    return teams