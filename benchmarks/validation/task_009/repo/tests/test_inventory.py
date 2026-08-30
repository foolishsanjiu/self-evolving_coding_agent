from inventory import count_matches, find_skus

RECORDS = [{"sku": "A1", "name": "Red Chair"}, {"sku": "B2", "name": "Blue Desk"}]


def test_exact_case_search() -> None:
    assert find_skus(RECORDS, "Chair") == ["A1"]
    assert count_matches(RECORDS, "Chair") == 1
