from botocore.exceptions import ClientError

from app.core.s3 import _storage_error_message


def _client_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": "test"}}, "PutObject")


def test_storage_error_message_identifies_invalid_credentials():
    assert _storage_error_message(_client_error("InvalidAccessKeyId")) == (
        "File storage credentials are invalid"
    )


def test_storage_error_message_identifies_missing_permission():
    assert _storage_error_message(_client_error("AccessDenied")) == (
        "File storage credentials do not have permission to upload"
    )


def test_storage_error_message_identifies_wrong_region():
    assert _storage_error_message(_client_error("PermanentRedirect")) == (
        "The file storage bucket region is incorrect"
    )


def test_storage_error_message_keeps_unknown_errors_generic():
    assert _storage_error_message(_client_error("Unexpected")) == (
        "File storage rejected the upload"
    )
