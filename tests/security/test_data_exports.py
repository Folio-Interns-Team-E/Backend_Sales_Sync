import csv
import io
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from app.services.data_export_service import export_workspace_data, safe_csv_value


def test_csv_formula_injection_is_neutralized():
    for dangerous in ("=cmd()", "+1+1", "-2+3", "@SUM(A1)", "\tformula", "\rformula"):
        assert safe_csv_value(dangerous) == "'" + dangerous
    assert safe_csv_value("normal") == "normal"


async def test_export_is_tenant_scoped_and_has_stable_columns():
    team_id = uuid4()
    row = SimpleNamespace(
        id=uuid4(), name="=Injected", email="person@example.com", company_name="Acme",
        job_title="VP Sales", status="Qualified", source="Manual", score=85,
        created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
    )
    db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [row]))))

    content, count = await export_workspace_data(db, team_id, "leads")

    parsed = list(csv.reader(io.StringIO(content.lstrip("\ufeff"))))
    assert count == 1
    assert parsed[0] == ["id", "name", "email", "company_name", "job_title", "status", "source", "score", "created_at", "updated_at"]
    assert parsed[1][1] == "'=Injected"
    statement = db.execute.call_args.args[0]
    assert team_id in statement.compile().params.values()
    assert "LIMIT" in str(statement)
