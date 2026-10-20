from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from app.services.admin_dashboard_service import aggregate_ai_feedback


def message(content: str, feedback: dict):
    return SimpleNamespace(
        id=uuid4(),
        chat_id=uuid4(),
        content=content,
        created_at=datetime(2026, 10, 20, tzinfo=timezone.utc),
        metadata_log={"feedback_by_user": feedback},
    )


def test_aggregate_ai_feedback_counts_ratings_reasons_and_rate():
    result = aggregate_ai_feedback([
        message("Useful answer", {"user-a": {"rating": "up"}}),
        message("Wrong answer", {"user-b": {"rating": "down", "reason": "incorrect"}}),
        message("Missing detail", {"user-c": {"rating": "down", "reason": "incomplete"}}),
    ])

    assert result["total_ratings"] == 3
    assert result["helpful"] == 1
    assert result["unhelpful"] == 2
    assert result["helpful_rate"] == 33.3
    assert result["reasons"]["incorrect"] == 1
    assert result["reasons"]["incomplete"] == 1
    assert len(result["recent_negative"]) == 2


def test_aggregate_ai_feedback_ignores_invalid_metadata_and_limits_recent_items():
    messages = [message(f"Response {index}", {str(index): {"rating": "down", "reason": "irrelevant"}}) for index in range(12)]
    messages.append(SimpleNamespace(metadata_log={"feedback_by_user": "invalid"}))

    result = aggregate_ai_feedback(messages)

    assert result["total_ratings"] == 12
    assert result["reasons"]["irrelevant"] == 12
    assert len(result["recent_negative"]) == 10

