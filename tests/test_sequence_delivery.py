from datetime import datetime, timezone
from types import SimpleNamespace

from app.services.sequence_delivery_service import render_message, sequence_day_start


def test_render_message_replaces_supported_lead_fields():
    lead = SimpleNamespace(name="Ayesha Khan", company_name="Acme", job_title="VP Sales")
    assert render_message("Hi {{first_name}} at {{company}} — {{name}}, {{job_title}}", lead) == "Hi Ayesha at Acme — Ayesha Khan, VP Sales"


def test_sequence_day_start_uses_sequence_timezone():
    now = datetime(2026, 10, 10, 20, 30, tzinfo=timezone.utc)
    assert sequence_day_start(now, "Asia/Karachi") == datetime(2026, 10, 10, 19, 0, tzinfo=timezone.utc)


def test_sequence_day_start_falls_back_to_utc_for_invalid_zone():
    now = datetime(2026, 10, 10, 20, 30, tzinfo=timezone.utc)
    assert sequence_day_start(now, "Invalid/Zone") == datetime(2026, 10, 10, tzinfo=timezone.utc)
