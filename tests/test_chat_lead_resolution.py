from types import SimpleNamespace

from app.services.chat_service import ChatService


def lead(name, company, email, title="CEO"):
    return SimpleNamespace(name=name, company_name=company, email=email, job_title=title)


def test_unique_lead_is_selected_directly():
    ada = lead("Ada Lovelace", "Analytical Engines", "ada@example.com")
    assert ChatService._resolve_lead_candidate([ada], ["Ada"], "draft an email to Ada") is ada


def test_full_name_selects_one_of_multiple_partial_matches():
    john_acme = lead("John Smith", "Acme", "john@acme.test")
    john_beta = lead("John Ahmed", "Beta", "john@beta.test")
    selected = ChatService._resolve_lead_candidate(
        [john_acme, john_beta],
        ["John", "Smith"],
        "Draft an email to John Smith",
    )
    assert selected is john_acme


def test_company_or_email_disambiguates_duplicate_names():
    acme = lead("John Smith", "Acme", "john@acme.test")
    beta = lead("John Smith", "Beta", "john@beta.test")
    assert ChatService._resolve_lead_candidate(
        [acme, beta], ["John Smith"], "Draft for John Smith at Beta"
    ) is beta
    assert ChatService._resolve_lead_candidate(
        [acme, beta], ["John Smith"], "Draft for john@acme.test"
    ) is acme


def test_ambiguous_partial_match_is_not_guessed():
    candidates = [
        lead("John Smith", "Acme", "john@acme.test"),
        lead("John Ahmed", "Beta", "john@beta.test"),
    ]
    assert ChatService._resolve_lead_candidate(candidates, ["John"], "Draft for John") is None
    message = ChatService._lead_clarification_message(candidates, "draft an email for")
    assert "won't guess" in message
    assert "Acme" in message and "Beta" in message
