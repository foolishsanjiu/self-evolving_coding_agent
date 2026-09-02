from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class Plan:
    plan_id: str
    monthly_price: Decimal


@dataclass(frozen=True)
class Subscription:
    plan_id: str
    period_start: date
    period_end: date


@dataclass(frozen=True)
class InvoiceAdjustment:
    amount_cents: int
