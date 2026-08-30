from tax import add_tax


def order_total(subtotal: float, discount: float, tax_percent: float) -> float:
    discounted = max(0, subtotal - discount)
    return add_tax(discounted, tax_percent)
