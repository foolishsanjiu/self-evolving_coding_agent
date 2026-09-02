from datetime import date
from decimal import Decimal

import pytest
from billing import Plan, PlanCatalog, Subscription, plan_change_adjustment


def test_catalog_requires_known_plan() -> None:
    catalog = PlanCatalog([Plan("basic", Decimal("10.00"))])

    assert catalog.require("basic").monthly_price == Decimal("10.00")
    with pytest.raises(ValueError, match="unknown plan"):
        catalog.require("missing")


def test_same_plan_has_no_adjustment() -> None:
    subscription = Subscription("basic", date(2026, 1, 1), date(2026, 1, 31))

    result = plan_change_adjustment(
        subscription,
        "basic",
        date(2026, 1, 20),
        PlanCatalog([]),
    )

    assert result.amount_cents == 0
