from billing.models import Plan


class PlanCatalog:
    def __init__(self, plans: list[Plan]) -> None:
        self._plans = {plan.plan_id: plan for plan in plans}

    def require(self, plan_id: str) -> Plan:
        try:
            return self._plans[plan_id]
        except KeyError as exc:
            raise ValueError(f"unknown plan: {plan_id}") from exc
