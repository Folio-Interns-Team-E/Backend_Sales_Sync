import hashlib
import hmac
import json

from app.config import settings
from app.routers.billing import _tier_for_plan, _timestamp, _valid_signature


def test_safepay_raw_body_signature(monkeypatch):
    secret = "test-webhook-secret"
    monkeypatch.setattr(settings, "safepay_webhook_secret", secret)
    payload = {"type": "subscription.payment.succeeded", "data": {"id": "sub_123"}}
    raw = json.dumps(payload, separators=(",", ":")).encode()
    signature = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()

    assert _valid_signature(raw, payload, signature)
    assert not _valid_signature(raw, payload, "0" * 64)


def test_safepay_plan_ids_map_to_internal_tiers(monkeypatch):
    monkeypatch.setattr(settings, "safepay_plus_plan_id", "plan_plus")
    monkeypatch.setattr(settings, "safepay_pro_plan_id", "plan_pro")

    assert _tier_for_plan("plan_plus") == "plus"
    assert _tier_for_plan("plan_pro") == "pro"
    assert _tier_for_plan("plan_unknown") is None


def test_safepay_protobuf_timestamp_conversion():
    result = _timestamp({"seconds": 1_700_000_000, "nanos": 1})
    assert result.timestamp() == 1_700_000_000
