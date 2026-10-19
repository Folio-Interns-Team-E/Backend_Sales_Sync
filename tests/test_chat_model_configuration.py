import ast
import inspect
import textwrap

from app.ai.email_agent import EmailAgent
from app.ai.icp_agent import ICPAgent
from app.ai.supervisor_agent import SupervisorAgent
from app.services.chat_service import ChatService


def test_chat_name_is_derived_from_first_user_message_without_ai_call():
    assert ChatService.derive_chat_name("draft an email to Lal Majid") == "Draft an email to Lal Majid"
    assert ChatService.derive_chat_name("https://example.com") == "New Chat"
    assert ChatService.derive_chat_name(
        "Create a detailed proposal for Acme covering onboarding pricing implementation and support"
    ) == "Create a detailed proposal for Acme covering onboarding…"


def test_email_and_icp_agents_use_supported_model():
    assert EmailAgent.MODEL == "openai/gpt-oss-120b"
    assert ICPAgent.MODEL == "openai/gpt-oss-120b"


def test_chat_error_handler_traceback_import_is_not_shadowed():
    tree = ast.parse(textwrap.dedent(inspect.getsource(ChatService.send_message)))
    assert not any(
        isinstance(node, (ast.Import, ast.ImportFrom))
        and any(alias.name == "traceback" for alias in node.names)
        for node in ast.walk(tree)
    )


def test_supervisor_normalizes_meeting_aliases_and_parameters():
    result = SupervisorAgent.normalize_action(
        {
            "action": "CREATE_MEETING",
            "parameters": {
                "keywords": "Jane Doe",
                "limit": 900,
                "start_time": "2026-10-17T14:00:00",
            },
        }
    )

    assert result == {
        "action": "MEETING_OPERATION",
        "parameters": {
            "keywords": ["Jane Doe"],
            "industry": [],
            "country": [],
            "limit": 50,
            "start_time": "2026-10-17T14:00:00",
        },
    }


def test_supervisor_rejects_unknown_actions_and_invalid_limits_safely():
    result = SupervisorAgent.normalize_action(
        {"action": "DROP_DATABASE", "parameters": {"limit": "many", "keywords": None}}
    )

    assert result["action"] == "NORMAL"
    assert result["parameters"]["limit"] == 20
    assert result["parameters"]["keywords"] == []


def test_email_quality_gate_rejects_unusable_drafts():
    valid = {
        "subject": "Pipeline review",
        "body": "Your team is scaling outbound at Acme.\n\nSaleSync helps reps automate qualified follow-up.\n\nWould comparing workflows be useful?",
    }
    invalid = {
        "subject": "A very long and clickbait subject",
        "body": "Hope this email finds you well. This is not split into three paragraphs.",
    }

    assert EmailAgent.validate_email(valid) == []
    problems = EmailAgent.validate_email(invalid)
    assert "Keep the subject under five words." in problems
    assert "Use exactly three paragraphs separated by blank lines." in problems
    assert "Remove generic cold-email clichés." in problems
