def find_skus(records: list[dict[str, str]], query: str) -> list[str]:
    matches = []
    for record in records:
        if query in record["name"]:
            matches.append(record["sku"])
    return matches


def count_matches(records: list[dict[str, str]], query: str) -> int:
    count = 0
    for record in records:
        if query in record["name"]:
            count += 1
    return count
