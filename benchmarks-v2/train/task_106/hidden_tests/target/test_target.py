from datetime import date
from decimal import Decimal

from billing import Plan, PlanCatalog, Subscription, plan_change_adjustment


def _catalog() -> PlanCatalog:
    return PlanCatalog(
        [
            Plan("basic", Decimal("10.00")),
            Plan("pro", Decimal("20.00")),
        ]
    )


def test_upgrade_uses_inclusive_remaining_days_and_catalog_prices() -> None:
    subscription = Subscription("basic", date(2026, 1, 1), date(2026, 1, 31))

    result = plan_change_adjustment(subscription, "pro", date(2026, 1, 17), _catalog())

    assert result.amount_cents == 484


def test_downgrade_produces_a_half_up_rounded_credit() -> None:
    subscription = Subscription("pro", date(2026, 1, 1), date(2026, 1, 31))

    result = plan_change_adjustment(subscription, "basic", date(2026, 1, 17), _catalog())

    assert result.amount_cents == -484
