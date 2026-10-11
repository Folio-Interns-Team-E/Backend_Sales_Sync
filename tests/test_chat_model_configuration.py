import ast
import inspect
import textwrap

from app.ai.email_agent import EmailAgent
from app.ai.icp_agent import ICPAgent
from app.services.chat_service import ChatService


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
