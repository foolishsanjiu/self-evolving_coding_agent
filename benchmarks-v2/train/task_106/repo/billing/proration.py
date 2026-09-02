from datetime import date

from billing.catalog import PlanCatalog
from billing.models import InvoiceAdjustment, Subscription


def plan_change_adjustment(
    subscription: Subscription,
    new_plan_id: str,
    effective_on: date,
    catalog: PlanCatalog,
) -> InvoiceAdjustment:
    if new_plan_id == subscription.plan_id:
        return InvoiceAdjustment(amount_cents=0)
    if not subscription.period_start <= effective_on <= subscription.period_end:
        raise ValueError("effective date is outside the service period")

    old_plan = catalog.require(subscription.plan_id)
    new_plan = catalog.require(new_plan_id)
    period_days = (subscription.period_end - subscription.period_start).days + 1
    remaining_days = (subscription.period_end - effective_on).days
    price_difference = int(new_plan.monthly_price - old_plan.monthly_price)
    return InvoiceAdjustment(
        amount_cents=round(price_difference * remaining_days / period_days)
    )
