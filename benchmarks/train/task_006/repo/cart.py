def cart_total(prices: list[float], discount_percent: float) -> float:
    if not prices:
        return 0.0
    discounted_first = prices[0] * (1 - discount_percent / 100)
    return discounted_first + sum(prices[1:])
