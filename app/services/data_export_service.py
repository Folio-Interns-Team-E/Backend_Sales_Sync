import csv
import io
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select

from app.models.audit_event import AuditEvent
from app.models.crm import Contact
from app.models.lead import Lead
from app.models.opportunity import Opportunity

MAX_EXPORT_ROWS = 50_000

EXPORTS = {
    "leads": (
        Lead,
        ("id", "name", "email", "company_name", "job_title", "status", "source", "score", "created_at", "updated_at"),
    ),
    "contacts": (
        Contact,
        ("id", "first_name", "last_name", "email", "phone", "job_title", "lifecycle_stage", "account_id", "owner_id", "created_at", "updated_at"),
    ),
    "opportunities": (
        Opportunity,
        ("id", "name", "company_name", "stage", "amount", "currency", "probability", "expected_close_date", "loss_reason", "lead_id", "owner_id", "created_at", "updated_at"),
    ),
    "audit": (
        AuditEvent,
        ("id", "actor_user_id", "action", "target_type", "target_id", "created_at"),
    ),
}


def safe_csv_value(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (datetime, date)):
        result = value.isoformat()
    elif isinstance(value, Decimal):
        result = format(value, "f")
    else:
        result = str(value)
    if result.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + result
    return result


async def export_workspace_data(db, team_id, resource: str) -> tuple[str, int]:
    model, columns = EXPORTS[resource]
    rows = list((await db.execute(
        select(model)
        .where(model.team_id == team_id)
        .order_by(model.created_at.desc(), model.id.desc())
        .limit(MAX_EXPORT_ROWS)
    )).scalars().all())
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(columns)
    writer.writerows([safe_csv_value(getattr(row, column)) for column in columns] for row in rows)
    return "\ufeff" + output.getvalue(), len(rows)
