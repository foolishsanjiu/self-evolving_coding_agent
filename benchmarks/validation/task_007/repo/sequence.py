def median(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[len(ordered) // 2]
