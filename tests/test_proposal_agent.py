import io
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.ai.proposal_agent import ProposalAgent


class _Result:
    def scalar_one_or_none(self):
        return SimpleNamespace(icp="Enterprise software buyers")


class _Db:
    async def execute(self, _query):
        return _Result()


@pytest.mark.asyncio
async def test_proposal_run_reuses_generated_metadata(monkeypatch):
    agent = ProposalAgent(_Db())
    proposal_data = {"executive_summary": "A focused proposal"}
    styles = {"primary_color_hex": "#1B365D"}
    compile_calls = 0

    async def fake_compile(**_kwargs):
        nonlocal compile_calls
        compile_calls += 1
        return "Acme_Proposal", proposal_data, styles

    monkeypatch.setattr(agent, "_compile_proposal_data", fake_compile)
    monkeypatch.setattr(agent, "create_proposal_document", lambda **_kwargs: io.BytesIO(b"docx"))

    filename, stream, returned_data, returned_styles = await agent.run(
        "Create a proposal for Acme",
        uuid4(),
    )

    assert compile_calls == 1
    assert filename == "Acme_Proposal.docx"
    assert stream.getvalue() == b"docx"
    assert returned_data == proposal_data
    assert returned_styles == styles
