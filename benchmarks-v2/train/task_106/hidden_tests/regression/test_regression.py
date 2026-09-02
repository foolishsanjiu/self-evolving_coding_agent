from datetime import date
from decimal import Decimal

import pytest
from billing import Plan, PlanCatalog, Subscription, plan_change_adjustment


def _catalog() -> PlanCatalog:
    return PlanCatalog(
        [
            Plan("starter", Decimal("0.10")),
            Plan("plus", Decimal("0.20")),
        ]
    )


def test_full_period_change_charges_the_full_cent_difference() -> None:
    subscription = Subscription("starter", date(2026, 2, 1), date(2026, 2, 28))

    result = plan_change_adjustment(subscription, "plus", date(2026, 2, 1), _catalog())

    assert result.amount_cents == 10


@pytest.mark.parametrize("effective_on", [date(2026, 1, 31), date(2026, 3, 1)])
def test_effective_date_must_be_inside_the_service_period(effective_on: date) -> None:
    subscription = Subscription("starter", date(2026, 2, 1), date(2026, 2, 28))

    with pytest.raises(ValueError, match="outside the service period"):
        plan_change_adjustment(subscription, "plus", effective_on, _catalog())
