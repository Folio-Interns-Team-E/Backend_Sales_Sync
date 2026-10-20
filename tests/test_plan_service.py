from app.services.plan_service import PLAN_LIMITS, normalize_tier


def test_launch_plan_limits_are_centralized():
    assert set(PLAN_LIMITS) == {"free", "plus", "pro"}
    assert PLAN_LIMITS["free"].members == 3
    assert PLAN_LIMITS["plus"].leads == 5_000
    assert PLAN_LIMITS["pro"].emails_monthly == 10_000


def test_legacy_paid_tiers_keep_equivalent_access():
    assert normalize_tier("growth") == "plus"
    assert normalize_tier("enterprise") == "pro"
    assert normalize_tier("unexpected") == "free"
