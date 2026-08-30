import inspect

import inventory

RECORDS = [
    {"sku": "A1", "name": "Red Chair"},
    {"sku": "B2", "name": "CHAIR MAT"},
    {"sku": "C3", "name": "Blue Desk"},
]


def test_both_callers_are_case_insensitive() -> None:
    assert inventory.find_skus(RECORDS, "chair") == ["A1", "B2"]
    assert inventory.count_matches(RECORDS, "chair") == 2


def test_shared_match_helper_exists() -> None:
    assert "def _matches" in inspect.getsource(inventory)
