import hashlib
import hmac
import json

import httpx
import pytest
from fastapi import HTTPException

from app.config import settings
from app.routers.billing import _timestamp, _valid_signature
from app.services.billing_service import BillingService


def test_safepay_raw_body_signature(monkeypatch):
    secret = "test-webhook-secret"
    monkeypatch.setattr(settings, "safepay_webhook_secret", secret)
    payload = {"type": "subscription.payment.succeeded", "data": {"id": "sub_123"}}
    raw = json.dumps(payload, separators=(",", ":")).encode()
    signature = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()

    assert _valid_signature(raw, payload, signature)
    assert not _valid_signature(raw, payload, "0" * 64)


def test_safepay_protobuf_timestamp_conversion():
    result = _timestamp({"seconds": 1_700_000_000, "nanos": 1})
    assert result.timestamp() == 1_700_000_000


def test_manual_plan_prices_are_stored_in_paisas():
    assert BillingService._amount("plus") == 3_000_000
    assert BillingService._amount("pro") == 6_000_000


@pytest.mark.asyncio
async def test_safepay_tracker_failure_has_actionable_configuration_error(monkeypatch):
    monkeypatch.setattr(settings, "safepay_secret_key", "server-key")

    async def failed_request(self, method, url, **kwargs):
        request = httpx.Request(method, url)
        return httpx.Response(500, request=request)

    monkeypatch.setattr(httpx.AsyncClient, "request", failed_request)

    with pytest.raises(HTTPException) as raised:
        await BillingService._request("POST", "/order/payments/v3/", json={})

    assert raised.value.status_code == 502
    assert "SAFEPAY_PUBLIC_KEY" in raised.value.detail
    assert "configured Safepay environment" in raised.value.detail
