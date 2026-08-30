from inventory import count_matches, find_skus


def test_no_match_behavior() -> None:
    records = [{"sku": "A1", "name": "Red Chair"}]
    assert find_skus(records, "lamp") == []
    assert count_matches(records, "lamp") == 0
