import pytest
from fastapi import HTTPException

from app.services.lead_import_service import LeadImportService


def test_csv_import_accepts_common_column_names_and_normalizes_email():
    rows, invalid = LeadImportService.parse_csv(
        b"Full Name,Work Email,Company Name,Job Title\nJane Doe, JANE@EXAMPLE.COM ,Acme,VP Sales\n"
    )
    assert invalid == 0
    assert rows[0]["name"] == "Jane Doe"
    assert rows[0]["email"] == "jane@example.com"
    assert rows[0]["company"] == "Acme"


def test_csv_import_counts_invalid_rows():
    rows, invalid = LeadImportService.parse_csv(b"name,email\nValid,valid@example.com\nBad,not-an-email\n")
    assert len(rows) == 1
    assert invalid == 1


def test_csv_import_requires_name_and_email_headers():
    with pytest.raises(HTTPException) as error:
        LeadImportService.parse_csv(b"company,title\nAcme,VP Sales\n")
    assert error.value.status_code == 400
