from __future__ import annotations

from uuid import uuid4

import pytest


async def create_team(client, user, name="E2E Team"):
    response = await client.post("/teams/", json={"name": name}, headers=user["headers"])
    assert response.status_code == 201, response.text
    return response.json()["data"]


@pytest.mark.asyncio
async def test_team_01_create_team_assigns_admin(client, api_user):
    admin = await api_user("team-admin")
    team = await create_team(client, admin)
    assert team["name"] == "E2E Team"
    assert team["invite_code"]
    assert team["members"] == [
        {
            "id": admin["id"],
            "full_name": "Team-Admin Test User",
            "email": admin["email"],
            "role": "admin",
        }
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["", " ", "\t"])
async def test_team_02_rejects_blank_names(client, api_user, name):
    admin = await api_user("blank-team")
    response = await client.post("/teams/", json={"name": name}, headers=admin["headers"])
    assert response.status_code in {400, 422}


@pytest.mark.asyncio
async def test_team_03_enforces_one_team_membership(client, api_user):
    user = await api_user("one-team")
    await create_team(client, user, "First Team")
    second = await client.post("/teams/", json={"name": "Second Team"}, headers=user["headers"])
    assert second.status_code == 400


@pytest.mark.asyncio
async def test_team_04_join_valid_invite_code(client, api_user):
    admin = await api_user("join-admin")
    rep = await api_user("join-rep")
    team = await create_team(client, admin)

    joined = await client.post(
        "/teams/join",
        json={"invite_code": team["invite_code"]},
        headers=rep["headers"],
    )
    assert joined.status_code == 200
    members = {member["id"]: member["role"] for member in joined.json()["data"]["members"]}
    assert members[rep["id"]] == "rep"


@pytest.mark.asyncio
async def test_team_05_invalid_invite_code_fails(client, api_user):
    user = await api_user("invalid-code")
    response = await client.post(
        "/teams/join",
        json={"invite_code": "definitely-invalid"},
        headers=user["headers"],
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_team_06_duplicate_membership_is_rejected(client, api_user):
    admin = await api_user("duplicate-member")
    team = await create_team(client, admin)
    response = await client.post(
        "/teams/join",
        json={"invite_code": team["invite_code"]},
        headers=admin["headers"],
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_team_07_list_only_current_users_teams(client, api_user):
    first = await api_user("list-first")
    second = await api_user("list-second")
    first_team = await create_team(client, first, "First Private Team")
    await create_team(client, second, "Second Private Team")

    response = await client.get("/teams/", headers=first["headers"])
    assert response.status_code == 200
    assert [team["id"] for team in response.json()["data"]] == [first_team["id"]]


@pytest.mark.asyncio
async def test_team_08_nonmember_cannot_read_update_or_delete(client, api_user):
    owner = await api_user("owner")
    outsider = await api_user("outsider")
    team = await create_team(client, owner)

    read = await client.get(f"/teams/{team['id']}", headers=outsider["headers"])
    update = await client.patch(
        f"/teams/{team['id']}",
        json={"name": "Stolen"},
        headers=outsider["headers"],
    )
    delete = await client.delete(f"/teams/{team['id']}", headers=outsider["headers"])
    assert [read.status_code, update.status_code, delete.status_code] == [403, 403, 403]


@pytest.mark.asyncio
async def test_team_15_admin_changes_member_role(client, api_user):
    admin = await api_user("role-admin")
    member = await api_user("role-member")
    team = await create_team(client, admin)
    await client.post(
        "/teams/join",
        json={"invite_code": team["invite_code"]},
        headers=member["headers"],
    )

    response = await client.put(
        f"/teams/{team['id']}/members/{member['id']}/role",
        json={"role": "manager"},
        headers={**admin["headers"], "X-Team-Id": team["id"]},
    )
    assert response.status_code == 200
    roles = {item["id"]: item["role"] for item in response.json()["data"]["members"]}
    assert roles[member["id"]] == "manager"


@pytest.mark.asyncio
async def test_team_16_rep_cannot_change_roles(client, api_user):
    admin = await api_user("rbac-admin")
    rep = await api_user("rbac-rep")
    target = await api_user("rbac-target")
    team = await create_team(client, admin)
    for user in (rep, target):
        await client.post(
            "/teams/join",
            json={"invite_code": team["invite_code"]},
            headers=user["headers"],
        )

    response = await client.put(
        f"/teams/{team['id']}/members/{target['id']}/role",
        json={"role": "manager"},
        headers={**rep["headers"], "X-Team-Id": team["id"]},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_team_17_admin_cannot_change_own_role(client, api_user):
    admin = await api_user("self-role")
    team = await create_team(client, admin)
    response = await client.put(
        f"/teams/{team['id']}/members/{admin['id']}/role",
        json={"role": "rep"},
        headers={**admin["headers"], "X-Team-Id": team["id"]},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_team_18_admin_removes_member(client, api_user):
    admin = await api_user("remove-admin")
    rep = await api_user("remove-rep")
    team = await create_team(client, admin)
    await client.post(
        "/teams/join",
        json={"invite_code": team["invite_code"]},
        headers=rep["headers"],
    )
    response = await client.delete(
        f"/teams/{team['id']}/members/{rep['id']}",
        headers={**admin["headers"], "X-Team-Id": team["id"]},
    )
    assert response.status_code == 200
    assert rep["id"] not in {member["id"] for member in response.json()["data"]["members"]}


@pytest.mark.asyncio
async def test_team_19_admin_cannot_remove_self(client, api_user):
    admin = await api_user("remove-self")
    team = await create_team(client, admin)
    response = await client.delete(
        f"/teams/{team['id']}/members/{admin['id']}",
        headers={**admin["headers"], "X-Team-Id": team["id"]},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_team_21_mismatched_path_and_header_team_is_denied(client, api_user):
    first = await api_user("mismatch-first")
    second = await api_user("mismatch-second")
    first_team = await create_team(client, first, "First Team")
    second_team = await create_team(client, second, "Second Team")

    response = await client.get(
        f"/teams/{second_team['id']}/invite-code",
        headers={**first["headers"], "X-Team-Id": first_team["id"]},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_team_23_team_header_validation(client, api_user):
    user = await api_user("header-validation")
    missing = await client.get(f"/teams/{uuid4()}/invite-code", headers=user["headers"])
    malformed = await client.get(
        f"/teams/{uuid4()}/invite-code",
        headers={**user["headers"], "X-Team-Id": "not-a-uuid"},
    )
    unknown = await client.get(
        f"/teams/{uuid4()}/invite-code",
        headers={**user["headers"], "X-Team-Id": str(uuid4())},
    )
    assert missing.status_code == 422
    assert malformed.status_code == 400
    assert unknown.status_code == 403
